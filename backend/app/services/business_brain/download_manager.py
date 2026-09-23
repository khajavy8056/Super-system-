"""v4.0 — Download manager for Business Brain model files.

The old fetch path was a single ``urlopen`` stream: no progress beyond a raw
MB counter, no resume, no retry, one source. On a shop PC (often on a slow or
filtered connection where huggingface.co is unreachable) that means one hiccup
kills a ~1 GB download and the Windows installer build fails. The owner asked
for a *download manager* with a visible progress bar; this module is that
manager, built on the standard library only — no new dependencies.

What it does
------------
* **Progress bar** — percent, downloaded/total MB, live speed, ETA; renders
  on one console line and falls back to plain ASCII when the console (or a
  pipe, e.g. PowerShell capturing output) cannot show Unicode.
* **Resume** — a ``<dest>.dl`` scratch file plus a ``<dest>.dl.control.json``
  state file record every segment's position, so an interrupted download
  continues from where it stopped instead of restarting a 1 GB transfer.
* **Segments** — the file is fetched over several parallel HTTP Range
  connections (default 4), which is what makes large downloads survivable on
  lossy links. Servers without Range support fall back to one stream.
* **Retries** — every segment retries with exponential backoff before the
  source is considered failed.
* **Multiple official sources** — callers pass a list (the Model Registry
  provides the primary plus the official fallbacks); the manager tries them
  in order and reports why each one failed.
* **Internet Download Manager** — on Windows, if IDM is installed it can take
  the download over (``downloader="auto"/"idm"``): the URL is handed to IDMan
  and IDM's own window — progress bar included — does the work while we wait
  and verify. The final sha256 gate is *always* ours, no matter who moved the
  bytes.

Checksum policy: this module *reports* the sha256 of what it produced (and the
digest the host reported, if any); enforcing it against the Model Registry pin
stays with the caller (ModelManager / prepare_windows_installer), exactly as
before. A network failure keeps the resumable partial — an unverified partial
is not a corrupt file, and the final hash gate still decides adoption.
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from pathlib import Path
from typing import Callable, Sequence

USER_AGENT = "SupermarketBrain/4.0"
CHUNK = 256 * 1024
MB = 1024 * 1024
#: parallel Range connections for the built-in engine
DEFAULT_CONNECTIONS = 4
MAX_CONNECTIONS = 16
#: segments smaller than this are not worth a connection of their own
MIN_SEGMENT_BYTES = 8 * MB
PROBE_TIMEOUT = 30
SOCKET_TIMEOUT = 60
#: per-segment retries before the *source* is considered failed
MAX_SEGMENT_ATTEMPTS = 6
CONTROL_VERSION = 1
#: how long IDM may take to actually create the output file (error dialog,
#: dead proxy, 403 …) before we move on to the next source
IDM_START_TIMEOUT = 120.0

ProgressFn = Callable[[int, int], None]


class DownloadError(RuntimeError):
    """All sources failed. ``attempts`` lists (host, reason) per source."""

    def __init__(self, message: str, attempts: list[tuple[str, str]] | None = None):
        super().__init__(message)
        self.attempts = attempts or []


class IDMNotStarted(DownloadError):
    """IDM accepted the command but never produced the file (dead URL/proxy)."""


def sha256_file(path: str | Path, *, chunk: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def force_utf8_stdio() -> None:
    """Best-effort UTF-8 for redirected Windows consoles (never crash a build
    because a console codepage cannot encode a character)."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except Exception:  # noqa: BLE001 — cosmetic only
            pass


# ------------------------------------------------------------------- helpers
def _host(url: str) -> str:
    return url.split("//", 1)[-1].split("/", 1)[0].lower()


def _etag_digest(headers) -> str | None:
    """Hugging Face reports the LFS sha256 in X-Linked-Etag ("hex", quoted)."""
    for key in ("X-Linked-Etag", "X-Linked-ETag", "ETag"):
        value = headers.get(key)
        if not value:
            continue
        candidate = value.strip().strip('"')
        if len(candidate) == 64 and all(c in "0123456789abcdef" for c in candidate):
            return candidate
    return None


def _parse_content_range(value: str | None) -> int:
    """``bytes 0-0/12345`` → 12345; 0 when the total is unknown."""
    if not value or "/" not in value:
        return 0
    tail = value.rsplit("/", 1)[-1].strip()
    try:
        return int(tail)
    except ValueError:
        return 0


