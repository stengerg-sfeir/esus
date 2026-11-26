"""Application errors, one class per registered failure."""



from __future__ import annotations

class CategoryNotFoundError(LookupError):
    """Raised when a requested category ID does not exist in the database."""


class ProductNotFoundError(LookupError):
    """Raised when a requested product ID does not exist in the database."""
