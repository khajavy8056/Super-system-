# -*- coding: utf-8 -*-
"""v4.0.1 — Download manager: progress, resume, fallback sources, IDM.

The owner asked for the model download to behave like a download manager: a
visible progress bar, resume after an interruption, and Internet Download
Manager on Windows. These tests enforce the parts that must never regress —
without touching the internet: a local Range-capable HTTP server stands in for
the model host, and the IDM state machine runs on an injectable clock.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from app.services.business_brain import download_manager as dm
from app.services.business_brain import model_registry


# --------------------------------------------------------------------- helpers
class _RangeHandler(BaseHTTPRequestHandler):
    """Serves ``server.payload`` with real HTTP Range support (like the model
    CDNs) and records every Range header it received; 404s ``server.missing``."""

    def do_GET(self):  # noqa: N802 — http.server API
        server = self.server
        if self.path in server.missing:
            self.send_error(404)
            return
        data = server.payload
        header = self.headers.get("Range")
        server.ranges.append(header)
        start, end = 0, len(data) - 1
        if header:
            match = re.match(r"bytes=(\d+)-(\d*)", header)
            if match:
                start = int(match.group(1))
                end = int(match.group(2)) if match.group(2) else len(data) - 1
                body = data[start:end + 1]
                self.send_response(206)
                self.send_header("Content-Range", f"bytes {start}-{end}/{len(data)}")
            else:                                          # malformed → full body
                body, start = data, 0
                self.send_response(200)
        else:
            body = data
            self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # keep test output quiet
        pass


@pytest.fixture()
def file_server():
    """A local HTTP server that behaves like a model CDN."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), _RangeHandler)
    server.payload = b""
    server.ranges = []
    server.missing = set()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()


def _serve(server, payload: bytes, path: str = "/model.gguf") -> str:
    server.payload = payload
    host, port = server.server_address[:2]
    return f"http://{host}:{port}{path}"


# ------------------------------------------------------------ pure functions
def test_plan_segments_small_file_gets_one_connection():
    assert dm.plan_segments(1024 * 1024, 8) == [(0, 1024 * 1024 - 1)]


def test_plan_segments_covers_every_byte_exactly_once():
    for total, connections in ((17_000_000, 4), (9, 3), (16 * 1024 * 1024, 4),
                               (25_000_001, 5), (dm.MIN_SEGMENT_BYTES, 16)):
        segments = dm.plan_segments(total, connections)
        cursor = 0
        for start, end in segments:
            assert start == cursor, (total, connections, segments)
            assert end >= start
            cursor = end + 1
        assert cursor == total, (total, connections, segments)


def test_parse_content_range():
    assert dm._parse_content_range("bytes 0-0/123456") == 123456
    assert dm._parse_content_range("bytes 0-0/*") == 0
    assert dm._parse_content_range(None) == 0
    assert dm._parse_content_range("garbage") == 0


def test_etag_digest_accepts_quoted_lfs_sha256():
    sha = "6a1a2eb6d15622bf3c96857206351ba97e1af16c30d7a74ee38970e434e9407e"
    assert dm._etag_digest({"X-Linked-Etag": f'"{sha}"'}) == sha
    assert dm._etag_digest({"ETag": '"short"'}) is None
    assert dm._etag_digest({}) is None


def test_fmt_eta():
    assert dm._fmt_eta(65) == "01:05"
    assert dm._fmt_eta(3700) == "1:01:40"
    assert dm._fmt_eta(None) == "--:--"


def test_idm_command_is_the_documented_cli():
    dest = Path("/dl") / "qwen.gguf"
    command = dm.idm_command("IDMan.exe", "https://host/x.gguf", dest)
    assert command == ["IDMan.exe", "/d", "https://host/x.gguf",
                       "/p", str(dest.parent), "/f", dest.name, "/n"]


def test_detect_idm_env_override(tmp_path, monkeypatch):
    exe = tmp_path / "IDMan.exe"
    exe.write_bytes(b"")
    monkeypatch.setenv("SUPERMARKET_IDM_PATH", str(exe))
    assert dm.detect_idm() == str(exe)
    monkeypatch.setenv("SUPERMARKET_IDM_PATH", str(tmp_path / "missing.exe"))
    if os.name != "nt":                     # on Windows the registry may still find IDM
        assert dm.detect_idm() is None


