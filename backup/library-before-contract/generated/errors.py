"""Application errors, one class per registered failure."""



class BookNotFoundError(LookupError):
    """Raised when a book with the given ISBN or ID is not found in the database."""


class AuthorNotFoundError(LookupError):
    """Raised when an author with the given ID is not found in the database."""


class MemberNotFoundError(LookupError):
    """Raised when a member with the given ID is not found in the database."""


class LoanNotFoundError(LookupError):
    """Raised when a loan with the given ID is not found in the database."""


class BookAlreadyExistsError(ValueError):
    """Raised when attempting to add a book with an existing ISBN."""


class MemberAlreadyExistsError(ValueError):
    """Raised when attempting to add a member with an existing email."""


class InsufficientCopiesError(RuntimeError):
    """Raised when attempting to borrow a book with zero available copies."""


class InvalidReturnDateError(RuntimeError):
    """Raised when a book is returned before its due date."""
