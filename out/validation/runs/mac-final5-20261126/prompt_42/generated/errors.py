"""Application errors, one class per registered failure."""



from __future__ import annotations

class CustomerNotFoundError(LookupError):
    """Raised when a customer is requested but not found in the system by customer_id."""


class PurchaseNotFoundError(LookupError):
    """Raised when a purchase is requested but not found in the system by purchase_id."""


class InvalidCustomerIdError(ValueError):
    """Raised when a customer_id provided is not a valid integer or is otherwise malformed."""


class MissingCustomerEmailError(KeyError):
    """Raised when attempting to access a customer's email but the email field is missing from the customer record."""


class MissingPurchaseAmountError(KeyError):
    """Raised when attempting to access a purchase's amount but the amount field is missing from the purchase record."""
