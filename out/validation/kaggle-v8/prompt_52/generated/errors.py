"""Application errors, one class per registered failure."""



from __future__ import annotations

class BookNotFoundError(LookupError):
    """Raised when a requested book is not found in the library system by its book_id."""


class MemberNotFoundError(LookupError):
    """Raised when a requested member is not found in the system by their member_id."""


class BorrowRecordNotFoundError(LookupError):
    """Raised when a borrow record is not found in the system by its borrow_id."""


class BookAlreadyBorrowedError(RuntimeError):
    """Raised when an attempt is made to borrow a book that is already currently borrowed by another member."""


class InvalidReturnDateError(ValueError):
    """Raised when a return date is set to a date earlier than the borrow date, which is invalid."""
