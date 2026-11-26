"""Application errors, one class per registered failure."""



from __future__ import annotations

class BookNotFoundError(LookupError):
    """Raised when a requested book is not found in the system during a lookup operation."""


class MemberNotFoundError(LookupError):
    """Raised when a requested member is not found in the system during a lookup operation."""


class LoanNotFoundError(LookupError):
    """Raised when a requested loan is not found in the system during a lookup operation."""


class BookAlreadyLoanedError(RuntimeError):
    """Raised when an attempt is made to loan a book that is already actively borrowed by another member."""


class InvalidLoanDateError(ValueError):
    """Raised when a loan date is provided that is in the future or invalid."""


class InvalidDueDateError(ValueError):
    """Raised when a due date is provided that is earlier than the loan date or invalid."""
