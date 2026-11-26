"""Application errors, one class per registered failure."""



from __future__ import annotations

class CustomerNotFoundError(LookupError):
    """Raised when a customer is referenced by an order but not found in the database."""


class ProductNotFoundError(LookupError):
    """Raised when a product is referenced in an order but not found in the database."""


class OrderNotFoundError(LookupError):
    """Raised when an order is referenced for cancellation or lookup but not found in the database."""


class InvalidOrderStatusError(ValueError):
    """Raised when an invalid order status is provided during order creation or cancellation."""


class InsufficientStockError(ValueError):
    """Raised when an order attempts to include a product with insufficient stock quantity."""


class InvalidQuantityError(ValueError):
    """Raised when a product quantity in an order is negative or zero."""


class AtomicOperationFailedError(RuntimeError):
    """Raised when an atomic transaction fails due to a database constraint or rollback during a modification operation."""
