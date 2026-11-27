"""Application errors, one class per registered failure."""



from __future__ import annotations

class BookingNotFoundError(LookupError):
    """Raised when a requested booking is not found in the system."""


class DuplicateBookingError(RuntimeError):
    """Raised when the system detects a duplicate booking attempt for the same room and date range, indicating a data inconsistency."""


class GuestNotFoundError(LookupError):
    """Raised when a requested guest is not found in the system."""


class InvalidDateError(ValueError):
    """Raised when a check-in or check-out date is invalid, such as a check-in date that is after the check-out date."""


class RoomAlreadyBookedError(ValueError):
    """Raised when an attempt is made to book a room during a period that is already occupied."""


class RoomNotFoundError(LookupError):
    """Raised when a requested room is not found in the system."""
