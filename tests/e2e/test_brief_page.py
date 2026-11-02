"""The Brief page (/r/inbox-triage/brief): Save (email-to-self + retention), Run now, Forget
mailbox, the brief email reaching fake SMTP, a failed brief email shown to the owner, the
daily 07:00 job in Admin > Schedules, and no horizontal overflow at 390px."""

from __future__ import annotations

import json
import sqlite3
import time

from playwright.sync_api import Page, expect
from test_inbox_triage import _seed
from ui import admin_login

HTTP_SETUP = {"mail": True}
PATH = "/r/inbox-triage/brief"


def _setting(bot, key: str) -> str | None:
    with sqlite3.connect(bot.data / "bot.db") as db:
        row = db.execute("select value from settings where key=?", (key,)).fetchone()
    return row[0] if row else None


def _wait(cond, timeout: float = 15) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if cond():
            return True
        time.sleep(0.2)
    return False


def _open(page: Page, bot) -> None:
    admin_login(page, bot.base)
    page.goto(bot.base + PATH)
    expect(page.locator("h1")).to_have_text("Inbox brief")


def test_save_run_now_forget(page: Page, ready_bot, mail) -> None:
    _seed(mail)
    _open(page, ready_bot)
    page.fill("#retention_days", "7")
    page.locator("#save-brief-settings").click()
    page.wait_for_load_state()
    expect(page.locator("#retention_days")).to_have_value("7")
    assert _setting(ready_bot, "inbox.retention_days") == "7"
    page.goto(ready_bot.base + PATH)  # survives a reload
    expect(page.locator("#retention_days")).to_have_value("7")

    page.locator("#run-brief").click()
    page.wait_for_load_state()
    assert _wait(lambda: _setting(ready_bot, "inbox.last_brief")), (
        "Run now built no brief"
    )
    page.goto(ready_bot.base + PATH)
    expect(page.locator("#brief")).to_contain_text("Needs a reply")
    expect(page.locator("#brief")).to_contain_text("Invoice 2291")

    page.locator("#forget-mailbox").click()
    page.wait_for_load_state()
    expect(page.locator("#brief")).to_contain_text("No brief yet")
    assert not _setting(ready_bot, "inbox.cache")
    assert not page.js_errors


def test_brief_page_wraps_on_mobile(page: Page, ready_bot, mail) -> None:
    _seed(mail)
    _open(page, ready_bot)
    page.locator("#run-brief").click()
    assert _wait(lambda: _setting(ready_bot, "inbox.last_brief"))
    page.goto(ready_bot.base + PATH)
    over = page.evaluate(
        "() => { const p = document.querySelector('#brief');"
        " return [p.scrollWidth - p.clientWidth,"
        " document.documentElement.scrollWidth - window.innerWidth]; }"
    )
    assert over[0] <= 1 and over[1] <= 1, over


def test_email_to_self_reaches_smtp(page: Page, ready_bot, mail) -> None:
    _seed(mail)
    _open(page, ready_bot)
    page.check("#email_self")
    page.locator("#save-brief-settings").click()
    page.wait_for_load_state()
    expect(page.locator("#email_self")).to_be_checked()
    before = len(mail.smtp.messages)
    page.locator("#run-brief").click()
    assert _wait(
        lambda: any(b"Your inbox brief" in m for m in mail.smtp.messages[before:])
    ), "brief email never reached fake SMTP"
    msg = next(m for m in mail.smtp.messages[before:] if b"Your inbox brief" in m)
    assert b"admin@example.com" in msg and b"Needs a reply" in msg
    page.goto(ready_bot.base + PATH)
    expect(page.locator("#brief-email-error")).to_have_count(0)
    page.uncheck("#email_self")
    page.locator("#save-brief-settings").click()


def test_failed_brief_email_shown(page: Page, ready_bot, mail) -> None:
    _seed(mail)
    _open(page, ready_bot)
    ready_bot.set_setting("email_allowlist", json.dumps([]))  # admin no longer allowed
    page.check("#email_self")
    page.locator("#save-brief-settings").click()
    page.wait_for_load_state()
    page.locator("#run-brief").click()
    assert _wait(lambda: _setting(ready_bot, "inbox.brief_email_error"))
    page.goto(ready_bot.base + PATH)
    expect(page.locator("#brief-email-error")).to_contain_text("The brief email failed")
    ready_bot.set_setting("email_allowlist", json.dumps(["admin@example.com"]))
    page.uncheck("#email_self")
    page.locator("#save-brief-settings").click()


def _save_admin(page: Page, field) -> None:
    form = page.locator("form", has=field)
    with page.expect_navigation():
        form.locator("button:not([type=button])").last.click()


def test_daily_brief_schedule_in_admin(page: Page, ready_bot) -> None:
    admin_login(page, ready_bot.base)
    page.goto(ready_bot.base + "/admin?tab=bot")
    field = page.locator("#job_schedule_daily_brief")
    expect(field).to_have_value("daily 07:00")
    field.fill("daily 06:30")
    _save_admin(page, field)
    page.goto(ready_bot.base + "/admin?tab=bot")
    expect(page.locator("#job_schedule_daily_brief")).to_have_value("daily 06:30")
    page.locator("#job_schedule_daily_brief").fill("daily 07:00")
    _save_admin(page, page.locator("#job_schedule_daily_brief"))
