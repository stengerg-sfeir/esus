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
    """Raised when an order attempts to include a product quantity that exceeds the available stock quantity."""


class OrderCancellationFailedError(RuntimeError):
    """Raised when an order cancellation fails due to an inconsistent database state, such as an order being referenced in another transaction or already cancelled."""


class InvalidInputError(ValueError):
    """Raised when user input does not conform to expected formats, such as invalid email addresses or non-numeric values for prices or quantities."""
