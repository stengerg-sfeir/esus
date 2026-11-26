"""Application errors, one class per registered failure."""



from __future__ import annotations

class InvalidOrderLineError(ValueError):
    """Raised when an order line contains invalid data such as a negative quantity or invalid product ID, preventing the creation of the order or its lines."""
