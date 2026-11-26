"""Application errors, one class per registered failure."""



from __future__ import annotations

class CategoryNotFoundError(LookupError):
    """Raised when a requested category is not found in the database."""


class ExpenseNotFoundError(LookupError):
    """Raised when an expense with the specified ID is not found in the database."""


class BudgetExceededException(RuntimeError):
    """Raised when adding or updating an expense causes a category's budget to be exceeded for a given month."""
