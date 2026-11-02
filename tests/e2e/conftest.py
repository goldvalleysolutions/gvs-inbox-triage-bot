"""Playwright e2e fixtures: core from source + this repo's /bot on uvicorn, stub LLM.

Core is pinned to CORE_SHA. Point GVS_CORE_DIR at a gvs-core-bot checkout of that commit
(with its requirements installed), or let the fixture clone it into .e2e/core (needs
GitHub access to the private repo). The checkout is copied to a temp dir, so the
throwaway GVS root key never touches it. Each bot gets a fresh temp /data.

On failure, a screenshot and a Playwright trace go to tests/e2e/artifacts/ (gitignored).
Kept identical across the bot repos.
"""

from __future__ import annotations

import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest
from playwright.sync_api import Browser, Page, Playwright, sync_playwright

CORE_SHA = (
    "1c6e619a234efe210769071b9e54ace6977f86ce"  # gvs-core-bot test: jobs (#42) + mail (#43)
)
REPO = Path(__file__).resolve().parents[2]
ARTIFACTS = Path(__file__).resolve().parent / "artifacts"
sys.path.insert(0, str(REPO / "scripts"))

import fakecert
from fakeimap import FakeIMAP
from fakesmtp import FakeSMTP
from steps_web import Web, write_root_key

MAIL_USER, MAIL_PASSWORD = "owner@example.com", "app-pass"  # fake servers only

VIEWPORTS = {
    "desktop": {"viewport": {"width": 1280, "height": 800}},
    "mobile": {
        "viewport": {"width": 390, "height": 844},
        "device_scale_factor": 3,
        "is_mobile": True,
        "has_touch": True,
    },
}


def _core_source() -> Path:
    given = os.environ.get("GVS_CORE_DIR")
    if given:
        core = Path(given).resolve()
    else:
        core = REPO / ".e2e" / "core"
        if not (core / "core" / "app.py").is_file():
            url = os.environ.get(
                "GVS_CORE_REPO",
                "https://github.com/goldvalleysolutions/gvs-core-bot.git",
            )
            subprocess.run(["git", "clone", "-q", url, str(core)], check=True)
            subprocess.run(
                ["git", "-C", str(core), "checkout", "-q", CORE_SHA], check=True
            )
    head = subprocess.run(
        ["git", "-C", str(core), "rev-parse", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if head and not head.startswith(CORE_SHA):
        pytest.exit(
            f"core at {head[:7]}, the suite is pinned to {CORE_SHA}", returncode=2
        )
    return core


class Mail:
    """Fake IMAP (records flags/APPEND) + fake SMTP on 127.0.0.1 with a test cert."""

    def __init__(self, folder: Path) -> None:
        self.bundle = fakecert.write(folder)
        self.imap = FakeIMAP(user=MAIL_USER, password=MAIL_PASSWORD).start()
        self.smtp = FakeSMTP(user=MAIL_USER, password=MAIL_PASSWORD).start()

    def env(self) -> dict[str, str]:
        return {
            "SSL_CERT_FILE": str(self.bundle),
            "MAIL_ALLOW_PRIVATE_HOSTS": "1",
            "MAIL_EXTRA_PORTS": f"{self.imap.port},{self.smtp.port}",
        }

    def close(self) -> None:
        self.imap.close()
        self.smtp.close()


@pytest.fixture(scope="session")
def mail(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Mail]:
    box = Mail(tmp_path_factory.mktemp("fake-tls"))
    yield box
    box.close()


def mail_fields(box: Mail, password: str = MAIL_PASSWORD) -> dict[str, str]:
    """The setup Mail account fields for the fake servers (one app password)."""
    return {
        "SMTP_HOST": "127.0.0.1",
        "SMTP_PORT": str(box.smtp.port),
        "SMTP_USER": MAIL_USER,
        "SMTP_PASSWORD": password,
        "SMTP_FROM": MAIL_USER,
        "IMAP_HOST": "127.0.0.1",
        "IMAP_PORT": str(box.imap.port),
    }


@pytest.fixture(scope="session")
def core_copy(tmp_path_factory: pytest.TempPathFactory, mail: Mail) -> tuple[Path, Path]:
    """(core dir with a throwaway root key installed, ctl dir holding its private key)."""
    src = _core_source()
    dst = tmp_path_factory.mktemp("core") / "core"
    shutil.copytree(
        src, dst, ignore=shutil.ignore_patterns(".git", "__pycache__", ".venv")
    )
    ctl = tmp_path_factory.mktemp("ctl")
    write_root_key(ctl)
    shutil.copy(ctl / "gvs_root.pub", dst / "keys" / "gvs_root.pub")
    global MAIL_ENV
    MAIL_ENV = mail.env()
    return dst, ctl


MAIL_ENV: dict[str, str] = {}


class Bot:
    """One bot process: core + this repo's bot/ on uvicorn, a temp /data, stub LLM."""

    def __init__(self, core: Path, ctl: Path, data: Path) -> None:
        self.core, self.ctl, self.data = core, ctl, data
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            self.port = sock.getsockname()[1]
        self.base = f"http://127.0.0.1:{self.port}"
        self.proc: subprocess.Popen[bytes] | None = None
        self.extra_env: dict[str, str] = {}

    def start(self) -> Bot:
        env = {
            **os.environ,
            "PYTHONPATH": str(self.core),
            "GVS_BOT_DIR": str(REPO / "bot"),
            "GVS_DATA_DIR": str(self.data),
            **MAIL_ENV,
            **self.extra_env,
        }
        self.proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "core.app:app",
                "--port",
                str(self.port),
                "--log-level",
                "warning",
            ],
            cwd=self.core,
            env=env,
        )
        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                if (
                    urllib.request.urlopen(self.base + "/health", timeout=2).status
                    == 200
                ):
                    return self
            except OSError:
                time.sleep(0.2)
        raise RuntimeError("bot did not become healthy")

    def stop(self) -> None:
        if self.proc:
            self.proc.terminate()
            self.proc.wait(timeout=10)
            self.proc = None

    def restart(self) -> None:
        self.stop()
        self.start()

    @property
    def bot_id(self) -> str:
        with sqlite3.connect(self.data / "bot.db") as db:
            return db.execute(
                "select value from settings where key='bot_id'"
            ).fetchone()[0]

    def set_setting(self, key: str, value: str) -> None:
        with sqlite3.connect(self.data / "bot.db") as db:
            db.execute(
                "INSERT OR REPLACE INTO settings(key, value) VALUES(?, ?)", (key, value)
            )

    def root_login_url(self) -> str:
        """A signed one-time GVS root login link (throwaway key from core_copy)."""
        import secrets

        sys.path.insert(0, str(self.core))
        from core.auth.token import load_private_key, sign_token

        key = load_private_key(self.ctl / "gvs_test_ed25519")
        return (
            self.base
            + "/gvs/login?token="
            + sign_token(key, self.bot_id, secrets.token_urlsafe(8))
        )


