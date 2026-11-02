#!/usr/bin/env python3
"""In-process SMTP sink for CI. No real mail leaves the machine.

Speaks enough ESMTP for smtplib: EHLO lists STARTTLS (test cert, scripts/fakecert.py) and,
after TLS (or always with ``starttls=False``), AUTH PLAIN/LOGIN. ``commands`` records
every line so a test can prove AUTH was never sent without TLS.
"""

from __future__ import annotations

import contextlib
import socket
import threading


class FakeSMTP:
    def __init__(
        self,
        host: str = "127.0.0.1",
        starttls: bool = True,
        user: str = "owner@example.com",
        password: str = "app-pass",
    ) -> None:
        self.messages: list[bytes] = []
        self.commands: list[str] = []
        self.starttls, self.user, self.password = starttls, user, password
        self.host = host
        self._sock = socket.socket()
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((host, 0))
        self._sock.listen(5)
        self.port = self._sock.getsockname()[1]
        self._stop = False
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> FakeSMTP:
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
            try:
                with contextlib.suppress(OSError):  # incl. a refused TLS handshake
                    self._handle(conn)
            finally:
                conn.close()

    def _handle(self, conn: socket.socket) -> None:
        import base64

        from fakecert import server_context

        state = {"conn": conn, "tls": False}

        def send(line: str) -> None:
            state["conn"].sendall(line.encode())  # type: ignore[attr-defined]

        def creds_ok(blob: str) -> bool:
            with contextlib.suppress(ValueError):
                parts = base64.b64decode(blob).split(b"\0")
                return parts[1:] == [self.user.encode(), self.password.encode()]
            return False

        send("220 fake SMTP\r\n")
        data_mode = False
        buf = b""
        while True:
            chunk = state["conn"].recv(4096)  # type: ignore[attr-defined]
            if not chunk:
                return
            buf += chunk
            if data_mode:
                if b"\r\n.\r\n" in buf:
                    self.messages.append(buf)
                    buf = b""
                    data_mode = False
                    send("250 OK\r\n")
                continue
            while b"\r\n" in buf:
                line, buf = buf.split(b"\r\n", 1)
                text = line.decode(errors="replace")
                cmd = text.upper()
                self.commands.append(text)
                if cmd.startswith(("EHLO", "HELO")):
                    tls_line = (
                        "250-STARTTLS\r\n" if self.starttls and not state["tls"] else ""
                    )
                    auth = state["tls"] or not self.starttls
                    send("250-fake\r\n" + tls_line + ("250-AUTH PLAIN\r\n" if auth else "")
                         + "250 OK\r\n")  # fmt: skip
                elif cmd.startswith("STARTTLS") and self.starttls and not state["tls"]:
                    send("220 go ahead\r\n")
                    state["conn"] = server_context().wrap_socket(conn, server_side=True)
                    state["tls"] = True
                    buf = b""
                elif cmd.startswith("AUTH PLAIN"):
                    blob = text.split(" ", 2)[2] if text.count(" ") >= 2 else ""
                    send("235 ok\r\n" if creds_ok(blob) else "535 bad credentials\r\n")
                elif cmd.startswith("DATA"):
                    send("354 go\r\n")
                    data_mode = True
                    break
                elif cmd.startswith("QUIT"):
                    send("221 bye\r\n")
                    return
                else:
                    send("250 OK\r\n")


def main() -> None:
    """CLI for scripts/inbox-triage-steps.sh: print the port, serve until killed.

    The container reaches this test-only server via host.docker.internal (docker0), so it
    listens beyond loopback. Random port, plain SMTP, lives only for the steps run.
    """
    # nosemgrep: python.lang.security.audit.network.bind.avoid-bind-to-all-interfaces
    server = FakeSMTP(host="0.0.0.0", starttls=False).start()
    print(server.port, flush=True)
    with contextlib.suppress(KeyboardInterrupt):
        server.thread.join()


if __name__ == "__main__":
    main()
