"""Application errors, one class per registered failure."""



from __future__ import annotations

class AlreadyReturnedLoanError(RuntimeError):
    """Raised when an attempt is made to return a loan that is already marked as returned."""


class AuthorNotFoundError(LookupError):
    """Raised when an author is not found during lookup by ID or name."""


class BookNotFoundError(LookupError):
    """Raised when a book is not found during lookup by ID, title, author, or ISBN."""


class InvalidBookCopiesError(ValueError):
    """Raised when a book's available_copies is set to a negative value."""


class InvalidBookIdError(ValueError):
    """Raised when a book ID is not a valid integer or does not exist in the system."""


class InvalidLoanStatusError(ValueError):
    """Raised when a loan status is set to an invalid value such as 'invalid' or 'unknown'."""


class InvalidMemberIdError(ValueError):
    """Raised when a member ID is not a valid integer or does not exist in the system."""


class LoanNotFoundError(LookupError):
    """Raised when a loan is not found during lookup by ID or member/book reference."""


class MemberNotFoundError(LookupError):
    """Raised when a member is not found during lookup by ID or email."""


class MissingRequiredFieldError(ValueError):
    """Raised when a required field (e.g., title, isbn, member_id, book_id) is missing in a command or request."""
