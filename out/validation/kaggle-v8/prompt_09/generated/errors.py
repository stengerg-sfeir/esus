"""Application errors, one class per registered failure."""



from __future__ import annotations

class EmployeeNotFoundError(LookupError):
    """Raised when an employee is requested by ID but not found in the database."""
