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


    def borrow_book(self, member_id: int = None, book_id: int = None) -> None:
        """Allows a member to borrow a book. The book must be available and the member must exist. If the book is already borrowed, the operation fails. [llm-written by server — review]"""
        member = self._repos['MemberRepository'].read_one(member_id=member_id)
        if not member:
            raise errors.MemberNotFoundError('member not found')
        book = self._repos['BookRepository'].read_one(book_id=book_id)
        if not book:
            raise errors.BookNotFoundError('book not found')
        if not book.available_status:
            raise errors.BookNotFoundError('book is not available')
        borrow_record = self._repos['BorrowRecordRepository'].create_borrow_record(book_id=book_id, member_id=member_id, borrow_date=datetime.datetime.now())
        self._repos['BookRepository'].update(book_id=book_id, available_status=False)

    def return_book(self, member_id: int = None, book_id: int = None) -> None:
        """Returns a borrowed book to the library. The book must be currently borrowed by a member. After return, the book becomes available again. [mechanical return]"""
        records = self._repos['BorrowRecordRepository'].read_all(book_id=book_id, member_id=member_id)
        for record in records:
            if getattr(record, 'is_returned', None):
                continue
            self._repos['BorrowRecordRepository'].update(borrow_id=record.borrow_id, is_returned=True, return_date=datetime.datetime.now())
            self._repos['BookRepository'].update(book_id=book_id, available_status=True)
            return
        raise errors.BorrowRecordNotFoundError('borrow record not found')
