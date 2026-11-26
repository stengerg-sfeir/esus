"""Application errors, one class per registered failure."""



from __future__ import annotations

class ProductNotFoundError(LookupError):
    """Raised when a product is referenced by a product_id that does not exist in the inventory."""


class SaleProductNotFoundError(LookupError):
    """Raised when a sale attempts to reference a product_id that does not exist in the inventory."""
