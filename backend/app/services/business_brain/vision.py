"""v4.0 — Vision interface (§43).

The requirement is explicit: ship the **interface** now, the capability later.

So this module defines:

* :class:`VisionProvider` — the contract a future camera/shelf-analysis engine
  (on-device, or a service the owner chooses) must satisfy;
* :class:`NullVisionProvider` — the shipped implementation, which reports
  "not available" instead of pretending;
* :class:`VisionEvidence` — what shelf analysis may contribute as **evidence**:
  facings, empty shelf slots, misplaced products, price-tag gaps;
* the rule that matters: vision evidence is never sufficient on its own for a
  financial decision. :func:`can_decide` encodes that, and the planner must ask
  it before using any vision-derived number in money terms.

Nothing here downloads a model or reads a camera. Existing hardware integration
(``services/hw``: printers, drawers, scanners, scales, label printers, customer
displays) is untouched by this file — those are devices, not perception.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime

#: observation kinds the brain may receive. An unknown kind is ignored rather
#: than interpreted, so a future provider cannot smuggle new semantics in.
KINDS = ("SHELF_FACINGS", "EMPTY_SLOT", "MISPLACED_PRODUCT", "MISSING_PRICE_TAG",
         "EXPIRY_VISIBLE_ESTIMATE", "PLANOGRAM_DEVIATION")


@dataclass
class VisionObservation:
    kind: str
    product_id: int | None = None
    value: float | None = None          # e.g. facings count, empty slots
    confidence: float = 0.0             # 0..1, provider-reported
    shelf: str | None = None
    at: datetime | None = None
    note: str = ""

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(f"unknown vision observation kind: {self.kind}")

    def to_dict(self) -> dict:
        data = asdict(self)
        data["at"] = (self.at or datetime.utcnow()).isoformat()
        return data


@dataclass
class VisionEvidence:
    """Evidence container — deliberately mirrors ``schemas.Evidence``."""

    domain: str = "vision"
    available: bool = False
    provider: str = "none"
    observations: list[VisionObservation] = field(default_factory=list)
    summary: str = ""
    #: vision never produces money; this stays empty by contract
    numbers: dict = field(default_factory=dict)
    flags: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    confidence: str = "low"

    def to_dict(self) -> dict:
        return {"domain": self.domain, "available": self.available, "provider": self.provider,
                "summary": self.summary, "numbers": dict(self.numbers), "flags": list(self.flags),
                "sources": list(self.sources), "confidence": self.confidence,
                "observations": [o.to_dict() for o in self.observations]}


class VisionProvider:
    """Contract for a future perception engine."""

    name = "none"

    def available(self) -> bool:
        return False

    def observe(self, *, product_ids: list[int] | None = None, shelf: str | None = None) -> VisionEvidence:
        raise NotImplementedError

    def status(self) -> dict:
        return {"provider": self.name, "available": self.available(),
                "kinds": list(KINDS),
                "note": "در این نسخه فقط رابط پیاده‌سازی شده است؛ موتور بینایی همراه محصول نیست"}


class NullVisionProvider(VisionProvider):
    """The shipped implementation: honest, silent, and totally dependency-free."""

    name = "unavailable"

    def available(self) -> bool:
        return False

    def observe(self, *, product_ids: list[int] | None = None, shelf: str | None = None) -> VisionEvidence:
        return VisionEvidence(available=False, provider=self.name,
                              summary="شواهد تصویری در دسترس نیست؛ تصمیم‌ها فقط بر داده‌های فروش استوارند",
                              flags=["VISION_UNAVAILABLE"])


#: module-level provider the app can swap later (settings-driven) without touching callers
PROVIDER: VisionProvider = NullVisionProvider()


def get_provider() -> VisionProvider:
    return PROVIDER


def set_provider(provider: VisionProvider) -> None:
    global PROVIDER
    PROVIDER = provider


def can_decide(*, financial: bool, evidence: VisionEvidence | None) -> tuple[bool, str]:
    """§43 — vision alone may never carry a financial decision.

    Returns ``(allowed, reason)``. The planner calls this before it turns any
    vision-derived observation into money.
    """
    if financial and evidence is not None and evidence.available and evidence.observations:
        return False, ("شواهد تصویری به‌تنهایی برای تصمیم مالی کافی نیست؛ باید با "
                       "فروش، موجودی، رفتار مشتری و حاشیهٔ سود ترکیب شود")
    return True, ""


def status() -> dict:
    return PROVIDER.status()


__all__ = ["KINDS", "VisionObservation", "VisionEvidence", "VisionProvider", "NullVisionProvider",
           "get_provider", "set_provider", "can_decide", "status"]
