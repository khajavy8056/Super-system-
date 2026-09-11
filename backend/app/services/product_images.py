"""v2.5 — automatic product pictures found by NAME (not only barcode).

When a product is saved («شیر پرچرب ۱ لیتری میهن») the system looks the picture
up in the background and stores it locally, so the thumbnail shows up in the
POS, the catalogue, receiving and stock-taking — on Windows and (through the
catalogue sync) on the phones.

Source ladder — every source is free, keyless and has a public API/terms that
allow programmatic access (user rule: no paid / account-bound dependency):

1. OpenFoodFacts by **barcode** (exact — highest trust) ................ ODbL
2. OpenFoodFacts **text search** (fa/en name, brand) ..................... ODbL
3. Wikimedia Commons file search (fa → en query) .............. CC / public domain
4. Wikipedia page image (fa → en)  ...................... CC-BY-SA / fair thumbnails
5. DuckDuckGo image search (HTML endpoint, no key) — last resort, only when
   ``images.web_fallback`` is enabled (default **on**, operator can disable).

Every candidate goes through the same byte-level validation as the barcode
pipeline (:func:`resolvers._fetch_image`: real image, ≥64px, ≤8MB) and is
stored under ``MEDIA_DIR/products``. The product's ``image_url`` becomes the
LOCAL path — never a hot-linked URL (§21).

Relevance: the candidate title/description is scored against the product's
name tokens (after Persian normalisation + a small fa→en dictionary for
grocery words) so «رب گوجه» does not end up with a picture of a tomato *plant*.
"""
from __future__ import annotations

import json
import logging
import re
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Brand, ImageAsset, Product, SystemSetting
from . import resolvers
from .catalog import _normalize_name

log = logging.getLogger("supermarket.images")

UA = "SupermarketSystem/2.5 (+https://github.com/khajavy8056/Super-system-; product-thumbnails)"
TIMEOUT = 10.0

# Persian grocery vocabulary → English search words. Deliberately small and
# high-precision: it is used to *widen* the query on English sources and to
# score result titles, not to translate names for display.
FA_EN = {
    "شیر": "milk", "ماست": "yogurt", "پنیر": "cheese", "کره": "butter", "خامه": "cream", "دوغ": "doogh",
    "رب": "tomato paste", "گوجه": "tomato", "گوجه‌فرنگی": "tomato", "سس": "sauce", "کچاپ": "ketchup", "مایونز": "mayonnaise",
    "برنج": "rice", "ماکارونی": "pasta", "اسپاگتی": "spaghetti", "آرد": "flour", "نان": "bread", "لواش": "lavash",
    "روغن": "oil", "زیتون": "olive", "شکر": "sugar", "قند": "sugar cubes", "نمک": "salt", "چای": "tea", "قهوه": "coffee",
    "نسکافه": "instant coffee", "عدس": "lentils", "لوبیا": "beans", "نخود": "chickpeas", "کنسرو": "canned", "تن": "tuna",
    "ماهی": "fish", "مرغ": "chicken", "گوشت": "meat", "سوسیس": "sausage", "کالباس": "cold cuts", "تخم‌مرغ": "eggs", "تخم": "egg",
    "آب": "water", "معدنی": "mineral", "نوشابه": "soda", "دلستر": "malt beverage", "آبمیوه": "juice", "شربت": "syrup",
    "بیسکویت": "biscuit", "کیک": "cake", "شکلات": "chocolate", "آدامس": "chewing gum", "چیپس": "chips", "پفک": "cheese puffs",
    "پاستیل": "gummy candy", "بستنی": "ice cream", "ویفر": "wafer", "کلوچه": "cookie", "خرما": "dates", "کشمش": "raisins",
    "پودر": "powder", "لباسشویی": "laundry detergent", "ظرفشویی": "dishwashing liquid", "مایع": "liquid", "صابون": "soap",
    "شامپو": "shampoo", "خمیردندان": "toothpaste", "مسواک": "toothbrush", "دستمال": "tissue", "کاغذی": "paper",
    "پوشک": "diapers", "سفیدکننده": "bleach", "جرم‌گیر": "descaler", "اسفنج": "sponge", "کیسه": "bag", "زباله": "garbage",
    "سیب": "apple", "موز": "banana", "پرتقال": "orange", "خیار": "cucumber", "پیاز": "onion", "سیب‌زمینی": "potato",
    "هویج": "carrot", "لیمو": "lemon", "انار": "pomegranate", "هندوانه": "watermelon", "خربزه": "melon", "انگور": "grapes",
    "زعفران": "saffron", "زردچوبه": "turmeric", "فلفل": "pepper", "دارچین": "cinnamon", "ادویه": "spice", "عسل": "honey",
    "مربا": "jam", "حلوا": "halva", "ارده": "tahini", "سرکه": "vinegar", "آبلیمو": "lime juice", "غلات": "cereal",
    "کورن‌فلکس": "cornflakes", "پنکیک": "pancake", "سیریال": "cereal", "پرچرب": "whole", "کم‌چرب": "low fat", "لیتری": "1 liter",
    "باتری": "battery", "لامپ": "light bulb", "فویل": "aluminum foil", "کبریت": "matches", "فندک": "lighter",
}
STOP = {"عدد", "بسته", "کیلو", "کیلوگرم", "گرم", "گرمی", "لیتر", "لیتری", "میلی", "سی‌سی", "تایی", "بزرگ", "کوچک", "متوسط", "مخصوص", "ویژه", "اصل", "درجه", "یک", "دو", "و"}
_NUM = re.compile(r"[\d۰-۹٠-٩]+")


