"""Windows/standalone launcher — starts the local backend and opens the web panel.

Used by the frozen executable (PyInstaller, onefile) and directly in dev:

    python installer/windows/run_supermarket.py

Design notes (phase 6):
- User data (SQLite DB, logs, per-install JWT secret) lives in ``~/SupermarketSystem``
  so reinstalling/updating the app never wipes data.
- The JWT secret is generated once per install and persisted — tokens survive
  restarts (root-cause fix vs falling back to the dev default key).
- The browser opens only after ``/health`` answers 200 (real readiness probe),
  not after a bare TCP connect.
"""
from __future__ import annotations

import logging
import os
import secrets
import socket
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

APP_NAME = "SupermarketSystem"


def backend_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))  # type: ignore[arg-type]
    return Path(__file__).resolve().parent.parent.parent / "backend"


def data_dir() -> Path:
    base = Path.home() / APP_NAME
    (base / "logs").mkdir(parents=True, exist_ok=True)
    return base


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def persistent_secret(base: Path) -> str:
    """Return SECRET_KEY from env, or the per-install persisted key, or a new one."""
    env_key = os.environ.get("SECRET_KEY", "").strip()
    if env_key:
        return env_key
    key_file = base / "secret.key"
    if key_file.exists():
        key = key_file.read_text(encoding="utf-8").strip()
        if key:
            return key
    key = secrets.token_hex(32)
    key_file.write_text(key, encoding="utf-8")
    try:  # best-effort: only the user may read the key
        os.chmod(key_file, 0o600)
    except OSError:
        pass
    return key


def wait_healthy(port: int, timeout: float = 30.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1.0) as resp:
                if resp.status == 200:
                    return True
        except OSError:
            pass
        time.sleep(0.25)
    return False


def main() -> None:
    base = data_dir()
    sys.path.insert(0, str(backend_dir()))

    os.environ.setdefault("DATABASE_URL", f"sqlite:///{base / 'supermarket.db'}")
    os.environ.setdefault("SECRET_KEY", persistent_secret(base))
    if getattr(sys, "frozen", False):
        os.environ.setdefault("ENVIRONMENT", "production")

    log_file = base / "logs" / "supermarket.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.FileHandler(log_file, encoding="utf-8"), logging.StreamHandler(sys.stdout)],
    )
    log = logging.getLogger("launcher")

    import uvicorn
    from app.database import init_db

    init_db()

    port = free_port()
    log.info("data dir: %s", base)
    log.info("log file: %s", log_file)

    server = threading.Thread(
        target=uvicorn.run,
        args=("app.main:app",),
        kwargs={"host": "127.0.0.1", "port": port, "log_level": "warning"},
        daemon=True,
    )
    server.start()

    url = f"http://127.0.0.1:{port}"
    print(f"Supermarket System is starting at {url}")
    if wait_healthy(port):
        log.info("healthy, opening browser")
        webbrowser.open(url)
    else:
        log.error("backend did not become healthy in time; open %s manually", url)
        print(f"Backend slow to start — open {url} in your browser.")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Shutting down. Goodbye!")


if __name__ == "__main__":
    main()
