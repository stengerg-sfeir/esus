"""Application errors, one class per registered failure."""



from __future__ import annotations

class EventNotFoundError(LookupError):
    """Raised when an event is requested by an event ID that does not exist in the system."""


class RegistrationNotFoundError(LookupError):
    """Raised when a registration is requested by a registration ID that does not exist in the system."""


class UserNotFoundError(LookupError):
    """Raised when a user is requested by a user ID that does not exist in the system."""


class EventCapacityExceededError(ValueError):
    """Raised when a registration attempt is made for an event that has reached its capacity."""
