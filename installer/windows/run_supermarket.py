"""Windows/standalone launcher — starts the local backend and opens the web panel.

Used by the frozen executable (PyInstaller, onefile) and directly in dev:

    python installer/windows/run_supermarket.py

Design notes (phase 6):
- User data (SQLite DB, logs, per-install JWT secret) lives in ``~/SupermarketSystem``
  so reinstalling/updating the app never wipes data.
- The JWT secret is generated once per install and persisted — tokens survive
  restarts (root-cause fix vs falling back to the dev default key).
- The window opens only after ``/health`` answers 200 (real readiness probe),
  not after a bare TCP connect.

Design notes (v1.0.0, §19 — dedicated desktop window):
- The panel opens in a **dedicated application window**, not as a tab in
  whatever browser happens to be default. Edge/Chrome "app mode"
  (``--app=URL``) gives a chrome-less, resizable window with its own taskbar
  entry and its own profile — a real desktop shell, with no 100 MB embedded
  browser runtime to ship and no extra dependency to freeze.
- Edge ships with every Windows 10/11, so this works on a clean install.
  Chrome is tried next; the plain default browser is the last resort and is
  reached only if no app-mode engine could be started.
- ``SUPERMARKET_BROWSER_MODE=system`` forces the old behaviour, for the rare
  machine where a locked-down policy blocks app mode.
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


# ---------------------------------------------------------------------------
# §19 — dedicated desktop window
# ---------------------------------------------------------------------------
#: App-mode engines, best first. Edge is part of Windows 10/11 itself, so it is
#: the only one that can be relied on for a clean install.
_APP_MODE_CANDIDATES = (
    ("msedge", (
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    )),
    ("chrome", (
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    )),
)


def find_app_mode_browser():
    """Locate a browser that supports ``--app`` window mode.

    Returns ``(exe_path, engine_name)`` or ``None``. Deliberately returns
    ``None`` on non-Windows platforms instead of raising: the launcher must
    degrade to the default browser rather than crash, and it keeps this module
    importable (and therefore testable) on the Linux build machine.
    """
    if sys.platform != "win32":
        return None

    import winreg

    def from_registry(name: str):
        """HKLM/HKCU App Paths is where Windows records the real install path.

        Reading it beats guessing directories: an per-user Chrome install, or
        an Edge that was moved, is still found.
        """
        for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                with winreg.OpenKey(hive, rf"SOFTWARE\Microsoft\Windows\CurrentVersion"
                                          rf"\App Paths\{name}.exe") as key:
                    value = winreg.QueryValue(key, None)
                    if value and Path(value).exists():
                        return value
            except OSError:
                continue
        return None

    for engine, paths in _APP_MODE_CANDIDATES:
        found = from_registry(engine)
        if found:
            return found, engine
        for candidate in paths:
            if Path(candidate).exists():
                return candidate, engine
    return None


def open_window(url: str, base: Path, log):
    """Open the panel in a dedicated window; fall back to the default browser.

    Returns the ``Popen`` handle for the window, or ``None`` when the system
    browser was used instead (a browser tab is owned by the browser process, so
    there is nothing for us to track).
    """
    if os.environ.get("SUPERMARKET_BROWSER_MODE", "").strip().lower() == "system":
        log.info("SUPERMARKET_BROWSER_MODE=system — using the default browser")
        webbrowser.open(url)
        return None

    import subprocess

    found = find_app_mode_browser()
    if not found:
        log.warning("no app-mode browser engine found; falling back to the default browser")
        webbrowser.open(url)
        return None

    exe, engine = found
    # A private profile keeps the app out of the user's personal browsing
    # session (no shared cookies/extensions) and stops Chrome/Edge from
    # handing the URL to an already-running window of the user's own profile,
    # which would defeat the whole point of a dedicated window.
    profile = base / "webview-profile"
    profile.mkdir(parents=True, exist_ok=True)
    argv = [
        exe,
        f"--app={url}",
        f"--user-data-dir={profile}",
        "--new-window",
        "--window-size=1440,900",
        "--disable-session-crashed-bubble",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    try:
        proc = subprocess.Popen(argv, close_fds=True)
    except OSError as exc:
        log.error("could not start %s (%s); falling back to the default browser", exe, exc)
        webbrowser.open(url)
        return None

    # A browser that refuses the flags exits immediately. Detect that here and
    # fall back, rather than leaving the user staring at nothing.
    try:
        proc.wait(timeout=2.0)
    except subprocess.TimeoutExpired:
        log.info("dedicated window started via %s (pid %s)", engine, proc.pid)
        return proc

    log.error("%s exited immediately (code %s); falling back to the default browser",
              engine, proc.returncode)
    webbrowser.open(url)
    return None


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
    window = None
    if wait_healthy(port):
        log.info("healthy, opening the application window")
        window = open_window(url, base, log)
    else:
        log.error("backend did not become healthy in time; open %s manually", url)
        print(f"Backend slow to start — open {url} in your browser.")

    try:
        while True:
            time.sleep(1)
            # If the user closes the application window the process should end
            # too, otherwise a headless server is left holding the port and the
            # shortcut appears to "do nothing" on the next launch.
            if window is not None and window.poll() is not None:
                log.info("application window closed (exit %s); shutting down",
                         window.returncode)
                break
    except KeyboardInterrupt:
        print("Shutting down. Goodbye!")
    finally:
        if window is not None and window.poll() is None:
            window.terminate()


def _fatal(exc: BaseException) -> None:
    """Show a readable message (and where the log is) instead of PyInstaller's
    raw 'Unhandled exception in script' dialog; the full traceback is logged."""
    import traceback

    base = data_dir()
    log_file = base / "logs" / "supermarket.log"
    try:
        with open(log_file, "a", encoding="utf-8") as fh:
            fh.write("\n=== FATAL on startup ===\n" + traceback.format_exc())
    except Exception:
        pass
    msg = (
        "برنامه هنگام شروع با خطا مواجه شد و اجرا نشد.\n\n"
        f"{type(exc).__name__}: {str(exc)[:600]}\n\n"
        f"گزارش کامل: {log_file}\n"
        f"پایگاه داده: {base / 'supermarket.db'}\n\n"
        "اگر این خطا پس از به‌روزرسانی رخ داده، از پایگاه داده نسخهٔ پشتیبان بگیرید و دوباره اجرا کنید؛ "
        "در صورت تکرار، فایل گزارش را برای پشتیبانی ارسال کنید."
    )
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, msg, "Supermarket System", 0x10 | 0x100000)  # MB_ICONERROR | MB_RTLREADING
    except Exception:
        print(msg, file=sys.stderr)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception as exc:  # noqa: BLE001
        _fatal(exc)
        sys.exit(1)
