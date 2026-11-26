"""Application errors, one class per registered failure."""



from __future__ import annotations

class UserNotFoundError(LookupError):
    """Raised when a user is requested but not found in the system by user_id."""


class ProductNotFoundError(LookupError):
    """Raised when a product is requested but not found in the system by product_id."""


class OrderNotFoundError(LookupError):
    """Raised when an order is requested but not found in the system by order_id."""


class OrderCreationFailedError(RuntimeError):
    """Raised when an order cannot be created due to an internal inconsistency, such as a user not being logged in or a required field being missing."""
