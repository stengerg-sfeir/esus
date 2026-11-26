"""Application errors, one class per registered failure."""



from __future__ import annotations

class BookNotFoundError(LookupError):
    """Raised when a requested book is not found in the library database."""


class MemberNotFoundError(LookupError):
    """Raised when a requested member is not found in the library database."""


class LoanNotFoundError(LookupError):
    """Raised when a requested loan record is not found in the database."""


class BookAlreadyBorrowedError(RuntimeError):
    """Raised when an attempt is made to loan a book that is already currently borrowed by another member."""


class MemberNotEligibleForLoanError(RuntimeError):
    """Raised when a member is not eligible to borrow books due to inactive membership status or other restrictions."""


class LoanDateBeforeReturnDateError(ValueError):
    """Raised when a loan date is provided that is after the return date, which is logically invalid."""
