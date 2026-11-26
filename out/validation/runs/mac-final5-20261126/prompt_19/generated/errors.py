"""Application errors, one class per registered failure."""



from __future__ import annotations

class TaskAlreadyConfirmedError(RuntimeError):
    """Raised by TaskService.confirm_order when the requested operation is not valid."""


class TaskNotConfirmedError(RuntimeError):
    """Raised by TaskService.cancel_order when the requested operation is not valid."""


class DuplicateTaskIdError(RuntimeError):
    """Raised by TaskService.validate_and_import_tasks when the requested operation is not valid."""


class MissingRequiredFieldError(LookupError):
    """Raised by TaskValidationService.validate_task_creation when the requested operation is not valid."""
