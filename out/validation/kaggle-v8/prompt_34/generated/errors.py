"""Application errors, one class per registered failure."""



from __future__ import annotations

class InvalidOrderLineError(ValueError):
    """Raised when an order line contains invalid data such as an invalid product ID, negative quantity, or invalid unit price."""


class OrderLineNotFoundError(KeyError):
    """Raised when attempting to reference an order line that does not exist in the order's line collection."""


class OrderNotFoundError(LookupError):
    """Raised when attempting to look up an order by order_id that does not exist in the system."""
