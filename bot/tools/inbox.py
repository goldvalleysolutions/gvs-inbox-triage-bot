"""Inbox Triage Bot tools: thin wrappers on Core's read-only IMAP connector.

mail.list / mail.read read the local cache (synced through ``core.tools.imap``, which only
EXAMINEs and BODY.PEEKs: no flags change). brief.build makes the daily brief now and returns
it; brief.now starts the ``daily_brief`` job (``core.sdk.jobs.run_now``), which also saves it
for the app page and, if turned on, emails it to the owner.

Brief shape (matches the product brief and the website card): categories clients, billing,
vendors, newsletters, other; urgency now / today / FYI; a 1-2 line summary per message; a
"needs a reply" list. Classification is rule-based ($0, works on the stub model); the live
model can rephrase it in chat.
"""

from __future__ import annotations

import json
import re
import time
from email.utils import parseaddr
from typing import Any

from core.sdk import tool
from core.tools import imap
from core.tools.registry import registered

CATEGORIES = ("clients", "billing", "vendors", "newsletters", "other")
URGENCY = ("now", "today", "FYI")
CACHE_KEY = "inbox.cache"
BRIEF_KEY = "inbox.last_brief"
RETENTION_KEY = "inbox.retention_days"
EMAIL_SELF_KEY = "inbox.brief_email_self"
DEFAULT_RETENTION_DAYS = 30
BODY_KEEP = 8192

_DEMO = [
    (
        "Dana Ortiz <dana@ortizdental.example>",
        "Can we move Thursday's install?",
        (
            "Hi, something came up. Can we move Thursday's install to Friday morning? "
            "Please confirm today so I can tell my staff."
        ),
    ),
    (
        "Billing <billing@hostco.example>",
        "Invoice 2291 is past due",
        "Your invoice 2291 for $49.00 is past due. Please pay now to avoid suspension.",
    ),
    (
        "Ace Supply <orders@acesupply.example>",
        "Quote for 40 cable runs",
        "Attached is the quote you asked for. Can you approve it by Friday?",
    ),
    (
        "The Weekly Byte <news@weeklybyte.example>",
        "This week in small business tech",
        "Five tools we liked this week. Unsubscribe at any time.",
    ),
]

_AUTOMATED = re.compile(
    r"no-?reply|do-?not-?reply|mailer-daemon|notifications?@|news(letter)?@"
)
_NEWSLETTER = re.compile(
    r"unsubscribe|newsletter|weekly digest|view in browser|this week in", re.IGNORECASE
)
_BILLING = re.compile(
    r"invoice|payment|past due|overdue|receipt|billing|refund|charge[ds]?\b|statement|balance due",
    re.IGNORECASE,
)
_VENDOR = re.compile(
    r"\bquote\b|supplier|vendor|shipment|shipping|purchase order|\bPO\b|delivery|order #|"
    r"order confirmation|restock",
    re.IGNORECASE,
)
_NOW = re.compile(
    r"\burgent\b|\basap\b|immediately|right away|past due|overdue|final notice|"
    r"suspen|emergency|outage|\bdown\b|pay now",
    re.IGNORECASE,
)
_TODAY = re.compile(
    r"\btoday\b|by (end of )?day|\beod\b|tomorrow|deadline|by (mon|tues|wednes|thurs|fri)day|"
    r"please (confirm|reply|let me know|approve)|can you|could you|\?",
    re.IGNORECASE,
)
_ASK = re.compile(
    r"\?|please (confirm|reply|let me know|approve|send|call)|can you|could you|let me know",
    re.IGNORECASE,
)


# --- cache ---------------------------------------------------------------------------------
def _cache(store: Any) -> dict[str, dict[str, Any]]:
    try:
        return json.loads(store.get_setting(CACHE_KEY) or "{}")
    except ValueError:
        return {}


def _save(store: Any, cache: dict[str, dict[str, Any]]) -> None:
    store.set_setting(CACHE_KEY, json.dumps(cache))


def retention_days(store: Any) -> int:
    try:
        return max(1, int(store.get_setting(RETENTION_KEY) or DEFAULT_RETENTION_DAYS))
    except ValueError:
        return DEFAULT_RETENTION_DAYS


def purge(store: Any, now: float | None = None) -> int:
    """Drop cached messages older than the retention window. Returns how many went."""
    cutoff = (now or time.time()) - retention_days(store) * 86400
    cache = _cache(store)
    keep = {k: v for k, v in cache.items() if float(v.get("fetched_at", 0)) >= cutoff}
    _save(store, keep)
    return len(cache) - len(keep)


def forget(store: Any) -> None:
    """'Forget mailbox': wipe the cache, the last brief and the sync cursor."""
    for key in (CACHE_KEY, BRIEF_KEY, "imap.uidvalidity", "imap.last_uid"):
        store.set_setting(key, "")


def _demo_connector() -> imap.ImapConnector:
    raw = [
        (
            f"From: {s}\r\nTo: owner@example.com\r\nSubject: {subj}\r\n"
            f"Date: Sun, 01 Nov 2026 08:0{i}:00 -0500\r\nMessage-ID: <demo{i}@example>\r\n\r\n"
            f"{body}\r\n"
        ).encode()
        for i, (s, subj, body) in enumerate(_DEMO)
    ]
    return imap.ImapConnector("stub", fixtures=raw)


def sync(store: Any) -> int:
    """One capped, read-only incremental sync into the cache. Demo mail until IMAP is set."""
    cfg = imap.account(store)
    conn = imap.ImapConnector("live", cfg=cfg) if cfg["host"] else _demo_connector()
    msgs = imap.sync_store(store, conn)
    cache = _cache(store)
    now = time.time()
    for m in msgs:
        row = m.as_dict()
        row["body"] = (row.get("body") or "")[:BODY_KEEP]
        row["fetched_at"] = now
        cache[str(m.uid)] = row
    _save(store, cache)
    return len(msgs)


