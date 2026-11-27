"""Application errors, one class per registered failure."""



from __future__ import annotations

class CustomerNotFoundError(LookupError):
    """Raised when an invoice references a customer that does not exist in the system."""


class InvoiceLineNotFoundError(LookupError):
    """Raised when an invoice line with a given line_id is not found in the invoice's lines."""


class ProductNotFoundError(LookupError):
    """Raised when an invoice line references a product that does not exist in the system."""
