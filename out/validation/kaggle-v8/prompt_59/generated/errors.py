"""Application errors, one class per registered failure."""



from __future__ import annotations

class CustomerNotFoundError(LookupError):
    """Raised when a customer is requested by an ID that does not exist in the system."""


class ProductNotFoundError(LookupError):
    """Raised when a product is requested by an ID that does not exist in the system."""


class OrderNotFoundError(LookupError):
    """Raised when an order is requested by an ID that does not exist in the system."""


class OrderLineNotFoundError(LookupError):
    """Raised when an order line is requested by an ID that does not exist in the system."""


class DiscountNotFoundError(LookupError):
    """Raised when a discount is requested by an ID that does not exist in the system."""


class InsufficientStockError(ValueError):
    """Raised when an order line attempts to place a quantity that exceeds the available stock level of the product."""


class OrderCancellationError(RuntimeError):
    """Raised when an order is attempted to be cancelled but is already in a final state (e.g., 'cancelled' or 'completed')."""


class StockRestorationError(RuntimeError):
    """Raised when stock restoration is attempted for an order that does not exist or has already been processed."""
