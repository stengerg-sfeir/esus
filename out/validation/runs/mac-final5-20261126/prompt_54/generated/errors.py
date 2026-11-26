"""Application errors, one class per registered failure."""



from __future__ import annotations

class AppointmentStartTimeEqualsEndTimeError(ValueError):
    """Raised when an appointment is created with a start time that is equal to its end time, as the application allows such appointments but treats it as a special case of valid input."""
