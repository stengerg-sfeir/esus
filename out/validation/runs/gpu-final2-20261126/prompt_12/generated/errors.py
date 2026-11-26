"""Application errors, one class per registered failure."""



from __future__ import annotations

class CustomerEmailDuplicateError(ValueError):
    """Raised when attempting to create a customer with an email that is already in use."""


class CustomerNotFoundError(LookupError):
    """Raised when a customer is requested by ID but not found in the database."""


class CustomerNameNotFoundError(LookupError):
    """Raised when a customer is searched by name and no matching customer is found."""
