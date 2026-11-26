"""Application errors, one class per registered failure."""



from __future__ import annotations

class OrderStatusInvalidError(ValueError):
    """Raised by OrderService.confirm_order when the requested operation is not valid."""


class OrderAlreadyConfirmedError(RuntimeError):
    """Raised by OrderService.confirm_order when the requested operation is not valid."""


class OrderNotConfirmedError(RuntimeError):
    """Raised by OrderService.ship_order when the requested operation is not valid."""
