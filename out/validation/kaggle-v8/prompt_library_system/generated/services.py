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



class LibraryService:

    def __init__(self, repos):
        self._repos = repos


    def borrow_book(self, member_id: int = None, book_id: int = None) -> None:
        """Borrows a book by member and book ID, checks availability, creates a loan, and decrements available copies. All operations are performed in a single transaction. [llm-written by server — review]"""
        member = self._repos['MemberRepository'].read_one(id=member_id)
        if member is None:
            raise errors.MemberNotFoundError
        book = self._repos['BookRepository'].read_one(id=book_id)
        if book is None:
            raise errors.BookNotFoundError
        if book.available_copies <= 0:
            raise errors.InvalidBookCopiesError
        loan = self._repos['LoanRepository'].create(book_id=book_id, member_id=member_id, loan_date=datetime.date.today(), due_date=datetime.date.today() + datetime.timedelta(days=14))
        book.available_copies = book.available_copies - 1
        self._repos['BookRepository'].update(id=book.id, available_copies=book.available_copies)

    def return_book(self, loan_id: int = None) -> None:
        """Returns a loan by loan ID, sets return_date to today, updates status to 'returned', and increments the book's available copies. If the loan is already returned, raises AlreadyReturnedLoanError. [llm-written by server — review]"""
        loan = self._repos['LoanRepository'].read_one(id=loan_id)
        if loan is None:
            raise errors.LoanNotFoundError
        if loan.status == 'returned':
            raise errors.AlreadyReturnedLoanError
        loan.return_date = datetime.date.today()
        loan.status = 'returned'
        self._repos['LoanRepository'].update(id=loan_id, return_date=loan.return_date, status=loan.status)
        book = self._repos['BookRepository'].read_one(loan.book_id)
        if book is None:
            raise errors.BookNotFoundError
        book.available_copies = book.available_copies + 1
        self._repos['BookRepository'].update(id=book.id, available_copies=book.available_copies)

    def get_overdue_loans(self) -> list[models.Loan]:
        """Returns all loans that are overdue (due_date < today and return_date is None). This is a read-only operation that computes overdue status based on current date. [mechanical overdue read]"""
        records = self._repos['LoanRepository'].read_all()
        today = datetime.date.today()
        result = []
        for loan in records:
            if loan.due_date is None or loan.due_date >= today:
                continue
            if loan.return_date is not None:
                continue
            loan.status = 'overdue'
            result.append(loan)
        return result

    def renew_membership(self, member_id: int = None) -> None:
        """Toggles the active status of a member (True to False, False to True). [llm-written by server — review]"""
        member = self._repos['MemberRepository'].read_one(id=member_id)
        if member is None:
            raise errors.MemberNotFoundError
        member.is_active = not member.is_active
        self._repos['MemberRepository'].update(id=member_id, is_active=member.is_active)

    def search_books(self, query: str = None) -> list[models.Book]:
        """Searches for books by title, author name, or ISBN using case-insensitive substring matching. Returns all matching books, one per result even if multiple fields match. ISBN miss returns empty list. [delegates to the repository search]"""
        return self._repos['BookRepository'].search_by_title_or_author_or_isbn(query)


def _atomic(method):
    """Run a multi-write service method in one store transaction."""
    def wrapper(self, *args, **kwargs):
        store = None
        for repo in self._repos.values():
            store = getattr(repo, '_store', None)
            if store is not None:
                break
        if store is None or not hasattr(store, 'transaction'):
            return method(self, *args, **kwargs)
        with store.transaction():
            return method(self, *args, **kwargs)
    wrapper.__name__ = method.__name__
    wrapper.__doc__ = method.__doc__
    wrapper.__wrapped__ = method
    return wrapper


for _name in ['borrow_book', 'return_book']:
    if hasattr(LibraryService, _name):
        setattr(LibraryService, _name, _atomic(getattr(LibraryService, _name)))
