"""Application errors, one class per registered failure."""



from __future__ import annotations

class TaskStatusInvalidError(ValueError):
    """Raised by TaskService.confirm_order when the requested operation is not valid."""


class TaskNotConfirmedError(RuntimeError):
    """Raised by TaskService.cancel_order when the requested operation is not valid."""


class MissingRequiredFieldError(LookupError):
    """Raised by TaskService.validate_imported_tasks when the requested operation is not valid."""
