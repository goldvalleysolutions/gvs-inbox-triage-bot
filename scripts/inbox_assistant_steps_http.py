"""Drive the Inbox Assistant walkthrough against a running image (CI + make)."""

from __future__ import annotations

import json
import re
import secrets
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path

import httpx2

from core.auth.token import load_private_key, public_openssh, sign_token
from tests.mcp_helpers import call_tool, enable_mcp_http, list_tools

BRAND = "Inbox Assistant in a Box"


def _opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))


def request(
    opener: urllib.request.OpenerDirector,
    base: str,
    method: str,
    path: str,
    data: dict[str, str] | bytes | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, str]:
    body: bytes | None = None
    hdrs = dict(headers or {})
    if isinstance(data, dict):
        body = urllib.parse.urlencode(data).encode()
        hdrs.setdefault("Content-Type", "application/x-www-form-urlencoded")
    elif isinstance(data, bytes):
        body = data
    req = urllib.request.Request(base + path, data=body, headers=hdrs, method=method)
    try:
        resp = opener.open(req, timeout=20)
        return resp.status, resp.read().decode()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode()


def csrf_from(html: str) -> str:
    match = re.search(r"name=csrf value='([^']+)'", html)
    if not match:
        raise SystemExit("no csrf field in " + html[:400])
    return match.group(1)


def post_form(
    opener: urllib.request.OpenerDirector,
    base: str,
    path: str,
    fields: dict[str, str],
    html: str | None = None,
) -> tuple[int, str]:
    if html is None:
        _, html = request(opener, base, "GET", path)
    payload = dict(fields)
    payload["csrf"] = csrf_from(html)
    return request(opener, base, "POST", path, payload)


def ask(opener: urllib.request.OpenerDirector, base: str, text: str) -> dict:
    code, raw = request(
        opener,
        base,
        "POST",
        "/api/ask",
        json.dumps({"text": text}).encode(),
        {"Content-Type": "application/json"},
    )
    if code != 200:
        raise SystemExit(f"/api/ask {code}: {raw[:300]}")
    return json.loads(raw)


