"""Application errors, one class per registered failure."""



from __future__ import annotations

class CategoryNotFoundError(LookupError):
    """Raised when a requested category ID does not exist in the database."""


class ExpenseNotFoundError(LookupError):
    """Raised when a requested expense ID does not exist in the database."""


class BudgetExceededException(RuntimeError):
    """Raised when adding or updating an expense causes the total spending in a category to exceed its monthly budget limit for a given month."""
