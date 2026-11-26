"""Application errors, one class per registered failure."""



from __future__ import annotations

class CustomerNotFoundError(LookupError):
    """Raised when a customer is requested by an ID that does not exist in the database."""


class ProductNotFoundError(LookupError):
    """Raised when a product is requested by an ID that does not exist in the database."""


class OrderNotFoundError(LookupError):
    """Raised when an order is requested by an ID that does not exist in the database."""


class InvalidOrderStatusError(ValueError):
    """Raised when an order status is set to a value not in the allowed set (e.g., 'cancelled', 'completed', 'pending')."""


class InsufficientStockError(ValueError):
    """Raised when an order attempts to include a product that is out of stock."""


class AtomicOperationFailedError(RuntimeError):
    """Raised when an atomic operation (such as creating an order or cancelling an order) fails due to a database constraint or transaction rollback, indicating the system cannot proceed with the current state."""
