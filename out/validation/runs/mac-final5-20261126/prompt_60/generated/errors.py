"""Application errors, one class per registered failure."""



from __future__ import annotations

class CustomerNotFoundError(LookupError):
    """Raised when a customer is requested but not found in the database by customer_id."""


class ProductNotFoundError(LookupError):
    """Raised when a product is requested but not found in the database by product_id."""


class CategoryNotFoundError(LookupError):
    """Raised when a category is requested but not found in the database by category_id."""


class OrderNotFoundError(LookupError):
    """Raised when an order is requested but not found in the database by order_id."""


class OrderItemNotFoundError(LookupError):
    """Raised when an order item is requested but not found in the database by order_item_id."""


class InvoiceNotFoundError(LookupError):
    """Raised when an invoice is requested but not found in the database by invoice_id."""


class InvalidOrderStatusError(ValueError):
    """Raised when an order status is set to a value not in the allowed set: 'pending', 'confirmed', 'shipped', 'cancelled'."""


class InsufficientStockError(ValueError):
    """Raised when attempting to confirm an order that contains products with insufficient stock."""


class InvalidProductIdError(ValueError):
    """Raised when a product ID is provided that does not exist or is invalid."""


class InvalidCategoryIdError(ValueError):
    """Raised when a category ID is provided that does not exist or is invalid."""


class InvalidCustomerIdError(ValueError):
    """Raised when a customer ID is provided that does not exist or is invalid."""


class OrderAlreadyConfirmedError(RuntimeError):
    """Raised when attempting to confirm an order that is already confirmed or shipped."""


class OrderCannotBeCancelledError(RuntimeError):
    """Raised when attempting to cancel an order that is not confirmed."""


class OrderCannotBeShippedError(RuntimeError):
    """Raised when attempting to ship an order that is not confirmed."""


class OrderCannotBeCancelledAfterShipmentError(RuntimeError):
    """Raised when attempting to cancel an order that has already been shipped."""


class FileNotFoundError(OSError):
    """Raised when the SQLite database file is not found at the specified path."""


class MalformedCSVError(ValueError):
    """Raised when a CSV file contains malformed data that cannot be parsed into valid records."""
