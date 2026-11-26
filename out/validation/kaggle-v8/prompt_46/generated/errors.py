"""Application errors, one class per registered failure."""



from __future__ import annotations

class ClientNotFoundError(LookupError):
    """Raised when an invoice or payment references a client that does not exist in the system."""


class InvoiceNotFoundError(LookupError):
    """Raised when an invoice is referenced in a payment or lookup but does not exist in the system."""


class PaymentNotFoundError(LookupError):
    """Raised when a payment is referenced but does not exist in the system."""


class MissingClientReferenceError(KeyError):
    """Raised when an invoice is created without a valid client_id reference."""


class MissingInvoiceReferenceError(KeyError):
    """Raised when a payment is created without a valid invoice_id reference."""
