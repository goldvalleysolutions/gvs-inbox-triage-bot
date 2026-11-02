"""Publish workflow guardrails: push to main hard-fails naming each missing Docker Hub
secret; workflow_dispatch is a dry run that never logs in or pushes."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
TEXT = (REPO / ".github" / "workflows" / "publish.yml").read_text()
DOC = yaml.safe_load(TEXT)
ON = DOC.get("on", DOC.get(True))  # PyYAML parses bare `on:` as True
STEPS = DOC["jobs"]["release"]["steps"]
MODE = next(s for s in STEPS if s.get("id") == "mode")


def _run_mode(
    tmp_path: Path,
    event: str,
    ref: str,
    user: bool,
    token: bool,
    released: bool = False,
):
    """Execute the mode step's bash with a stub `gh`; return (rc, stdout, outputs)."""
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    gh = bindir / "gh"
    gh.write_text(f"#!/bin/sh\nexit {0 if released else 1}\n")
    gh.chmod(0o755)
    out = tmp_path / "out"
    out.write_text("")
    env = {
        "PATH": f"{bindir}:{os.environ['PATH']}",
        "EVENT": event,
        "REF": ref,
        "HAS_USERNAME": "true" if user else "false",
        "HAS_TOKEN": "true" if token else "false",
        "TAG": "v0.0.1",
        "GITHUB_REPOSITORY": "o/r",
        "GITHUB_OUTPUT": str(out),
    }
    p = subprocess.run(
        ["bash", "-e", "-c", MODE["run"]],
        check=False,
        env=env,
        capture_output=True,
        text=True,
    )
    outputs = dict(ln.split("=", 1) for ln in out.read_text().splitlines() if "=" in ln)
    return p.returncode, p.stdout, outputs


def test_triggers_main_only_plus_dispatch() -> None:
    assert set(ON) == {"push", "workflow_dispatch"}
    assert ON["push"]["branches"] == ["main"]


def test_main_push_fails_naming_each_missing_secret(tmp_path: Path) -> None:
    main = ("push", "refs/heads/main")
    rc, out, o = _run_mode(tmp_path, *main, user=False, token=False)
    assert rc != 0 and o.get("push") != "true"
    assert (
        "Missing secret DOCKERHUB_USERNAME" in out
        and "Missing secret DOCKERHUB_TOKEN" in out
    )
    rc, out, _ = _run_mode(tmp_path, *main, user=True, token=False)
    assert rc != 0 and "DOCKERHUB_TOKEN" in out and "DOCKERHUB_USERNAME" not in out
    rc, out, _ = _run_mode(tmp_path, *main, user=False, token=True)
    assert rc != 0 and "DOCKERHUB_USERNAME" in out and "DOCKERHUB_TOKEN" not in out
    rc, _, o = _run_mode(tmp_path, *main, user=True, token=True)
    assert rc == 0 and o["push"] == "true" and o["release"] == "true"
    rc, _, o = _run_mode(tmp_path, *main, user=True, token=True, released=True)
    assert rc == 0 and o["push"] == "false"


def test_dispatch_never_pushes_and_needs_no_secrets(tmp_path: Path) -> None:
    for user, token in ((False, False), (True, True)):
        rc, _, o = _run_mode(
            tmp_path, "workflow_dispatch", "refs/heads/main", user, token
        )
        assert rc == 0 and o["push"] == "false" and o["release"] == "false"
    for s in STEPS:
        w = s.get("with") or {}
        if w.get("push") is True or "login-action" in s.get("uses", ""):
            assert s["if"] == "steps.mode.outputs.push == 'true'"


def test_actions_pinned_and_no_latest() -> None:
    for s in STEPS:
        if "uses" in s:
            assert re.fullmatch(r"[\w./-]+@[0-9a-f]{40}", s["uses"]), s["uses"]
    assert ":latest" not in TEXT


def test_image_name_exact() -> None:
    names = set(re.findall(r"(goldvalleysolutions/[\w.-]+bot):", TEXT)) - {
        "goldvalleysolutions/core-bot"
    }
    names |= {
        f"goldvalleysolutions/{m}"
        for m in re.findall(r"\$\{\{ steps\.mode\.outputs\.ns \}\}/([\w.-]+):", TEXT)
    }
    assert names == {"goldvalleysolutions/inbox-triage-bot"}
    assert "ns=goldvalleysolutions;" in MODE["run"]


def test_main_publish_never_cancelled_in_progress() -> None:
    assert (
        DOC["concurrency"]["cancel-in-progress"] == "${{ github.event_name != 'push' }}"
    )


def test_dockerhub_description_workflow_is_single_owner() -> None:
    path = REPO / ".github" / "workflows" / "dockerhub-description.yml"
    text = path.read_text()
    wf = yaml.safe_load(text)
    on = wf[True]
    assert set(on) == {"push", "workflow_dispatch"}
    assert on["push"]["branches"] == ["main"]
    assert set(on["push"]["paths"]) == {
        "README.md",
        ".github/workflows/dockerhub-description.yml",
    }
    assert wf["permissions"] == {"contents": "read"}
    assert (
        "DOCKERHUB_USERNAME" in text and "DOCKERHUB_TOKEN" in text and "exit 1" in text
    )
    assert "readme-filepath: ./README.md" in text
    uses = [s["uses"] for j in wf["jobs"].values() for s in j["steps"] if "uses" in s]
    assert any(u.startswith("peter-evans/dockerhub-description@") for u in uses)
    for u in uses:
        assert re.fullmatch(r"[\w./-]+@[0-9a-f]{40}", u), u
    assert "dockerhub-description" not in TEXT
