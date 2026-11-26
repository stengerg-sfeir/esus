"""Application errors, one class per registered failure."""



from __future__ import annotations

class UserNotFoundError(LookupError):
    """Raised when a user is not found during authentication or lookup by user ID."""


class DocumentNotFoundError(LookupError):
    """Raised when a document is not found during retrieval, modification, or deletion by document ID."""


class DocumentModificationError(RuntimeError):
    """Raised when a document is modified in a way that violates business rules, such as changing the user ownership or altering metadata without authorization."""
