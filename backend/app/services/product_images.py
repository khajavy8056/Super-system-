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
BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

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
    # words of the product name that are not grocery vocabulary are usually the BRAND («میهن», «کاله»):
    # a candidate missing them is a different product → strong penalty
    specific = [w for w in want if w not in FA_EN and not re.fullmatch(r"[a-z0-9]+", w)]
    if specific and not any(w in t for w in specific):
        s -= 0.3
    # generic-plant / raw-ingredient / stock-photo penalty for processed goods (رب ≠ بوتهٔ گوجه، شیر ≠ کاسهٔ شیر)
    if any(k in t for k in GENERIC_WORDS):
        s -= 0.35
    # package-photo bonus: retail titles carry pack size / brand / container words
    if any(k in t for k in PACK_WORDS) or _NUM.search(title or ""):
        s += 0.15
    return max(0.0, min(1.0, s))


GENERIC_WORDS = ("plant", "flower", "field", "farm", "tree", "seedling", "botanical", "illustration", "drawing", "map", "logo",
                 "glass of", "bowl", "cup of", "pouring", "splash", "cow", "farmer", "harvest", "recipe", "dish", "meal",
                 "کاسه", "لیوان", "گاو", "مزرعه", "درخت", "بوته", "دستور پخت", "غذا", "نقاشی", "کارتون", "clipart", "vector", "icon")
PACK_WORDS = ("گرمی", "گرم", "لیتری", "لیتر", "بسته", "قوطی", "بطری", "پاکت", "عددی", "کیلویی", "کیلوگرم", "سی سی", "میلی",
              "pack", "bottle", "can ", "jar", "box", "bag", "ml", " g ", "kg", "gram", "liter", "litre", "brand")


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


def src_retail_barcode(c: httpx.Client, barcode: str | None, enabled: dict[str, bool] | None = None, **_) -> list[Candidate]:
    """Exact barcode hit on an Iranian marketplace (digits must appear in the listing title) → score 1.0."""
    from .providers.retail_ir import SHOPS, parse_shop
    if not barcode or not barcode.isdigit() or len(barcode) < 8 or barcode[:2] in {"02", "20", "21", "22", "23", "24", "25", "26", "27", "28", "29"}:
        return []
    out: list[Candidate] = []
    for code, spec in SHOPS.items():
        if not (enabled or {}).get(code, spec["default"]):
            continue
        try:
            r = c.get(spec["url"], params=spec["params"](barcode), timeout=TIMEOUT, headers={"Accept": "application/json", "User-Agent": BROWSER_UA})
            if r.status_code != 200:
                continue
            j = r.json()
        except (httpx.HTTPError, ValueError):
            continue
        for h in parse_shop(code, j, barcode):
            if h.get("image"):
                out.append(Candidate(h["image"], f"retail:{code}:barcode", h["title"], 1.0, {"packaged": True, "exact": True}))
    return out


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


# --- Iranian retail catalogues (v2.5.1) -------------------------------------------
# These return *packaged product* photos with Persian titles — exactly what a shop
# wants on a shelf/POS thumbnail — so they rank right after an exact barcode hit.
# All are public, keyless search endpoints used by the stores' own web front-ends;
# schemas are not contractual, therefore results are parsed with a tolerant JSON
# walker (any object with a Persian title + an image URL) and every source is
# individually switchable. Torob's terms discourage automated extraction by shops,
# so it is OFF by default (images.retail.torob=true to enable at your own risk).
RETAIL_SOURCES: dict[str, dict] = {
    # verified live 2026-09-11: data.products[].{title_fa, images.main.url[0], data_layer.brand}
    "digikala": {"url": "https://api.digikala.com/v1/search/", "params": lambda q: {"q": q, "page": 1}, "default": True},
    # verified live 2026-09-11: products[].{name, photo.MEDIUM|SMALL}
    "basalam": {"url": "https://search.basalam.com/ai-engine/api/v2.0/product/search", "params": lambda q: {"q": q, "rows": 12}, "default": True},
    # needs StoreIds + a bearer token from the web app → not usable keyless; kept for operators who have one (off)
    "okala": {"url": "https://apigateway.okala.com/api/Search/v1/Product/Search", "params": lambda q: {"search": q, "pageSize": 12, "pageNumber": 1, "StoreIds": 1}, "default": False},
    # terms discourage automated extraction by shops → off by default
    "torob": {"url": "https://api.torob.com/v4/base-product/search/", "params": lambda q: {"q": q, "query": q, "size": 12, "page": 0, "source": "next_desktop"}, "default": False},
}
_IMG_EXT = re.compile(r"\.(jpe?g|png|webp)(\?|$)", re.I)


