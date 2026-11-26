"""Application errors, one class per registered failure."""



from __future__ import annotations

class CustomerEmailDuplicateError(ValueError):
    """Raised when an attempt is made to create a customer with an email that is already in use."""


class CustomerNotFoundError(LookupError):
    """Raised when a customer is requested by ID but no such customer exists in the database."""
