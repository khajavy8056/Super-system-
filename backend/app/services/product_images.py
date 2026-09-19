"""Product pictures — LOCAL ONLY (v3.5).

What this module used to do (v2.5–v3.4) was hunt for a photo on the open web:
OpenFoodFacts by barcode, OpenFoodFacts text search, Wikimedia Commons,
Wikipedia page images, and as a last resort DuckDuckGo image search — plus a
v2.6 Iranian-retail ladder that scraped Basalam/Torob listings. All of that is
**removed**:

* the default product bank now ships its own pictures — 13 537 of its 13 570
  lines carry one to three direct image links — so there is nothing left to
  search for;
* scraping third-party storefronts is fragile (layouts change, they rate-limit,
  they block data-centre IPs), slow, and needs the till to be online;
* a guessed photo on a real product is worse than no photo: the cashier sells
  the wrong line.

What remains:

* **store what the bank ships.** ``image_url`` / ``gallery`` are direct links;
  ``mirror_remote`` copies them into ``MEDIA_DIR/products`` so the shop keeps
  its pictures when the internet is down (§21 — ``image_url`` should end up a
  local path, never a hot link).
* **operator upload / paste-a-URL** (``set_image_from_bytes``,
  ``set_image_from_url``) with the same byte-level validation as before.
* the ``SyncJob`` queue entry points, so the phones and the sync worker keep
  working; ``backfill`` now honestly reports ``OFFLINE_MODE``.

Nothing here ever invents a picture. If there is no local file and no link to
mirror, the product simply has no thumbnail.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Brand, ImageAsset, Product, SystemSetting
from . import resolvers

log = logging.getLogger("supermarket.images")

UA = "SupermarketSystem/3.5 (+https://github.com/khajavy8056/Super-system-; product-thumbnails)"
TIMEOUT = 10.0


@dataclass
class Candidate:
    """A picture the operator may pick — v3.5: only ever the product's own links."""
    url: str
    title: str = ""
    source: str = "bank"
    score: float = 1.0


# --- helpers ---------------------------------------------------------------------
def setting(db: Session, key: str, default: str) -> str:
    row = db.execute(select(SystemSetting).where(SystemSetting.key == key)).scalar_one_or_none()
    return (row.value if row and row.value is not None else default)


def online_enabled() -> bool:
    """Web picture lookups were REMOVED in v3.5 — always ``False``.

    Kept as a function (rather than deleted) because the resolver pipeline and
    the tests ask it to decide whether any external source may be consulted.
    """
    return False


def _local_media(rel: str) -> str:
    return f"/media/{rel}"


def _client(client: httpx.Client | None) -> tuple[httpx.Client, bool]:
    if client is not None:
        return client, False
    return httpx.Client(timeout=TIMEOUT, headers={"User-Agent": UA}, follow_redirects=True), True


def gallery_of(product: Product) -> list[str]:
    """The picture links a product shipped with (``gallery`` JSON, else ``image_url``)."""
    urls: list[str] = []
    raw = getattr(product, "gallery", None)
    if raw:
        try:
            for u in json.loads(raw):
                if isinstance(u, str) and u.startswith("http") and u not in urls:
                    urls.append(u)
        except (ValueError, TypeError):
            pass
    if not urls and product.image_url and product.image_url.startswith("http"):
        urls.append(product.image_url)
    return urls[:3]


def list_candidates(db: Session, product: Product, *, client: httpx.Client | None = None,  # noqa: ARG001
                    limit: int = 12) -> list[dict]:
    """For the picker UI: the product's OWN shipped pictures — nothing is fetched.

    The old implementation returned web search results. There is no search any
    more, so the picker offers the one/two/three links the bank carried for this
    line (and nothing at all for a hand-typed product, which the operator
    photographs or uploads instead).
    """
    return [{"url": u, "title": product.name, "source": "bank", "score": 1.0}
            for u in gallery_of(product)[:limit]]


# --- local storage ----------------------------------------------------------------
def set_image_from_bytes(db: Session, product: Product, buf: bytes, report: dict | None = None,
                         *, url: str = "upload", source: str = "upload") -> dict:
    """Validate + store bytes under ``MEDIA_DIR/products`` and make them primary."""
    if report is None:
        fmt = resolvers._sniff_format(buf)
        if fmt is None or len(buf) < resolvers.MIN_IMAGE_BYTES or len(buf) > resolvers.MAX_IMAGE_BYTES:
            return {"ok": False, "reason": "INVALID_IMAGE"}
        dims = resolvers._image_dimensions(buf, fmt) or (None, None)
        report = {"format": fmt, "width": dims[0], "height": dims[1]}
    rel = resolvers.store_image_locally(product.barcode or f"p{product.id}", buf, report["format"])
    for old in db.execute(select(ImageAsset).where(ImageAsset.product_id == product.id,
                                                   ImageAsset.is_primary.is_(True))).scalars():
        old.is_primary = False
    db.add(ImageAsset(product_id=product.id, barcode=product.barcode, url=url, local_path=rel,
                      format=report.get("format"), width=report.get("width"), height=report.get("height"),
                      confidence="HIGH", is_primary=True, status="STORED", created_at=datetime.utcnow()))
    product.image_url = _local_media(rel)
    db.flush()
    return {"ok": True, "source": source, "local_path": product.image_url, "image_url": product.image_url}


