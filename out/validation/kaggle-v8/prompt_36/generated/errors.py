"""Application errors, one class per registered failure."""



from __future__ import annotations

class CategoryNotFoundError(LookupError):
    """Raised when a requested category does not exist in the system."""


class ProductNotFoundError(LookupError):
    """Raised when a requested product does not exist in the system."""


class CategoryCannotBeDeletedError(RuntimeError):
    """Raised when an attempt is made to delete a category that still has products assigned to it."""
