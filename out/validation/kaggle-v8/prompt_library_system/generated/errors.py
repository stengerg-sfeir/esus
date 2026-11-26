"""Application errors, one class per registered failure."""



from __future__ import annotations

class AlreadyReturnedLoanError(RuntimeError):
    """Raised when an attempt is made to return a loan that is already marked as returned."""


class BookNotFoundError(LookupError):
    """Raised when a book is not found during lookup by title, ISBN, or author ID."""


class AuthorNotFoundError(LookupError):
    """Raised when an author is not found during lookup by ID or name."""


class MemberNotFoundError(LookupError):
    """Raised when a member is not found during lookup by ID or email."""


class LoanNotFoundError(LookupError):
    """Raised when a loan is not found during lookup by ID."""


class InvalidBookCopiesError(ValueError):
    """Raised when the number of available copies is negative or not an integer."""


class InvalidBookAuthorIDError(KeyError):
    """Raised when a book is attempted to be added with a non-existent author ID."""


class InvalidLoanBookIDError(KeyError):
    """Raised when a loan is attempted to be created with a book ID that does not exist."""


class MalformedQueryError(ValueError):
    """Raised when a search query is empty or contains invalid characters that prevent substring matching."""