@dataclass
class Candidate:
    url: str
    source: str
    title: str = ""
    score: float = 0.0
    extra: dict = field(default_factory=dict)


# --- helpers ---------------------------------------------------------------------

def setting(db: Session, key: str, default: str) -> str:
    row = db.execute(select(SystemSetting).where(SystemSetting.key == key)).scalar_one_or_none()
    return row.value if row and row.value not in (None, "") else default


def tokens(name: str) -> list[str]:
    n = _normalize_name(name)
    n = _NUM.sub(" ", n)
    out = []
    for t in re.split(r"[\s\-_/،,()«»\"']+", n):
        t = t.strip()
        if len(t) >= 2 and t not in STOP:
            out.append(t)
    return out


def english_query(name: str, brand: str | None) -> str:
    words = []
    for t in tokens(name):
        if re.fullmatch(r"[a-z0-9]+", t):
            words.append(t)
        elif t in FA_EN:
            words.append(FA_EN[t])
    if brand:
        words.append(brand)
    # dedupe, keep order
    seen, out = set(), []
    for w in " ".join(words).split():
        if w not in seen:
            seen.add(w); out.append(w)
    return " ".join(out).strip()


def persian_query(name: str, brand: str | None) -> str:
    q = " ".join(tokens(name))
    if brand and brand not in q:
        q = f"{q} {brand}"
    return q.strip()


def score_title(title: str, name: str, brand: str | None) -> float:
    """0..1 — token overlap of the candidate title with the product name (fa + en)."""
    t = _normalize_name(title or "").lower()
    if not t:
        return 0.25  # unknown title: neutral
    want = set(tokens(name))
    want_en = set(english_query(name, None).split())
    hit = sum(1 for w in want if w in t) + sum(0.8 for w in want_en if w in t)
    total = max(1.0, len(want) + 0.8 * len(want_en))
    s = hit / total
    if brand and _normalize_name(brand).lower() in t:
        s += 0.25
    # generic-plant / raw-ingredient penalty for processed goods (رب ≠ بوتهٔ گوجه)
    if any(k in t for k in ("plant", "flower", "field", "farm", "tree", "seedling", "botanical", "illustration", "drawing", "map", "logo")):
        s -= 0.35
    return max(0.0, min(1.0, s))


def _client(client: httpx.Client | None) -> tuple[httpx.Client, bool]:
    if client is not None:
        return client, False
    return httpx.Client(timeout=TIMEOUT, follow_redirects=True, headers={"User-Agent": UA, "Accept-Language": "fa,en;q=0.8"}), True


def _json(c: httpx.Client, url: str, params: dict | None = None) -> dict | list | None:
    try:
        r = c.get(url, params=params, timeout=TIMEOUT)
        if r.status_code != 200:
            return None
        return r.json()
    except (httpx.HTTPError, ValueError):
        return None


# --- sources ---------------------------------------------------------------------

def src_off_barcode(c: httpx.Client, barcode: str | None, **_) -> list[Candidate]:
    # INT- internal codes and GS1 "restricted circulation" 20–29 prefixes (in-store labels,
    # e.g. the bundled starter catalogue) are not global GTINs → never ask OFF about them.
    if not barcode or barcode.startswith("INT-") or not barcode.isdigit() or barcode[:2] in {"02", "20", "21", "22", "23", "24", "25", "26", "27", "28", "29"}:
        return []
    j = _json(c, f"https://world.openfoodfacts.org/api/v2/product/{barcode}.json", {"fields": "product_name,brands,image_front_url,image_url"})
    if not isinstance(j, dict) or j.get("status") != 1:
        return []
    p = j.get("product") or {}
    url = p.get("image_front_url") or p.get("image_url")
    if not url:
        return []
    return [Candidate(url, "openfoodfacts:barcode", p.get("product_name") or "", 1.0)]


