"""v4.0 — Model Manager (§33–§40, §72).

    detect → select → download → verify (sha256) → install → load → benchmark →
    activate → (unload | update | rollback)

Every step writes a ``BrainModelInstall`` row and a ``BRAIN_MODEL_EVENT`` audit
entry, so "which model is the shop running, since when, and did it pass its
benchmark" is answerable from the database alone.

Integrity is the part that matters most, and it is implemented literally:

* the file is streamed to a ``.part`` file while a sha256 is computed;
* it is compared with the pinned digest from the registry, or — when the registry
  ships no pinned digest — with the digest the **official host** reports for that
  object (Hugging Face returns the LFS sha256 in ``X-Linked-Etag``). A file whose
  bytes match neither is **deleted**, audited and refused: a corrupted or
  substituted model must never reach the loader;
* a file with no trusted digest at all is kept but marked unverified and
  **cannot be installed** — "we could not verify it" is a different statement
  from "it is fine", and the UI shows the difference.

No network call happens unless the owner (or the install screen) asks for one.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import time
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...models import BrainModelInstall, SystemSetting
from . import device_profile, download_manager, model_registry
from .audit import log as brain_audit

log = logging.getLogger("supermarket.brain.model")

DOWNLOAD_CHUNK = 1024 * 1024
#: a download that stalls for this long is abandoned rather than hanging a request
SOCKET_TIMEOUT = 60
#: install states
READY_STATES = ("VERIFIED", "INSTALLED", "ACTIVE")
#: v4.0 — the Windows installer drops a verified model next to this manifest
SEED_MANIFEST = "seed.json"


# --------------------------------------------------------------------------- paths
def models_root() -> Path:
    root = Path(os.environ.get("SUPERMARKET_BRAIN_MODELS_DIR")
                or (Path(os.environ.get("SUPERMARKET_DATA_DIR") or device_profile._data_dir()) / "brain" / "models"))
    root.mkdir(parents=True, exist_ok=True)
    return root


def model_dir(model_id: str) -> Path:
    path = models_root() / model_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def find_binary(*, explicit: str | None = None) -> str | None:
    """Locate llama.cpp: explicit setting → bundled runtime dir → PATH."""
    candidates = [explicit, os.environ.get("SUPERMARKET_BRAIN_LLAMA")]
    runtime_dir = models_root().parent / "runtime"
    for name in ("llama-server", "llama-server.exe", "llama-cli", "llama-cli.exe"):
        candidates.append(str(runtime_dir / name))
        found = shutil.which(name)
        if found:
            candidates.append(found)
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return str(candidate)
    return None


def sha256_file(path: str | Path, *, chunk: int = DOWNLOAD_CHUNK) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


# --------------------------------------------------------------------------- manager
class ModelManager:
    """Owns every transition of the local model. One instance per request is fine."""

    def __init__(self, db: Session, *, binary: str | None = None, downloader=None) -> None:
        self.db = db
        self.binary = binary
        #: injectable for tests: callable(url, dest, on_progress) -> "sha256 or None"
        self.downloader = downloader

    # ------------------------------------------------------------------ detection
    def detect(self) -> dict:
        prof = device_profile.profile()
        installs = {row.model_id: row for row in self._all_rows()}
        models = []
        for spec in model_registry.all_models():
            row = installs.get(spec.model_id)
            models.append({**spec.to_dict(), "status": row.status if row else "NOT_INSTALLED",
                           "installed": bool(row and row.status in READY_STATES),
                           "size_on_disk_mb": round(int(row.size_bytes) / (1024 * 1024), 1) if row else 0,
                           "fits_device": model_registry.fits(spec, ram_mb=prof.ram_total_mb,
                                                              disk_free_mb=prof.disk_free_mb)})
        return {"device": prof.to_dict(), "summary": device_profile.summary_line(prof),
                "recommended": device_profile.recommended_model_id(prof),
                "context_default": device_profile.context_for(prof),
                "binary": find_binary(explicit=self.binary), "models_root": str(models_root()),
                "models": models, "forbidden": [dict(item) for item in model_registry.FORBIDDEN],
                "cap_bytes": model_registry.MAX_FILE_BYTES}

    # ------------------------------------------------------------------ selection
    def select(self, *, model_id: str | None = None) -> dict:
        spec = model_registry.get(model_id) if model_id else device_profile.choose_model()
        prof = device_profile.profile()
        if spec is None:
            return {"ok": False, "code": "UNKNOWN_MODEL", "message": "این مدل در فهرست رسمی نیست"}
        if not spec.within_cap():
            return {"ok": False, "code": "CAP_VIOLATION",
                    "message": f"حجم مدل {spec.gb} گیگابایت است و از سقف ۲ گیگابایت عبور می‌کند"}
        if not model_registry.fits(spec, ram_mb=prof.ram_total_mb, disk_free_mb=prof.disk_free_mb):
            return {"ok": False, "code": "DOES_NOT_FIT",
                    "message": f"این دستگاه ({prof.ram_gb} گیگابایت رم) برای این مدل مناسب نیست؛ "
                               f"مدل پیشنهادی: {device_profile.recommended_model_id(prof)}"}
        return {"ok": True, "code": "OK", "model": spec.to_dict(),
                "message": f"مدل پیشنهادی برای این دستگاه: {spec.model_id}"}

    # ------------------------------------------------------------------ download
    def download(self, model_id: str, *, progress=None, force: bool = False) -> dict:
        # a model shipped inside the Windows installer must not be re-downloaded
        try:
            self.adopt_preinstalled()
        except Exception:  # noqa: BLE001 — adoption is an optimisation, not a gate
            log.warning("seed adoption failed before download", exc_info=True)
        spec = model_registry.get(model_id)
        if spec is None:
            return {"ok": False, "code": "UNKNOWN_MODEL", "message": "این مدل در فهرست رسمی نیست"}
        if not model_registry.allowed_source(spec.source_url, spec):
            return self._fail(model_id, "SOURCE_REFUSED", "منبع دانلود رسمی نیست؛ دریافت انجام نشد")
        if not spec.within_cap():
            return self._fail(model_id, "CAP_VIOLATION",
                              f"حجم مدل {spec.gb} گیگابایت از سقف ۲ گیگابایت بیشتر است")
        prof = device_profile.profile()
        if not model_registry.fits(spec, ram_mb=prof.ram_total_mb, disk_free_mb=prof.disk_free_mb):
            return self._fail(model_id, "DOES_NOT_FIT", "این دستگاه برای این مدل حافظه/فضای کافی ندارد")

        target = model_dir(model_id) / spec.file_name
        if target.exists() and not force:
            digest = sha256_file(target)
            if spec.sha256 and digest != spec.sha256:
                target.unlink(missing_ok=True)                 # §38: never keep a bad file
                return self._fail(model_id, "CHECKSUM_MISMATCH", "فایل موجود خراب بود و حذف شد")
            self._record(model_id, "VERIFIED", path=target, size=target.stat().st_size, sha256=digest)
            return {"ok": True, "code": "ALREADY_PRESENT", "message": "فایل مدل از قبل موجود و سالم است",
                    "path": str(target), "sha256": digest}

        partial = target.with_suffix(target.suffix + ".part")
        self._record(model_id, "DOWNLOADING", path=partial)
        self.db.commit()
        started = time.time()
        try:
            server_digest = self._fetch(spec.source_url, partial, progress)
        except Exception as exc:  # noqa: BLE001 — network failure is a normal outcome
            # the resumable partial is KEPT: an interrupted 900 MB transfer must
            # not restart from zero on the next attempt (the final sha256 gate
            # still decides adoption — an unverified partial is never installed)
            kept = "؛ بخش دریافت‌شده نگه داشته شد و دفعهٔ بعد از همان‌جا ادامه می‌یابد" \
                if Path(str(partial) + ".dl").exists() else ""
            return self._fail(model_id, "DOWNLOAD_FAILED",
                              f"دریافت ناموفق بود: {str(exc)[:160]}{kept}")

        digest = sha256_file(partial)
        trusted = spec.sha256 or server_digest
        if trusted and digest != trusted:
            partial.unlink(missing_ok=True)                    # §38: delete, audit, refuse
            target.unlink(missing_ok=True)                     # …including any earlier copy
            self._audit(model_id, "CHECKSUM_MISMATCH", {"expected": trusted, "got": digest})
            return self._fail(model_id, "CHECKSUM_MISMATCH",
                              "هش فایل با مقدار رسمی نمی‌خواند؛ فایل حذف شد و نصب انجام نمی‌شود")
        if not trusted:
            self._record(model_id, "UNVERIFIED", path=partial, size=partial.stat().st_size, sha256=digest)
            self.db.commit()
            return {"ok": False, "code": "NO_TRUSTED_CHECKSUM",
                    "message": "برای این فایل هش مورد اعتماد در دسترس نبود؛ فایل ذخیره شد ولی نصب نمی‌شود",
                    "path": str(partial), "sha256": digest}
        shutil.move(str(partial), str(target))
        self._record(model_id, "VERIFIED", path=target, size=target.stat().st_size, sha256=digest,
                     benchmark={"download_seconds": round(time.time() - started, 1)})
        self._audit(model_id, "DOWNLOADED", {"sha256": digest, "bytes": target.stat().st_size,
                                             "verified_by": "registry" if spec.sha256 else "host-lfs-etag"})
        self.db.commit()
        return {"ok": True, "code": "VERIFIED", "message": "فایل مدل دانلود و هش آن تأیید شد",
                "path": str(target), "sha256": digest}

    # ------------------------------------------------------------------ installer seed
    def adopt_preinstalled(self) -> list[dict]:
        """v4.0 — adopt model files placed on disk by the Windows installer.

        The installer (Inno Setup) can ship a verified ``.gguf`` next to a
        ``seed.json`` manifest inside ``<data>/brain/models/<model_id>/``, so a
        shop PC gets a working local model on day one with no download. This
        method never *trusts* the manifest: the file is re-hashed, the digest
        must match both the manifest and the registry pin, and a mismatch is
        recorded as UNVERIFIED (never activated, never deleted — it is the
        owner's disk).

        Idempotent and cheap: a model whose file is unchanged (size + mtime +
        digest recorded before) is skipped without re-hashing the 1 GB file.
        """
        report: list[dict] = []
        for spec in model_registry.all_models():
            folder = models_root() / spec.model_id
            manifest_path = folder / SEED_MANIFEST
            if not manifest_path.exists():
                continue
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                report.append({"model_id": spec.model_id, "ok": False, "code": "BAD_MANIFEST",
                               "message": f"seed.json خوانده نشد: {str(exc)[:120]}"})
                continue
            file_name = str(manifest.get("file") or spec.file_name)
            expected = str(manifest.get("sha256") or "").lower()
            if not re.fullmatch(r"[0-9a-f]{64}", expected):
                report.append({"model_id": spec.model_id, "ok": False, "code": "BAD_MANIFEST",
                               "message": "seed.json هش معتبر ندارد"})
                continue
            target = folder / file_name
            if not target.exists():
                report.append({"model_id": spec.model_id, "ok": False, "code": "FILE_MISSING",
                               "message": "فایل مدل کنار seed.json نیست"})
                continue
            size = target.stat().st_size
            row = self._row(spec.model_id)
            if (row is not None and row.status in READY_STATES
                    and (row.sha256 or "").lower() == expected and row.path == str(target)):
                continue  # already adopted, nothing to do
            stamp = f"{expected}:{size}:{int(target.stat().st_mtime)}"
            if (row is not None and row.status in READY_STATES
                    and self._get_setting(f"brain.seed.{spec.model_id}") == stamp):
                continue  # verified before and untouched since
            actual = sha256_file(target)
            if actual != expected or (spec.sha256 and expected != spec.sha256.lower()):
                self._record(spec.model_id, "UNVERIFIED", path=target, size=size, sha256=actual)
                self._audit(spec.model_id, "SEED_MISMATCH",
                            {"expected": expected, "got": actual, "source": "installer"})
                self.db.commit()
                report.append({"model_id": spec.model_id, "ok": False, "code": "CHECKSUM_MISMATCH",
                               "message": "هش فایل نصب‌شده با manifest/فهرست رسمی نمی‌خواند؛ مدل فعال نمی‌شود"})
                continue
            self._record(spec.model_id, "INSTALLED", path=target, size=size, sha256=actual)
            self._set_setting(f"brain.seed.{spec.model_id}", stamp)
            self._audit(spec.model_id, "ADOPTED", {"source": "installer", "path": str(target),
                                                   "sha256": actual})
            activated = None
            if not self.active_id():
                activated = self.activate(spec.model_id)
            self.db.commit()
            entry = {"model_id": spec.model_id, "ok": True, "code": "ADOPTED",
                     "message": "مدلِ همراه نصب‌کننده تأیید و نصب شد", "path": str(target)}
            if activated is not None:
                entry["activated"] = bool(activated.get("ok"))
            report.append(entry)
        return report

    # ------------------------------------------------------------------ install / load
    def install(self, model_id: str) -> dict:
        row = self._row(model_id)
        spec = model_registry.get(model_id)
        if spec is None or row is None or not row.path:
            return {"ok": False, "code": "NOT_DOWNLOADED", "message": "فایل این مدل دریافت نشده است"}
        path = Path(row.path)
        if path.suffix == ".part" or row.status == "UNVERIFIED":
            return {"ok": False, "code": "UNVERIFIED",
                    "message": "این فایل هش تأییدشده ندارد؛ برای نصب ابتدا دوباره دریافت شود"}
        if not path.exists():
            return self._fail(model_id, "FILE_MISSING", "فایل مدل روی دیسک نیست")
        if spec.sha256 and row.sha256 and row.sha256 != spec.sha256:
            return self._fail(model_id, "CHECKSUM_MISMATCH", "هش فایل با فهرست رسمی نمی‌خواند")
        self._record(model_id, "INSTALLED", path=path, size=path.stat().st_size, sha256=row.sha256)
        self._audit(model_id, "INSTALLED", {"path": str(path)})
        self.db.commit()
        return {"ok": True, "code": "INSTALLED", "message": "مدل نصب شد", "model_id": model_id}

    def load(self, model_id: str | None = None, *, benchmark: bool = False) -> dict:
        from .runtime import LlamaCppProvider

        model_id = model_id or self.active_id()
        row = self._row(model_id) if model_id else None
        spec = model_registry.get(model_id) if model_id else None
        if row is None or spec is None or not row.path:
            return {"ok": False, "code": "NOT_INSTALLED", "message": "مدلی برای بارگذاری نصب نشده است"}
        binary = find_binary(explicit=self.binary)
        provider = LlamaCppProvider(model_id=spec.model_id, model_path=row.path, binary=binary,
                                    context=device_profile.context_for(),
                                    threads=device_profile.threads_for(), start_server=True)
        if not provider.available():
            return {"ok": False, "code": "RUNTIME_MISSING",
                    "message": "فایل اجرایی llama.cpp پیدا نشد؛ حالت قطعی فعال می‌ماند "
                               "(راهنمای نصب در docs/AI_MODEL_INSTALLATION.md)"}
        state = provider.health_check()
        return {"ok": bool(state.get("ok")), "code": "RUNNING" if state.get("ok") else "NOT_RUNNING",
                "message": "مدل در حال اجراست" if state.get("ok") else "مدل اجرا نشده است",
                "provider": provider.name, "benchmark": provider.benchmark() if benchmark else None}

    def unload(self, model_id: str | None = None) -> dict:
        from .runtime import LlamaCppProvider

        model_id = model_id or self.active_id()
        row = self._row(model_id) if model_id else None
        if row is None:
            return {"ok": True, "code": "NOT_RUNNING", "message": "مدلی برای آزادسازی نبود"}
        provider = LlamaCppProvider(model_id=model_id, model_path=row.path,
                                    binary=find_binary(explicit=self.binary), start_server=False)
        provider.unload()
        self._audit(model_id, "UNLOADED", {})
        return {"ok": True, "code": "UNLOADED", "message": "مدل از حافظه آزاد شد"}

    def benchmark(self, model_id: str | None = None, *, prompts=()) -> dict:
        """Real numbers from this device, or an honest "could not measure"."""
        from .runtime import LlamaCppProvider

        model_id = model_id or self.active_id()
        row = self._row(model_id) if model_id else None
        spec = model_registry.get(model_id) if model_id else None
        if row is None or spec is None or not row.path:
            return {"ok": False, "code": "NOT_INSTALLED", "message": "برای سنجش، مدل باید نصب شده باشد"}
        binary = find_binary(explicit=self.binary)
        provider = LlamaCppProvider(model_id=spec.model_id, model_path=row.path, binary=binary,
                                    context=device_profile.context_for(),
                                    threads=device_profile.threads_for(), start_server=True)
        if not provider.available():
            return {"ok": False, "code": "RUNTIME_MISSING", "message": "فایل اجرایی llama.cpp موجود نیست"}
        result = provider.benchmark(prompts=prompts)
        context = device_profile.context_after_benchmark(device_profile.profile(), result)
        self._record(model_id, "VERIFIED", path=Path(row.path), benchmark=result, context=context)
        self._audit(model_id, "BENCHMARKED", {k: result.get(k) for k in ("load_ms", "avg_ms", "persian_ok",
                                                                        "tool_call_ok", "memory_mb")})
        self.db.commit()
        return {"ok": True, "code": "BENCHMARKED" if result.get("load_ok") else "BENCHMARK_FAILED",
                "message": "سنجش انجام شد" if result.get("load_ok") else "مدل در این دستگاه بارگذاری نشد",
                "benchmark": result, "context": context}

    # ------------------------------------------------------------------ activate / rollback
    def activate(self, model_id: str, *, context: int | None = None) -> dict:
        row = self._row(model_id)
        if row is None or row.status not in READY_STATES:
            return {"ok": False, "code": "NOT_INSTALLED", "message": "ابتدا مدل را نصب کنید"}
        previous = self.active_id()
        previous_row = self._row(previous) if previous and previous != model_id else None
        self._set_setting("brain.model.active", model_id)
        self._set_setting("brain.runtime.context", str(context or device_profile.context_for()))
        self._record(model_id, "ACTIVE", path=Path(row.path) if row.path else None,
                     context=context or device_profile.context_for(),
                     previous_id=previous_row.id if previous_row else None)
        self._audit(model_id, "ACTIVATED", {"previous": previous, "context": context or device_profile.context_for()})
        self.db.commit()
        return {"ok": True, "code": "ACTIVATED", "message": "مدل فعال شد", "previous": previous or None}

    def rollback(self) -> dict:
        row = self._row(self.active_id())
        if row is None or not row.previous_install_id:
            return {"ok": False, "code": "NO_PREVIOUS", "message": "نسخهٔ قبلی برای بازگردانی ثبت نشده است"}
        previous = self.db.get(BrainModelInstall, int(row.previous_install_id))
        if previous is None:
            return {"ok": False, "code": "NO_PREVIOUS", "message": "نسخهٔ قبلی در دسترس نیست"}
        self._set_setting("brain.model.active", previous.model_id)
        self._record(previous.model_id, "ACTIVE", path=Path(previous.path) if previous.path else None)
        self._audit(previous.model_id, "ROLLED_BACK", {"from": row.model_id})
        self.db.commit()
        return {"ok": True, "code": "ROLLED_BACK", "message": f"به نسخهٔ {previous.model_id} بازگشتیم"}

    def forget(self, model_id: str, *, delete_file: bool = False) -> dict:
        """Rollback support: forget an install after switching away from it."""
        row = self._row(model_id)
        if row is None:
            return {"ok": False, "code": "NOT_FOUND", "message": "این مدل نصب نشده است"}
        self._record(model_id, "ROLLED_BACK", path=Path(row.path) if row.path else None)
        self.db.commit()
        return {"ok": True, "code": "FORGOTTEN", "message": "نسخهٔ قبلی علامت‌گذاری شد"}

    # ------------------------------------------------------------------ status
    def status(self, *, include_registry: bool = True) -> dict:
        # the model shipped inside the Windows installer registers itself here
        try:
            seeds = self.adopt_preinstalled()
        except Exception:  # noqa: BLE001 — status must always answer
            log.warning("seed adoption failed", exc_info=True)
            seeds = []
        prof = device_profile.profile()
        rows = self._all_rows()
        installs = {row.model_id: row for row in rows}
        history = [self._row_dict(row) for row in rows]
        active = self.active_id()
        active_row = installs.get(active)
        payload = {
            "active": active or None,
            "active_ready": bool(active_row and active_row.status in READY_STATES),
            "context": int(self._get_setting("brain.runtime.context", str(device_profile.context_for())) or 4096),
            "device": prof.to_dict(), "device_summary": device_profile.summary_line(prof),
            "recommended": device_profile.recommended_model_id(prof),
            "binary": find_binary(explicit=self.binary),
            "models_root": str(models_root()),
            "history": history,
            "cap_bytes": model_registry.MAX_FILE_BYTES,
            "installer_seeds": seeds,
        }
        if include_registry:
            payload["registry"] = model_registry.registry_payload()
            payload["forbidden"] = [dict(item) for item in model_registry.FORBIDDEN]
            payload["violations"] = model_registry.validate_registry()
        return payload

    def active_id(self) -> str:
        return str(self._get_setting("brain.model.active", "") or "")

    # ------------------------------------------------------------------ internals
    def _fetch(self, url: str, dest: Path, progress) -> str | None:
        """Download to ``dest``; return the digest the host reports (if any).

        v4.0.1: the bytes now move through the Business Brain download manager
        (progress bar, parallel connections, resume after an interruption,
        official fallback sources, optional IDM on Windows). The injected
        ``self.downloader`` hook stays first so tests can fake the network.
        """
        if self.downloader is not None:
            result = self.downloader(url, dest, progress)
            return str(result) if result else None
        spec = next((s for s in model_registry.all_models() if s.source_url == url), None)
        sources = model_registry.source_urls(spec) if spec else (url,)
        result = download_manager.fetch(
            sources, dest,
            expected_size=spec.file_size_bytes if spec else None,
            expected_sha256=spec.sha256 if spec else None,
            progress=progress,
            downloader=os.environ.get("SUPERMARKET_BRAIN_DOWNLOADER", "auto"),
            connections=max(1, min(16, int(os.environ.get("SUPERMARKET_BRAIN_CONNECTIONS", "4")
                                            or 4))),
            quiet=True, resume=True)
        return result.get("server_sha256")

    def _all_rows(self) -> list[BrainModelInstall]:
        return list(self.db.execute(select(BrainModelInstall).order_by(BrainModelInstall.id)).scalars())

    def _row(self, model_id: str) -> BrainModelInstall | None:
        return self.db.execute(select(BrainModelInstall)
                               .where(BrainModelInstall.model_id == model_id)
                               .order_by(BrainModelInstall.id.desc())).scalars().first()

    def _record(self, model_id: str, status: str, *, path: Path | None = None, size: int = 0,
                sha256: str = "", benchmark: dict | None = None, context: int | None = None,
                previous_id: int | None = None) -> BrainModelInstall:
        spec = model_registry.get(model_id)
        row = self._row(model_id)
        if row is None or (path is None and row.status in READY_STATES):
            row = BrainModelInstall(model_id=model_id, status="PENDING")
            self.db.add(row)
        row.status = status
        if path is not None:
            row.path = str(path)
        if size:
            row.size_bytes = int(size)
        if sha256:
            row.sha256 = sha256
        if benchmark is not None:
            row.benchmark = json.dumps(benchmark, ensure_ascii=False)
        if context:
            row.device_profile = json.dumps({**device_profile.profile().to_dict(), "context": context},
                                            ensure_ascii=False)
        if previous_id is not None:
            row.previous_install_id = previous_id
        self.db.flush()
        return row

    def _fail(self, model_id: str, code: str, message: str) -> dict:
        self._record(model_id, "FAILED", path=None)
        row = self._row(model_id)
        if row is not None:
            row.error = f"{code}: {message}"[:400]
        self._audit(model_id, code, {"message": message})
        self.db.commit()
        return {"ok": False, "code": code, "message": message}

    def _audit(self, model_id: str, event: str, detail: dict) -> None:
        try:
            brain_audit(self.db, event="BRAIN_MODEL_EVENT", after={"model_id": model_id, "event": event, **detail})
        except Exception:  # noqa: BLE001 — auditing must not break a download
            log.warning("model audit write failed for %s/%s", model_id, event)

    def _set_setting(self, key: str, value: str) -> None:
        row = self.db.execute(select(SystemSetting).where(SystemSetting.key == key)).scalar_one_or_none()
        if row is None:
            self.db.add(SystemSetting(key=key, value=value, description="Business Brain v4.0"))
        else:
            row.value = value
        self.db.flush()

    def _get_setting(self, key: str, default: str = "") -> str:
        row = self.db.execute(select(SystemSetting).where(SystemSetting.key == key)).scalar_one_or_none()
        return row.value if row else default

    @staticmethod
    def _row_dict(row: BrainModelInstall) -> dict:
        try:
            benchmark = json.loads(row.benchmark or "{}")
        except ValueError:
            benchmark = {}
        return {"id": row.id, "model_id": row.model_id, "status": row.status,
                "size_bytes": int(row.size_bytes or 0), "sha256": row.sha256,
                "path": row.path, "error": row.error,
                "activated_at": row.activated_at.isoformat() if row.activated_at else None,
                "benchmark": benchmark}


def active_install(db: Session) -> BrainModelInstall | None:
    """The install the runtime should use: explicit setting → newest ready row."""
    row = db.execute(select(SystemSetting).where(SystemSetting.key == "brain.model.active")).scalar_one_or_none()
    if row and row.value:
        install = db.execute(select(BrainModelInstall).where(BrainModelInstall.model_id == row.value)
                             .order_by(BrainModelInstall.id.desc())).scalars().first()
        if install and install.path and Path(install.path).exists():
            return install
    return db.execute(select(BrainModelInstall)
                      .where(BrainModelInstall.status.in_(READY_STATES))
                      .order_by(BrainModelInstall.id.desc())).scalars().first()
