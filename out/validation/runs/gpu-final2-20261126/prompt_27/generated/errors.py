"""Application errors, one class per registered failure."""



from __future__ import annotations

class CustomerNotFoundError(LookupError):
    """Raised when a customer is referenced in a reservation but no customer with the given customer_id exists."""


class RoomNotFoundError(LookupError):
    """Raised when a room is referenced in a reservation but no room with the given room_id exists."""


class ReservationOverlapError(ValueError):
    """Raised when a new reservation overlaps with an existing reservation in the same room."""
