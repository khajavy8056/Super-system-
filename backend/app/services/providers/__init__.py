"""Provider registry — add a provider class here to make it configurable.

v3.5 — the two web-scraping providers are gone:

* ``retail_ir``  (Basalam / Torob listings, matched by barcode-in-title)
* ``openfoodfacts`` / ``openfoodfacts_img`` (ODbL, keyless)

The default product bank now carries 13 570 real lines with their exact GTIN and
their own pictures, so identifying an unknown code by scraping third-party
storefronts bought nothing and cost a network round trip at the till (plus the
usual breakage when those sites change or rate-limit). ``bootstrap`` switches
those source rows off on upgrade.

What remains is ``custom_http`` — a generic, shop-configured JSON endpoint. A
store that runs its own identification service can still point the resolver at
it; nothing is contacted unless the shop registers and enables one.
"""
from __future__ import annotations

from .base import BaseProvider, LookupField, ProviderError, ProviderLookup
from .custom_http import CustomHttpProvider

REGISTRY: dict[str, type[BaseProvider]] = {
    CustomHttpProvider.code: CustomHttpProvider,
}

__all__ = [
    "REGISTRY",
    "BaseProvider",
    "LookupField",
    "ProviderError",
    "ProviderLookup",
    "CustomHttpProvider",
]
