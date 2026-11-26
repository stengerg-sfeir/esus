"""Application errors, one class per registered failure."""



from __future__ import annotations

class InsufficientStockError(ValueError):
    """Raised when a product in an order has insufficient stock to fulfill the requested quantity."""


class CustomerNotFoundError(KeyError):
    """Raised when attempting to place an order for a customer that does not exist in the system."""


class ProductNotFoundError(KeyError):
    """Raised when attempting to reference a product in an order that does not exist in the system."""


class OrderNotFoundError(LookupError):
    """Raised when attempting to retrieve an order that does not exist in the system."""


class ProductStockQuantityError(ValueError):
    """Raised when a product's stock quantity is not a non-negative integer."""
