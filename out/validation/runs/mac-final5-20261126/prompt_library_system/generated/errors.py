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


class InvalidMemberIDError(ValueError):
    """Raised when a member ID provided in a borrow or return command is not a valid integer or does not reference an existing member."""


class InvalidBookIDError(ValueError):
    """Raised when a book ID provided in a borrow or return command is not a valid integer or does not reference an existing book."""


class NegativeAvailableCopiesError(ValueError):
    """Raised when a book is attempted to be created or updated with a negative number of available copies."""


class MissingRequiredFieldError(ValueError):
    """Raised when a required field (e.g., title, ISBN, member name, email) is missing in a command input."""


class DuplicateEmailError(KeyError):
    """Raised when attempting to add a member with an email that already exists in the system."""