def _dk_big(url: str) -> str:
    """Digikala search thumbnails come as 300px; ask the CDN for 600px (same key, no auth)."""
    return re.sub(r"h_\d+,w_\d+", "h_600,w_600", url)


def parse_retail(code: str, j) -> list[tuple[str, str, str | None]]:
    """(title, image_url, brand) triples from a retail search response — exact shapes first, tolerant walker as fallback."""
    out: list[tuple[str, str, str | None]] = []
    try:
        if code == "digikala":
            for p in ((j.get("data") or {}).get("products") or []):
                urls = (((p.get("images") or {}).get("main") or {}).get("url") or [])
                if p.get("title_fa") and urls:
                    out.append((p["title_fa"], _dk_big(urls[0]), (p.get("data_layer") or {}).get("brand")))
        elif code == "basalam":
            for p in (j.get("products") or []):
                ph = p.get("photo") or {}
                url = ph.get("MEDIUM") or ph.get("LARGE") or ph.get("SMALL")
                if p.get("name") and url:
                    out.append((p["name"], url, (p.get("vendor") or {}).get("name")))
        elif code == "torob":
            for p in (j.get("results") or []):
                if p.get("name1") and p.get("image_url"):
                    out.append((p["name1"], p["image_url"], None))
        elif code == "okala":
            for p in (j.get("entities") or []):
                title = p.get("name") or p.get("productName") or p.get("title")
                img = _first_image_url(p)
                if title and img:
                    out.append((title, img, p.get("brandName")))
    except (AttributeError, TypeError):
        pass
    if not out:  # schema drifted → best-effort walker
        pairs: list[tuple[str, str]] = []
        _walk_products(j, ("title_fa", "name", "name1", "productName", "title"), pairs)
        out = [(t, u, None) for t, u in pairs]
    return out


def _walk_products(node, title_keys: tuple[str, ...], out: list[tuple[str, str]], depth: int = 0) -> None:
    """Tolerant walker: collect (title, image_url) pairs from any JSON shape."""
    if depth > 8 or len(out) > 40:
        return
    if isinstance(node, dict):
        title = next((str(node[k]) for k in title_keys if isinstance(node.get(k), str) and node[k].strip()), None)
        if title:
            img = _first_image_url(node)
            if img:
                out.append((title, img))
                return
        for v in node.values():
            _walk_products(v, title_keys, out, depth + 1)
    elif isinstance(node, list):
        for v in node:
            _walk_products(v, title_keys, out, depth + 1)


def _first_image_url(node, depth: int = 0) -> str | None:
    if depth > 4:
        return None
    if isinstance(node, str):
        return node if node.startswith("http") and (_IMG_EXT.search(node) or "/image" in node or "img" in node) else None
    if isinstance(node, dict):
        for k in ("image_url", "imageUrl", "image", "images", "main", "url", "photo", "MEDIUM", "thumbnail", "src", "productImage", "picture"):
            if k in node:
                r = _first_image_url(node[k], depth + 1)
                if r:
                    return r
        for k, v in node.items():
            if "imag" in k.lower() or "photo" in k.lower() or "pic" in k.lower():
                r = _first_image_url(v, depth + 1)
                if r:
                    return r
    if isinstance(node, list):
        for v in node[:3]:
            r = _first_image_url(v, depth + 1)
            if r:
                return r
    return None


def src_retail_ir(c: httpx.Client, name: str, brand: str | None, enabled: dict[str, bool] | None = None, **_) -> list[Candidate]:
    out: list[Candidate] = []
    q = persian_query(name, brand)
    if not q:
        return out
    for code, spec in RETAIL_SOURCES.items():
        if not (enabled or {}).get(code, spec["default"]):
            continue
        try:
            r = c.get(spec["url"], params=spec["params"](q), timeout=TIMEOUT, headers={"Accept": "application/json", "User-Agent": BROWSER_UA})
            if r.status_code != 200:
                continue
            j = r.json()
        except (httpx.HTTPError, ValueError):
            continue
        for title, url, rbrand in parse_retail(code, j)[:12]:
            full = f"{title} {rbrand}" if rbrand else title
            out.append(Candidate(url, f"retail:{code}", full, min(1.0, score_title(full, name, brand) + 0.1), {"packaged": True}))
    # all enabled shops are queried and ranked together — the first shop's "good enough" must not hide another shop's exact pack
    return out