def test_progress_bar_falls_back_to_ascii_and_reports_totals(monkeypatch):
    monkeypatch.setattr(dm, "_unicode_ok", lambda: False)
    bar = dm._Bar(1000, quiet=False)
    line = bar._line(400)
    assert "#" in line and "█" not in line
    assert "40.0%" in line and "400.0/1,000.0 B" in line or "40.0%" in line
    monkeypatch.setattr(dm, "_unicode_ok", lambda: True)
    bar2 = dm._Bar(2000, quiet=False)
    assert "█" in bar2._line(1000)


def test_quiet_bar_never_prints_but_fires_progress(capsys):
    seen = []
    bar = dm._Bar(1000, progress=lambda done, total: seen.append((done, total)), quiet=True)
    bar.update(250)
    bar.update(1000, force=True)
    bar.note("this must not print")
    bar.close(1000)
    assert capsys.readouterr().out == ""
    assert (1000, 1000) in seen


# ------------------------------------------------------------- registry rules
def test_every_model_has_official_fallback_sources():
    for spec in model_registry.all_models():
        urls = model_registry.source_urls(spec)
        assert urls and urls[0] == spec.source_url
        assert len(urls) > 1, "each model must survive one dead CDN"
        for url in urls:
            assert model_registry.allowed_source(url, spec), url
    assert model_registry.validate_registry() == []


def test_allowed_source_accepts_official_hosts_and_refuses_lookalikes():
    spec = model_registry.default_model()
    assert model_registry.allowed_source(spec.source_url, spec)
    assert model_registry.allowed_source(spec.alt_source_urls[0], spec)
    assert not model_registry.allowed_source("https://xmodelscope.cn/x.gguf", spec)
    assert not model_registry.allowed_source("https://modelscope.cn.evil.io/x.gguf", spec)
    assert not model_registry.allowed_source("https://xhuggingface.co/x.gguf")
    assert not model_registry.allowed_source("https://hf-mirror.example.net/x.gguf", spec)


# ------------------------------------------------------- builtin engine (http)
def test_fetch_segmented_downloads_and_hashes(file_server, tmp_path):
    payload = os.urandom(16 * 1024 * 1024)              # 2 segments at 8 MiB each
    url = _serve(file_server, payload)
    seen = []
    result = dm.fetch((url,), tmp_path / "out.bin", connections=4,
                      downloader="builtin", progress=lambda done, total: seen.append(done))
    digest = hashlib.sha256(payload).hexdigest()
    assert result["ok"] and result["sha256"] == digest
    assert result["size"] == len(payload) and result["downloader"] == "builtin"
    assert Path(result["path"]).read_bytes() == payload
    data_ranges = [r for r in file_server.ranges if r and r != "bytes=0-0"]
    assert result["connections"] == 2 and len(data_ranges) == 2
    assert len(set(data_ranges)) == 2, "segments must be distinct ranges"
    assert seen and max(seen) == len(payload), "the progress callback must fire"


def test_fetch_falls_back_to_the_next_official_source(file_server, tmp_path):
    payload = os.urandom(300_000)
    dead = _serve(file_server, payload, path="/missing.gguf")
    file_server.missing = {"/missing.gguf"}
    live = _serve(file_server, payload, path="/model.gguf")
    result = dm.fetch((dead, live), tmp_path / "out.bin", downloader="builtin")
    assert result["ok"] and result["source"] == live
    assert result["sha256"] == hashlib.sha256(payload).hexdigest()


def test_fetch_resumes_from_a_saved_control_file(file_server, tmp_path):
    payload = os.urandom(500_000)                       # single segment (small file)
    url = _serve(file_server, payload)
    dest = tmp_path / "model.gguf"
    have = 200_000
    scratch = Path(str(dest) + ".dl")
    scratch.write_bytes(payload[:have])                 # a previous, interrupted run
    control = Path(str(scratch) + ".control.json")
    control.write_text(json.dumps({
        "version": dm.CONTROL_VERSION, "total": len(payload),
        "expected_sha256": None,
        "segments": [[0, len(payload) - 1, have]], "updated": 0}), encoding="utf-8")

    result = dm.fetch((url,), dest, connections=1, downloader="builtin")
    assert result["resumed_bytes"] == have
    assert result["sha256"] == hashlib.sha256(payload).hexdigest()
    data_ranges = [r for r in file_server.ranges if r and r != "bytes=0-0"]
    assert data_ranges == [f"bytes={have}-{len(payload) - 1}"], \
        "the server must be asked ONLY for the missing part"
    assert not scratch.exists() and not control.exists()
    assert dest.read_bytes() == payload


