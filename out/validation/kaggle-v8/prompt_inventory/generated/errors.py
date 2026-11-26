"""Application errors, one class per registered failure."""



from __future__ import annotations

class CategoryNotFoundError(LookupError):
    """Raised when a requested category is not found in the database."""


class ProductNotFoundError(LookupError):
    """Raised when a requested product is not found in the database."""
