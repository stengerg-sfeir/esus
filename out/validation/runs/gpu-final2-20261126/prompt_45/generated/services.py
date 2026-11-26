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


    def validate_booking_dates(self, room_id: int = None, check_in_date: datetime.datetime = None, check_out_date: datetime.datetime = None) -> bool:
        """Validates that the check-in and check-out dates are valid and non-overlapping with existing bookings for the specified room. [llm-written by server — review]"""
        room_bookings = self._repos['BookingRepository'].findOverlappingBookings(roomId=room_id, checkInDate=check_in_date.date(), checkOutDate=check_out_date.date())
        if room_bookings:
            return False
        return True

    def check_room_availability(self, room_id: int = None, check_in_date: datetime.datetime = None, check_out_date: datetime.datetime = None) -> bool:
        """Checks if a room is available during a specified date range by verifying no overlapping bookings exist. [llm-written by server — review]"""
        room_bookings = self._repos['BookingRepository'].findOverlappingBookings(roomId=room_id, checkInDate=check_in_date.date(), checkOutDate=check_out_date.date())
        return len(room_bookings) == 0

    def create_booking(self, room_id: int = None, guest_id: int = None, check_in_date: Any = None, check_out_date: Any = None, booking_status: str = None) -> None:
        """Creates a new Booking. [mechanical CRUD wrapper]"""
        if room_id is None or guest_id is None or check_in_date is None or check_out_date is None or booking_status is None:
            raise ValueError('missing required field')
        self._repos['BookingRepository'].create(room_id=room_id, guest_id=guest_id, check_in_date=check_in_date, check_out_date=check_out_date, booking_status=booking_status)

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

    def read_booking_by_id(self, id: int = None) -> models.Booking | None:
        """Reads one Booking by its key. [mechanical standard read]"""
        try:
            return self._repos['BookingRepository'].read_one(id)
        except errors.BookingNotFoundError:
            return None

    def update_booking(self, id: int = None, room_id: int = None, guest_id: int = None, check_in_date: Any = None, check_out_date: Any = None, booking_status: str = None) -> None:
        """Updates an existing Booking. [mechanical CRUD wrapper]"""
        self._repos['BookingRepository'].update(id=id, room_id=room_id, guest_id=guest_id, check_in_date=check_in_date, check_out_date=check_out_date, booking_status=booking_status)

    def delete_booking(self, id: int = None) -> None:
        """Deletes an existing Booking. [mechanical CRUD wrapper]"""
        self._repos['BookingRepository'].delete(id=id)
