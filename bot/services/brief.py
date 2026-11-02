"""Daily brief job (``daily 07:00`` local, editable in admin → Schedules) and the Brief page.

The job syncs read-only, purges past retention, builds the brief, saves it for the page and,
when "Email the brief to me" is on, sends it to the owner's own address over SMTP.
Page: /r/inbox-triage/brief (bot admin only): last brief, email-to-self, retention days,
Run now, Forget mailbox.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from core.auth import csrf
from core.sdk.jobs import Job, run_now
from core.ui.html import bot_name, esc, page

_NAME = "gvs_inbox_triage"


def _inbox() -> Any:
    mod = sys.modules.get(_NAME)
    if mod is None:
        path = Path(__file__).resolve().parents[1] / "tools" / "inbox.py"
        spec = importlib.util.spec_from_file_location(_NAME, path)
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        sys.modules[_NAME] = mod
    return mod


def daily_brief(ctx: Any) -> str:
    inbox = _inbox()
    store = ctx.store
    brief = inbox.build_brief(store)
    store.log("job", "brief.built", f"trigger={ctx.trigger} items={len(brief['items'])}", "job")
    if store.get_setting(inbox.EMAIL_SELF_KEY) == "1" and store.admin_email():
        from core.tools.builtins import email_send

        try:
            email_send(
                store,
                to=store.admin_email(),
                subject="Your inbox brief",
                body=brief["text"],
                actor="job",
                source="job",
            )
        except Exception as exc:  # a failed email never fails the brief
            store.log("job", "brief.email", f"result=error {type(exc).__name__}", "job")
    return brief["text"]


jobs = [Job("daily_brief", daily_brief, schedule="daily 07:00", description="Inbox brief")]

router = APIRouter()


@router.get("/brief")
def brief_page(request: Request) -> Any:
    inbox = _inbox()
    store = request.app.state.store
    last = inbox.last_brief(store)
    text = last["text"] if last else "No brief yet. Use Run now, or say “brief me” in chat."
    checked = " checked" if store.get_setting(inbox.EMAIL_SELF_KEY) == "1" else ""
    tok = csrf.token(request)
    hidden = f"<input type=hidden name=csrf value='{esc(tok)}'>"
    body = (
        "<h1>Inbox brief</h1>"
        f"<pre id=brief style='white-space:pre-wrap'>{esc(text)}</pre>"
        f"<form method=post action=/r/inbox-triage/brief/settings>{hidden}"
        f"<label><input type=checkbox id=email_self name=email_self value=1{checked}> "
        "Email the brief to me</label> "
        "<label>Keep mail for (days) <input id=retention_days name=retention_days "
        f"type=number min=1 value={inbox.retention_days(store)}></label> "
        "<button id=save-brief-settings>Save</button></form>"
        f"<form method=post action=/r/inbox-triage/brief/run>{hidden}"
        "<button id=run-brief>Run now</button></form>"
        f"<form method=post action=/r/inbox-triage/brief/forget>{hidden}"
        "<button id=forget-mailbox>Forget mailbox</button></form>"
        "<p>Change the 7:00 AM time in Admin → Schedules.</p>"
    )
    return page("Inbox brief", body, csrf=tok, bot=bot_name(request))


async def _form(request: Request) -> dict[str, str] | None:
    form = {k: str(v) for k, v in (await request.form()).items()}
    return form if csrf.valid(request, form) else None


@router.post("/brief/settings")
async def brief_settings(request: Request) -> Any:
    form = await _form(request)
    if form is None:
        return page("Rejected", "<h1>Rejected</h1>", status=403, bot=bot_name(request))
    inbox, store = _inbox(), request.app.state.store
    store.set_setting(inbox.EMAIL_SELF_KEY, "1" if form.get("email_self") == "1" else "0")
    days = (form.get("retention_days") or "").strip()
    if days.isdigit() and int(days) >= 1:
        store.set_setting(inbox.RETENTION_KEY, days)
    return RedirectResponse("/r/inbox-triage/brief", status_code=303)


@router.post("/brief/run")
async def brief_run(request: Request) -> Any:
    if await _form(request) is None:
        return page("Rejected", "<h1>Rejected</h1>", status=403, bot=bot_name(request))
    run_now("daily_brief")
    return RedirectResponse("/r/inbox-triage/brief", status_code=303)


@router.post("/brief/forget")
async def brief_forget(request: Request) -> Any:
    if await _form(request) is None:
        return page("Rejected", "<h1>Rejected</h1>", status=403, bot=bot_name(request))
    _inbox().forget(request.app.state.store)
    request.app.state.store.log("admin", "inbox.forget", "cache wiped", "admin")
    return RedirectResponse("/r/inbox-triage/brief", status_code=303)