def main() -> None:
    base, smtp_port, repo, cname = sys.argv[1:5]
    key_path = Path(repo) / "tests" / "fixtures" / "gvs_test_ed25519"
    opener = _opener()

    print("step 1 setup")
    code, html = request(opener, base, "GET", "/setup")
    assert code == 200, code
    code, _ = post_form(
        opener,
        base,
        "/setup",
        {
            "step": "box_admin",
            "username": "admin",
            "password": "secret12",
            "email": "admin@example.com",
        },
        html,
    )
    assert code in {200, 303}, code
    code, html = request(opener, base, "GET", "/setup")
    code, _ = post_form(
        opener,
        base,
        "/setup",
        {"step": "model", "provider": "stub", "model": "stub", "spend_cap": "25"},
        html,
    )
    assert code in {200, 303}, code
    code, html = request(opener, base, "GET", "/setup")
    code, _ = post_form(
        opener,
        base,
        "/setup",
        {
            "step": "connectors",
            "SMTP_HOST": "host.docker.internal",
            "SMTP_PORT": smtp_port,
            "SMTP_FROM": "box@example.com",
        },
        html,
    )
    assert code in {200, 303}, code
    code, html = request(opener, base, "GET", "/setup")
    if "value=wizard" in html:
        raise SystemExit("inbox-assistant must not add a wizard step")
    code, _ = post_form(opener, base, "/setup", {"step": "self_test"}, html)
    assert code in {200, 303}, code
    code, home = request(opener, base, "GET", "/")
    assert code == 200 and BRAND in home
    assert "Powered by Gold Valley Solutions" in home

    print("step 2 clock")
    assert ask(opener, base, "CALL clock.now {}")["blocked"] is False

    print("step 3 notes")
    assert ask(opener, base, 'CALL notes {"text":"follow up invoice 1041"}')["blocked"] is False

    print("step 4 email")
    ask(
        opener,
        base,
        'CALL email.send {"to":"admin@example.com","subject":"Re: invoice 1041","body":"paid"}',
    )

    print("step 5 web blocked")
    assert ask(opener, base, "CALL web.browse {}")["blocked"] is True

    print("step 6 root edit")
    Path("/tmp/gvs_test.pub").write_text(public_openssh(load_private_key(key_path)))
    subprocess.check_call(["docker", "cp", "/tmp/gvs_test.pub", f"{cname}:/tmp/gvs_test.pub"])
    subprocess.check_call(
        ["docker", "exec", "-u", "0", cname, "cp", "/tmp/gvs_test.pub", "/app/keys/gvs_root.pub"]
    )
    box_id = subprocess.check_output(
        [
            "docker",
            "exec",
            cname,
            "python",
            "-c",
            "import sqlite3; c=sqlite3.connect('/data/bot.db'); "
            "print(c.execute(\"select value from settings where key='box_id'\").fetchone()[0])",
        ],
        text=True,
    ).strip()
    token = sign_token(load_private_key(key_path), box_id, secrets.token_urlsafe(8))
    code, _ = request(opener, base, "GET", "/gvs/login?token=" + token)
    assert code in {303, 200}, code
    code, role_html = request(opener, base, "GET", "/gvs/role")
    assert code == 200, code
    code, _ = post_form(
        opener,
        base,
        "/gvs/role",
        {"text": "You are Maple Inbox, a maple-shop clerk. You do not browse the web."},
        role_html,
    )
    assert code in {200, 303}, code
    assert "Maple Inbox" in ask(opener, base, "who are you?")["text"]

    print("step 7 box admin 404")
    admin = _opener()
    code, login_html = request(admin, base, "GET", "/admin/login")
    assert code == 200
    code, _ = post_form(
        admin,
        base,
        "/admin/login",
        {"username": "admin", "password": "secret12"},
        login_html,
    )
    assert code in {200, 303}, code
    for path in ("/gvs/role", "/gvs/skills", "/gvs/memory", "/gvs/activity"):
        code, body = request(admin, base, "GET", path)
        assert code == 404, (path, code)
        assert BRAND in body

    print("step 8 model switch (dummy key, then stub)")
    code, settings_html = request(admin, base, "GET", "/admin")
    assert code == 200
    code, _ = post_form(
        admin,
        base,
        "/admin/settings",
        {
            "provider": "openai_compat",
            "model": "gpt-4o-mini",
            "api_key": "sk-not-a-real-key",
        },
        settings_html,
    )
    assert code in {200, 303}, code
    code, settings_html = request(admin, base, "GET", "/admin")
    assert "sk-not-a-real-key" not in settings_html
    code, _ = post_form(
        admin, base, "/admin/settings", {"provider": "stub", "model": "stub"}, settings_html
    )
    assert code in {200, 303}, code
    print("step 9 mcp")
    http = httpx2.Client(base_url=base, follow_redirects=True, timeout=30.0)
    token = enable_mcp_http(http, mode="read_only", name="inbox")
    names = list_tools(f"{base}/mcp", token)
    assert "ask" in names and "email.send" not in names, names
    asked = call_tool(f"{base}/mcp", token, "ask", {"text": "ping"})
    assert "(stub)" in asked or "ping" in asked, asked
    http.post("/api/admin/mcp", json={"mode": "write_with_approval"}).raise_for_status()
    pending = json.loads(
        call_tool(
            f"{base}/mcp",
            token,
            "email.send",
            {"to": "admin@example.com", "subject": "invoice", "body": "draft reply"},
        )
    )
    assert pending["status"] == "pending_approval", pending
    approved = http.post(f"/api/approvals/{pending['id']}/approve").json()
    assert approved["status"] == "approved", approved
    http.close()
    print("OK inbox-assistant-steps")


if __name__ == "__main__":
    main()
