"""v1.2.6 regression: the Windows launcher must start the backend even when
sys.stdout/sys.stderr are None (PyInstaller console=False). v1.2.5 died
silently there: uvicorn's default log config calls sys.stdout.isatty()."""
from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

LAUNCHER = Path(__file__).resolve().parents[2] / "installer" / "windows" / "run_supermarket.py"


def _data_dir(home: Path) -> Path:
    """v1.0.0 (RASA) — دادهٔ کاربر در ~/RasaSystem است (نام قدیمی: SupermarketSystem)."""
    return home / "RasaSystem"


def test_launcher_becomes_healthy_without_console(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    # v1.0.0 — پوشهٔ نسخه‌های قبلی باید یک‌بار و درجا تحویل گرفته شود (داده دست‌نخورده)
    legacy = home / "SupermarketSystem"
    legacy.mkdir()
    (legacy / "legacy-marker.txt").write_text("data from v4.8.0")
    env = dict(os.environ, HOME=str(home), USERPROFILE=str(home))
    env.pop("DATABASE_URL", None)
    code = (
        # This is a headless logging/readiness test, NOT a real WebView2 test.
        # The required native shell is stubbed instead of restoring a browser fallback.
        "import sys, runpy, types, time; "
        "sys.modules['webview'] = types.SimpleNamespace("
        "create_window=lambda *a, **k: types.SimpleNamespace(events=types.SimpleNamespace()), "
        "start=lambda **k: time.sleep(60)); "
        "sys.stdout = None; sys.stderr = None; "
        f"sys.argv = ['run_supermarket']; runpy.run_path({str(LAUNCHER)!r}, run_name='__main__')"
    )
    proc = subprocess.Popen([sys.executable, "-c", code], env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        port_file = _data_dir(home) / "server.port"
        deadline = time.monotonic() + 40
        healthy = False
        while time.monotonic() < deadline and proc.poll() is None:
            try:
                port = int(port_file.read_text().strip())
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as r:
                    healthy = r.status == 200
                    if healthy:
                        break
            except Exception:
                pass
            time.sleep(0.5)
        assert healthy, (_data_dir(home) / "logs" / "supermarket.log").read_text()[-2000:]
        assert (_data_dir(home) / "legacy-marker.txt").read_text() == "data from v4.8.0", "پوشهٔ قدیمی باید درجا منتقل شود"
        assert not legacy.exists(), "پوشهٔ قدیمی بعد از مهاجرت نباید باقی بماند"
        assert proc.poll() is None, "launcher exited although it was healthy"
    finally:
        proc.kill()
        proc.wait(timeout=10)