# --- triage --------------------------------------------------------------------------------
def classify(msg: dict[str, Any]) -> dict[str, Any]:
    sender = str(msg.get("sender", ""))
    addr = parseaddr(sender)[1].lower()
    subject = str(msg.get("subject", ""))
    body = str(msg.get("body", ""))
    text = f"{subject}\n{body}"
    automated = bool(_AUTOMATED.search(addr))
    if _NEWSLETTER.search(text) or (automated and not _BILLING.search(text)):
        category = "newsletters"
    elif _BILLING.search(text):
        category = "billing"
    elif _VENDOR.search(text):
        category = "vendors"
    elif not automated and _ASK.search(text):
        category = "clients"
    else:
        category = "other"
    if category == "newsletters":
        urgency = "FYI"
    elif _NOW.search(text):
        urgency = "now"
    elif _TODAY.search(text):
        urgency = "today"
    else:
        urgency = "FYI"
    needs_reply = (
        category in ("clients", "vendors", "billing")
        and not automated
        and bool(_ASK.search(text))
    )
    return {
        "uid": msg.get("uid"),
        "sender": sender,
        "subject": subject,
        "category": category,
        "urgency": urgency,
        "needs_reply": needs_reply,
        "summary": summarize(msg),
    }


def summarize(msg: dict[str, Any]) -> str:
    """1-2 lines: who and what, then the first sentence of the body."""
    name = (
        parseaddr(str(msg.get("sender", "")))[0]
        or parseaddr(str(msg.get("sender", "")))[1]
    )
    body = " ".join(str(msg.get("body", "")).split())
    first = re.split(r"(?<=[.!?])\s", body, maxsplit=1)[0] if body else ""
    line1 = f"{name or 'Unknown'}: {msg.get('subject') or '(no subject)'}"
    return line1 + (f"\n  {first[:160]}" if first else "")


_ORDER = {u: i for i, u in enumerate(URGENCY)}


def build_brief(store: Any) -> dict[str, Any]:
    """Sync, purge past retention, classify every cached message, render the brief."""
    new = sync(store)
    purge(store)
    rows = sorted(
        (classify(m) for m in _cache(store).values()),
        key=lambda r: (_ORDER[r["urgency"]], -int(r["uid"] or 0)),
    )
    stamp = time.strftime("%a %b %d, %I:%M %p", time.localtime())
    lines = [f"Daily brief — {stamp} ({len(rows)} messages, {new} new)", ""]
    reply = [r for r in rows if r["needs_reply"]]
    lines.append(f"Needs a reply ({len(reply)})")
    lines += [
        f"- [{r['urgency']}] {r['summary'].splitlines()[0]} (#{r['uid']})"
        for r in reply
    ]
    if not reply:
        lines.append("- nothing waiting on you")
    for cat in CATEGORIES:
        group = [r for r in rows if r["category"] == cat]
        lines += ["", f"{cat.capitalize()} ({len(group)})"]
        for r in group:
            head, *rest = r["summary"].splitlines()
            lines.append(f"- [{r['urgency']}] {head} (#{r['uid']})")
            lines += rest
    brief = {"text": "\n".join(lines), "items": rows, "at": time.time()}
    store.set_setting(BRIEF_KEY, json.dumps(brief))
    return brief


def last_brief(store: Any) -> dict[str, Any] | None:
    raw = store.get_setting(BRIEF_KEY)
    try:
        return json.loads(raw) if raw else None
    except ValueError:
        return None


# --- tools ---------------------------------------------------------------------------------
def mail_list(store: Any, limit: int = 20, **_: Any) -> str:
    sync(store)
    rows = sorted(_cache(store).values(), key=lambda m: -int(m["uid"]))[
        : max(1, int(limit))
    ]
    out = []
    for m in rows:
        c = classify(m)
        out.append(
            f"#{m['uid']} [{c['category']}/{c['urgency']}] {m['sender']}: {m['subject']}"
        )
    return "\n".join(out) or "No messages in the window."


def mail_read(store: Any, uid: int, **_: Any) -> str:
    m = _cache(store).get(str(uid))
    if m is None:
        sync(store)
        m = _cache(store).get(str(uid))
    if m is None:
        return f"No message #{uid} in the cache."
    return (
        f"From: {m['sender']}\nTo: {m['to']}\nDate: {m['date']}\nSubject: {m['subject']}\n"
        f"Message-ID: {m['message_id']}\n\n{m['body']}"
    )


def brief_build(store: Any, **_: Any) -> str:
    return build_brief(store)["text"]


def brief_now(store: Any, **_: Any) -> str:
    from core.sdk.jobs import run_now

    if run_now("daily_brief"):
        return "Started the daily brief. It shows on the Brief page in a moment."
    return "The daily brief is already running (or the job runner is off)."


TOOLS = (
    ("mail.list", mail_list, {"limit": {"type": "integer"}}, [], "read", True,
     "Listing recent mail"),
    ("mail.read", mail_read, {"uid": {"type": "integer"}}, ["uid"], "read", True,
     "Reading one message"),
    ("brief.build", brief_build, {}, [], "read", True, "Building the inbox brief"),
    ("brief.now", brief_now, {}, [], "action", False, "Starting the daily brief job"),
)  # fmt: skip

for _name, _fn, _props, _req, _kind, _untrusted, _label in TOOLS:
    if _name not in registered():
        tool(
            _name,
            schema={"type": "object", "properties": _props, "required": _req},
            kind=_kind,
            label=_label,
            untrusted=_untrusted,
        )(_fn)