def set_image_from_url(db: Session, product: Product, url: str, *, client: httpx.Client | None = None,
                       source: str = "manual") -> dict:
    """Operator picked a link (or pasted one): download, validate, store locally."""
    report, buf = resolvers._fetch_image(url, client=client)
    if not (report.get("ok") and buf):
        return {"ok": False, "reason": report.get("reason", "INVALID_IMAGE")}
    return set_image_from_bytes(db, product, buf, report, url=url, source=source)


def mirror_remote(db: Session, product: Product, *, client: httpx.Client | None = None,
                  force: bool = False) -> dict:
    """Copy the picture the bank shipped into local media (§21: never hot-link).

    Honest about every outcome: ``ALREADY_LOCAL`` / ``STORED`` / ``NO_REMOTE_IMAGE``
    / ``FETCH_FAILED``. Never raises, never blocks a save, never invents a photo.
    """
    if product.image_url and not product.image_url.startswith("http") and not force:
        return {"ok": True, "reason": "ALREADY_LOCAL", "local_path": product.image_url, "tried": 0}
    urls = gallery_of(product)
    if not urls:
        return {"ok": False, "reason": "NO_REMOTE_IMAGE", "tried": 0}
    c, close = _client(client)
    tried = 0
    try:
        for url in urls:
            tried += 1
            report, buf = resolvers._fetch_image(url, client=c)
            if not (report.get("ok") and buf):
                continue
            rep = set_image_from_bytes(db, product, buf, report, url=url, source="bank")
            if rep.get("ok"):
                rep.update({"reason": "STORED", "tried": tried})
                return rep
    finally:
        if close:
            c.close()
    return {"ok": False, "reason": "FETCH_FAILED", "tried": tried}


# ``find_and_store`` is the name the sync worker and the API call; it is now a
# thin alias for "mirror whatever the product shipped with".
def find_and_store(db: Session, product: Product, *, client: httpx.Client | None = None,
                   force: bool = False) -> dict:
    return mirror_remote(db, product, client=client, force=force)


# --- background queue -------------------------------------------------------------
def enqueue(db: Session, product_id: int, *, user_id: int | None = None) -> None:
    """Queue a background mirror of the product's shipped picture.

    Does nothing when the product has no remote link to copy — with the bank
    imported there is no point queueing 13 570 no-op jobs.
    """
    if not online_enabled():
        return
    from . import sync as sync_svc
    if setting(db, "images.auto_find", "true").lower() != "true":
        return
    from ..models import SyncJob
    dup = db.execute(select(SyncJob.id).where(
        SyncJob.idempotency_key == f"product-image:{product_id}")).scalar_one_or_none()
    if dup:
        return
    try:
        sync_svc.enqueue(db, job_type="PRODUCT_IMAGE", payload={"product_id": product_id},
                         reference_type="Product", reference_id=product_id,
                         idempotency_key=f"product-image:{product_id}", user_id=user_id, max_attempts=8)
    except Exception:  # noqa: BLE001 — a duplicate key must never break a save
        log.debug("image job already queued for product %s", product_id)


def backfill(db: Session, *, limit: int = 500, user_id: int | None = None) -> dict:
    """Mirror pictures for products that shipped a link but have no local file yet."""
    if not online_enabled():
        return {"queued": 0, "reason": "OFFLINE_MODE"}
    rows = db.execute(select(Product).where(
        Product.deleted_at.is_(None), Product.is_active.is_(True),
        (Product.image_url.is_(None)) | (Product.image_url == "")).limit(limit)).scalars().all()
    for p in rows:
        enqueue(db, p.id, user_id=user_id)
    return {"queued": len(rows)}


def missing_count(db: Session) -> int:
    from sqlalchemy import func
    return int(db.execute(select(func.count(Product.id)).where(
        Product.deleted_at.is_(None), Product.is_active.is_(True),
        (Product.image_url.is_(None)) | (Product.image_url == ""))).scalar() or 0)


def status(db: Session) -> dict:
    """What the settings panel shows — v3.5: no web sources are listed any more."""
    return {
        "missing": missing_count(db),
        "auto_find": setting(db, "images.auto_find", "true") == "true",
        "web_lookup": False,
        "note": "تصاویر از بانک پیش‌فرض کالا می‌آیند؛ جستجو در اینترنت حذف شده است.",
    }
