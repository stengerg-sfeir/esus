"""Application errors, one class per registered failure."""



from __future__ import annotations

class UserNotFoundError(LookupError):
    """Raised when a user is requested but not found in the system."""


class DocumentNotFoundError(LookupError):
    """Raised when a document is requested but not found in the system."""


class DocumentOwnershipError(RuntimeError):
    """Raised when a user tries to perform an action on a document that is not owned by them."""
