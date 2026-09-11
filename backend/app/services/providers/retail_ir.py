"""Iranian retail catalogues as a *barcode → product* provider (v2.6).

Why: GS1 Iran (prefix 626) has no keyless lookup API and OpenFoodFacts knows only
a few hundred Iranian items, so a scanned Iranian pack usually resolved to
nothing. Iranian marketplaces, however, index the GTIN — Basalam sellers write it
straight into the listing title («خامه صبحانه پگاه 200 گرم – 6260007424016»),
and their public search endpoint (the one the web front-end uses, no key) returns
the title, a packaged-product photo, the pack size and the category.

Precision rule (the whole point after the "bowl of milk" incident): a hit is
accepted ONLY when the scanned digits literally appear in the listing title.
Anything else — "did you mean" results, similar items, category fillers — is
discarded, so the provider either returns the real product or NOT_FOUND. Torob is
the one exception (its matcher uses a hidden barcode field, not the title): it is
accepted only when the search returns exactly one result, and it is OFF by
default because its terms discourage automated extraction.

Verified live 2026-09-12 with 6260007424016 (Pegah cream) and 6263812801249
(Cheetoz): Basalam answered both with the exact pack; Digikala's numeric search
returns unrelated suggestions and is therefore not used for barcodes.
"""
from __future__ import annotations

import re

import httpx

from ...config import settings
from .base import BaseProvider, LookupField, ProviderError, ProviderLookup

BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

SHOPS: dict[str, dict] = {
    "basalam": {
        "url": "https://search.basalam.com/ai-engine/api/v2.0/product/search",
        "params": lambda q: {"q": q, "rows": 12},
        "default": True,
    },
    "torob": {
        "url": "https://api.torob.com/v4/base-product/search/",
        "params": lambda q: {"q": q, "query": q, "size": 5, "page": 0, "source": "next_desktop"},
        "default": False,
    },
}

_FA_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_SEP = re.compile(r"\s*[-–—|·,،:]\s*$")
_PACK = re.compile(r"(\d+(?:[.,]\d+)?)\s*(گرم|گرمی|کیلوگرم|کیلو|لیتر|لیتری|میلی\s?لیتر|سی\s?سی|عددی|عدد)")


def _digits(s: str) -> str:
    return re.sub(r"\D", "", (s or "").translate(_FA_DIGITS))


def clean_title(title: str, barcode: str) -> str:
    """«خامه صبحانه پگاه 200 گرم – 6260007424016» → «خامه صبحانه پگاه 200 گرم»."""
    t = (title or "").translate(_FA_DIGITS)
    t = t.replace(barcode, " ")
    t = re.sub(r"\b(بارکد|کد|code|barcode)\s*[:：]?\s*$", " ", t, flags=re.I)
    t = re.sub(r"\s{2,}", " ", t).strip()
    t = _SEP.sub("", t).strip(" -–—|·,،:")
    return t


def title_has_barcode(title: str, barcode: str) -> bool:
    return bool(barcode) and barcode in _digits(title)


def parse_shop(code: str, j, barcode: str) -> list[dict]:
    """Normalised hits [{title,image,unit,category,brand}] that pass the precision rule."""
    out: list[dict] = []
    if not isinstance(j, dict):
        return out
    if code == "basalam":
        for p in (j.get("products") or []):
            if not isinstance(p, dict):
                continue
            title = str(p.get("name") or "")
            if not title_has_barcode(title, barcode):
                continue
            ph = p.get("photo") or {}
            img = ph.get("LARGE") or ph.get("MEDIUM") or ph.get("SMALL") if isinstance(ph, dict) else None
            out.append({"title": title, "image": img, "unit": p.get("mainAttribute"),
                        "category": p.get("categoryTitle"), "brand": None})
    elif code == "torob":
        results = [r for r in (j.get("results") or []) if isinstance(r, dict) and r.get("name1")]
        if len(results) == 1:  # exact match only — one product for one code
            r = results[0]
            out.append({"title": str(r["name1"]), "image": r.get("image_url"), "unit": None,
                        "category": ((j.get("categories") or [{}])[0] or {}).get("title"), "brand": None})
    return out


