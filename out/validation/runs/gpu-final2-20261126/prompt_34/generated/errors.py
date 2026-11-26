"""Application errors, one class per registered failure."""



from __future__ import annotations

class InvalidOrderLineError(ValueError):
    """Raised when an order line contains invalid data such as negative quantity or invalid product ID."""


class OrderLineNotFoundError(LookupError):
    """Raised when a required product ID in an order line does not exist in the product catalog."""
