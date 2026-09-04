"""Barcode / image / price resolvers (blueprint §48–57, §127–131).

Resolution order (no fake data):
1. Local database  -> 2. Local cache -> 3. Configured external sources ->
4. Manual entry. The POS is never blocked by an external API failure (§129).
External results are always stored with source + timestamp + confidence and are
only merged into the master product after human confirmation (§52).
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import ExternalSource, ImageAsset, MarketPrice, Product, ProductResolverResult
from .catalog import get_product_by_barcode


class ResolverError(Exception):
    pass


def _active_sources(db: Session, source_type: str) -> list[ExternalSource]:
    return list(
        db.execute(
            select(ExternalSource)
            .where(ExternalSource.source_type == source_type, ExternalSource.is_active.is_(True))
            .order_by(ExternalSource.priority.asc())
        ).scalars()
    )


def _fetch(source: ExternalSource, barcode: str) -> Any | None:
    """Call a configured source. Returns parsed JSON or None on failure."""
    if not source.base_url:
        return None
    url = source.base_url.replace("{barcode}", barcode)
    headers = {}
    if source.api_key:
        headers["Authorization"] = f"Bearer {source.api_key}"
    try:
        resp = httpx.get(url, headers=headers, timeout=settings.EXTERNAL_TIMEOUT_SECONDS)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return None


def _looks_valid(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def resolve_barcode(db: Session, barcode: str) -> dict:
    """Resolve a scanned barcode to product data."""
    local = get_product_by_barcode(db, barcode)
    if local:
        return {"origin": "local", "product": _product_dict(local), "need_manual": False}

    # Local cache: previously approved resolver results for this barcode.
    approved = db.execute(
        select(ProductResolverResult)
        .where(ProductResolverResult.barcode == barcode, ProductResolverResult.status == "APPROVED")
        .limit(1)
    ).scalars().all()
    if approved and approved[0].product_id:
        product = db.get(Product, approved[0].product_id)
        if product:
            return {"origin": "cache", "product": _product_dict(product), "need_manual": False}

    # External sources (product type).
    results: list[dict] = []
    for source in _active_sources(db, "PRODUCT"):
        payload = _fetch(source, barcode)
        if payload:
            extracted = _extract_fields(payload)
            for field, value in extracted.items():
                if _looks_valid(value):
                    results.append({"field": field, "value": value, "source": source.code,
                                    "confidence": "MEDIUM"})
    if results:
        for r in results:
            db.add(ProductResolverResult(
                barcode=barcode, source_id=None, field=r["field"], value=r["value"],
                confidence=r["confidence"], status="PENDING", created_at=datetime.utcnow(),
            ))
        db.flush()
        return {"origin": "external", "candidates": results, "need_manual": False, "product": None}

    return {"origin": "none", "candidates": [], "need_manual": True,
            "message": "No product data found. Manual entry required."}


def _extract_fields(payload: Any) -> dict[str, str]:
    """Best-effort extraction of known fields from arbitrary JSON."""
    out: dict[str, str] = {}
    if not isinstance(payload, dict):
        return out
    mapping = {
        "name": ("name", "title", "product_name", "item_name"),
        "brand": ("brand", "brand_name", "manufacturer"),
        "model": ("model", "sku"),
        "description": ("description", "details"),
        "unit": ("unit", "uom"),
        "category": ("category", "category_name"),
    }
    for target, keys in mapping.items():
        for k in keys:
            if k in payload and _looks_valid(payload[k]):
                out[target] = str(payload[k])
                break
    return out


def resolve_image(db: Session, barcode: str, product_id: int | None = None) -> dict:
    sources = _active_sources(db, "IMAGE")
    candidates: list[dict] = []
    for source in sources:
        payload = _fetch(source, barcode)
        if payload:
            url = payload.get("image_url") or payload.get("url") or payload.get("image")
            if url:
                asset = ImageAsset(
                    product_id=product_id, barcode=barcode, source_id=source.id, url=url,
                    confidence="MEDIUM", status="PENDING", created_at=datetime.utcnow(),
                )
                db.add(asset)
                candidates.append({"url": url, "source": source.code, "confidence": "MEDIUM"})
    db.flush()
    return {"candidates": candidates, "count": len(candidates)}


def resolve_market_price(db: Session, barcode: str, product_id: int | None = None) -> dict:
    sources = _active_sources(db, "PRICE")
    found: list[Decimal] = []
    for source in sources:
        payload = _fetch(source, barcode)
        if payload:
            price = _extract_price(payload)
            if price is not None:
                db.add(MarketPrice(
                    product_id=product_id, barcode=barcode, source_id=source.id,
                    price=price, confidence="MEDIUM", observed_at=datetime.utcnow(),
                    created_at=datetime.utcnow(),
                ))
                found.append(price)
    db.flush()
    if not found:
        return {"prices": [], "aggregate": None}
    found.sort()
    n = len(found)
    median = found[n // 2] if n % 2 else (found[n // 2 - 1] + found[n // 2]) / 2
    return {
        "prices": [float(p) for p in found],
        "aggregate": {
            "min": float(min(found)), "max": float(max(found)),
            "median": float(median), "average": float(sum(found) / n), "count": n,
        },
    }


def _extract_price(payload: Any) -> Decimal | None:
    if isinstance(payload, dict):
        for k in ("price", "sell_price", "market_price", "value"):
            if k in payload:
                try:
                    return Decimal(str(payload[k]))
                except Exception:
                    return None
    return None


def _product_dict(p: Product) -> dict:
    return {
        "id": p.id,
        "barcode": p.barcode,
        "name": p.name,
        "sku": p.sku,
        "brand_id": p.brand_id,
        "category_id": p.category_id,
        "unit_id": p.unit_id,
        "model": p.model,
        "description": p.description,
        "image_url": p.image_url,
        "min_stock_alert": p.min_stock_alert,
        "is_active": p.is_active,
    }
