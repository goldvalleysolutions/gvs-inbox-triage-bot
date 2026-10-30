"""Inbox Assistant e2e: setup, chat with its tools, MCP (desktop + mobile)."""

from __future__ import annotations

import time

from conftest import smtp_fields
from playwright.sync_api import Page, expect
from steps_web import mcp_list
from ui import admin_web, chat, mcp_initialize, setup_ui

BRAND = "Inbox Assistant"
HTTP_SETUP = {"smtp": True}


def test_setup(page: Page, fresh_bot, smtp) -> None:
    seen = setup_ui(page, fresh_bot.base, smtp_fields(smtp))
    assert seen == ["bot_admin", "access", "model", "connectors", "self_test"], seen
    page.goto(fresh_bot.base + "/")
    expect(page.locator("body")).to_contain_text(BRAND)
    expect(page.locator("body")).to_contain_text("Powered by Gold Valley Solutions")
    assert not page.js_errors


def test_chat_tools(page: Page, ready_bot, smtp) -> None:
    page.goto(ready_bot.base + "/")
    for call in ("CALL clock.now {}", 'CALL notes {"text":"follow up invoice 1041"}'):
        reply = chat(page, call)
        assert "error" not in (reply.get_attribute("class") or ""), call
        expect(reply.locator("summary")).to_have_count(1)
    sent = len(smtp.messages)
    chat(
        page,
        'CALL email.send {"to":"admin@example.com","subject":"Re: 1041","body":"paid"}',
    )
    deadline = time.time() + 5
    while len(smtp.messages) == sent and time.time() < deadline:
        time.sleep(0.1)
    assert len(smtp.messages) > sent, "fake SMTP got nothing"
    expect(chat(page, "CALL web.browse {}")).to_contain_text("not allowed")
    assert not page.js_errors


def test_mcp_initialize_and_tools(ready_bot) -> None:
    token = admin_web(ready_bot.base).enable_mcp("read_only", "e2e")
    assert mcp_initialize(ready_bot.base, token)["serverInfo"]["name"]
    names = mcp_list(ready_bot.base, token)
    assert "ask" in names and "email.send" not in names, names
