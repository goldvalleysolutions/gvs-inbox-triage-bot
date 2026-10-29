"""Drive the Inbox Assistant walkthrough inside the bot image under test."""

from __future__ import annotations

import json
import re
import secrets
import sqlite3
import sys
import urllib.error
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat
from core.auth.token import load_private_key, public_openssh, sign_token

BRAND = "Inbox Assistant Bot"
MCP_ACCEPT = "application/json, text/event-stream"


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


def json_request(
    opener: urllib.request.OpenerDirector,
    base: str,
    method: str,
    path: str,
    obj: dict,
) -> tuple[int, str]:
    return request(
        opener,
        base,
        method,
        path,
        json.dumps(obj).encode(),
        {"Content-Type": "application/json", "Accept": "application/json"},
    )


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


def _install_runtime_root_key() -> Path:
    priv = Path("/tmp/gvs_test_ed25519")
    priv.write_bytes(
        Ed25519PrivateKey.generate().private_bytes(
            Encoding.PEM, PrivateFormat.OpenSSH, NoEncryption()
        )
    )
    Path("/app/keys/gvs_root.pub").write_text(public_openssh(load_private_key(priv)))
    return priv


def _bot_id() -> str:
    row = sqlite3.connect("/data/bot.db").execute(
        "select value from settings where key='bot_id'"
    ).fetchone()
    if not row:
        raise SystemExit("no bot_id in /data/bot.db")
    return row[0]


def _mcp_body(raw: str) -> dict:
    raw = raw.strip()
    if not raw:
        return {}
    if raw[0] in "{[":
        msg = json.loads(raw)
    else:
        chunks = [ln[5:].strip() for ln in raw.splitlines() if ln.startswith("data:")]
        if not chunks:
            raise SystemExit("no mcp data: " + raw[:400])
        msg = json.loads(chunks[-1])
    if msg.get("error"):
        raise SystemExit(f"mcp error: {msg['error']}")
    return msg.get("result") or {}


def mcp_rpc(
    base: str,
    token: str,
    method: str,
    params: dict | None,
    rpc_id: int | None,
    session: str | None,
) -> tuple[str | None, dict]:
    payload: dict = {"jsonrpc": "2.0", "method": method}
    if rpc_id is not None:
        payload["id"] = rpc_id
    if params is not None:
        payload["params"] = params
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": MCP_ACCEPT,
        "Content-Type": "application/json",
        "Origin": base.rstrip("/"),
    }
    if session:
        headers["Mcp-Session-Id"] = session
    req = urllib.request.Request(
        base.rstrip("/") + "/mcp/",
        data=json.dumps(payload).encode(),
        headers=headers,
        method="POST",
    )
    try:
        resp = urllib.request.urlopen(req, timeout=30)
        body = resp.read().decode()
        sid = resp.headers.get("Mcp-Session-Id") or resp.headers.get("mcp-session-id") or session
        return sid, _mcp_body(body) if rpc_id is not None else {}
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"/mcp/ {method} {exc.code}: {exc.read()[:400]}") from exc


def enable_mcp_token(opener: urllib.request.OpenerDirector, base: str, name: str) -> str:
    code, raw = json_request(opener, base, "POST", "/api/admin/mcp", {"mode": "read_only"})
    if code not in {200, 201, 204}:
        raise SystemExit(f"/api/admin/mcp {code}: {raw[:300]}")
    code, raw = json_request(opener, base, "POST", "/api/admin/mcp/tokens", {"name": name})
    if code not in {200, 201}:
        raise SystemExit(f"/api/admin/mcp/tokens {code}: {raw[:300]}")
    data = json.loads(raw)
    token = data.get("token") or data.get("secret") or data.get("value")
    if not token:
        raise SystemExit("no mcp token in " + raw[:400])
    return token


def mcp_tool_names(base: str, token: str) -> tuple[str | None, list[str]]:
    sid, _ = mcp_rpc(
        base,
        token,
        "initialize",
        {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "inbox-steps", "version": "0"},
        },
        1,
        None,
    )
    mcp_rpc(base, token, "notifications/initialized", None, None, sid)
    sid, result = mcp_rpc(base, token, "tools/list", {}, 2, sid)
    return sid, [t["name"] for t in result.get("tools") or []]


def mcp_call_tool(base: str, token: str, session: str | None, name: str, arguments: dict) -> str:
    _, result = mcp_rpc(
        base, token, "tools/call", {"name": name, "arguments": arguments}, 3, session
    )
    texts = [c.get("text", "") for c in result.get("content") or [] if isinstance(c, dict)]
    return "\n".join(texts)


def main() -> None:
    base, smtp_port = sys.argv[1:3]
    key_path = _install_runtime_root_key()
    opener = _opener()

    print("step 1 setup")
    code, html = request(opener, base, "GET", "/setup")
    assert code == 200, code
    code, _ = post_form(
        opener,
        base,
        "/setup",
        {
            "step": "bot_admin",
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
            "SMTP_FROM": "assistant@example.com",
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
    bot_id = _bot_id()
    token = sign_token(load_private_key(key_path), bot_id, secrets.token_urlsafe(8))
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

    print("step 7 bot admin 404")
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
    mcp_token = enable_mcp_token(admin, base, "inbox")
    session, names = mcp_tool_names(base, mcp_token)
    assert "ask" in names and "email.send" not in names, names
    asked = mcp_call_tool(base, mcp_token, session, "ask", {"text": "ping"})
    assert "(stub)" in asked or "ping" in asked, asked
    code, raw = json_request(
        admin, base, "POST", "/api/admin/mcp", {"mode": "write_with_approval"}
    )
    if code not in {200, 201, 204}:
        raise SystemExit(f"mcp write mode {code}: {raw[:300]}")
    pending_raw = mcp_call_tool(
        base,
        mcp_token,
        session,
        "email.send",
        {"to": "admin@example.com", "subject": "invoice", "body": "draft reply"},
    )
    pending = json.loads(pending_raw)
    assert pending["status"] == "pending_approval", pending
    code, raw = json_request(admin, base, "POST", f"/api/approvals/{pending['id']}/approve", {})
    if code not in {200, 201}:
        raise SystemExit(f"approve {code}: {raw[:300]}")
    approved = json.loads(raw)
    assert approved["status"] == "approved", approved
    print("OK inbox-assistant-steps")


if __name__ == "__main__":
    main()
