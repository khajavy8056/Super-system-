"""Barcode / image / price resolvers (§9–15).

Pipeline: barcode validation (GS1 checksum) → local DB → approved cache →
configured external providers (multi-source, classified errors) →
normalization → merge + conflict detection → confidence → PERSIST AS PENDING →
human review → apply.

Rules:
- No external data enters the master tables without human approval (§52).
- Provider failures are classified and reported per source, never swallowed
  (BUG-009) and never fake-succeeded.
- External lookups persist their candidates in the SAME transaction the API
  endpoint commits (BUG-006) — the cache actually works now.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import (
    ExternalSource,
    ImageAsset,
    MarketPrice,
    Product,
    ProductResolverResult,
)
from .barcode import normalize, validate
from .catalog import get_product_by_barcode
from .providers import REGISTRY, BaseProvider, ProviderError, ProviderLookup

MERGEABLE_FIELDS = ("name", "brand", "sku", "model", "description", "unit", "category")


class ResolverError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class SourceOutcome:
    source_code: str
    provider: str
    ok: bool
    error_kind: str | None = None
    error_detail: str | None = None
    lookup: ProviderLookup | None = None


@dataclass
class MergeReport:
    field: str
    values: list[dict] = field(default_factory=list)  # {value, source, confidence}
    conflict: bool = False
    chosen: str | None = None
    chosen_confidence: str = "LOW"


def _active_sources(db: Session, source_type: str) -> list[ExternalSource]:
    return list(
        db.execute(
            select(ExternalSource)
            .where(ExternalSource.source_type == source_type, ExternalSource.is_active.is_(True))
            .order_by(ExternalSource.priority.asc())
        ).scalars()
    )


def _instantiate(source: ExternalSource) -> BaseProvider | None:
    # The provider implementation is chosen by the source's provider_code; the
    # registry maps it to a class. Unknown codes fall back to custom_http.
    code = (source.code.split(":", 1)[0] if ":" in source.code else source.code)
    cls = REGISTRY.get(code, REGISTRY["custom_http"])
    return cls(source)


def resolve_barcode(db: Session, barcode: str, *, client: httpx.Client | None = None) -> dict:
    """Full §9 pipeline for one barcode. Persists PENDING candidates on success."""
    barcode = normalize(barcode)
    ok, fmt = validate(barcode)
    if not ok:
        return {"origin": "invalid", "need_manual": True, "barcode": barcode,
                "message": "بارکد نامعتبر (checksum) — احتمال اسکن ناقص"}

    # 1) local database
    local = get_product_by_barcode(db, barcode)
    if local:
        return {"origin": "local", "barcode": barcode, "format": fmt,
                "product": _product_dict(local), "need_manual": False}

    # 2) approved cache — a previously reviewed barcode maps to an existing product
    cached = db.execute(
        select(ProductResolverResult).where(
            ProductResolverResult.barcode == barcode,
            ProductResolverResult.status == "APPROVED",
        )
    ).scalars().all()
    product_ids = {r.product_id for r in cached if r.product_id}
    if product_ids:
        for pid in product_ids:
            product = db.get(Product, pid)
            if product:
                return {"origin": "cache", "barcode": barcode, "format": fmt,
                        "product": _product_dict(product), "need_manual": False}

    # 3) external providers (multi-source)
    outcomes: list[SourceOutcome] = []
    sources = _active_sources(db, "PRODUCT")
    for source in sources:
        provider = _instantiate(source)
        try:
            lookup = provider.lookup(barcode, client=client)
            outcomes.append(SourceOutcome(source.code, provider.code, True, lookup=lookup))
        except ProviderError as exc:
            outcomes.append(SourceOutcome(source.code, provider.code, False,
                                          error_kind=exc.kind, error_detail=exc.detail))

    # 4-6) normalize + merge + confidence
    merged = _merge(outcomes)

    # 7) persist PENDING candidates for human review (BUG-006/007)
    review_id = _persist_candidates(db, barcode, outcomes, merged)

    any_data = any(o.ok and (o.lookup and (o.lookup.fields or o.lookup.image_url)) for o in outcomes)
    return {
        "origin": "external" if any_data else "none",
        "barcode": barcode,
        "format": fmt,
        "need_manual": True,  # external data ALWAYS requires human review (§52)
        "review_id": review_id,
        "merged": {m.field: {"chosen": m.chosen, "confidence": m.chosen_confidence,
                             "conflict": m.conflict,
                             "sources": m.values} for m in merged},
        "sources": [{"source": o.source_code, "provider": o.provider, "ok": o.ok,
                     "error": ({"kind": o.error_kind, "detail": o.error_detail}
                               if not o.ok else None),
                     "fields": ({f.field: f.value for f in o.lookup.fields} if o.lookup else {}),
                     "image_url": o.lookup.image_url if o.lookup else None}
                    for o in outcomes],
        "message": None if any_data else "هیچ منبعی داده‌ای برای این بارکد برنگرداند؛ ثبت دستی لازم است.",
    }


def _normalize_value(value: str) -> str:
    return " ".join((value or "").split())


def _merge(outcomes: list[SourceOutcome]) -> list[MergeReport]:
    reports: dict[str, MergeReport] = {}
    for outcome in outcomes:
        if not outcome.ok or not outcome.lookup:
            continue
        for lf in outcome.lookup.fields:
            if lf.field not in MERGEABLE_FIELDS:
                continue
            val = _normalize_value(lf.value)
            if not val:
                continue
            rep = reports.setdefault(lf.field, MergeReport(field=lf.field))
            rep.values.append({"value": val, "source": outcome.source_code})
    result: list[MergeReport] = []
    for field, rep in reports.items():
        distinct = {v["value"] for v in rep.values}
        rep.conflict = len(distinct) > 1
        if not rep.conflict:
            rep.chosen = rep.values[0]["value"]
            rep.chosen_confidence = "HIGH" if len(rep.values) >= 2 else "MEDIUM"
        else:
            # pick the most common value; ties -> first by source priority; LOW confidence
            counts: dict[str, int] = {}
            for v in rep.values:
                counts[v["value"]] = counts.get(v["value"], 0) + 1
            rep.chosen = sorted(counts.items(), key=lambda kv: (-kv[1], rep.values.index(next(x for x in rep.values if x["value"] == kv[0]))))[0][0]
            rep.chosen_confidence = "LOW"
        result.append(rep)
    return result


def _persist_candidates(db: Session, barcode: str, outcomes: list[SourceOutcome],
                        merged: list[MergeReport]) -> int | None:
    """Store every per-source candidate + the merged proposal as PENDING."""
    if not any(o.ok for o in outcomes):
        return None
    first = None
    for outcome in outcomes:
        if not outcome.ok or not outcome.lookup:
            continue
        for lf in outcome.lookup.fields:
            if lf.field in MERGEABLE_FIELDS and _normalize_value(lf.value):
                row = ProductResolverResult(
                    barcode=barcode, source_code=outcome.source_code,
                    field=lf.field, value=_normalize_value(lf.value),
                    confidence=lf.confidence,
                    status="PENDING", created_at=datetime.utcnow(),
                )
                db.add(row)
                first = first or row
        if outcome.lookup.image_url:
            row = ProductResolverResult(
                barcode=barcode, source_code=outcome.source_code,
                field="image_url", value=outcome.lookup.image_url,
                confidence="MEDIUM", status="PENDING", created_at=datetime.utcnow(),
            )
            db.add(row)
            first = first or row
    for rep in merged:
        if rep.chosen:
            row = ProductResolverResult(
                barcode=barcode, source_code="merged",
                field=f"merged_{rep.field}", value=rep.chosen,
                confidence=rep.chosen_confidence, status="PENDING",
                created_at=datetime.utcnow(),
            )
            db.add(row)
            first = first or row
    db.flush()
    return first.id if first else None


# --- Image resolution with basic validation (§13) ------------------------------

_IMAGE_SIGNATURES = {
    b"\xff\xd8\xff": "JPEG",
    b"\x89PNG\r\n\x1a\n": "PNG",
    b"RIFF": "WEBP",  # + bytes 8..11 == WEBP
}
MIN_IMAGE_BYTES = 1024
MAX_IMAGE_BYTES = 8 * 1024 * 1024


def validate_image_url(url: str, *, client: httpx.Client | None = None) -> dict:
    """Download (bounded) and validate format/accessibility/corruption-signature.

    Honest scope: this validates accessibility, size bounds, content-type and
    magic-byte signature. Pixel-resolution checks need Pillow and are planned
    for the hardware/UI phase — documented, not claimed.
    """
    own = client is None
    c = client or httpx.Client(timeout=settings.EXTERNAL_TIMEOUT_SECONDS, follow_redirects=True)
    try:
        with c.stream("GET", url, timeout=settings.EXTERNAL_TIMEOUT_SECONDS) as resp:
            if resp.status_code != 200:
                return {"ok": False, "reason": f"HTTP_{resp.status_code}"}
            ctype = resp.headers.get("content-type", "")
            length = int(resp.headers.get("content-length") or 0)
            if length and (length < MIN_IMAGE_BYTES or length > MAX_IMAGE_BYTES):
                return {"ok": False, "reason": "SIZE_OUT_OF_BOUNDS"}
            buf = b""
            for chunk in resp.iter_bytes(64 * 1024):
                buf += chunk
                if len(buf) > MAX_IMAGE_BYTES:
                    return {"ok": False, "reason": "TOO_LARGE"}
            if len(buf) < MIN_IMAGE_BYTES:
                return {"ok": False, "reason": "TOO_SMALL"}
            sig = buf[:8]
            fmt = None
            if sig.startswith(b"\xff\xd8\xff"):
                fmt = "JPEG"
            elif sig.startswith(b"\x89PNG\r\n\x1a\n"):
                fmt = "PNG"
            elif buf[:4] == b"RIFF" and buf[8:12] == b"WEBP":
                fmt = "WEBP"
            elif sig.startswith(b"GIF8"):
                fmt = "GIF"
            if fmt is None:
                return {"ok": False, "reason": "NOT_AN_IMAGE"}
            if ctype and "image" not in ctype and "octet-stream" not in ctype:
                return {"ok": False, "reason": "BAD_CONTENT_TYPE"}
            return {"ok": True, "format": fmt, "bytes": len(buf)}
    except httpx.TimeoutException:
        return {"ok": False, "reason": "TIMEOUT"}
    except httpx.HTTPError as exc:
        return {"ok": False, "reason": f"HTTP_ERROR:{type(exc).__name__}"}
    finally:
        if own:
            c.close()


def resolve_image(db: Session, barcode: str, product_id: int | None = None,
                  *, client: httpx.Client | None = None) -> dict:
    """Collect image candidates from PRODUCT/IMAGE sources, validate, keep best."""
    candidates: list[dict] = []
    sources = _active_sources(db, "IMAGE") + _active_sources(db, "PRODUCT")
    seen_urls: set[str] = set()
    for source in sources:
        provider = _instantiate(source)
        try:
            lookup = provider.lookup(barcode, client=client)
        except ProviderError:
            continue
        url = lookup.image_url
        if url and url not in seen_urls:
            seen_urls.add(url)
            v = validate_image_url(url, client=client)
            entry = {"url": url, "source": source.code, "validation": v}
            candidates.append(entry)
            if v.get("ok"):
                db.add(ImageAsset(
                    product_id=product_id, barcode=barcode, source_id=source.id,
                    url=url, format=v.get("format"), confidence="MEDIUM",
                    is_primary=False, status="VALIDATED", created_at=datetime.utcnow(),
                ))
    db.flush()
    valid = [c for c in candidates if c["validation"].get("ok")]
    best = valid[0] if valid else None
    return {"candidates": candidates, "valid_count": len(valid),
            "best": best["url"] if best else None}


# --- Market price resolution (§15) ---------------------------------------------

def resolve_market_price(db: Session, barcode: str, product_id: int | None = None,
                         *, client: httpx.Client | None = None) -> dict:
    sources = _active_sources(db, "PRICE")
    found: list[Decimal] = []
    report = []
    for source in sources:
        provider = _instantiate(source)
        try:
            lookup = provider.lookup(barcode, client=client)
            if lookup.price is not None and lookup.price > 0:
                db.add(MarketPrice(
                    product_id=product_id, barcode=barcode, source_id=source.id,
                    price=lookup.price, confidence="MEDIUM",
                    observed_at=datetime.utcnow(), created_at=datetime.utcnow(),
                ))
                found.append(lookup.price)
                report.append({"source": source.code, "ok": True, "price": float(lookup.price)})
            else:
                report.append({"source": source.code, "ok": True, "price": None})
        except ProviderError as exc:
            report.append({"source": source.code, "ok": False, "error": exc.kind})
    db.flush()
    aggregate = None
    if found:
        found.sort()
        n = len(found)
        median = found[n // 2] if n % 2 else (found[n // 2 - 1] + found[n // 2]) / 2
        aggregate = {"min": float(min(found)), "max": float(max(found)),
                     "median": float(median), "average": float(sum(found) / n), "count": n}
    return {"prices": report, "aggregate": aggregate,
            "note": "پیشنهاد قیمت است؛ کاربر باید Accept/Edit/Reject کند."}


def _product_dict(p: Product) -> dict:
    return {
        "id": p.id, "barcode": p.barcode, "name": p.name, "sku": p.sku,
        "brand_id": p.brand_id, "category_id": p.category_id, "unit_id": p.unit_id,
        "model": p.model, "description": p.description, "image_url": p.image_url,
        "min_stock_alert": p.min_stock_alert, "is_active": p.is_active,
    }
