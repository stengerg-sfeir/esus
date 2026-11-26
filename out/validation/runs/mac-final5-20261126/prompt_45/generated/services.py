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



class BookingService:

    def __init__(self, repos):
        self._repos = repos


    def check_room_availability(self, room_id: int = None, check_in_date: str = None, check_out_date: str = None) -> bool:
        """Checks if a room is available for booking during a specified date range. [llm-written by server — review]"""
        check_in_date = _as_date(check_in_date)
        check_out_date = _as_date(check_out_date)
        if check_in_date is None or check_out_date is None:
            return False
        if check_in_date >= check_out_date:
            return False
        conflicting_bookings = self._repos['BookingRepository'].read_all_bookings_for_room_and_date_range(room_id=room_id, check_in_date=check_in_date, check_out_date=check_out_date)
        return len(conflicting_bookings) == 0

    def create_booking(self, guest_id: int = None, room_id: int = None, check_in_date: str = None, check_out_date: str = None, status: str = None) -> str:
        """Creates a new booking for a guest in a room, ensuring no overlap with existing bookings. [llm-written by generator-contract-fallback — review]"""
        if any(str(row.room_id) == str(room_id) and str(row.check_in_date or '') < str(check_out_date) and str(check_in_date) < str(row.check_out_date or '') for row in self._repos['BookingRepository'].read_all()):
            raise errors.RoomConflictError('confirmed precondition failed')
        return self._repos['BookingRepository'].create(guest_id=guest_id, room_id=room_id, check_in_date=check_in_date, check_out_date=check_out_date, status=status)

    def read_all_bookings(self) -> list[models.Booking]:
        """Lists every Booking. [composes BookingRepository.read_all over READ_ALL]"""
        records = self._repos['BookingRepository'].read_all()
        criteria = []
        out = []
        for record in records:
            row = record if isinstance(record, dict) else vars(record)
            if all(_holds(row.get(field), operator, value)
                   for field, operator, value in criteria):
                out.append(record)
        return out

    def read_booking_by_id(self, booking_id: int = None) -> models.Booking | None:
        """Reads one Booking by its key. [mechanical standard read]"""
        try:
            return self._repos['BookingRepository'].read_one(booking_id)
        except errors.BookingNotFoundError:
            return None

    def update_booking(self, booking_id: int = None, guest_id: int = None, room_id: int = None, check_in_date: Any = None, check_out_date: Any = None, status: str = None) -> None:
        """Updates an existing Booking. [mechanical CRUD wrapper]"""
        self._repos['BookingRepository'].update(booking_id=booking_id, guest_id=guest_id, room_id=room_id, check_in_date=check_in_date, check_out_date=check_out_date, status=status)

    def delete_booking(self, booking_id: int = None) -> None:
        """Deletes an existing Booking. [mechanical CRUD wrapper]"""
        self._repos['BookingRepository'].delete(booking_id=booking_id)
