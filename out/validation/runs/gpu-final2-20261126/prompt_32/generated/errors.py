"""Application errors, one class per registered failure."""



from __future__ import annotations

class OrderStateException(RuntimeError):
    """Raised by OrderService.confirm_order when the requested operation is not valid."""
