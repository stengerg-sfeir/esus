"""Application errors, one class per registered failure."""



from __future__ import annotations

class CategoryNotFoundError(LookupError):
    """Raised when a category is requested by ID but not found in the database."""


class CustomerNotFoundError(LookupError):
    """Raised when a customer is requested by ID but not found in the database."""


class InsufficientStockError(ValueError):
    """Raised when attempting to confirm an order that would result in insufficient stock for one or more products."""


class InvalidOrderStatusError(ValueError):
    """Raised when an order status is set to a value not in the allowed set: pending, confirmed, shipped, cancelled."""


class InvalidPriceError(ValueError):
    """Raised when a product price is set to a negative or non-numeric value."""


class InvalidProductIdError(KeyError):
    """Raised when a product ID is used in an order but not present in the product catalog."""


class InvoiceNotFoundError(LookupError):
    """Raised when an invoice is requested by ID but not found in the database."""


class MalformedCSVError(OSError):
    """Raised when a CSV file is malformed or cannot be parsed during import."""


class OrderAlreadyConfirmedError(RuntimeError):
    """Raised when attempting to confirm an order that is already confirmed or cancelled."""


class OrderCannotBeCancelledError(RuntimeError):
    """Raised when attempting to cancel an order that is not confirmed."""


class OrderCannotBeShippedError(RuntimeError):
    """Raised when attempting to ship an order that is not confirmed."""


class OrderItemNotFoundError(LookupError):
    """Raised when an order item is requested by ID but not found in the database."""


class OrderNotFoundError(LookupError):
    """Raised when an order is requested by ID but not found in the database."""


class ProductNotFoundError(LookupError):
    """Raised when a product is requested by ID but not found in the database."""
