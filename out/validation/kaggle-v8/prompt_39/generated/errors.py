"""Application errors, one class per registered failure."""



from __future__ import annotations

class UserNotFoundError(LookupError):
    """Raised when a user is requested but not found in the system by user_id."""


class ProductNotFoundError(LookupError):
    """Raised when a product is requested but not found in the system by product_id."""


class OrderNotFoundError(LookupError):
    """Raised when an order is requested but not found in the system by order_id."""


class InvalidUserRoleError(RuntimeError):
    """Raised when a user attempts an action that is not permitted by their role, such as modifying a product or another user's data."""


class MissingRequiredFieldError(ValueError):
    """Raised when a required field (such as email or product name) is missing or empty during user or product creation."""


class InvalidEmailError(ValueError):
    """Raised when an email address is provided in an invalid format during user creation."""


class InvalidPriceError(ValueError):
    """Raised when a product price is provided as a negative value or non-numeric during product creation."""


class OrderCreationFailedError(RuntimeError):
    """Raised when an order cannot be created due to a system-level constraint, such as a user not being authenticated or exceeding order limits."""
