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


class InvalidStartDateError(ValueError):
    """Raised when the start_date of a reservation is invalid (e.g., in the future or not properly formatted)."""


class InvalidEndDateError(ValueError):
    """Raised when the end_date of a reservation is invalid (e.g., before the start_date or in the future)."""


class InvalidRoomIdError(KeyError):
    """Raised when a room_id is provided in a reservation but not present in the room registry."""


class InvalidCustomerIdError(KeyError):
    """Raised when a customer_id is provided in a reservation but not present in the customer registry."""
