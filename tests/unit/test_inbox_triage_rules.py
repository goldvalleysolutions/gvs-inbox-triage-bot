"""Unit tests for the rule-based triage (bot/tools/inbox.py): classify and build_brief.

Needs gvs-core-bot importable (GVS_CORE_DIR, or .e2e/core cloned by the e2e suite).
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[2]
_core = Path(os.environ.get("GVS_CORE_DIR") or REPO / ".e2e" / "core")
if (_core / "core").is_dir() and str(_core) not in sys.path:
    sys.path.insert(0, str(_core))
pytest.importorskip("core.sdk", reason="gvs-core-bot not importable (set GVS_CORE_DIR)")


def _load() -> Any:
    name = "gvs_inbox_triage"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, REPO / "bot/tools/inbox.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    sys.modules[name] = mod
    return mod


inbox = _load()


class Store:
    def __init__(self) -> None:
        self.settings: dict[str, str] = {}

    def get_setting(self, key: str) -> str | None:
        return self.settings.get(key)

    def set_setting(self, key: str, value: str) -> None:
        self.settings[key] = value


def msg(uid: Any, sender: str, subject: str, body: str) -> dict[str, Any]:
    return {"uid": uid, "sender": sender, "subject": subject, "body": body}


CASES = [
    # (sender, subject, body, category, urgency, needs_reply)
    ("Dana <dana@ortiz.example>", "Install", "Can you move it? Please confirm today.",
     "clients", "today", True),
    ("Dana <dana@ortiz.example>", "Site down", "Our site is down, urgent. Can you look?",
     "clients", "now", True),
    ("Dana <dana@ortiz.example>", "Logo", "Any thoughts on the new logo?",
     "clients", "FYI", True),
    ("Billing <billing@hostco.example>", "Invoice 2291 past due", "Pay now.",
     "billing", "now", False),
    ("Sam <sam@acct.example>", "Invoice 77", "Could you confirm the invoice?",
     "billing", "FYI", True),
    ("Ace <orders@ace.example>", "Quote for cables", "Please approve by Friday.",
     "vendors", "today", True),
    ("Ace <orders@ace.example>", "Shipment sent", "Your shipment left the warehouse.",
     "vendors", "FYI", False),
    ("Byte <news@byte.example>", "This week", "Tools we liked. Unsubscribe.",
     "newsletters", "FYI", False),
    ("Alerts <noreply@svc.example>", "Login", "New login from Chrome.",
     "newsletters", "FYI", False),
    ("Pat <pat@friend.example>", "Photos", "Here are the photos from Saturday.",
     "other", "FYI", False),
]  # fmt: skip


@pytest.mark.parametrize("case", CASES, ids=[f"{c[3]}-{c[4]}" for c in CASES])
def test_classify(case) -> None:
    sender, subject, body, category, urgency, needs = case
    got = inbox.classify(msg(1, sender, subject, body))
    assert (got["category"], got["urgency"], got["needs_reply"]) == (
        category,
        urgency,
        needs,
    )
    assert got["summary"].count("\n") <= 1


def test_every_category_and_urgency_covered() -> None:
    assert {c[3] for c in CASES} == set(inbox.CATEGORIES)
    assert {c[4] for c in CASES} == set(inbox.URGENCY)


def test_question_mark_alone_is_not_today() -> None:
    got = inbox.classify(msg(1, "Dana <d@x.example>", "Hi", "How was the weekend?"))
    assert got["urgency"] == "FYI"
    got = inbox.classify(msg(1, "Dana <d@x.example>", "Hi", "Need it by end of day?"))
    assert got["urgency"] == "today"


def _brief(monkeypatch, rows: list[dict[str, Any]]) -> dict[str, Any]:
    store = Store()
    import time

    store.set_setting(
        inbox.CACHE_KEY,
        json.dumps(
            {str(i): {**r, "fetched_at": time.time()} for i, r in enumerate(rows)}
        ),
    )
    monkeypatch.setattr(inbox, "sync", lambda s: 0)
    out = inbox.build_brief(store)
    assert json.loads(store.settings[inbox.BRIEF_KEY])["text"] == out["text"]  # saved
    return out


def test_build_brief_groups_orders_and_lists_replies(monkeypatch) -> None:
    rows = [msg(i + 1, *c[:3]) for i, c in enumerate(CASES)]
    out = _brief(monkeypatch, rows)
    text = out["text"]
    for cat in inbox.CATEGORIES:
        n = sum(1 for c in CASES if c[3] == cat)
        assert f"{cat.capitalize()} ({n})" in text
    need = [i + 1 for i, c in enumerate(CASES) if c[5]]
    assert f"Needs a reply ({len(need)})" in text
    reply_block = text.split("Needs a reply")[1].split("\n\n")[0]
    for uid in need:
        assert f"(#{uid})" in reply_block
    order = [inbox._ORDER[r["urgency"]] for r in out["items"]]
    assert order == sorted(order)  # now, today, FYI


def test_build_brief_empty_and_bad_uid(monkeypatch) -> None:
    assert "nothing waiting on you" in _brief(monkeypatch, [])["text"]
    out = _brief(
        monkeypatch,
        [msg("", "A <a@x.example>", "s", "b"), msg(3, "B <b@x.example>", "s", "b")],
    )
    assert len(out["items"]) == 2  # empty uid sorts last, no crash


def test_purge_respects_retention() -> None:
    store = Store()
    store.set_setting(inbox.RETENTION_KEY, "2")
    store.set_setting(
        inbox.CACHE_KEY,
        json.dumps(
            {"1": {"fetched_at": 1000.0}, "2": {"fetched_at": 1000.0 + 3 * 86400}}
        ),
    )
    assert inbox.purge(store, now=1000.0 + 4 * 86400) == 1
    assert list(json.loads(store.settings[inbox.CACHE_KEY])) == ["2"]
