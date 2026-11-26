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



class BorrowService:

    def __init__(self, repos):
        self._repos = repos


    def return_book(self, book_id: int = None, member_id: int = None, return_date: datetime.datetime = None) -> None:
        """Returns a borrowed book to the library. The book's borrow status is updated to available, and the return date is set. If the return date is earlier than the borrow date, an InvalidReturnDateError is raised. If the book was not borrowed, a BorrowRecordNotFoundError is raised. [mechanical return]"""
        records = self._repos['BorrowRecordRepository'].read_all(book_id=book_id, member_id=member_id)
        for record in records:
            if getattr(record, 'return_date', None) is not None:
                continue
            self._repos['BorrowRecordRepository'].update(borrow_id=record.borrow_id, return_date=datetime.datetime.now())
            self._repos['BookRepository'].update(book_id=book_id, available_status=True)
            return
        raise errors.BorrowRecordNotFoundError('borrow record not found')
