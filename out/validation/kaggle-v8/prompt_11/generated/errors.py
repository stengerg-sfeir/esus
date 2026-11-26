"""Application errors, one class per registered failure."""



from __future__ import annotations

class BookIsbnDuplicateError(ValueError):
    """Raised when an attempt is made to create a book with an ISBN that is already in use."""


class BookNotFoundError(LookupError):
    """Raised when a book is requested by ID but no book with that ID exists in the database."""
