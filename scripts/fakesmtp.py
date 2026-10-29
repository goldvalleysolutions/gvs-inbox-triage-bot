#!/usr/bin/env python3
"""Stdlib SMTP sink. Prints the bound port to stdout and stays up."""

from __future__ import annotations

import socket
import threading


def _handle(conn: socket.socket) -> None:
    try:
        conn.sendall(b"220 fakesmtp\r\n")
        buf = b""
        data_mode = False
        while True:
            chunk = conn.recv(4096)
            if not chunk:
                break
            buf += chunk
            if data_mode:
                if b"\r\n.\r\n" not in buf:
                    continue
                conn.sendall(b"250 ok\r\n")
                buf = b""
                data_mode = False
                continue
            while b"\r\n" in buf:
                line, buf = buf.split(b"\r\n", 1)
                cmd = line.decode("utf-8", "replace").upper()
                if cmd.startswith("EHLO") or cmd.startswith("HELO"):
                    conn.sendall(b"250-fakesmtp\r\n250 8BITMIME\r\n")
                elif cmd.startswith("DATA"):
                    conn.sendall(b"354 go\r\n")
                    data_mode = True
                    break
                elif cmd.startswith("QUIT"):
                    conn.sendall(b"221 bye\r\n")
                    return
                else:
                    conn.sendall(b"250 ok\r\n")
    finally:
        conn.close()


def main() -> None:
    sock = socket.socket()
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", 0))
    sock.listen(16)
    print(sock.getsockname()[1], flush=True)
    while True:
        conn, _ = sock.accept()
        threading.Thread(target=_handle, args=(conn,), daemon=True).start()


if __name__ == "__main__":
    main()
