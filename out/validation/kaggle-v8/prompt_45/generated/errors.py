"""Application errors, one class per registered failure."""



from __future__ import annotations

class RoomNotFoundError(LookupError):
    """Raised when a requested room is not found in the system."""


class GuestNotFoundError(LookupError):
    """Raised when a requested guest is not found in the system."""


class BookingNotFoundError(LookupError):
    """Raised when a requested booking is not found in the system."""


class RoomConflictError(RuntimeError):
    """Raised when an attempt is made to book a room during a period that overlaps with an existing booking."""