def src_off_search(c: httpx.Client, name: str, brand: str | None, **_) -> list[Candidate]:
    out: list[Candidate] = []
    for q in (persian_query(name, brand), english_query(name, brand)):
        if not q:
            continue
        j = _json(c, "https://world.openfoodfacts.org/cgi/search.pl",
                  {"search_terms": q, "search_simple": 1, "action": "process", "json": 1, "page_size": 8,
                   "fields": "product_name,product_name_fa,brands,image_front_url,image_url"})
        for p in (j or {}).get("products", []) if isinstance(j, dict) else []:
            url = p.get("image_front_url") or p.get("image_url")
            if not url:
                continue
            title = " ".join(x for x in (p.get("product_name_fa"), p.get("product_name"), p.get("brands")) if x)
            out.append(Candidate(url, "openfoodfacts:search", title, score_title(title, name, brand)))
        if out:
            break
    return out


def src_commons(c: httpx.Client, name: str, brand: str | None, **_) -> list[Candidate]:
    out: list[Candidate] = []
    for q in (persian_query(name, brand), english_query(name, brand)):
        if not q:
            continue
        j = _json(c, "https://commons.wikimedia.org/w/api.php",
                  {"action": "query", "generator": "search", "gsrsearch": f"{q} filetype:bitmap", "gsrnamespace": 6, "gsrlimit": 8,
                   "prop": "imageinfo", "iiprop": "url|size|mime", "iiurlwidth": 600, "format": "json"})
        pages = ((j or {}).get("query") or {}).get("pages") or {} if isinstance(j, dict) else {}
        for p in pages.values():
            ii = (p.get("imageinfo") or [{}])[0]
            url = ii.get("thumburl") or ii.get("url")
            if not url or not str(ii.get("mime", "")).startswith("image/") or "svg" in str(ii.get("mime", "")):
                continue
            title = str(p.get("title", "")).replace("File:", "")
            out.append(Candidate(url, "wikimedia-commons", title, score_title(title, name, brand)))
        if out:
            break
    return out


def src_wikipedia(c: httpx.Client, name: str, brand: str | None, **_) -> list[Candidate]:
    out: list[Candidate] = []
    for lang, q in (("fa", persian_query(name, None)), ("en", english_query(name, None))):
        if not q:
            continue
        j = _json(c, f"https://{lang}.wikipedia.org/w/api.php",
                  {"action": "query", "generator": "search", "gsrsearch": q, "gsrlimit": 4, "prop": "pageimages",
                   "piprop": "thumbnail|name", "pithumbsize": 600, "format": "json"})
        pages = ((j or {}).get("query") or {}).get("pages") or {} if isinstance(j, dict) else {}
        for p in pages.values():
            th = (p.get("thumbnail") or {}).get("source")
            if not th:
                continue
            title = f"{p.get('title', '')} {p.get('pageimage', '')}"
            out.append(Candidate(th, f"wikipedia:{lang}", title, score_title(title, name, brand) * 0.9))
        if out:
            break
    return out


def src_duckduckgo(c: httpx.Client, name: str, brand: str | None, **_) -> list[Candidate]:
    """Keyless image search (same endpoint the DDG web UI uses). Best effort —
    if the token handshake changes we simply return nothing."""
    q = persian_query(name, brand) or english_query(name, brand)
    if not q:
        return []
    try:
        r = c.get("https://duckduckgo.com/", params={"q": q, "iax": "images", "ia": "images"}, timeout=TIMEOUT)
        m = re.search(r"vqd=([\d-]+)", r.text) or re.search(r'vqd="([\d-]+)"', r.text)
        if not m:
            return []
        j = _json(c, "https://duckduckgo.com/i.js", {"l": "ir-fa", "o": "json", "q": q, "vqd": m.group(1), "f": ",,,,,", "p": "1"})
    except httpx.HTTPError:
        return []
    out = []
    for it in (j or {}).get("results", [])[:10] if isinstance(j, dict) else []:
        url = it.get("image")
        if not url:
            continue
        title = it.get("title") or ""
        out.append(Candidate(url, "duckduckgo", title, score_title(title, name, brand) * 0.85))
    return out


SOURCES = [
    ("openfoodfacts:barcode", src_off_barcode),
    ("openfoodfacts:search", src_off_search),
    ("wikimedia-commons", src_commons),
    ("wikipedia", src_wikipedia),
    ("duckduckgo", src_duckduckgo),
]


# --- pipeline --------------------------------------------------------------------

