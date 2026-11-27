"""Services. A method with the same name as a repository method delegates
to it; anything else raises NotImplementedError with its work order.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple, Union

import calendar
import csv
import datetime
import json

import models
import errors
from store import match_criterion


def _holds(actual, operator, expected):
    """Twin of `store._holds`: the operators filter composition reuses."""
    if operator == "eq":
        return actual == expected
    if operator == "ge":
        return actual is not None and actual >= expected
    if operator == "le":
        return actual is not None and actual <= expected
    if operator == "gt":
        return actual is not None and actual > expected
    if operator == "lt":
        return actual is not None and actual < expected
    raise ValueError(f"unknown operator {operator!r}")


def _as_date(value):
    """Accept an ISO string or a date object; return a date or None."""
    if value is None or isinstance(value, datetime.date):
        return value
    return datetime.date.fromisoformat(str(value))



class EventRegistrationService:

    def __init__(self, repos):
        self._repos = repos


    def register_for_event(self, event_id: int = None, user_id: int = None) -> None:
        """Allows a user to register for an event. If the event is at full capacity, this method raises a RegistrationCapacityExceededError. [llm-written by server — review]"""
        event = self._repos['EventRepository'].read_one(event_id=event_id)
        if not event:
            raise errors.EventNotFoundError
        if self._repos['EventRepository'].is_event_full(event_id=event_id):
            raise errors.RegistrationCapacityExceededError
        registration = self._repos['RegistrationRepository'].create(event_id=event_id, user_id=user_id)