@pytest.fixture
def fresh_bot(core_copy: tuple[Path, Path], tmp_path: Path) -> Iterator[Bot]:
    """A bot that has not been set up yet (for the setup and hello walkthrough tests)."""
    bot = Bot(core_copy[0], core_copy[1], tmp_path / "data").start()
    yield bot
    bot.stop()


@pytest.fixture(scope="module")
def ready_bot(
    core_copy: tuple[Path, Path], tmp_path_factory: pytest.TempPathFactory, request
) -> Iterator[Bot]:
    """A bot already through setup (over HTTP), shared by the chat/page/MCP tests."""
    bot = Bot(core_copy[0], core_copy[1], tmp_path_factory.mktemp("data")).start()
    setup = dict(getattr(request.module, "HTTP_SETUP", {}))
    if setup.pop("mail", False):
        setup["smtp"] = mail_fields(request.getfixturevalue("mail"))
    elif setup.pop("smtp", False):
        setup["smtp"] = smtp_fields(request.getfixturevalue("smtp"))
    Web(bot.base).setup(**setup)
    yield bot
    bot.stop()


@pytest.fixture(scope="session")
def smtp(mail: Mail) -> FakeSMTP:
    """The fake SMTP server; .messages holds what the bot sent."""
    return mail.smtp


def smtp_fields(server: object) -> dict[str, str]:
    return {
        "SMTP_HOST": "127.0.0.1",
        "SMTP_PORT": str(server.port),  # type: ignore[attr-defined]
        "SMTP_FROM": "bot@example.com",
    }


@pytest.fixture(scope="session")
def pw() -> Iterator[Playwright]:
    with sync_playwright() as p:
        yield p


@pytest.fixture(scope="session")
def browser(pw: Playwright) -> Iterator[Browser]:
    b = pw.chromium.launch()
    yield b
    b.close()


@pytest.fixture(params=list(VIEWPORTS))
def page(browser: Browser, request) -> Iterator[Page]:
    ctx = browser.new_context(**VIEWPORTS[request.param])
    ctx.tracing.start(screenshots=True, snapshots=True)
    pg = ctx.new_page()
    errors: list[str] = []
    csp: list[str] = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.on(
        "console",
        lambda m: csp.append(m.text) if "Content Security Policy" in m.text else None,
    )
    pg.js_errors = errors  # type: ignore[attr-defined]
    pg.csp_errors = csp  # type: ignore[attr-defined]
    yield pg
    rep = getattr(request.node, "rep_call", None)
    if rep is not None and rep.failed:
        ARTIFACTS.mkdir(exist_ok=True)
        name = request.node.name.replace("/", "_").replace("[", "-").rstrip("]")
        try:
            pg.screenshot(path=str(ARTIFACTS / f"{name}.png"), full_page=True)
        finally:
            ctx.tracing.stop(path=str(ARTIFACTS / f"{name}.trace.zip"))
    else:
        ctx.tracing.stop()
    ctx.close()


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item, call):
    rep = yield
    if rep.when == "call":
        item.rep_call = rep
    return rep