def find_candidates(name: str, brand: str | None, barcode: str | None, *, client: httpx.Client | None = None,
                    web_fallback: bool = True, min_score: float = 0.34) -> list[Candidate]:
    c, own = _client(client)
    found: list[Candidate] = []
    try:
        for code, fn in SOURCES:
            if code == "duckduckgo" and not web_fallback:
                continue
            try:
                cands = fn(c, name=name, brand=brand, barcode=barcode)
            except Exception as exc:  # noqa: BLE001 — one source must never break the ladder
                log.info("image source %s failed: %s", code, exc)
                cands = []
            good = [x for x in cands if x.score >= min_score]
            found.extend(good)
            # exact barcode hit or a strong name match → stop early (fewer requests, better precision)
            if any(x.score >= 0.75 for x in good):
                break
    finally:
        if own:
            c.close()
    seen, out = set(), []
    for x in sorted(found, key=lambda x: -x.score):
        if x.url not in seen:
            seen.add(x.url); out.append(x)
    return out


def _local_media(rel: str) -> str:
    return f"/media/{rel}"


def find_and_store(db: Session, product: Product, *, client: httpx.Client | None = None, force: bool = False) -> dict:
    """Find a picture for ``product`` by name/brand/barcode and store it locally.

    Returns a report dict: {ok, source, url, local_path, score, tried, reason}.
    Never raises; never blocks product creation.
    """
    if product.image_url and not force:
        return {"ok": True, "reason": "ALREADY_HAS_IMAGE", "local_path": product.image_url, "tried": 0}
    brand = None
    if product.brand_id:
        b = db.get(Brand, product.brand_id)
        brand = b.name if b else None
    web = setting(db, "images.web_fallback", "true").lower() == "true"
    min_score = float(setting(db, "images.min_score", "0.34") or 0.34)
    cands = find_candidates(product.name, brand, product.barcode, client=client, web_fallback=web, min_score=min_score)
    tried = 0
    for cand in cands[:6]:
        tried += 1
        report, buf = resolvers._fetch_image(cand.url, client=client)
        if not (report.get("ok") and buf):
            continue
        try:
            rel = resolvers.store_image_locally(product.barcode or f"p{product.id}", buf, report["format"])
        except (OSError, KeyError) as exc:
            log.info("store failed: %s", exc)
            continue
        db.add(ImageAsset(product_id=product.id, barcode=product.barcode, url=cand.url, local_path=rel,
                          format=report.get("format"), width=report.get("width"), height=report.get("height"),
                          confidence="HIGH" if cand.score >= 0.75 else "MEDIUM", is_primary=True, status="STORED",
                          created_at=datetime.utcnow()))
        product.image_url = _local_media(rel)
        db.flush()
        return {"ok": True, "source": cand.source, "url": cand.url, "title": cand.title, "score": round(cand.score, 2),
                "local_path": product.image_url, "tried": tried}
    return {"ok": False, "reason": "NO_VALID_IMAGE" if cands else "NO_CANDIDATES", "tried": tried,
            "candidates": [{"source": x.source, "score": round(x.score, 2), "title": x.title[:80]} for x in cands[:6]]}


def enqueue(db: Session, product_id: int, *, user_id: int | None = None) -> None:
    """Queue the background lookup (drained by the sync worker every 15 s; retries with backoff when offline)."""
    from . import sync as sync_svc
    if setting(db, "images.auto_find", "true").lower() != "true":
        return
    from ..models import SyncJob
    dup = db.execute(select(SyncJob.id).where(SyncJob.idempotency_key == f"product-image:{product_id}")).scalar_one_or_none()
    if dup:
        return
    try:
        sync_svc.enqueue(db, job_type="PRODUCT_IMAGE", payload={"product_id": product_id},
                         reference_type="Product", reference_id=product_id,
                         idempotency_key=f"product-image:{product_id}", user_id=user_id, max_attempts=8)
    except Exception:  # noqa: BLE001 — duplicate idempotency key etc. must never break a save
        log.debug("image job already queued for product %s", product_id)


def backfill(db: Session, *, limit: int = 500, user_id: int | None = None) -> dict:
    """Queue every active product without a picture (starter catalogue, imports, old data)."""
    rows = db.execute(select(Product.id).where(Product.deleted_at.is_(None), Product.is_active.is_(True),
                                               (Product.image_url.is_(None)) | (Product.image_url == "")).limit(limit)).scalars().all()
    for pid in rows:
        enqueue(db, pid, user_id=user_id)
    return {"queued": len(rows)}


def missing_count(db: Session) -> int:
    from sqlalchemy import func
    return int(db.execute(select(func.count(Product.id)).where(Product.deleted_at.is_(None), Product.is_active.is_(True),
                                                                (Product.image_url.is_(None)) | (Product.image_url == ""))).scalar() or 0)
