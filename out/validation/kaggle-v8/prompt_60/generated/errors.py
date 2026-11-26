"""Application errors, one class per registered failure."""



from __future__ import annotations

class CustomerNotFoundError(LookupError):
    """Raised when a customer is requested by an ID that does not exist in the database."""


class ProductNotFoundError(LookupError):
    """Raised when a product is requested by an ID that does not exist in the database."""


class CategoryNotFoundError(LookupError):
    """Raised when a category is requested by an ID that does not exist in the database."""


class OrderNotFoundError(LookupError):
    """Raised when an order is requested by an ID that does not exist in the database."""


class OrderItemNotFoundError(LookupError):
    """Raised when an order item is requested by an ID that does not exist in the database."""


class InvoiceNotFoundError(LookupError):
    """Raised when an invoice is requested by an ID that does not exist in the database."""


class InvalidOrderStatusError(ValueError):
    """Raised when an order status is set to a value that is not one of pending, confirmed, shipped, or cancelled."""


class InsufficientStockError(ValueError):
    """Raised when an order attempts to reserve stock that is not available in the product's current quantity."""


class InvalidProductIdError(ValueError):
    """Raised when a product ID is provided that is not valid (e.g., not a positive integer or not matching a known product)."""


class InvalidCustomerIdError(ValueError):
    """Raised when a customer ID is provided that is not valid (e.g., not a positive integer or not matching a known customer)."""


class InvalidCategoryIdError(ValueError):
    """Raised when a category ID is provided that is not valid (e.g., not a positive integer or not matching a known category)."""


class OrderCannotBeCancelledError(RuntimeError):
    """Raised when an attempt is made to cancel an order that is not in the confirmed state."""


class OrderCannotBeConfirmedError(RuntimeError):
    """Raised when an attempt is made to confirm an order that is already confirmed, shipped, or cancelled."""


class OrderCannotBeShippedError(RuntimeError):
    """Raised when an attempt is made to ship an order that is not in the confirmed state."""


class FileNotFoundError(OSError):
    """Raised when the SQLite database file cannot be found or accessed."""


class MalformedCSVError(ValueError):
    """Raised when a CSV file contains malformed data that cannot be parsed into valid records."""
