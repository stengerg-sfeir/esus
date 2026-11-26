"""Application errors, one class per registered failure."""



from __future__ import annotations

class EventNotFoundError(LookupError):
    """Raised when an event is requested by an event ID that does not exist in the system."""


class RegistrationCapacityExceededError(ValueError):
    """Raised when an attempt is made to register for an event that has reached its maximum capacity."""


class RegistrationEventIdNotFoundError(KeyError):
    """Raised when a registration record is attempted to be created without a valid event_id that exists in the system."""


class RegistrationUserIdNotFoundError(KeyError):
    """Raised when a registration record is attempted to be created without a valid user_id that exists in the system."""
