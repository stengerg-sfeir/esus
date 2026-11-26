"""Application errors, one class per registered failure."""



from __future__ import annotations

class BookIsbnDuplicateError(ValueError):
    """Raised when an attempt is made to add a book with an ISBN that is already in the database."""


class BookNotFoundError(LookupError):
    """Raised when a book is requested by ID but no book with that ID exists in the database."""


class BookIdNotFoundError(LookupError):
    """Raised when a book is searched or retrieved by ID but no book with that ID exists in the database."""
