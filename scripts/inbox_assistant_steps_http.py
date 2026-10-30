"""Inbox Assistant walkthrough over web chat, the admin forms and MCP (no REST API).

Usage: inbox_assistant_steps_http.py BASE SMTP_HOST SMTP_PORT CTL BOT_ID
(CTL holds gvs_test_ed25519; its public half is installed as the bot's root key.)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from steps_web import Web, check_access_policy, fail, mcp_call, mcp_list


def admin_checks(base: str, brand: str) -> Web:
    """Bot admin signs in; GVS root screens stay 404 for it; untested model key refused."""
    admin = Web(base)
    admin.admin_login()
    for path in ("/gvs/role", "/gvs/skills", "/gvs/memory", "/gvs/activity"):
        code, body = admin.get(path)
        assert code == 404 and brand in body, (path, code)
    return admin


BRAND = "Inbox Assistant"


def main() -> None:
    base, smtp_host, smtp_port, ctl, bot_id = sys.argv[1:6]
    web = Web(base)

    print("step 1 setup")
    web.setup(
        smtp={
            "SMTP_HOST": smtp_host,
            "SMTP_PORT": smtp_port,
            "SMTP_FROM": "bot@example.com",
        }
    )
    code, home = web.get("/")
    assert code == 200 and BRAND in home and "Powered by Gold Valley Solutions" in home

    print("step 2 clock")
    assert web.ask("CALL clock.now {}")["blocked"] is False

    print("step 3 notes")
    assert web.ask('CALL notes {"text":"follow up invoice 1041"}')["blocked"] is False

    print("step 4 email")
    sent = web.ask(
        'CALL email.send {"to":"admin@example.com","subject":"Re: 1041","body":"paid"}'
    )
    assert not sent.get("error"), sent

    print("step 5 web blocked")
    assert web.ask("CALL web.browse {}")["blocked"] is True

    print("step 6 root edit")
    web.root_login(Path(ctl) / "gvs_test_ed25519", bot_id)
    web.form(
        "/gvs/role",
        {"text": "You are Maple Inbox, a maple-shop clerk. You do not browse."},
    )
    assert "Maple Inbox" in web.ask("who are you?")["text"]

    print("step 7 bot admin: root screens 404")
    admin = admin_checks(base, BRAND)
    check_access_policy(base, admin, ["/"])  # Anyone / Signed-in users only

    print("step 8 model switch (untested key refused, then stub)")
    admin.model_switch_gated()

    print("step 9 mcp")
    token = admin.enable_mcp("read_only", "inbox")
    names = mcp_list(base, token)
    assert "ask" in names and "email.send" not in names, names
    asked = mcp_call(base, token, "ask", {"text": "ping"})
    assert "(stub)" in asked or "ping" in asked, asked
    admin.set_mcp_access("write_with_approval")
    pending = json.loads(
        mcp_call(
            base,
            token,
            "email.send",
            {"to": "admin@example.com", "subject": "invoice", "body": "draft reply"},
        )
    )
    if pending.get("status") not in {"pending_approval", "approval_required"}:
        fail(f"expected pending_approval: {pending}")
    assert admin.approve(pending["id"]) == "approved", "approval did not run"
    print("OK inbox-assistant-steps")


if __name__ == "__main__":
    main()
