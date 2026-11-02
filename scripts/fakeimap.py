"""In-process fake IMAP4rev1 server for tests (adapted from gvs-core-bot tests/fakeimap.py). No real mailbox.

``writes`` lists any command that could change the mailbox (STORE, COPY, MOVE,
EXPUNGE, APPEND, DELETE, SELECT, non-PEEK BODY[] fetch...), so a test can prove a
reader is read-only. ``appended`` keeps (folder, flags, message) of each APPEND.
"""

from __future__ import annotations

import contextlib
import re
import socket
import threading

WRITE_COMMANDS = {
    "STORE", "COPY", "MOVE", "EXPUNGE", "APPEND", "DELETE", "RENAME", "CREATE", "SELECT",
    "SUBSCRIBE", "UNSUBSCRIBE", "CLOSE",
}  # fmt: skip


def make_message(n: int, subject: str = "", body: str = "", sender: str = "") -> bytes:
    return (
        f"From: {sender or f'sender{n}@example.com'}\r\nTo: owner@example.com\r\n"
        f"Subject: {subject or f'Message {n}'}\r\nDate: Sun, 01 Nov 2026 09:00:00 -0500\r\n"
        f"Message-ID: <m{n}@example.com>\r\n\r\n{body or f'Body of message {n}.'}\r\n"
    ).encode()


def parse_astring(text: str) -> tuple[str | None, str]:
    """One IMAP astring: a quoted string (backslash escapes) or an atom. Rest follows."""
    if text.startswith('"'):
        out, i = [], 1
        while i < len(text):
            c = text[i]
            if c == "\\" and i + 1 < len(text) and text[i + 1] in '"\\':
                out.append(text[i + 1])
                i += 2
                continue
            if c == '"':
                return "".join(out), text[i + 1 :]
            if c == "\\":
                return None, ""
            out.append(c)
            i += 1
        return None, ""
    atom, _, rest = text.partition(" ")
    if not atom or any(c in atom for c in '(){ %*"\\'):
        return None, ""
    return atom, (" " + rest if rest else "")


class FakeIMAP:
    def __init__(
        self,
        messages: list[bytes] | None = None,
        user: str = "owner@example.com",
        password: str = "app-pass",  # noqa: S107 - fake server
        uidvalidity: int = 7,
        starttls: bool = True,
    ) -> None:
        self.starttls = starttls  # offer STARTTLS (a test cert from scripts/fakecert.py)
        self.mail = {i + 1: m for i, m in enumerate(messages or [])}
        self.user, self.password, self.uidvalidity = user, password, uidvalidity
        self.commands: list[str] = []
        self.writes: list[str] = []
        self.appended: list[tuple[str, str, bytes]] = []
        self.opened: list[str] = []  # mailbox names as parsed (quoted strings decoded)
        self._sock = socket.socket()
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(5)
        self.port = self._sock.getsockname()[1]
        self._stop = False
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> FakeIMAP:
        self.thread.start()
        return self

    def close(self) -> None:
        self._stop = True
        with contextlib.suppress(OSError):
            socket.create_connection(("127.0.0.1", self.port), timeout=0.2).close()
        self._sock.close()

    def _run(self) -> None:
        while not self._stop:
            try:
                self._sock.settimeout(0.3)
                conn, _ = self._sock.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    def _handle(self, conn: socket.socket) -> None:
        from fakecert import server_context

        f = conn.makefile("rb")
        tls = False
        out = conn.sendall
        out(b"* OK fake IMAP ready\r\n")
        with contextlib.suppress(OSError, ValueError):
            while True:
                line = f.readline()
                if not line:
                    return
                text = line.decode("utf-8", "replace").rstrip("\r\n")
                tag, _, rest = text.partition(" ")
                cmd, _, args = rest.partition(" ")
                cmd = cmd.upper()
                self.commands.append(f"{cmd} {args}".strip())
                if cmd == "UID":
                    sub, _, args = args.partition(" ")
                    cmd = "UID " + sub.upper()
                if cmd.split()[-1] in WRITE_COMMANDS:
                    self.writes.append(text)
                if cmd == "CAPABILITY":
                    extra = " STARTTLS" if self.starttls and not tls else ""
                    out(f"* CAPABILITY IMAP4rev1 AUTH=PLAIN{extra}\r\n".encode())
                elif cmd == "STARTTLS" and self.starttls and not tls:
                    out(f"{tag} OK begin TLS\r\n".encode())
                    conn = server_context().wrap_socket(conn, server_side=True)
                    f, out, tls = conn.makefile("rb"), conn.sendall, True
                    continue
                elif cmd == "STARTTLS":
                    out(f"{tag} BAD no STARTTLS\r\n".encode())
                    continue
                elif cmd == "LOGIN":
                    parts = [p.strip('"') for p in args.split(" ")]
                    if parts[:2] != [self.user, self.password]:
                        out(f"{tag} NO [AUTHENTICATIONFAILED] bad login\r\n".encode())
                        continue
                elif cmd in ("EXAMINE", "SELECT"):
                    name, _ = parse_astring(args)
                    if name is None:
                        out(f"{tag} BAD mailbox name\r\n".encode())
                        continue
                    self.opened.append(name)
                    out(f"* {len(self.mail)} EXISTS\r\n".encode())
                    out(f"* OK [UIDVALIDITY {self.uidvalidity}] ok\r\n".encode())
                    mode = "READ-ONLY" if cmd == "EXAMINE" else "READ-WRITE"
                    out(f"{tag} OK [{mode}] done\r\n".encode())
                    continue
                elif cmd == "UID SEARCH":
                    m = re.search(r"UID (\d+):\*", args)
                    low = int(m.group(1)) if m else 1
                    hits = [u for u in self.mail if u >= low] or (
                        [max(self.mail)] if self.mail else []
                    )
                    out(("* SEARCH " + " ".join(map(str, hits)) + "\r\n").encode())
                elif cmd == "UID FETCH":
                    if re.search(r"BODY\[", args.upper().replace("BODY.PEEK[", "")):
                        self.writes.append(text)  # a non-PEEK body fetch sets \\Seen
                    ids, _, _ = args.partition(" ")
                    cap = re.search(r"<0\.(\d+)>", args)
                    for seq, uid in enumerate(sorted(self.mail), 1):
                        if str(uid) not in ids.split(","):
                            continue
                        raw = self.mail[uid]
                        part = raw[: int(cap.group(1))] if cap else raw
                        head = f"* {seq} FETCH (UID {uid} RFC822.SIZE {len(raw)} BODY[]<0> "
                        out(head.encode() + f"{{{len(part)}}}\r\n".encode() + part + b")\r\n")
                elif cmd == "APPEND":
                    name, rest = parse_astring(args)
                    m = re.match(r" (\(.*?\)) .*\{(\d+)\}$", rest)
                    if name is None or not m:
                        out(f"{tag} BAD APPEND syntax\r\n".encode())
                        continue
                    out(b"+ go ahead\r\n")
                    data = f.read(int(m.group(2)))
                    f.readline()
                    self.appended.append((name, m.group(1), data))
                elif cmd == "LOGOUT":
                    out(b"* BYE\r\n" + f"{tag} OK bye\r\n".encode())
                    return
                out(f"{tag} OK done\r\n".encode())
