"""Application errors, one class per registered failure."""



from __future__ import annotations

class CategoryNotFoundError(LookupError):
    """Raised when a product is requested by category but that category does not exist in the inventory."""


class ProductNotFoundError(LookupError):
    """Raised when a product is requested by SKU but not found in the inventory."""


class ProductSKUExistsError(ValueError):
    """Raised when attempting to create a product with a SKU that already exists in the inventory."""
