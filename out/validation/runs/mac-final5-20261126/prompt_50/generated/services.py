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


    def check_event_capacity(self, event_id: int = None) -> bool:
        """Checks if an event has reached its capacity and returns whether registration is allowed. [llm-written by server — review]"""
        event = self._repos['EventRepository'].read_one(event_id=event_id)
        if event is None:
            raise errors.EventNotFoundError(f'Event with id {event_id} not found')
        if event.current_attendees_count is None:
            raise errors.EventNotFoundError(f'Event with id {event_id} not found')
        registrations = self._repos['RegistrationRepository'].get_registrations_by_event_id(event_id=event_id)
        current_count = len(registrations)
        return current_count < event.capacity
