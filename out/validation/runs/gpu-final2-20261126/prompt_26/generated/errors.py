"""Application errors, one class per registered failure."""



from __future__ import annotations

class BookAlreadyLoanedError(RuntimeError):
    """Raised when an attempt is made to loan a book that is already actively borrowed."""


class BookNotFoundError(LookupError):
    """Raised when a requested book is not found in the system during a lookup operation."""


class LoanNotFoundError(LookupError):
    """Raised when a requested loan is not found in the system during a lookup operation."""


class MemberNotAuthorizedError(PermissionError):
    """Raised when a member attempts to borrow a book without proper authorization, such as not being a registered member."""


class MemberNotFoundError(LookupError):
    """Raised when a requested member is not found in the system during a lookup operation."""