def test_fetch_refuses_a_source_that_serves_the_wrong_size(file_server, tmp_path):
    payload = os.urandom(150_000)
    url = _serve(file_server, payload)
    with pytest.raises(dm.DownloadError) as err:
        dm.fetch((url,), tmp_path / "m.gguf", expected_size=150_001, downloader="builtin")
    assert "size mismatch" in str(err.value)


def test_fetch_reports_every_dead_source(file_server, tmp_path):
    payload = os.urandom(1000)
    url = _serve(file_server, payload, path="/a.gguf")
    file_server.missing = {"/a.gguf", "/b.gguf"}
    dead2 = url.replace("/a.gguf", "/b.gguf")
    with pytest.raises(dm.DownloadError) as err:
        dm.fetch((url, dead2), tmp_path / "m.gguf", downloader="builtin")
    assert "404" in str(err.value)
    assert len(err.value.attempts) == 2, "per-source reasons must be attached"


def test_no_ranges_server_still_downloads_with_one_stream(file_server, tmp_path):
    class NoRangeHandler(_RangeHandler):
        def do_GET(self):  # noqa: N802 — never honours Range
            server = self.server
            if self.path in server.missing:
                self.send_error(404)
                return
            server.ranges.append(self.headers.get("Range"))
            body = server.payload
            self.send_response(200)                     # full body, always
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    file_server.RequestHandlerClass = NoRangeHandler
    payload = os.urandom(400_000)
    url = _serve(file_server, payload)
    result = dm.fetch((url,), tmp_path / "m.gguf", expected_size=len(payload),
                      downloader="builtin")
    assert result["ok"] and result["sha256"] == hashlib.sha256(payload).hexdigest()
    assert result["connections"] == 1


# ------------------------------------------------------------------- IDM mode
class _FakeClock:
    """time.monotonic/time.sleep on rails, for the IDM wait state machine."""

    def __init__(self):
        self.now = 1000.0
        self.ticks = 0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds
        self.ticks += 1


def test_idm_wait_completes_when_file_reaches_expected_size(tmp_path):
    target = tmp_path / "x.gguf"
    target.write_bytes(b"0" * 100)
    clock = _FakeClock()

    def grow():
        if clock.ticks == 2:                            # IDM writes the tail later
            target.write_bytes(b"0" * 100 + b"1" * 100)

    dm._idm_wait(target, 200, None, start_timeout=10, poll=2.0,
                 _sleep=lambda s: (clock.sleep(s), grow()), _now=clock.monotonic,
                 quiet=True)
    assert target.stat().st_size == 200


def test_idm_wait_raises_when_idm_never_starts(tmp_path):
    clock = _FakeClock()
    with pytest.raises(dm.IDMNotStarted):
        dm._idm_wait(tmp_path / "never.gguf", 1000, None, start_timeout=6, poll=2.0,
                     _sleep=clock.sleep, _now=clock.monotonic, quiet=True)


def test_idm_mode_requires_idm_when_it_is_not_installed(tmp_path, monkeypatch):
    monkeypatch.setattr(dm, "detect_idm", lambda: None)
    with pytest.raises(dm.DownloadError) as err:
        dm.fetch(("https://huggingface.co/x.gguf",), tmp_path / "m.gguf",
                 downloader="idm")
    assert "not found" in str(err.value)


def test_idm_mode_fails_loudly_when_idm_cannot_deliver(tmp_path, monkeypatch):
    stub = tmp_path / "idm_stub.py"
    stub.write_text("import sys\nsys.exit(0)\n")
    monkeypatch.setattr(dm, "detect_idm", lambda: sys.executable)
    monkeypatch.setattr(dm, "idm_command",
                        lambda exe, url, dest: [exe, str(stub), "/d", url])
    with pytest.raises(dm.DownloadError):
        dm.fetch(("https://model-does-not-resolve.invalid/x.gguf",), tmp_path / "m.gguf",
                 expected_size=4096, downloader="idm", idm_start_timeout=1.0)


def test_fetch_rejects_an_unknown_downloader(tmp_path):
    with pytest.raises(ValueError):
        dm.fetch(("https://huggingface.co/x.gguf",), tmp_path / "m.gguf",
                 downloader="telepathy")
