"""Windows launcher — starts the local backend and opens the web panel.

Used by the frozen executable (PyInstaller) and usable directly in dev:
    python run_supermarket.py
"""
from __future__ import annotations

import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def backend_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)  # noqa: SLF001
    return Path(__file__).resolve().parent.parent.parent / "backend"


def data_dir() -> Path:
    # Keep user data outside the install dir so updates never wipe the DB.
    base = Path.home() / "SupermarketSystem"
    base.mkdir(parents=True, exist_ok=True)
    return base


def main() -> None:
    sys.path.insert(0, str(backend_dir()))
    os = __import__("os")
    os.environ.setdefault("DATABASE_URL", f"sqlite:///{data_dir() / 'supermarket.db'}")

    port = free_port()
    os.environ.setdefault("PORT", str(port))

    import uvicorn
    from app.database import init_db

    init_db()

    def serve() -> None:
        uvicorn.run("app.main:app", host="127.0.0.1", port=port, log_level="warning")

    threading.Thread(target=serve, daemon=True).start()

    url = f"http://127.0.0.1:{port}"
    print(f"Supermarket System is running at {url}")
    for _ in range(50):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            break
        except OSError:
            time.sleep(0.2)
    webbrowser.open(url)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
