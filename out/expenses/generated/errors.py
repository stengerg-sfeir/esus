"""Application errors, one class per registered failure."""



class CategoryNotFoundError(LookupError):
    """Raised when a category with the given ID is not found in the database."""


class ExpenseNotFoundError(LookupError):
    """Raised when an expense with the given ID is not found in the database."""


class BudgetExceededException(RuntimeError):
    """Raised when an expense exceeds the budget limit for its category and month."""


class InvalidBudgetMonthError(ValueError):
    """Raised when an invalid month format (not 'YYYY-MM') is provided for budget operations."""


class InvalidDateFormatError(ValueError):
    """Raised when an expense date is not in ISO format (YYYY-MM-DD)."""


class MalformedCSVError(ValueError):
    """Raised when the CSV data is malformed or incomplete."""


class MissingFileError(OSError):
    """Raised when a required file is missing during export operations."""
