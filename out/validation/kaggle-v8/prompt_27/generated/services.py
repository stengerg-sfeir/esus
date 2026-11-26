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



class ReservationService:

    def __init__(self, repos):
        self._repos = repos


    def create_reservation(self, customer_id: int = None, room_id: int = None, start_date: datetime.datetime = None, end_date: datetime.datetime = None) -> Any:
        """Creates a new reservation for a customer in a room, validating that the room and customer exist and that the reservation does not overlap with any existing reservation. [mechanical CRUD wrapper]"""
        if customer_id is None or room_id is None or start_date is None or end_date is None:
            raise ValueError('missing required field')
        return self._repos['ReservationRepository'].create(customer_id=customer_id, room_id=room_id, start_date=start_date, end_date=end_date)

    def read_reservation_by_id(self, reservation_id: int = None) -> models.Reservation | None:
        """Reads one Reservation by its key. [mechanical standard read]"""
        try:
            return self._repos['ReservationRepository'].read_one(reservation_id)
        except errors.ReservationNotFoundError:
            return None

    def read_all_reservations(self) -> list[models.Reservation]:
        """Lists every Reservation. [composes ReservationRepository.read_all over READ_ALL]"""
        records = self._repos['ReservationRepository'].read_all()
        criteria = []
        out = []
        for record in records:
            row = record if isinstance(record, dict) else vars(record)
            if all(_holds(row.get(field), operator, value)
                   for field, operator, value in criteria):
                out.append(record)
        return out

    def update_reservation(self, reservation_id: int = None, customer_id: int = None, room_id: int = None, start_date: Any = None, end_date: Any = None) -> None:
        """Updates an existing Reservation. [mechanical CRUD wrapper]"""
        self._repos['ReservationRepository'].update(reservation_id=reservation_id, customer_id=customer_id, room_id=room_id, start_date=start_date, end_date=end_date)

    def delete_reservation(self, reservation_id: int = None) -> None:
        """Deletes an existing Reservation. [mechanical CRUD wrapper]"""
        self._repos['ReservationRepository'].delete(reservation_id=reservation_id)
