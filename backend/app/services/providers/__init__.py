"""Provider registry — add a provider class here to make it configurable."""
from __future__ import annotations

from .base import BaseProvider, LookupField, ProviderError, ProviderLookup
from .custom_http import CustomHttpProvider
from .openfoodfacts import OpenFoodFactsProvider
from .retail_ir import RetailIrProvider

REGISTRY: dict[str, type[BaseProvider]] = {
    OpenFoodFactsProvider.code: OpenFoodFactsProvider,
    CustomHttpProvider.code: CustomHttpProvider,
    RetailIrProvider.code: RetailIrProvider,
}

__all__ = [
    "REGISTRY",
    "BaseProvider",
    "LookupField",
    "ProviderError",
    "ProviderLookup",
    "OpenFoodFactsProvider",
    "CustomHttpProvider",
    "RetailIrProvider",
]
