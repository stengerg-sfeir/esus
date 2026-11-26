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



class LoanService:

    def __init__(self, repos):
        self._repos = repos


    def create_loan(self, book_id: int = None, member_id: int = None, loan_date: Any = None, due_date: Any = None, is_active: bool = None) -> None:
        """Creates a new Loan. [mechanical CRUD wrapper]"""
        if book_id is None or member_id is None or loan_date is None or due_date is None or is_active is None:
            raise ValueError('missing required field')
        self._repos['LoanRepository'].create(book_id=book_id, member_id=member_id, loan_date=loan_date, due_date=due_date, is_active=is_active)

    def update_loan(self, id: int = None, book_id: int = None, member_id: int = None, loan_date: Any = None, due_date: Any = None, is_active: bool = None) -> None:
        """Updates an existing Loan. [mechanical CRUD wrapper]"""
        self._repos['LoanRepository'].update(id=id, book_id=book_id, member_id=member_id, loan_date=loan_date, due_date=due_date, is_active=is_active)

    def delete_loan(self, id: int = None) -> None:
        """Deletes an existing Loan. [mechanical CRUD wrapper]"""
        self._repos['LoanRepository'].delete(id=id)

    def read_loan_by_id(self, id: int = None) -> models.Loan | None:
        """Reads one Loan by its key. [mechanical standard read]"""
        try:
            return self._repos['LoanRepository'].read_one(id)
        except errors.LoanNotFoundError:
            return None
