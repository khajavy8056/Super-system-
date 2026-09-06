"""Aggregate all models so ``Base.metadata`` is fully populated."""
from . import catalog, external, inventory, marketing, sales, sync, system, user  # noqa: F401
from .base import SoftDeleteMixin, TimestampMixin
from .catalog import Brand, Category, Product, Unit
from .enums import *  # noqa: F401,F403
from .external import ExternalSource, ImageAsset, MarketPrice, ProductResolverResult
from .inventory import (ProductBatch, StockMovement, Stocktake, StocktakeItem,
                        StorageLocation, Warehouse)
from .marketing import Campaign, Coupon, CouponRedemption
from .sync import DiagnosticRun, SyncJob
from .pricing import PriceVersion
from .sales import (Customer, CustomerLedgerEntry, Invoice, InvoiceItem,
                    Payment, Return)
from .system import AuditLog, Counter, HardwareDevice, Notification, SmsMessage, SystemSetting
from .user import Permission, Role, User

__all__ = [
    "Base",
    "TimestampMixin",
    "SoftDeleteMixin",
    "User",
    "Role",
    "Permission",
    "Category",
    "Brand",
    "Unit",
    "Product",
    "ProductBatch",
    "PriceVersion",
    "StockMovement",
    "Stocktake",
    "StocktakeItem",
    "Warehouse",
    "StorageLocation",
    "Invoice",
    "InvoiceItem",
    "Payment",
    "Customer",
    "CustomerLedgerEntry",
    "Return",
    "ExternalSource",
    "ProductResolverResult",
    "ImageAsset",
    "MarketPrice",
    "SmsMessage",
    "HardwareDevice",
    "AuditLog",
    "Counter",
    "Notification",
    "SystemSetting",
    "Campaign",
    "Coupon",
    "CouponRedemption",
    "SyncJob",
    "DiagnosticRun",
]