class RetailIrProvider(BaseProvider):
    code = "retail_ir"
    name = "فروشگاه‌های ایرانی (باسلام / ترب) — بارکد در عنوان"
    can_return = ("product", "image")

    def _enabled(self) -> dict[str, bool]:
        import json
        flags = {k: v["default"] for k, v in SHOPS.items()}
        if self.source.connection:
            try:
                cfg = json.loads(self.source.connection)
                if isinstance(cfg, dict):
                    for k in flags:
                        if k in cfg:
                            flags[k] = bool(cfg[k])
            except (ValueError, TypeError):
                pass
        return flags

    def lookup(self, barcode: str, *, client: httpx.Client | None = None) -> ProviderLookup:
        barcode = _digits(barcode)
        if len(barcode) < 8 or barcode[:2] in {"02", "20", "21", "22", "23", "24", "25", "26", "27", "28", "29"}:
            raise ProviderError("NOT_FOUND", "in-store / internal code — not a global GTIN")
        own = client is None
        c = client or httpx.Client(timeout=settings.EXTERNAL_TIMEOUT_SECONDS, follow_redirects=True)
        errors: list[str] = []
        hits: list[tuple[str, dict]] = []
        try:
            for code, spec in SHOPS.items():
                if not self._enabled().get(code, spec["default"]):
                    continue
                try:
                    r = c.get(spec["url"], params=spec["params"](barcode), timeout=settings.EXTERNAL_TIMEOUT_SECONDS,
                              headers={"Accept": "application/json", "User-Agent": BROWSER_UA, "Accept-Language": "fa,en;q=0.8"})
                except httpx.TimeoutException:
                    errors.append(f"{code}=TIMEOUT"); continue
                except httpx.HTTPError as exc:
                    errors.append(f"{code}=UNREACHABLE:{type(exc).__name__}"); continue
                if r.status_code == 429:
                    errors.append(f"{code}=RATE_LIMITED"); continue
                if r.status_code != 200:
                    errors.append(f"{code}=HTTP_{r.status_code}"); continue
                try:
                    j = r.json()
                except ValueError:
                    errors.append(f"{code}=INVALID_RESPONSE"); continue
                for h in parse_shop(code, j, barcode):
                    hits.append((code, h))
        finally:
            if own:
                c.close()
        if not hits:
            if errors and len(errors) == sum(1 for k, v in SHOPS.items() if self._enabled().get(k, v["default"])):
                kind = errors[0].split("=", 1)[1].split(":", 1)[0]
                raise ProviderError(kind if kind in {"TIMEOUT", "RATE_LIMITED", "INVALID_RESPONSE"} else "UNREACHABLE", ", ".join(errors))
            raise ProviderError("NOT_FOUND", "no listing carries this barcode in its title" + (f" ({', '.join(errors)})" if errors else ""))

        shop, best = hits[0]
        out = ProviderLookup(provider_code=self.code, raw={"shop": shop, "hits": len(hits), "errors": errors})
        title = clean_title(best["title"], barcode)
        # several independent listings agreeing on the same barcode → HIGH
        conf = "HIGH" if len(hits) >= 2 else "MEDIUM"
        if title:
            out.fields.append(LookupField("name", title, conf))
        unit = best.get("unit")
        if not unit:
            m = _PACK.search(title)
            unit = f"{m.group(1)} {m.group(2)}" if m else None
        if unit:
            out.fields.append(LookupField("unit", str(unit), "LOW"))
        if best.get("category"):
            out.fields.append(LookupField("category", str(best["category"]), "LOW"))
        img = best.get("image") or next((h["image"] for _, h in hits if h.get("image")), None)
        if isinstance(img, str) and img.startswith(("http://", "https://")):
            out.image_url = img
        return out
