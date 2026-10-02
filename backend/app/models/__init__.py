"""Aggregate all models so ``Base.metadata`` is fully populated."""
from . import accounting, catalog, external, hr, insights, inventory, marketing, sales, sync, system, user  # noqa: F401
from .accounting import (Account, CashSession, Cheque, Expense, ExpenseCategory,
                         FiscalPeriod, JournalEntry, JournalLine, Supplier)
from .base import SoftDeleteMixin, TimestampMixin
from .catalog import Brand, Category, Product, Unit
from .enums import *  # noqa: F401,F403
from .external import BankItem, ExternalSource, ImageAsset, MarketPrice, ProductResolverResult
from .inventory import (ProductBatch, StockMovement, Stocktake, StocktakeItem,
                        StorageLocation, Warehouse)
from .marketing import Campaign, CampaignRedemption, Coupon, CouponRedemption
from .hr import (Achievement, Announcement, AnnouncementRead,
                 PayrollEntry, ScoreEvent, Shift, ShiftAssignment,
                 ShiftAttendance, UserWidgetLayout)
from .insights import Experiment, Insight
from .sync import DiagnosticRun, SyncJob
from .pricing import PriceVersion
from .sales import (Customer, CustomerLedgerEntry, Invoice, InvoiceItem,
                    Payment, Return)
from .system import AuditLog, Counter, HardwareDevice, Notification, SmsMessage, SupportMessage, SupportTicket, SystemSetting
from .user import Permission, Role, User, user_permissions, user_roles, role_permissions

__all__ = [
    "Base",
    "Account", "CashSession", "Cheque", "Expense", "ExpenseCategory", "FiscalPeriod",
    "JournalEntry", "JournalLine", "Supplier",
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
    "Insight",
    "Experiment",
    "SystemSetting",
    "SupportTicket",
    "SupportMessage",
    "Campaign",
    "Coupon",
    "CouponRedemption", "CampaignRedemption",
    "SyncJob",
    "DiagnosticRun",
]
