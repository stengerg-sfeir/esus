"""Services. A method with the same name as a repository method delegates
to it; anything else raises NotImplementedError with its work order.
"""

from typing import Any, Dict, List, Optional, Union

import calendar

import models
import errors
from store import match_criterion
import datetime


def _holds(actual, operator, expected):
    """Twin of `store._holds`: the operators filter composition reuses."""
    if operator == "eq":
        return actual == expected
    if operator == "ge":
        return actual is not None and actual >= expected
    if operator == "le":
        return actual is not None and actual <= expected
    raise ValueError(f"unknown operator {operator!r}")



class LibraryService:

    def __init__(self, repos):
        self._repos = repos


    def borrow_book(self, member_id: int = None, book_id: int = None) -> models.Loan:
        """Borrow a book by member and book IDs, checks availability, creates loan, and decrements copies. [llm-written by Ministral-3-3B-Instruct-2512-Q4_K_M.gguf — review]"""
        member = self._repos['MemberRepository'].read_one_member(member_id)
        if member is None:
            raise errors.MemberNotFoundError("Member not found")

        book = self._repos['BookRepository'].read_one_book(book_id)
        if book is None:
            raise errors.BookNotFoundError("Book not found")

        if book.available_copies <= 0:
            raise errors.InsufficientCopiesError("No available copies of this book")

        loan = models.Loan(
            book_id=book.id,
            member_id=member.id,
            loan_date=datetime.datetime.now(),
            due_date=datetime.datetime.now() + datetime.timedelta(days=14),
            status="active"
        )

        self._repos['LoanRepository'].create_loan(loan)
        book.available_copies -= 1
        updated_book = self._repos['BookRepository'].update_book(book_id, book)

        return updated_book

    def return_book(self, loan_id: int = None) -> models.Loan:
        """Returns a book by loan ID, sets return_date, updates status, and increments copies. [llm-written by Ministral-3-3B-Instruct-2512-Q4_K_M.gguf — review]"""
        loan = self._repos['LoanRepository'].read_one_loan(loan_id)
        if loan is None:
            raise errors.LoanNotFoundError("Loan not found")

        # Update return_date and status
        loan.return_date = datetime.datetime.now()
        loan.status = "returned"

        # Increment available copies for the book
        book = self._repos['BookRepository'].read_one_book(loan.book_id)
        if book is None:
            raise errors.BookNotFoundError("Book not found")

        book.available_copies += 1
        updated_book = self._repos['BookRepository'].update_book(loan.book_id, book)

        return updated_book

    def get_overdue_loans(self) -> List[models.Loan]:
        """Returns all overdue loans. [delegates to LoanRepository.get_overdue_loans — pattern realized by target]"""
        return self._repos['LoanRepository'].get_overdue_loans()

    def renew_membership(self, member_id: int = None) -> models.Member:
        """Renews membership by toggling is_active status. [llm-written by Ministral-3-3B-Instruct-2512-Q4_K_M.gguf — review]"""
        member = self._repos['MemberRepository'].read_one_member(member_id)
        if member is None:
            raise errors.MemberNotFoundError("Member not found")

        member.is_active = not member.is_active
        updated_member = self._repos['MemberRepository'].update_member(member_id, member)

        return updated_member

    def search_books(self, query: str = None) -> List[models.Book]:
        """Searches books by title, author, or ISBN. [llm-written by Ministral-3-3B-Instruct-2512-Q4_K_M.gguf — review]"""
        books = self._repos['BookRepository'].search_books_by_title_author_isbn(query)
        return books
