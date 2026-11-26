"""Application errors, one class per registered failure."""



from __future__ import annotations

class BookNotFoundError(LookupError):
    """Raised when a book is requested by book_id but no book with that ID exists in the database."""


class MemberNotFoundError(LookupError):
    """Raised when a member is requested by member_id but no member with that ID exists in the database."""


class LoanNotFoundError(LookupError):
    """Raised when a loan is requested by loan_id but no loan with that ID exists in the database."""


class BookAlreadyBorrowedError(RuntimeError):
    """Raised when an attempt is made to loan a book that is already currently borrowed by another member."""


class MemberNotEligibleForLoanError(RuntimeError):
    """Raised when a member is not eligible to borrow a book, for example, if their membership status is inactive."""
