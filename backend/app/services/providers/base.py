"""Provider abstraction for external barcode/image/price sources (§11).

The core resolver never talks to a specific vendor — it talks to Providers.
Providers are registered in ``__init__.REGISTRY`` and configured at runtime via
``ExternalSource`` rows (code, base_url, api_key, priority, is_active), so
sources can be added/removed without touching core logic.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import httpx

from ...config import settings


class ProviderError(Exception):
    """A provider failed in a *classified* way (never silently swallowed — §40).

    kind: TIMEOUT | UNREACHABLE | NOT_FOUND | INVALID_RESPONSE | RATE_LIMITED |
    HTTP_<code> | AUTH_ERROR
    """

    def __init__(self, kind: str, detail: str = ""):
        super().__init__(f"{kind}: {detail}")
        self.kind = kind
        self.detail = detail


@dataclass
class LookupField:
    field: str
    value: str
    confidence: str = "MEDIUM"


@dataclass
class ProviderLookup:
    """Normalized result of one provider for one barcode."""

    provider_code: str
    fields: list[LookupField] = field(default_factory=list)
    image_url: str | None = None
    price: Decimal | None = None
    raw: dict | None = None


class BaseProvider:
    """Subclasses implement ``lookup`` and declare what they can return."""

    code: str = ""
    name: str = ""
    can_return: tuple[str, ...] = ()  # subset of {"product", "image", "price"}

    def __init__(self, source):  # source: ExternalSource row
        self.source = source

    # -- shared HTTP helper with classified errors ---------------------------
    def _get(self, url: str, *, client: httpx.Client | None = None) -> Any:
        headers = {}
        if self.source.api_key:
            headers["Authorization"] = f"Bearer {self.source.api_key}"
        own = client is None
        c = client or httpx.Client(timeout=settings.EXTERNAL_TIMEOUT_SECONDS)
        try:
            resp = c.get(url, headers=headers, timeout=settings.EXTERNAL_TIMEOUT_SECONDS)
            if resp.status_code == 404:
                raise ProviderError("NOT_FOUND", url)
            if resp.status_code == 401 or resp.status_code == 403:
                raise ProviderError("AUTH_ERROR", f"status={resp.status_code}")
            if resp.status_code == 429:
                raise ProviderError("RATE_LIMITED", url)
            if resp.status_code >= 500:
                raise ProviderError(f"HTTP_{resp.status_code}", url)
            resp.raise_for_status()
            try:
                return resp.json()
            except ValueError as exc:
                raise ProviderError("INVALID_RESPONSE", f"non-JSON body: {exc}") from exc
        except httpx.TimeoutException as exc:
            raise ProviderError("TIMEOUT", str(exc)) from exc
        except httpx.ConnectError as exc:
            raise ProviderError("UNREACHABLE", str(exc)) from exc
        except httpx.HTTPError as exc:
            raise ProviderError("HTTP_ERROR", str(exc)) from exc
        finally:
            if own:
                c.close()

    def lookup(self, barcode: str, *, client: httpx.Client | None = None) -> ProviderLookup:
        raise NotImplementedError
