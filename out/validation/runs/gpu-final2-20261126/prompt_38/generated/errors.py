"""Application errors, one class per registered failure."""



from __future__ import annotations

class UserNotFoundError(LookupError):
    """Raised when a user is not found by their ID during authentication or lookup."""


class DocumentNotFoundError(LookupError):
    """Raised when a document is not found by its ID during retrieval or deletion."""


class UnauthorizedAccessError(RuntimeError):
    """Raised when a user attempts to access a document that does not belong to them."""


class DocumentOwnershipError(RuntimeError):
    """Raised when a user tries to modify or delete a document not owned by them."""
