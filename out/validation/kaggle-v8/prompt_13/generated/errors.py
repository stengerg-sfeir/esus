"""Application errors, one class per registered failure."""



from __future__ import annotations

class ProductSKUExistsError(ValueError):
    """Raised when an attempt is made to add a product with a SKU that already exists in the inventory."""


class ProductNotFoundError(LookupError):
    """Raised when a product is requested by SKU but no product with that SKU exists in the inventory."""
