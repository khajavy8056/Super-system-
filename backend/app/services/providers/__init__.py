"""Provider registry — add a provider class here to make it configurable."""
from __future__ import annotations

from .base import BaseProvider, LookupField, ProviderError, ProviderLookup
from .custom_http import CustomHttpProvider
from .openfoodfacts import OpenFoodFactsProvider

REGISTRY: dict[str, type[BaseProvider]] = {
    OpenFoodFactsProvider.code: OpenFoodFactsProvider,
    CustomHttpProvider.code: CustomHttpProvider,
}

__all__ = [
    "REGISTRY",
    "BaseProvider",
    "LookupField",
    "ProviderError",
    "ProviderLookup",
    "OpenFoodFactsProvider",
    "CustomHttpProvider",
]
