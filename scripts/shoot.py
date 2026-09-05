#!/usr/bin/env python3
"""Headless screenshot/PDF tool for the Supermarket web panel (PySide6 WebEngine).

Renders REAL pages from the running server (no mockups) and drives the SPA via
JavaScript. Verified working fully offscreen (no X server, no GPU, no fontconfig):

    LD_LIBRARY_PATH=<stublibs> python scripts/shoot.py scripts/shots.json

Requires the server running (default http://127.0.0.1:8000) and, on hosts
missing system Qt runtime deps (libEGL/libnss/...), stub libraries on
LD_LIBRARY_PATH — see scripts/make_qt_stublibs.py which generates them.

shots.json — a list of groups:

    [{
      "name": "admin",
      "url": "http://127.0.0.1:8000/",
      "viewport": [1440, 900],
      "steps": [ ... ],                 # run after load (e.g. login)
      "shots": [
        {"name": "admin-dashboard", "steps": [ ... ], "wait_ms": 800,
         "pdf": false, "full_height": true}
      ]
    }]

Step kinds: {"js": "<code>"} (awaited), {"wait_ms": 600}.
Outputs PNG to docs/screenshots/<name>.png (+ <name>.pdf when "pdf": true) and
prints a blank-check (distinct-color count) for every capture.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QSG_RHI_BACKEND", "software")  # render Quick widgets without OpenGL
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")
os.environ.setdefault(
    "QTWEBENGINE_CHROMIUM_FLAGS",
    "--no-sandbox --disable-gpu --disable-software-rasterizer --font-render-hinting=none",
)
os.environ.setdefault("QTWEBENGINE_FONT_FAMILY", "Vazirmatn")

from PySide6.QtCore import QEventLoop, QMarginsF, QTimer, QUrl
from PySide6.QtGui import QPageLayout, QPageSize
from PySide6.QtWebEngineCore import QWebEngineProfile
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineWidgets import QWebEngineView

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)


def log(msg: str) -> None:
    print(f"[shoot] {msg}", flush=True)


class Shooter:
    """One QWebEngineView per group (shared profile ⇒ shared localStorage)."""

    def __init__(self) -> None:
        self.app = QApplication.instance() or QApplication(sys.argv[:1])
        self.profile = QWebEngineProfile.defaultProfile()

    # ---- helpers -------------------------------------------------------

    def _wait(self, ms: int) -> None:
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    def _js(self, page, code: str, timeout_ms: int = 20000):
        """Run JavaScript; waits for the returned promise/value."""
        result = {"done": False, "value": None}
        loop = QEventLoop()

        def cb(res):
            result["done"] = True
            result["value"] = res
            loop.quit()

        page.runJavaScript(code, cb)
        QTimer.singleShot(timeout_ms, loop.quit)
        loop.exec()
        if not result["done"]:
            log("  js timeout (continuing)")
        elif result["value"] not in (None, ""):
            # Surface the return value: a silent step that quietly did nothing
            # was previously indistinguishable from one that worked.
            log(f"  js -> {str(result['value'])[:200]}")
        return result["value"]

    def _capture(self, view, name: str, pdf: bool = False, full_height: bool = True,
                base: tuple = None) -> None:
        page = view.page()
        if base and (view.width(), view.height()) != tuple(base):
            view.resize(*base)  # reset any previous full_height stretch
            self._wait(400)
        if full_height:
            # try to size the widget to the full document height for one tall shot
            size = self._js(page, "JSON.stringify([document.documentElement.scrollWidth,"
                                   "Math.max(document.documentElement.scrollHeight,"
                                   "document.body?document.body.scrollHeight:0)])")
            try:
                w, h = json.loads(size)
                w, h = int(w), int(h)
            except Exception:
                w, h = view.width(), view.height()
            h = max(h, 400)
            h = min(h, 4000)  # sanity cap
            view.resize(max(view.width(), min(w, 2200)), h)
            self._wait(700)  # let reflow + repaint settle
        pix = view.grab()
        target = OUT / f"{name}.png"
        pix.save(str(target))
        img = pix.toImage()
        colors = set()
        for y in range(0, img.height(), 3):
            for x in range(0, img.width(), 3):
                colors.add(img.pixel(x, y))
        blank = " (POSSIBLY BLANK!)" if len(colors) < 40 else ""
        log(f"saved {name}.png {pix.width()}x{pix.height()} colors={len(colors)}{blank}")
        if pdf:
            layout = QPageLayout(QPageSize(QPageSize.A4), QPageLayout.Portrait,
                                 QMarginsF(10, 10, 10, 10))
            loop = QEventLoop()
            page.printToPdf(str(OUT / f"{name}.pdf"), layout)
            page.pdfPrintingFinished.connect(lambda *a: loop.quit())
            QTimer.singleShot(30000, loop.quit)
            loop.exec()
            log(f"saved {name}.pdf")

    # ---- group runner ---------------------------------------------------

    def run_group(self, group: dict) -> None:
        name = group["name"]
        w, h = group.get("viewport", [1440, 900])
        view = QWebEngineView()
        view.resize(w, h)
        view.show()  # offscreen platform still needs show() to render
        page = view.page()
        loop = QEventLoop()
        loaded = {"ok": False}

        def on_load(ok: bool) -> None:
            loaded["ok"] = ok
            loop.quit()

        page.loadFinished.connect(on_load)
        log(f"group '{name}': loading {group['url']}")
        view.load(QUrl(group["url"]))
        QTimer.singleShot(60000, loop.quit)
        loop.exec()
        if not loaded["ok"]:
            log(f"  load FAILED for group {name}")
        for step in group.get("steps", []):
            self._run_step(page, step)
        self._wait(group.get("settle_ms", 1200))
        for shot in group.get("shots", []):
            log(f"  shot '{shot['name']}'")
            for step in shot.get("steps", []):
                self._run_step(page, step)
            self._wait(shot.get("wait_ms", 700))
            self._capture(view, shot["name"], pdf=shot.get("pdf", False),
                          full_height=shot.get("full_height", True), base=(w, h))
        view.deleteLater()
        self._wait(300)

    def _run_step(self, page, step: dict) -> None:
        if "js" in step:
            self._js(page, step["js"])
        elif "wait_ms" in step:
            self._wait(step["wait_ms"])


def main() -> None:
    spec_path = sys.argv[1]
    groups = json.loads(Path(spec_path).read_text(encoding="utf-8"))
    shooter = Shooter()
    for group in groups:
        try:
            shooter.run_group(group)
        except Exception as exc:  # keep going; report honestly
            log(f"ERROR in group {group.get('name')}: {exc}")
    log("done")


if __name__ == "__main__":
    main()