SOURCES = [
    ("openfoodfacts:barcode", src_off_barcode),
    ("retail-ir:barcode", src_retail_barcode),
    ("retail-ir", src_retail_ir),
    ("openfoodfacts:search", src_off_search),
    ("wikimedia-commons", src_commons),
    ("wikipedia", src_wikipedia),
    ("duckduckgo", src_duckduckgo),
]


# --- pipeline --------------------------------------------------------------------

def find_candidates(name: str, brand: str | None, barcode: str | None, *, client: httpx.Client | None = None,
                    web_fallback: bool = True, min_score: float = 0.34, retail: dict[str, bool] | None = None,
                    generic_fallback: bool = True) -> list[Candidate]:
    c, own = _client(client)
    found: list[Candidate] = []
    try:
        for code, fn in SOURCES:
            if code == "duckduckgo" and not web_fallback:
                continue
            # encyclopaedia sources give generic photos (a glass of milk) — only when nothing packaged was found
            if code in ("wikimedia-commons", "wikipedia") and (not generic_fallback or any(x.score >= 0.5 for x in found)):
                continue
            try:
                cands = fn(c, name=name, brand=brand, barcode=barcode, enabled=retail)
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
    cands = find_candidates(product.name, brand, product.barcode, client=client, web_fallback=web, min_score=min_score,
                            retail=retail_flags(db), generic_fallback=setting(db, "images.generic_fallback", "true").lower() == "true")
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


def retail_flags(db: Session) -> dict[str, bool]:
    return {k: setting(db, f"images.retail.{k}", "true" if v["default"] else "false").lower() == "true" for k, v in RETAIL_SOURCES.items()}


def list_candidates(db: Session, product: Product, *, client: httpx.Client | None = None, limit: int = 12) -> list[dict]:
    """For the picker UI: best candidates (URL + title + source + score), nothing stored."""
    brand = None
    if product.brand_id:
        b = db.get(Brand, product.brand_id)
        brand = b.name if b else None
    web = setting(db, "images.web_fallback", "true").lower() == "true"
    cands = find_candidates(product.name, brand, product.barcode, client=client, web_fallback=web, min_score=0.2,
                            retail=retail_flags(db), generic_fallback=True)
    return [{"url": x.url, "title": x.title, "source": x.source, "score": round(x.score, 2)} for x in cands[:limit]]


def set_image_from_url(db: Session, product: Product, url: str, *, client: httpx.Client | None = None, source: str = "manual") -> dict:
    """Operator picked a candidate (or pasted a URL): download, validate, store locally, make primary."""
    report, buf = resolvers._fetch_image(url, client=client)
    if not (report.get("ok") and buf):
        return {"ok": False, "reason": report.get("reason", "INVALID_IMAGE")}
    return set_image_from_bytes(db, product, buf, report, url=url, source=source)


def set_image_from_bytes(db: Session, product: Product, buf: bytes, report: dict | None = None, *, url: str = "upload", source: str = "upload") -> dict:
    if report is None:
        fmt = resolvers._sniff_format(buf)
        if fmt is None or len(buf) < resolvers.MIN_IMAGE_BYTES or len(buf) > resolvers.MAX_IMAGE_BYTES:
            return {"ok": False, "reason": "INVALID_IMAGE"}
        dims = resolvers._image_dimensions(buf, fmt) or (None, None)
        report = {"format": fmt, "width": dims[0], "height": dims[1]}
    rel = resolvers.store_image_locally(product.barcode or f"p{product.id}", buf, report["format"])
    for old in db.execute(select(ImageAsset).where(ImageAsset.product_id == product.id, ImageAsset.is_primary.is_(True))).scalars():
        old.is_primary = False
    db.add(ImageAsset(product_id=product.id, barcode=product.barcode, url=url, local_path=rel, format=report.get("format"),
                      width=report.get("width"), height=report.get("height"), confidence="HIGH", is_primary=True, status="STORED",
                      created_at=datetime.utcnow()))
    product.image_url = _local_media(rel)
    db.flush()
    return {"ok": True, "source": source, "local_path": product.image_url, "image_url": product.image_url}


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
