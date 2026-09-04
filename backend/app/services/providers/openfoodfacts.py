"""OpenFoodFacts provider — free, keyless, public (products + images).

Real API: https://world.openfoodfacts.org/api/v2/product/{barcode}.json
Response ``status=1`` means found; ``status=0`` means not found.
"""
from __future__ import annotations

from decimal import Decimal

import httpx

from .base import BaseProvider, LookupField, ProviderError, ProviderLookup


class OpenFoodFactsProvider(BaseProvider):
    code = "openfoodfacts"
    name = "OpenFoodFacts (public)"
    can_return = ("product", "image")

    BASE = "https://world.openfoodfacts.org/api/v2/product/{barcode}.json"

    def lookup(self, barcode: str, *, client: httpx.Client | None = None) -> ProviderLookup:
        url = self.source.base_url or self.BASE
        payload = self._get(url.replace("{barcode}", barcode), client=client)
        if not isinstance(payload, dict):
            raise ProviderError("INVALID_RESPONSE", "root is not an object")
        if payload.get("status") == 0:
            raise ProviderError("NOT_FOUND", "OFF status=0")
        product = payload.get("product")
        if not isinstance(product, dict):
            raise ProviderError("INVALID_RESPONSE", "missing product object")

        out = ProviderLookup(provider_code=self.code)
        name = (product.get("product_name") or "").strip()
        if name:
            out.fields.append(LookupField("name", name, "MEDIUM"))
        brand = (product.get("brands") or "").split(",")[0].strip()
        if brand:
            out.fields.append(LookupField("brand", brand, "MEDIUM"))
        quantity = (product.get("quantity") or "").strip()
        if quantity:
            out.fields.append(LookupField("unit", quantity, "LOW"))
        cats = product.get("categories_tags") or []
        if cats:
            last = str(cats[-1]).split(":", 1)[-1].replace("-", " ").strip()
            if last:
                out.fields.append(LookupField("category", last, "LOW"))
        desc = (product.get("generic_name") or "").strip()
        if desc:
            out.fields.append(LookupField("description", desc[:500], "LOW"))
        img = (product.get("image_front_url") or product.get("image_url") or "").strip()
        if img.startswith(("http://", "https://")):
            out.image_url = img
        return out
