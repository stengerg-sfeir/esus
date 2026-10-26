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
        """Borrow a book by member and book IDs, checks availability, creates loan, and decrements copies. [llm-written by server — review]"""
        member = self._repos['MemberRepository'].read_one_member(member_id=member_id)
        if member is None:
            raise errors.MemberNotFoundError(f"Member with id {member_id} not found")

        book = self._repos['BookRepository'].read_one_book(book_id)
        if book is None:
            raise errors.BookNotFoundError(f"Book with id {book_id} not found")

        if book.available_copies <= 0:
            raise errors.InsufficientCopiesError(f"Book with id {book_id} has no available copies")

        now = datetime.datetime.now()
        due_date = now + datetime.timedelta(days=14)

        loan = models.Loan(
            book_id=book_id,
            member_id=member_id,
            loan_date=now,
            due_date=due_date,
            status="active"
        )

        created_loan = self._repos['LoanRepository'].create_loan(loan=loan)

        book.available_copies -= 1
        updated_book = self._repos['BookRepository'].update_book(book_id, book)

        return created_loan

    def return_book(self, loan_id: int = None) -> models.Loan:
        """Returns a book by loan ID, sets return_date, updates status, and increments copies. [llm-written by server — review]"""
        loan = self._repos['LoanRepository'].read_one_loan(loan_id=loan_id)
        if loan is None:
            raise errors.LoanNotFoundError(f"Loan with id {loan_id} not found")

        now = datetime.datetime.now()

        if now > loan.due_date:
            raise errors.InvalidReturnDateError(f"Return date cannot be after due date for loan {loan_id}")

        loan.return_date = now
        loan.status = "returned"

        updated_loan = self._repos['LoanRepository'].update_loan(loan_id=loan_id, loan=loan)

        book = self._repos['BookRepository'].read_one_book(loan.book_id)
        if book is None:
            raise errors.BookNotFoundError(f"Book with id {loan.book_id} not found")

        book.available_copies += 1
        updated_book = self._repos['BookRepository'].update_book(loan.book_id, book)

        return updated_loan

    def get_overdue_loans(self) -> List[models.Loan]:
        """Returns all overdue loans. [delegates to LoanRepository.get_overdue_loans — pattern realized by target]"""
        return self._repos['LoanRepository'].get_overdue_loans()

    def renew_membership(self, member_id: int = None) -> models.Member:
        """Renews membership by toggling is_active status. [llm-written by server — review]"""
        member = self._repos['MemberRepository'].read_one_member(member_id=member_id)
        if member is None:
            raise errors.MemberNotFoundError(f"Member with id {member_id} not found")
        member.is_active = True
        updated_member = self._repos['MemberRepository'].update_member(member_id=member_id, member=member)
        return updated_member

    def search_books(self, query: str = None) -> List[models.Book]:
        """Searches books by title, author, or ISBN. [llm-written by server — review]"""
        if not query:
            return []

        results = []
        books = self._repos['BookRepository'].search_books_by_title_author_isbn(query=query)
        results.extend(books)

        # Search by author: find books where author name matches the query (case-insensitive substring)
        author_query = query.lower()
        authors = self._repos['AuthorRepository'].read_all_authors()
        author_ids = {author.id: author.name.lower() for author in authors}

        for book in self._repos['BookRepository'].read_all_books():
            if book.author_id is not None and author_ids.get(book.author_id, "").lower().find(author_query) != -1:
                results.append(book)

        # Search by ISBN (case-insensitive substring)
        for book in self._repos['BookRepository'].read_all_books():
            if book.isbn and query.lower() in book.isbn.lower():
                results.append(book)

        # Remove duplicates by checking book id
        unique_results = []
        seen_ids = set()
        for book in results:
            if book.id is not None and book.id not in seen_ids:
                seen_ids.add(book.id)
                unique_results.append(book)

        return unique_results


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
