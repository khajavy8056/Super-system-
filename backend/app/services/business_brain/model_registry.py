"""v4.0 — Model Registry (§29, §30, §36, §37).

The registry is the *policy document* the Model Manager obeys: which files may be
downloaded, from where, at what size, with which checksum, and which model fits
which device. Everything else in the model layer derives from this table, and the
v4.0 test suite iterates it — so a future contributor cannot quietly add a 4 GB
model to a product that must run on a 4 GB shop PC.

Hard rules encoded here and asserted by tests:

* **size** — every entry is ≤ 2 GiB (``MAX_FILE_BYTES``); the sum of all entries
  is not what ships, since only one is installed at a time;
* **source** — HTTPS on an official Qwen GGUF repository. No mirrors, no
  aggregators, no "someone's Google Drive";
* **quantization** — Q4_K_M is the baseline, Q3_K_M the 4 GB fallback. Q8 is
  refused outright (it breaks the size cap), as is Qwen3-4B in this release;
* **context** — 4096 by default. 8192 is only granted after a benchmark shows
  the device sustains it, never by configuration alone;
* **checksum** — a pinned sha256 when the release ships one, otherwise the
  digest Hugging Face reports for the LFS object (``X-Linked-Etag``). A download
  that cannot be verified to *some* trusted digest is never installed.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path

#: §29 — the one number the whole release is built around.
MAX_FILE_BYTES = 2 * 1024 * 1024 * 1024          # 2 GiB
MiB = 1024 * 1024

#: §30 — the shipped catalogue. Sizes are the real file sizes of these quants.
MODELS: tuple["ModelSpec", ...] = ()


@dataclass(frozen=True)
class ModelSpec:
    model_id: str
    family: str
    parameters: str
    quantization: str
    file_name: str
    file_size_bytes: int
    source_url: str
    #: sha256 of the file as published. ``None`` means "trust the digest the
    #: official host reports for this object" (Hugging Face LFS etag = sha256).
    sha256: str | None = None
    context_default: int = 4096
    context_max: int = 8192
    min_ram_mb: int = 4096
    recommended_ram_mb: int = 8192
    capabilities: tuple[str, ...] = ("chat", "tool_calling", "json", "persian")
    format: str = "gguf"
    license: str = "apache-2.0"
    notes: str = ""
    #: v4.2.1 — the owner's product branding for this model. The technical id
    #: stays (it pins the exact file); what the USER sees is this name.
    display_name: str = ""
    tier: str = "baseline"          # baseline | low-ram | experimental
    license_url: str = "https://huggingface.co/Qwen/Qwen3-1.7B-GGUF"
    source_host: str = "huggingface.co"
    #: Official fallback sources, tried in order when the primary is blocked or
    #: slow (a shop PC must not depend on one CDN). Qwen publishes the *same*
    #: objects on ModelScope — Alibaba's own hub, first-party for Qwen — and
    #: ModelScope reports the identical sha256 for both quants (checked
    #: 2026-09-23). This is not a mirror: it is the publisher's other channel,
    #: and the pinned sha256 gate applies to every source equally.
    alt_source_urls: tuple[str, ...] = ()
    alt_source_hosts: tuple[str, ...] = ()

    # ------------------------------------------------------------------ policy
    @property
    def max_file_size_bytes(self) -> int:
        return MAX_FILE_BYTES

    @property
    def gb(self) -> float:
        return round(self.file_size_bytes / (1024 ** 3), 2)

    def within_cap(self, cap: int = MAX_FILE_BYTES) -> bool:
        return 0 < self.file_size_bytes <= cap

    def to_dict(self) -> dict:
        data = asdict(self)
        data["file_size_mb"] = round(self.file_size_bytes / MiB, 1)
        data["within_cap"] = self.within_cap()
        data["max_file_size_bytes"] = MAX_FILE_BYTES
        return data


def _models() -> tuple[ModelSpec, ...]:
    """Built lazily so the dataclass exists before the tuples reference it.

    Sizes and sha256 values below are the **published** values from the official
    Qwen GGUF repository (Hugging Face LFS objects), read on 2026-09-22. They are
    the reason ``scripts/model/fetch_model.py`` can verify a download offline.
    """
    return (
        ModelSpec(
            model_id="qwen2.5-1.5b-instruct-q4_k_m",
            family="Qwen2.5",
            parameters="1.5B",
            quantization="Q4_K_M",
            file_name="qwen2.5-1.5b-instruct-q4_k_m.gguf",
            file_size_bytes=1_117_320_736,                   # 1.04 GiB, published size
            sha256="6a1a2eb6d15622bf3c96857206351ba97e1af16c30d7a74ee38970e434e9407e",
            source_url="https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/"
                       "qwen2.5-1.5b-instruct-q4_k_m.gguf",
            context_default=4096, context_max=8192,
            min_ram_mb=4096, recommended_ram_mb=8192, tier="baseline",
            capabilities=("chat", "tool_calling", "json", "persian"),
            license_url="https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF",
            alt_source_urls=(
                "https://modelscope.cn/models/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/master/"
                "qwen2.5-1.5b-instruct-q4_k_m.gguf",
            ),
            alt_source_hosts=("modelscope.cn",),
            notes="مدل پیش‌فرض v4.0 — سبک، چندزبانه، با پشتیبانی فراخوانی ابزار",
            display_name="مدل تخصصی سوپری‌من",
        ),
        ModelSpec(
            model_id="qwen2.5-1.5b-instruct-q3_k_m",
            family="Qwen2.5",
            parameters="1.5B",
            quantization="Q3_K_M",
            file_name="qwen2.5-1.5b-instruct-q3_k_m.gguf",
            file_size_bytes=924_455_968,                      # 0.86 GiB, published size
            sha256="58cb5c05ecef48e82961f1a2be6544145ea26136f69dddda4bbbd092f0e4b993",
            source_url="https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/"
                       "qwen2.5-1.5b-instruct-q3_k_m.gguf",
            context_default=4096, context_max=4096,
            # a machine sold as "4 GB" reports ~3.8 GB to the OS, so the fallback
            # tier must be installable there — otherwise the fallback never runs
            # on the exact device it exists for.
            min_ram_mb=3584, recommended_ram_mb=6144, tier="low-ram",
            capabilities=("chat", "tool_calling", "json", "persian"),
            license_url="https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF",
            alt_source_urls=(
                "https://modelscope.cn/models/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/master/"
                "qwen2.5-1.5b-instruct-q3_k_m.gguf",
            ),
            alt_source_hosts=("modelscope.cn",),
            notes="گزینهٔ ۴ گیگابایتی؛ کیفیت کمتر، حافظهٔ کمتر",
            display_name="سوپری‌من لایت",
        ),
    )


#: §29/§30 — refused on purpose, with the reason, so the refusal is documented
#: rather than re-litigated. Tests assert these stay refused.
FORBIDDEN: tuple[dict, ...] = (
    {"model_id": "qwen3-4b-q4_k_m", "reason": "حجم ≈۲٫۵ گیگابایت؛ از سقف ۲ گیگابایت عبور می‌کند",
     "sizes_gb": 2.5, "quantization": "Q4_K_M", "family": "Qwen3-4B"},
    {"model_id": "qwen3-1.7b-q8_0", "reason": "کوانتایز Q8 ممنوع است (۱٫۷۱ گیگابایت و بدون صرفهٔ کیفیت در "
                                               "دستگاه ۴ گیگابایتی)",
     "sizes_gb": 1.71, "quantization": "Q8_0", "family": "Qwen3"},
    {"model_id": "qwen3-1.7b-q4_k_m", "reason": "این فایل در مخزن رسمی Qwen3-1.7B-GGUF منتشر نشده است؛ "
                                                 "دانلود از آینه‌های غیررسمی مجاز نیست",
     "sizes_gb": 0.0, "quantization": "Q4_K_M", "family": "Qwen3"},
)


# ---------------------------------------------------------------- pinned digests
#: The Model Manager trusts ``spec.sha256``. A shop PC may additionally record the
#: digest it actually downloaded (``fetch_model.py --record``) into this sidecar
#: file; the sidecar can only ever *replace* a digest with another 64-char hex
#: value — it can never remove the requirement to verify.
DIGESTS_FILE = Path(os.environ.get("SUPERMARKET_BRAIN_DIGESTS",
                                   str(Path(__file__).with_name("model_digests.json"))))


def pinned_digests() -> dict[str, str]:
    try:
        data = json.loads(DIGESTS_FILE.read_text("utf-8"))
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in data.items() if isinstance(v, str) and re.fullmatch(r"[0-9a-f]{64}", v)}


def record_digest(model_id: str, sha256: str) -> Path:
    """Persist a verified digest for ``model_id``. Used by fetch_model.py --record."""
    if not re.fullmatch(r"[0-9a-f]{64}", (sha256 or "").strip().lower()):
        raise ValueError("sha256 must be 64 lowercase hex characters")
    if get(model_id) is None:
        raise KeyError(f"unknown model_id: {model_id}")
    data = pinned_digests()
    data[model_id] = sha256.strip().lower()
    DIGESTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = DIGESTS_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", "utf-8")
    tmp.replace(DIGESTS_FILE)
    _apply_pins()
    return DIGESTS_FILE


def _apply_pins() -> None:
    global MODELS
    pins = pinned_digests()
    if not pins:
        return
    MODELS = tuple(replace(spec, sha256=pins.get(spec.model_id, spec.sha256)) for spec in MODELS)


MODELS = _models()



# --------------------------------------------------------------------------- lookups
def all_models() -> tuple[ModelSpec, ...]:
    return MODELS


def get(model_id: str) -> ModelSpec | None:
    for spec in MODELS:
        if spec.model_id == model_id:
            return spec
    return None


def by_tier(tier: str) -> ModelSpec | None:
    """The model tagged for a device class — the only place tiers are resolved."""
    for spec in MODELS:
        if spec.tier == tier:
            return spec
    return None


def default_model() -> ModelSpec:
    """The baseline model; falls back to the largest entry if tiers were edited."""
    return by_tier("baseline") or by_size_desc()[0]


def by_size_desc() -> list[ModelSpec]:
    return sorted(MODELS, key=lambda s: s.file_size_bytes, reverse=True)


_apply_pins()


def registry_payload() -> list[dict]:
    return [spec.to_dict() for spec in MODELS]


def display_name(model_id: str | None) -> str:
    """v4.2.1 — the branded user-facing name for a model id (fallback: the id)."""
    spec = get(model_id) if model_id else None
    brand = getattr(spec, "display_name", "") if spec else ""
    return brand or (model_id or "")


def validate_registry(cap: int = MAX_FILE_BYTES) -> list[str]:
    """Return the list of policy violations (empty ⇒ healthy). Used by tests."""
    problems: list[str] = []
    seen: set[str] = set()
    for spec in MODELS:
        if spec.model_id in seen:
            problems.append(f"duplicate model_id: {spec.model_id}")
        seen.add(spec.model_id)
        if not spec.within_cap(cap):
            problems.append(f"{spec.model_id}: {spec.gb} GiB exceeds the {cap / 1024 ** 3:.0f} GiB cap")
        if not spec.source_url.startswith("https://"):
            problems.append(f"{spec.model_id}: source is not HTTPS")
        if spec.source_host not in spec.source_url:
            problems.append(f"{spec.model_id}: source is not on {spec.source_host}")
        for alt in spec.alt_source_urls:
            alt_host = alt.split("//", 1)[-1].split("/", 1)[0].lower()
            if not alt.startswith("https://"):
                problems.append(f"{spec.model_id}: fallback source is not HTTPS")
            elif alt_host not in spec.alt_source_hosts:
                problems.append(f"{spec.model_id}: fallback source {alt_host} is not an official host")
        if bool(spec.alt_source_urls) != bool(spec.alt_source_hosts):
            problems.append(f"{spec.model_id}: fallback urls and hosts are inconsistent")
        if spec.quantization.upper().startswith("Q8"):
            problems.append(f"{spec.model_id}: Q8 is forbidden")
        if "4B" in spec.parameters.upper():
            problems.append(f"{spec.model_id}: 4B parameters are forbidden in this release")
        if spec.context_default > spec.context_max:
            problems.append(f"{spec.model_id}: context_default exceeds context_max")
        if spec.context_default > 4096 and spec.tier != "experimental":
            problems.append(f"{spec.model_id}: default context must be 4096 on 4 GB devices")
        if not spec.file_name.endswith(".gguf"):
            problems.append(f"{spec.model_id}: file is not GGUF")
        if spec.sha256 is not None and not re.fullmatch(r"[0-9a-f]{64}", spec.sha256):
            problems.append(f"{spec.model_id}: pinned sha256 is not a sha256")
    return problems


def source_hosts(spec: ModelSpec | None = None) -> tuple[str, ...]:
    """Every official host for ``spec`` (primary first). No mirrors ever land here."""
    if spec is None:
        return ("huggingface.co",)
    return tuple(dict.fromkeys((spec.source_host, *spec.alt_source_hosts)))


def source_urls(spec: ModelSpec) -> tuple[str, ...]:
    """Download sources in priority order: the primary, then official fallbacks."""
    return (spec.source_url, *spec.alt_source_urls)


def allowed_source(url: str, spec: ModelSpec | None = None) -> bool:
    if not url.startswith("https://"):
        return False
    host = url.split("//", 1)[-1].split("/", 1)[0].lower()
    # exact host or a subdomain of it — "evil-huggingface.co" must not pass
    return any(host == allowed or host.endswith("." + allowed)
               for allowed in source_hosts(spec))


def fits(spec: ModelSpec, *, ram_mb: int, disk_free_mb: int | None = None) -> bool:
    """A model "fits" with room for the OS and the app, not just the file."""
    if ram_mb and ram_mb < spec.min_ram_mb:
        return False
    if disk_free_mb is not None and disk_free_mb < (spec.file_size_bytes / MiB) * 1.25:
        return False
    return True
