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


def _bind_std_streams(log_file: Path) -> None:
    """In a windowed (console=False) PyInstaller build ``sys.stdout`` and
    ``sys.stderr`` are ``None``. Anything that touches them - ``print``,
    ``logging.StreamHandler(sys.stdout)``, uvicorn's default log config
    (``sys.stdout.isatty()``) - raises, and because the server ran on a
    daemon thread that exception was swallowed: the process sat idle with no
    window and no error (the v1.2.5 report). Redirect both streams to the
    log file so nothing can ever trip on a missing console again."""
    if sys.stdout is None or sys.stderr is None or getattr(sys, "frozen", False):
        try:
            fh = open(log_file, "a", encoding="utf-8", buffering=1)
            if sys.stdout is None or getattr(sys, "frozen", False):
                sys.stdout = fh
            if sys.stderr is None or getattr(sys, "frozen", False):
                sys.stderr = fh
        except OSError:
            import io

            sys.stdout = sys.stdout or io.StringIO()
            sys.stderr = sys.stderr or io.StringIO()


def _message_box(text: str, title: str = "Supermarket System", icon: int = 0x10) -> None:
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, text, title, icon | 0x100000)  # MB_RTLREADING
    except Exception:
        print(text, file=sys.stderr)


def _single_instance_port(base: Path) -> int | None:
    """If a previous instance is still serving, return its port so a second
    click re-opens the window instead of silently starting a duplicate."""
    pf = base / "server.port"
    try:
        port = int(pf.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1.0) as resp:
            if resp.status == 200:
                return port
    except OSError:
        pass
    return None


def main() -> None:
    base = data_dir()
    log_file = base / "logs" / "supermarket.log"
    _bind_std_streams(log_file)
    sys.path.insert(0, str(backend_dir()))

    os.environ.setdefault("DATABASE_URL", f"sqlite:///{base / 'supermarket.db'}")
    os.environ.setdefault("SECRET_KEY", persistent_secret(base))
    if getattr(sys, "frozen", False):
        os.environ.setdefault("ENVIRONMENT", "production")

    handlers: list[logging.Handler] = [logging.FileHandler(log_file, encoding="utf-8")]
    if not getattr(sys, "frozen", False) and sys.stdout is not None:
        handlers.append(logging.StreamHandler(sys.stdout))
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
        force=True,
    )
    logging.getLogger("alembic").setLevel(logging.WARNING)
    log = logging.getLogger("launcher")
    log.info("=== launcher start (frozen=%s, exe=%s) ===", getattr(sys, "frozen", False), sys.executable)

    # Second click while already running -> just bring the panel up again.
    running = _single_instance_port(base)
    if running:
        log.info("instance already running on port %s; opening window only", running)
        open_window(f"http://127.0.0.1:{running}", base, log)
        return

    import uvicorn
    from app.database import init_db

    init_db()

    port = free_port()
    (base / "server.port").write_text(str(port), encoding="utf-8")
    log.info("data dir: %s", base)
    log.info("log file: %s", log_file)

    server_error: dict = {}

    def serve() -> None:
        try:
            # log_config=None: uvicorn's default dictConfig builds console
            # formatters that call sys.stdout.isatty(); with the root logger
            # already configured to the file above, plain propagation is
            # exactly what we want.
            uvicorn.run("app.main:app", host="127.0.0.1", port=port,
                        log_level="warning", log_config=None)
        except BaseException as exc:  # noqa: BLE001
            server_error["exc"] = exc
            log.exception("backend server crashed")

    server = threading.Thread(target=serve, name="uvicorn", daemon=True)
    server.start()

    url = f"http://127.0.0.1:{port}"
    log.info("Supermarket System is starting at %s", url)
    window = None
    if wait_healthy(port):
        log.info("healthy, opening the application window")
        window = open_window(url, base, log)
    else:
        detail = f"{type(server_error['exc']).__name__}: {server_error['exc']}" if server_error else "سرور در ۳۰ ثانیه آماده نشد."
        log.error("backend did not become healthy: %s", detail)
        _message_box(
            "برنامه نتوانست سرویس داخلی خود را راه‌اندازی کند.\n\n"
            f"{detail[:600]}\n\n"
            f"گزارش کامل: {log_file}\n"
            "در صورت تکرار، این فایل را برای پشتیبانی ارسال کنید."
        )
        sys.exit(1)

    try:
        while True:
            time.sleep(1)
            if server_error:
                raise RuntimeError(f"backend stopped: {server_error['exc']}")
            # If the user closes the application window the process should end
            # too, otherwise a headless server is left holding the port and the
            # shortcut appears to "do nothing" on the next launch.
            if window is not None and window.poll() is not None:
                log.info("application window closed (exit %s); shutting down",
                         window.returncode)
                break
    except KeyboardInterrupt:
        pass
    finally:
        try:
            (base / "server.port").unlink()
        except OSError:
            pass


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
    _message_box(msg)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception as exc:  # noqa: BLE001
        _fatal(exc)
        sys.exit(1)
