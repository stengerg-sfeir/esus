"""Application errors, one class per registered failure."""



from __future__ import annotations

class ClientNotFoundError(LookupError):
    """Raised when a client is referenced by an invoice or payment but does not exist in the system."""


class InvoiceNotFoundError(LookupError):
    """Raised when an invoice is referenced by a payment but does not exist in the system."""


class PaymentNotFoundError(LookupError):
    """Raised when a payment is referenced but the corresponding invoice does not exist in the system."""