def plan_segments(total: int, connections: int, min_segment: int = MIN_SEGMENT_BYTES) -> list[tuple[int, int]]:
    """Split ``[0, total)`` into inclusive (start, end) ranges.

    Small files get a single segment — parallelism must never turn a 2 MB
    download into four connections.
    """
    if total <= 0:
        return []
    count = max(1, min(connections, (total + min_segment - 1) // min_segment, total))
    base, extra = divmod(total, count)
    segments: list[tuple[int, int]] = []
    offset = 0
    for index in range(count):
        length = base + (1 if index < extra else 0)
        segments.append((offset, offset + length - 1))
        offset += length
    return segments


def idm_command(exe: str, url: str, dest: Path) -> list[str]:
    """The IDMan.exe command line that downloads ``url`` into ``dest``.

    ``/n`` starts silently (no confirmation dialog) — IDM's own window with
    its progress bar is the point of this integration.
    """
    return [exe, "/d", url, "/p", str(dest.parent), "/f", dest.name, "/n"]


def detect_idm() -> str | None:
    """Find Internet Download Manager if it is installed (Windows only)."""
    override = os.environ.get("SUPERMARKET_IDM_PATH")
    if override and Path(override).exists():
        return override
    for name in ("IDMan.exe", "IDMan"):
        found = shutil.which(name)
        if found:
            return found
    if os.name == "nt":
        for variable in ("ProgramFiles(x86)", "ProgramFiles", "ProgramW6432"):
            root = os.environ.get(variable)
            if not root:
                continue
            candidate = Path(root) / "Internet Download Manager" / "IDMan.exe"
            if candidate.exists():
                return str(candidate)
        try:
            import winreg  # type: ignore[import-not-found]

            for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
                try:
                    with winreg.OpenKey(hive, r"Software\DownloadManager") as key:
                        path, _ = winreg.QueryValueEx(key, "ExePath")
                        if path and Path(path).exists():
                            return str(path)
                except OSError:
                    continue
        except ImportError:  # non-Windows
            pass
    return None


# ----------------------------------------------------------------- progress
def _unicode_ok() -> bool:
    try:
        "█░".encode(sys.stdout.encoding or "ascii")
        return True
    except (UnicodeEncodeError, LookupError):
        return False


def _fmt_mb(value: float) -> str:
    return f"{value / MB:,.1f}"


def _fmt_eta(seconds: float | None) -> str:
    if seconds is None or seconds < 0 or seconds != seconds:  # NaN guard
        return "--:--"
    seconds = int(seconds)
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


class _Bar:
    """One-line live progress bar; ASCII-safe; prints milestones when piped."""

    def __init__(self, total: int, *, progress: ProgressFn | None = None,
                 quiet: bool = False, width: int = 26) -> None:
        self.total = total
        self.progress = progress
        self.quiet = quiet
        self.width = width
        self.is_tty = sys.stdout.isatty()
        self.unicode = _unicode_ok()
        self.samples: deque[tuple[float, int]] = deque([(time.monotonic(), 0)])
        self._last_draw = 0.0
        self._drawn = 0
        self._last_milestone = 0.0
        self._last_line = ""

    def update(self, done: int, force: bool = False) -> None:
        now = time.monotonic()
        self.samples.append((now, done))
        while len(self.samples) > 2 and now - self.samples[0][0] > 6:
            self.samples.popleft()
        if self.progress:
            try:
                self.progress(done, self.total)
            except Exception:  # noqa: BLE001 — a UI callback must not kill a download
                pass
        if self.quiet:
            return
        if self.is_tty:
            if force or now - self._last_draw >= 0.25:
                self._last_draw = now
                self._draw(done)
        elif force or now - self._last_milestone >= 30.0:
            self._last_milestone = now
            print(f"    {self._line(done)}", flush=True)

    def _speed(self) -> float | None:
        if len(self.samples) < 2:
            return None
        (t0, b0), (t1, b1) = self.samples[0], self.samples[-1]
        elapsed = t1 - t0
        if elapsed <= 0.05:
            return None
        return max(0.0, (b1 - b0) / elapsed)

    def _line(self, done: int) -> str:
        speed = self._speed()
        eta = (self.total - done) / speed if (speed and self.total and speed > 0) else None
        if self.total:
            pct = min(1.0, done / self.total)
            filled = int(pct * self.width)
            full, empty = ("█", "░") if self.unicode else ("#", ".")
            bar = full * filled + empty * (self.width - filled)
            line = (f"[{bar}] {pct * 100:5.1f}%  {_fmt_mb(done)}/{_fmt_mb(self.total)} MB")
        else:
            line = f"[{_fmt_mb(done)} MB]"
        if speed:
            line += f"  {speed / MB:5.2f} MB/s  ETA {_fmt_eta(eta)}"
        return line

    def _draw(self, done: int) -> None:
        line = f"  {self._line(done)}"
        pad = max(0, len(self._last_line) - len(line))
        print("\r" + line + " " * pad, end="", flush=True)
        self._last_line = line
        self._drawn += 1

    def note(self, message: str) -> None:
        """Print a normal log line without breaking an in-place bar."""
        if self.quiet:
            return
        if self.is_tty and self._drawn:
            print("\r" + " " * max(len(self._last_line), len(message) + 2) + "\r",
                  end="", flush=True)
            self._drawn = 0
            self._last_line = ""
        print(f"  {message}", flush=True)

    def close(self, done: int) -> None:
        self.update(done, force=True)
        if not self.quiet and self.is_tty and self._drawn:
            print(flush=True)
            self._drawn = 0


# ------------------------------------------------------------------- probe
class _Probe:
    __slots__ = ("total", "ranges", "server_sha256")

    def __init__(self, total: int, ranges: bool, server_sha256: str | None) -> None:
        self.total = total
        self.ranges = ranges
        self.server_sha256 = server_sha256


def _probe(url: str, headers: dict | None = None) -> _Probe:
    """Ask for byte 0 to learn the size, Range support and the LFS digest."""
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Range": "bytes=0-0", **(headers or {})})
    with urllib.request.urlopen(request, timeout=PROBE_TIMEOUT) as response:
        code = getattr(response, "status", None) or response.getcode() or 200
        ranges = code == 206
        if ranges:
            total = _parse_content_range(response.headers.get("Content-Range"))
        else:
            length = response.headers.get("Content-Length") or ""
            total = int(length) if length.isdigit() else 0
        return _Probe(total, ranges, _etag_digest(response.headers))


class _NoRanges(Exception):
    """Server ignored Range on a multi-segment plan — rerun single-stream."""


# ------------------------------------------------------------- control file
def _control_path(scratch: Path) -> Path:
    return Path(str(scratch) + ".control.json")


def _save_control(path: Path, payload: dict) -> None:
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    os.replace(tmp, path)


def _load_control(path: Path, total: int, expected_sha256: str | None,
                  plan: list[tuple[int, int]]) -> list[int] | None:
    """Reusable resume state, or None when it does not match this download."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if data.get("version") != CONTROL_VERSION or data.get("total") != total:
        return None
    if (data.get("expected_sha256") or None) != (expected_sha256 or None):
        return None
    segments = data.get("segments")
    if not isinstance(segments, list) or len(segments) != len(plan):
        return None
    done: list[int] = []
    for (start, end), state in zip(plan, segments):
        try:
            seg_start, seg_end, seg_done = state
        except (TypeError, ValueError):
            return None
        if (seg_start, seg_end) != (start, end):
            return None
        if not 0 <= seg_done <= end - start + 1:
            return None
        done.append(int(seg_done))
    return done


# ---------------------------------------------------------- builtin engine
def _fetch_builtin(sources: Sequence[str], dest: Path, *, expected_size: int | None,
                   expected_sha256: str | None, connections: int,
                   bar: _Bar, resume: bool = True) -> dict:
    """Segmented, resumable, multi-source download with the live progress bar."""
    scratch = Path(str(dest) + ".dl")
    control = _control_path(scratch)
    attempts: list[tuple[str, str]] = []
    connections = max(1, min(connections, MAX_CONNECTIONS))

    for index, url in enumerate(sources, 1):
        bar.note(f"source {index}/{len(sources)}: {_host(url)}"
                 + ("  (official fallback)" if index > 1 else ""))
        try:
            probe = _probe(url)
        except Exception as exc:  # noqa: BLE001 — a dead source is a normal outcome
            reason = (f"HTTP {exc.code}" if isinstance(exc, urllib.error.HTTPError)
                      else str(exc)[:120])
            attempts.append((_host(url), reason))
            bar.note(f"  ✗ {_host(url)}: {reason}")
            continue
        if expected_size and probe.total and probe.total != expected_size:
            reason = f"size mismatch (host {probe.total:,} B, expected {expected_size:,} B)"
            attempts.append((_host(url), reason))
            bar.note(f"  ✗ {reason}")
            continue

        total = probe.total or expected_size or 0
        try:
            if total:
                payload = _download_with_plan(
                    url, dest, scratch, control, total=total, ranges=probe.ranges,
                    connections=connections, expected_sha256=expected_sha256,
                    bar=bar, resume=resume)
            else:  # server reveals nothing: plain stream, no resume possible
                payload = _download_stream(url, dest, bar=bar)
        except _NoRanges:
            bar.note("  server ignored Range — retrying with a single connection")
            payload = _download_with_plan(
                url, dest, scratch, control, total=total, ranges=False,
                connections=1, expected_sha256=expected_sha256, bar=bar, resume=False)
        return {"ok": True, "path": str(dest), "size": dest.stat().st_size,
                "sha256": payload["sha256"], "server_sha256": probe.server_sha256,
                "source": url, "downloader": "builtin",
                "resumed_bytes": payload["resumed"], "connections": payload["connections"]}

    raise DownloadError(
        "all sources failed: " + "; ".join(f"{host}: {reason}" for host, reason in attempts),
        attempts)


def _download_with_plan(url: str, dest: Path, scratch: Path, control: Path, *, total: int,
                        ranges: bool, connections: int, expected_sha256: str | None,
                        bar: _Bar, resume: bool) -> dict:
    plan = plan_segments(total, connections)
    done = None
    if resume and scratch.exists():
        done = _load_control(control, total, expected_sha256, plan)
    if done is None:
        done = [0] * len(plan)
        scratch.unlink(missing_ok=True)
        with open(scratch, "wb") as fh:            # fresh sparse file
            fh.truncate(total)
    else:                                          # resume: keep the bytes we have
        with open(scratch, "r+b") as fh:
            fh.truncate(total)
    resumed = sum(done)

    state: list[list[int]] = []          # [start, end, done] per segment
    for (start, end), seg_done in zip(plan, done):
        state.append([start, end, seg_done])
    lock = threading.Lock()
    counter = {"done": resumed}
    errors: dict[int, str] = {}
    stop = threading.Event()
    workers = [threading.Thread(target=_segment_worker, daemon=True,
                                args=(url, scratch, state[i], ranges, lock, counter,
                                      errors, stop, i), name=f"dl-seg{i}")
               for i in range(len(state))]
    bar.total = total
    bar.note(("resuming at " if resumed else "downloading ")
             + f"{_fmt_mb(total)} MB"
             + (f" (already have {_fmt_mb(resumed)} MB)" if resumed else "")
             + (f", {len(workers)} connections" if len(workers) > 1 else ""))
    for worker in workers:
        worker.start()
    last_save = time.monotonic()
    try:
        while any(worker.is_alive() for worker in workers):
            with lock:
                bar.update(counter["done"])
            now = time.monotonic()
            if now - last_save >= 2.0:
                last_save = now
                with lock:
                    _save_control(control, _control_payload(total, expected_sha256, state))
            time.sleep(0.25)
    except KeyboardInterrupt:
        stop.set()
        for worker in workers:
            worker.join(timeout=5)
        with lock:
            _save_control(control, _control_payload(total, expected_sha256, state))
        bar.note("interrupted — partial download kept for resume")
        raise
    finally:
        for worker in workers:
            worker.join(timeout=5)
    _save_control(control, _control_payload(total, expected_sha256, state))
    if errors or stop.is_set() or any(s[2] != s[1] - s[0] + 1 for s in state):
        detail = "; ".join(f"segment {i}: {msg}" for i, msg in sorted(errors.items())) or \
            "incomplete after retries"
        raise DownloadError(f"source failed: {detail}")
    bar.update(total, force=True)

    bar.note("verifying the downloaded bytes (sha256) …")
    digest = sha256_file(scratch)
    os.replace(scratch, dest)
    control.unlink(missing_ok=True)
    return {"sha256": digest, "resumed": resumed, "connections": len(workers)}


def _control_payload(total: int, expected_sha256: str | None,
                     state: list[list[int]]) -> dict:
    return {"version": CONTROL_VERSION, "total": total,
            "expected_sha256": expected_sha256,
            "segments": [list(seg) for seg in state], "updated": time.time()}


def _segment_worker(url: str, scratch: Path, seg: list[int], ranges: bool,
                    lock: threading.Lock, counter: dict, errors: dict[int, str],
                    stop: threading.Event, index: int) -> None:
    """Fetch one (start, end) byte range into ``scratch``, resumable per attempt."""
    start, end, done = seg
    length = end - start + 1
    attempt = 0
    while done < length and not stop.is_set() and attempt <= MAX_SEGMENT_ATTEMPTS:
        pos = start + done
        headers = {"User-Agent": USER_AGENT}
        if ranges or pos > start:
            headers["Range"] = f"bytes={pos}-{end}"
        try:
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=SOCKET_TIMEOUT) as response, \
                    open(scratch, "r+b") as fh:
                code = getattr(response, "status", None) or response.getcode() or 200
                if code == 200 and pos != start:
                    with lock:                   # server ignored the resume range:
                        counter["done"] -= done  # those bytes will be re-fetched
                        done = 0
                        seg[2] = 0
                    attempt += 1
                    if attempt > MAX_SEGMENT_ATTEMPTS:
                        errors[index] = "server kept ignoring Range requests"
                        return
                    continue
                if code == 200 and (end - start + 1) != _content_length(response, end - start + 1):
                    raise _NoRanges()            # full body for a partial request
                fh.seek(pos)
                while not stop.is_set():
                    block = response.read(CHUNK)
                    if not block:
                        break
                    fh.write(block)
                    with lock:
                        done += len(block)
                        seg[2] = done
                        counter["done"] += len(block)
            if done > length:                    # server over-served this range
                raise OSError(f"range overrun by {done - length} bytes")
        except _NoRanges:
            stop.set()
            errors[index] = "server ignored Range requests"
            return
        except Exception as exc:  # noqa: BLE001 — retry, then let the source fail
            if os.environ.get("SUPERMARKET_DL_DEBUG"):
                import traceback
                traceback.print_exc()
            attempt += 1
            if attempt > MAX_SEGMENT_ATTEMPTS:
                errors[index] = str(exc)[:120]
                return
            time.sleep(min(30.0, 0.5 * (2 ** attempt)) + random.random() * 0.5)
    if done < length and not stop.is_set():
        errors.setdefault(index, "incomplete")


def _content_length(response, fallback: int) -> int:
    value = response.headers.get("Content-Length") or ""
    try:
        return int(value) if value.isdigit() else fallback
    except ValueError:
        return fallback


def _download_stream(url: str, dest: Path, *, bar: _Bar) -> dict:
    """No size, no Range: a plain single stream (rare; keeps us honest)."""
    bar.total = 0
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    done = 0
    with urllib.request.urlopen(request, timeout=SOCKET_TIMEOUT) as response, open(dest, "wb") as fh:
        while True:
            block = response.read(CHUNK)
            if not block:
                break
            fh.write(block)
            done += len(block)
            bar.update(done)
    bar.update(done, force=True)
    bar.note("verifying the downloaded bytes (sha256) …")
    return {"sha256": sha256_file(dest), "resumed": 0, "connections": 1}


# --------------------------------------------------------------------- IDM
def _idm_wait(dest: Path, expected_size: int | None, progress: ProgressFn | None,
              *, start_timeout: float = IDM_START_TIMEOUT, poll: float = 2.0,
              status_every: float = 15.0, quiet: bool = False,
              _sleep=time.sleep, _now=time.monotonic) -> int:
    """Wait for IDM to finish ``dest``; returns the size. Testable clock.

    Completion = file at the expected size and quiet for 5s (we hash afterwards
    regardless), or — when the size is unknown — quiet for 30s.
    """
    appeared = False
    last_size = -1
    last_change = _now()
    last_status = _now()
    deadline = _now() + start_timeout
    while True:
        try:
            size = dest.stat().st_size
        except OSError:
            size = 0
        now = _now()
        if size:
            appeared = True
        if size != last_size:
            last_size, last_change = size, now
        if size and progress:
            try:
                progress(size, expected_size or 0)
            except Exception:  # noqa: BLE001
                pass
        if expected_size and size > expected_size:
            raise DownloadError(f"IDM produced {size:,} B, expected {expected_size:,} B")
        if expected_size and size == expected_size and now - last_change >= 5:
            return size
        if not expected_size and size and now - last_change >= 30:
            return size
        if not size and not appeared and now >= deadline:
            raise IDMNotStarted(
                f"IDM did not start this download within {start_timeout:.0f}s")
        if size and not quiet and now - last_status >= status_every:
            last_status = now
            extra = f" ({size / expected_size * 100:.0f}%)" if expected_size else ""
            print(f"    IDM: {_fmt_mb(size)} MB{extra}", flush=True)
        _sleep(poll)


def _fetch_idm(exe: str, sources: Sequence[str], dest: Path, *, expected_size: int | None,
               progress: ProgressFn | None, bar: _Bar,
               start_timeout: float) -> dict | None:
    """Hand each source to IDM in turn; None = IDM could not deliver."""
    tmp = Path(str(dest) + ".idm")
    tmp.unlink(missing_ok=True)
    for index, url in enumerate(sources, 1):
        bar.note(f"source {index}/{len(sources)}: {_host(url)} via Internet Download Manager")
        tmp.unlink(missing_ok=True)
        try:
            process = subprocess.Popen(idm_command(exe, url, tmp),
                                       stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL)
        except OSError as exc:
            bar.note(f"  ✗ could not launch IDM: {exc}")
            return None
        try:
            code = process.wait(timeout=10)
            if code not in (0, None):
                bar.note(f"  ✗ IDMan.exe exited with {code}; trying the next source")
                continue
        except subprocess.TimeoutExpired:
            pass                                    # still running — that is fine
        try:
            _idm_wait(tmp, expected_size, progress, start_timeout=start_timeout,
                      quiet=bar.quiet)
        except IDMNotStarted as exc:
            bar.note(f"  ✗ {exc}; trying the next source")
            continue
        size = tmp.stat().st_size
        if expected_size and size != expected_size:
            bar.note(f"  ✗ IDM delivered {size:,} B, expected {expected_size:,} B")
            continue
        tmp.replace(dest)
        return {"ok": True, "path": str(dest), "size": size,
                "sha256": sha256_file(dest), "server_sha256": None,
                "source": url, "downloader": "idm", "resumed_bytes": 0,
                "connections": 1}
    return None


# -------------------------------------------------------------------- API
def fetch(sources: str | Sequence[str], dest: Path, *, expected_size: int | None = None,
          expected_sha256: str | None = None, progress: ProgressFn | None = None,
          connections: int = DEFAULT_CONNECTIONS, downloader: str = "auto",
          quiet: bool = False, resume: bool = True,
          idm_start_timeout: float = IDM_START_TIMEOUT) -> dict:
    """Download ``dest`` from the first source that works, like a manager would.

    ``sources``  one URL or several, tried in order (registry: official first).
    ``downloader``  ``auto`` (IDM if installed, else builtin) | ``idm`` | ``builtin``.
    Returns a dict with ok/path/size/sha256/source/downloader/resumed_bytes;
    raises :class:`DownloadError` when every source failed. The sha256 gate
    itself stays with the caller.
    """
    if isinstance(sources, str):
        sources = (sources,)
    sources = tuple(sources)
    if not sources:
        raise DownloadError("no download sources given")
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    bar = _Bar(expected_size or 0, progress=progress, quiet=quiet)

    if downloader not in ("auto", "idm", "builtin"):
        raise ValueError(f"unknown downloader: {downloader!r}")
    if downloader in ("auto", "idm"):
        exe = detect_idm()
        if downloader == "idm" and not exe:
            raise DownloadError(
                "Internet Download Manager (IDMan.exe) was requested but not found; "
                "install it or use --downloader builtin")
        if exe:
            bar.note(f"downloader: Internet Download Manager ({exe})")
            result = _fetch_idm(exe, sources, dest, expected_size=expected_size,
                                progress=progress, bar=bar, start_timeout=idm_start_timeout)
            if result is not None:
                bar.note(f"IDM finished: {_fmt_mb(result['size'])} MB")
                return result
            if downloader == "idm":
                raise DownloadError("IDM could not download from any official source")
            bar.note("IDM could not deliver — falling back to the built-in engine")
    bar.note(f"downloader: built-in engine ({connections} parallel connections)")
    result = _fetch_builtin(sources, dest, expected_size=expected_size,
                            expected_sha256=expected_sha256, connections=connections,
                            bar=bar, resume=resume)
    bar.note(f"done: {_fmt_mb(result['size'])} MB from {_host(result['source'])} "
             f"(sha256 {result['sha256'][:16]}…)")
    return result
