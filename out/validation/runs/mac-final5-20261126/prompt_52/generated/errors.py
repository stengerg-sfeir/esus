"""Application errors, one class per registered failure."""



from __future__ import annotations

class BookNotFoundError(LookupError):
    """Raised when a requested book is not found in the library system by its book_id."""


class MemberNotFoundError(LookupError):
    """Raised when a requested member is not found in the system by their member_id."""


class BorrowRecordNotFoundError(LookupError):
    """Raised when a borrow record is not found in the system by its borrow_id."""
