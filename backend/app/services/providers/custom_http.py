"""Generic HTTP JSON provider — configurable via ExternalSource (base_url template).

Intended for GS1-compatible services, Iranian barcode databases or any
in-house endpoint that returns JSON. Field mapping is configurable through
``source.connection`` (JSON: {"name": "path.to.field", ...}), defaulting to
common key names. This keeps vendor specifics OUT of the core (§11).
"""
from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation

import httpx

from .base import BaseProvider, LookupField, ProviderError, ProviderLookup

_DEFAULT_KEYS = {
    "name": ("name", "title", "product_name", "item_name", "productName"),
    "brand": ("brand", "brand_name", "manufacturer"),
    "sku": ("sku", "code", "model"),
    "description": ("description", "details"),
    "unit": ("unit", "uom", "quantity"),
    "category": ("category", "category_name", "groupName"),
}


def _dig(payload, dotted: str):
    cur = payload
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


class CustomHttpProvider(BaseProvider):
    code = "custom_http"
    name = "Generic HTTP JSON (configurable)"
    can_return = ("product", "image", "price")

    def _mapping(self) -> dict[str, str]:
        if self.source.connection:
            try:
                cfg = json.loads(self.source.connection)
                if isinstance(cfg, dict):
                    return cfg
            except (ValueError, TypeError):
                pass
        return {}

    def lookup(self, barcode: str, *, client: httpx.Client | None = None) -> ProviderLookup:
        if not self.source.base_url:
            raise ProviderError("INVALID_RESPONSE", "source has no base_url configured")
        url = self.source.base_url.replace("{barcode}", barcode)
        payload = self._get(url, client=client)
        if not isinstance(payload, dict):
            raise ProviderError("INVALID_RESPONSE", "root is not an object")

        mapping = self._mapping()
        out = ProviderLookup(provider_code=self.code)
        for target, keys in _DEFAULT_KEYS.items():
            override = mapping.get(target)
            candidates = [override] if override else keys
            for key in candidates:
                val = _dig(payload, key)
                if isinstance(val, str) and val.strip():
                    out.fields.append(LookupField(target, val.strip(), "MEDIUM"))
                    break
        img = None
        for key in (mapping.get("image"), "image_url", "image", "imageUrl", "img"):
            if not key:
                continue
            val = _dig(payload, key)
            if isinstance(val, str) and val.startswith(("http://", "https://")):
                img = val
                break
        out.image_url = img
        for key in (mapping.get("price"), "price", "sell_price", "market_price"):
            if not key:
                continue
            val = _dig(payload, key)
            if val is not None:
                try:
                    out.price = Decimal(str(val))
                    break
                except InvalidOperation:
                    continue
        if not out.fields and not out.image_url and out.price is None:
            raise ProviderError("NOT_FOUND", "no recognizable fields in payload")
        return out
