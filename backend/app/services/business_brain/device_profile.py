"""v4.0 — device profile (§31).

The brain must behave the same on an 8 GB office PC, a 4 GB shop machine and an
Android phone while *choosing different execution settings* on each. This module
answers three questions with no third-party dependency:

* how much memory is there (total and free),
* how many cores are usable,
* how much disk is free — a model download that fills the disk is worse than no
  model at all.

Everything here degrades to ``0``/``None`` rather than raising: a device that
cannot be measured must still be able to run the deterministic brain.
"""
from __future__ import annotations

import ctypes
import logging
import os
import platform
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path

log = logging.getLogger("supermarket.brain.device")

#: the app's own data directory may be relocated; measure the disk it lives on
def _data_dir() -> Path:
    env = os.environ.get("SUPERMARKET_DATA_DIR")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[3] / "data"


def total_ram_mb() -> int:
    if hasattr(os, "sysconf") and "SC_PHYS_PAGES" in os.sysconf_names:
        try:
            return int(os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE") / (1024 * 1024))
        except (ValueError, OSError):
            pass
    if platform.system() == "Windows":
        class _MemoryStatusEx(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

        status = _MemoryStatusEx()
        status.dwLength = ctypes.sizeof(_MemoryStatusEx)
        try:
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):  # type: ignore[attr-defined]
                return int(status.ullTotalPhys / (1024 * 1024))
        except Exception:  # noqa: BLE001
            pass
    return 0


def available_ram_mb() -> int:
    meminfo = Path("/proc/meminfo")
    if meminfo.exists():
        try:
            for line in meminfo.read_text().splitlines():
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) // 1024
        except OSError:
            pass
    return total_ram_mb()


def cpu_cores() -> int:
    return os.cpu_count() or 1


def disk_free_mb(path: Path | None = None) -> int:
    target = path or _data_dir()
    try:
        target.mkdir(parents=True, exist_ok=True)
        return int(shutil.disk_usage(str(target)).free / (1024 * 1024))
    except OSError:
        return 0


def gpu_hint() -> str | None:
    """Best-effort: only reports what it can actually see."""
    if platform.system() == "Windows":
        try:
            out = subprocess.run(["wmic", "path", "win32_videocontroller", "get", "name"],  # noqa: S603,S607
                                 capture_output=True, text=True, timeout=6)
            names = [n.strip() for n in out.stdout.splitlines()[1:] if n.strip()]
            return names[0] if names else None
        except (OSError, subprocess.SubprocessError):
            return None
    for candidate in ("/dev/dri/renderD128", "/dev/nvidia0"):
        if Path(candidate).exists():
            return candidate
    return None


@dataclass
class DeviceProfile:
    os_name: str
    os_version: str
    machine: str
    python: str
    cpu_cores: int
    ram_total_mb: int
    ram_available_mb: int
    disk_free_mb: int
    gpu: str | None = None
    is_android: bool = False
    notes: list[str] = field(default_factory=list)

    @property
    def ram_gb(self) -> float:
        return round(self.ram_total_mb / 1024, 1)

    @property
    def low_ram(self) -> bool:
        return 0 < self.ram_total_mb < 6144

    @property
    def tier(self) -> str:
        if not self.ram_total_mb:
            return "unknown"
        if self.ram_total_mb < 4096:
            return "minimal"
        if self.ram_total_mb < 6144:
            return "low"
        if self.ram_total_mb < 10240:
            return "standard"
        return "high"

    def to_dict(self) -> dict:
        data = asdict(self)
        data.update({"ram_gb": self.ram_gb, "low_ram": self.low_ram, "tier": self.tier})
        return data


def _is_android() -> bool:
    return bool(os.environ.get("ANDROID_ROOT") or os.environ.get("ANDROID_DATA")) or "android" in platform.platform().lower()


def profile() -> DeviceProfile:
    prof = DeviceProfile(os_name=platform.system(), os_version=platform.release(),
                         machine=platform.machine(), python=platform.python_version(),
                         cpu_cores=cpu_cores(), ram_total_mb=total_ram_mb(),
                         ram_available_mb=available_ram_mb(), disk_free_mb=disk_free_mb(),
                         gpu=gpu_hint(), is_android=_is_android())
    if prof.tier == "minimal":
        prof.notes.append("حافظهٔ دستگاه کمتر از ۴ گیگابایت است؛ اجرای مدل پیشنهاد نمی‌شود")
    elif prof.tier == "low":
        prof.notes.append("برای این دستگاه نسخهٔ Q3_K_M مناسب‌تر است")
    elif prof.tier == "high" and not prof.is_android:
        prof.notes.append("حافظه کافی است؛ پس از سنجش، پنجرهٔ ۸۱۹۲ می‌تواند فعال شود")
    if prof.disk_free_mb and prof.disk_free_mb < 2500:
        prof.notes.append("فضای دیسک برای دانلود مدل کمتر از حد لازم است")
    return prof


# --------------------------------------------------------------------------- policy
def choose_model(prof: DeviceProfile | None = None):
    """Which registry entry this device should install (§31)."""
    from . import model_registry

    prof = prof or profile()
    if prof.low_ram or prof.is_android:
        spec = model_registry.by_tier("low-ram")
        if spec:
            return spec
    return model_registry.default_model()


def context_size(prof: DeviceProfile | None = None) -> int:
    """4096 on anything that is not clearly comfortable (§31)."""
    prof = prof or profile()
    if prof.ram_total_mb >= 12288 and not prof.is_android:
        return 8192
    return 4096


def context_after_benchmark(prof: DeviceProfile | None, benchmark: dict) -> int:
    """Widen the window only when the *measured* device can hold it."""
    prof = prof or profile()
    if context_size(prof) < 8192:
        return context_size(prof)
    if not benchmark or not benchmark.get("load_ok", True):
        return 4096
    avg_ms = benchmark.get("avg_ms") or 0
    if avg_ms and avg_ms < 6000 and benchmark.get("persian_ok"):
        return 8192
    return 4096


def context_for(prof: DeviceProfile | None = None) -> int:
    """Alias kept for the Model Manager's vocabulary."""
    return context_size(prof)


def recommended_model_id(prof: DeviceProfile | None = None) -> str:
    return choose_model(prof).model_id


def threads_for(prof: DeviceProfile | None = None) -> int:
    prof = prof or profile()
    return max(1, prof.cpu_cores - 1)


def summary_line(prof: DeviceProfile | None = None) -> str:
    prof = prof or profile()
    gpu = f"، گرافیک {prof.gpu}" if prof.gpu else ""
    return (f"{prof.os_name} {prof.os_version} ({prof.machine}) — {prof.cpu_cores} هسته، "
            f"{prof.ram_gb} گیگابایت رم، {prof.ram_available_mb // 1024} گیگابایت آزاد{gpu}")
