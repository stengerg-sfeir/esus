"""Application errors, one class per registered failure."""



from __future__ import annotations

class BookAlreadyBorrowedError(ValueError):
    """Raised when an attempt is made to borrow a book that is already currently borrowed by another member."""


class BookNotAvailableError(LookupError):
    """Raised when a member tries to borrow a book that is not currently available (i.e., already borrowed)."""


class BookNotFoundError(LookupError):
    """Raised when a requested book is not found in the library system by book_id."""


class BorrowRecordNotFoundError(LookupError):
    """Raised when a borrow record is not found for a specific book_id and member_id combination."""


class InvalidReturnDateError(ValueError):
    """Raised when a return date is provided that is earlier than the borrow date in a return request."""


class MemberNotFoundError(LookupError):
    """Raised when a requested member is not found in the system by member_id."""
