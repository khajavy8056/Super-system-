"""Domain enums — single source of truth for constrained string values.

Stored as VARCHAR in the database (SQLite/portable friendly), validated at the
API boundary by Pydantic.
"""
from __future__ import annotations

from enum import Enum


class BatchStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SOLD_OUT = "SOLD_OUT"
    EXPIRED = "EXPIRED"
    BLOCKED = "BLOCKED"


class MovementType(str, Enum):
    PURCHASE_IN = "PURCHASE_IN"
    SALE_OUT = "SALE_OUT"
    RETURN_IN = "RETURN_IN"
    RETURN_OUT = "RETURN_OUT"
    WASTE = "WASTE"
    ADJUSTMENT = "ADJUSTMENT"
    TRANSFER_IN = "TRANSFER_IN"
    TRANSFER_OUT = "TRANSFER_OUT"
    STOCKTAKE = "STOCKTAKE"


class PriceType(str, Enum):
    SELL = "SELL"
    CONSUMER = "CONSUMER"
    SUGGESTED = "SUGGESTED"
    MARKET = "MARKET"


class InvoiceStatus(str, Enum):
    PENDING = "PENDING"
    PAID = "PAID"
    VOID = "VOID"
    REFUNDED = "REFUNDED"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"


class PaymentMethod(str, Enum):
    CASH = "CASH"
    CARD = "CARD"
    MIXED = "MIXED"
    OTHER = "OTHER"


class PrintStatus(str, Enum):
    NONE = "NONE"
    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class SmsStatus(str, Enum):
    PENDING = "PENDING"
    SENT = "SENT"
    FAILED = "FAILED"
    RETRYING = "RETRYING"


class StocktakeStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class StocktakeItemStatus(str, Enum):
    PENDING = "PENDING"
    COUNTED = "COUNTED"
    ADJUSTED = "ADJUSTED"


class Confidence(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class ExpiryStatus(str, Enum):
    EXPIRED = "EXPIRED"
    EXPIRING_TODAY = "EXPIRING_TODAY"
    EXPIRING_3_DAYS = "EXPIRING_3_DAYS"
    EXPIRING_7_DAYS = "EXPIRING_7_DAYS"
    EXPIRING_30_DAYS = "EXPIRING_30_DAYS"
    NORMAL = "NORMAL"


class AllocationPolicy(str, Enum):
    FIFO = "FIFO"
    FEFO = "FEFO"
    MANUAL = "MANUAL"
    HYBRID = "HYBRID"


class BatchSelectionMode(str, Enum):
    AUTO = "AUTO"
    MANUAL = "MANUAL"
    HYBRID = "HYBRID"


class HardwareType(str, Enum):
    PRINTER = "PRINTER"
    BARCODE_SCANNER = "BARCODE_SCANNER"
    CASH_DRAWER = "CASH_DRAWER"


class HardwareStatus(str, Enum):
    CONNECTED = "CONNECTED"
    DISCONNECTED = "DISCONNECTED"
    UNKNOWN = "UNKNOWN"


class PriceFreshness(str, Enum):
    FRESH = "FRESH"
    AGING = "AGING"
    STALE = "STALE"


class ResolverStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ReturnStatus(str, Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"


class ExternalSourceType(str, Enum):
    PRODUCT = "PRODUCT"
    IMAGE = "IMAGE"
    PRICE = "PRICE"
