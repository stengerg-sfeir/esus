"""Application errors, one class per registered failure."""



from __future__ import annotations

class InvoiceNotFoundError(LookupError):
    """Raised when an invoice is requested by an id that does not exist in the system."""


class CustomerNotFoundError(LookupError):
    """Raised when a customer is requested by an id that does not exist in the system."""


class ProductNotFoundError(LookupError):
    """Raised when a product is requested by an id that does not exist in the system."""


class InvoiceLineNotFoundError(LookupError):
    """Raised when an invoice line is requested by an id that does not exist in the system."""
