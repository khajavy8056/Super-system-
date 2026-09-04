"""Aggregate all models so ``Base.metadata`` is fully populated."""
from . import catalog, external, inventory, sales, system, user  # noqa: F401
from .base import SoftDeleteMixin, TimestampMixin
from .catalog import Brand, Category, Product, Unit
from .enums import *  # noqa: F401,F403
from .external import ExternalSource, ImageAsset, MarketPrice, ProductResolverResult
from .inventory import ProductBatch, StockMovement, Stocktake, StocktakeItem
from .pricing import PriceVersion
from .sales import Customer, Invoice, InvoiceItem, Payment, Return
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
    "Invoice",
    "InvoiceItem",
    "Payment",
    "Customer",
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
]
