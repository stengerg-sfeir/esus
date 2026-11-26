"""Application errors, one class per registered failure."""



from __future__ import annotations

class CustomerNotFoundError(LookupError):
    """Raised when a customer is requested but not found in the system by customer_id."""


class RoomNotFoundError(LookupError):
    """Raised when a room is requested but not found in the system by room_id."""


class ReservationNotFoundError(LookupError):
    """Raised when a reservation is requested but not found in the system by reservation_id."""


class OverlappingReservationError(ValueError):
    """Raised when a new reservation overlaps with an existing reservation in the same room."""
