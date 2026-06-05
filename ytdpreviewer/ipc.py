"""Local IPC so Explorer can open files in the running background process."""

from __future__ import annotations

import socket
import threading
from typing import Callable

HOST = "127.0.0.1"
PORT = 47321
ENCODING = "utf-8"


def send_path(path: str, timeout: float = 0.08) -> bool:
    """Send a file path to the background listener. Returns True if delivered."""
    try:
        with socket.create_connection((HOST, PORT), timeout=timeout) as sock:
            sock.sendall(path.encode(ENCODING))
        return True
    except OSError:
        return False


def start_listener(on_path: Callable[[str], None]) -> threading.Thread:
    """Start a daemon thread that receives paths and calls on_path."""

    def run() -> None:
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((HOST, PORT))
        server.listen(5)
        try:
            while True:
                conn, _ = server.accept()
                with conn:
                    data = conn.recv(65536)
                    if not data:
                        continue
                    path = data.decode(ENCODING).strip("\x00")
                    if path:
                        on_path(path)
        finally:
            server.close()

    thread = threading.Thread(target=run, name="ytd-ipc", daemon=True)
    thread.start()
    return thread
