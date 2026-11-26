"""Application errors, one class per registered failure."""


from __future__ import annotations

class AppError(Exception):
    """Fallback when no errors were registered."""

