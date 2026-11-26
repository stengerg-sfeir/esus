"""Application errors, one class per registered failure."""



from __future__ import annotations

class AppointmentStartTimeEqualsEndTimeError(ValueError):
    """Raised when an appointment is created with a start time that is equal to the end time, even though the requirements allow identical times."""
