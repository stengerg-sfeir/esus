"""Application errors, one class per registered failure."""



from __future__ import annotations

class CategoryNotFoundError(LookupError):
    """Raised when a requested category does not exist in the system."""


class CategoryStillHasProductsError(RuntimeError):
    """Raised when an attempt is made to delete a category while it still has products assigned to it."""


class ProductCategoryNotFoundError(LookupError):
    """Raised when a product is referenced with a category that does not exist."""
