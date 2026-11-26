"""Application errors, one class per registered failure."""



from __future__ import annotations

class ClientNotFoundError(LookupError):
    """Raised when an attempt is made to look up a client by ID that does not exist in the system."""


class InvoiceNotFoundError(LookupError):
    """Raised when an attempt is made to look up an invoice by ID that does not exist in the system."""


class PaymentNotFoundError(LookupError):
    """Raised when an attempt is made to look up a payment by ID that does not exist in the system."""


class MissingClientReferenceError(KeyError):
    """Raised when an invoice is created without a valid client ID reference."""


class MissingInvoiceReferenceError(KeyError):
    """Raised when a payment is created without a valid invoice ID reference."""
