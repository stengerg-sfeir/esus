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
        """Borrow a book by member and book IDs, checks availability, creates loan, and decrements copies. [llm-written by Qwen3-4B-Instruct-2507-Q4_K_M.gguf — review]"""
        member = self._repos['MemberRepository'].read_one_member(member_id)
        if member is None:
            raise errors.MemberNotFoundError(member_id)
        book = self._repos['BookRepository'].read_one_book(book_id)
        if book is None:
            raise errors.BookNotFoundError(book_id)
        if book.available_copies <= 0:
            raise errors.InsufficientCopiesError(book_id)
        loan = models.Loan(
            book_id=book.id,
            member_id=member.id,
            loan_date=datetime.datetime.now().isoformat(),
            due_date=(datetime.datetime.now() + datetime.timedelta(days=14)).isoformat(),
            status='active'
        )
        created_loan = self._repos['LoanRepository'].create_loan(loan)
        book.available_copies -= 1
        self._repos['BookRepository'].update_book(book_id, book)
        return created_loan

    def return_book(self, loan_id: int = None) -> models.Loan:
        """Returns a book by loan ID, sets return_date, updates status, and increments copies. [llm-written by Qwen3-4B-Instruct-2507-Q4_K_M.gguf — review]"""
        loan = self._repos['LoanRepository'].read_one_loan(loan_id)
        if loan is None:
            raise errors.LoanNotFoundError(loan_id)
        if loan.status == 'returned':
            raise errors.InvalidReturnDateError(loan_id)
        loan.return_date = datetime.datetime.now().isoformat()
        loan.status = 'returned'
        updated_loan = self._repos['LoanRepository'].update_loan(loan_id, loan)
        book = self._repos['BookRepository'].read_one_book(loan.book_id)
        if book is None:
            raise errors.BookNotFoundError(loan.book_id)
        book.available_copies += 1
        self._repos['BookRepository'].update_book(loan.book_id, book)
        return updated_loan

    def get_overdue_loans(self) -> List[models.Loan]:
        """Returns all overdue loans. [delegates to LoanRepository.get_overdue_loans — pattern realized by target]"""
        return self._repos['LoanRepository'].get_overdue_loans()

    def renew_membership(self, member_id: int = None) -> models.Member:
        """Renews membership by toggling is_active status. [llm-written by Qwen3-4B-Instruct-2507-Q4_K_M.gguf — review]"""
        member = self._repos['MemberRepository'].read_one_member(member_id)
        if member is None:
            raise errors.MemberNotFoundError(member_id)
        member.is_active = not member.is_active
        updated_member = self._repos['MemberRepository'].update_member(member_id, member)
        return updated_member

    def search_books(self, query: str = None) -> List[models.Book]:
        """Searches books by title, author, or ISBN. [llm-written by Qwen3-4B-Instruct-2507-Q4_K_M.gguf — review]"""
        results = []
        if query is None:
            return results

        books = self._repos['BookRepository'].search_books_by_title_author_isbn(query)
        results.extend(books)

        # Search by author: find books where author name matches the query
        authors = self._repos['AuthorRepository'].read_all_authors()
        author_names = {author.id: author.name for author in authors}

        for book in self._repos['BookRepository'].read_all_books():
            author_name = author_names.get(book.author_id)
            if author_name and query.lower() in author_name.lower():
                results.append(book)

        # Search by ISBN
        for book in self._repos['BookRepository'].read_all_books():
            if query.lower() in book.isbn.lower():
                results.append(book)

        # Remove duplicates by checking if book is already in results
        unique_results = []
        seen = set()
        for book in results:
            book_key = (book.title, book.isbn, book.author_id)
            if book_key not in seen:
                seen.add(book_key)
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
