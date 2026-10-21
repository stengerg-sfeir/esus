"""Repositories over an in-memory Store, one class per persistence port.

CRUD, reads and filters run for real. Anything else raises
NotImplementedError with its work order — an aggregate or guard body
is specified by its pattern, not invented here.
"""

from typing import Any, Dict, List, Optional, Union

import datetime

import models
import errors
from store import Store, match_criterion


def _record_values(data, field_names):
    """A dataclass or dict entity argument as a `{field: value}` dict."""
    if data is None:
        return {}
    if isinstance(data, dict):
        return {name: data.get(name) for name in field_names}
    return {name: getattr(data, name, None) for name in field_names}



class BookRepository:
    ENTITY = "Book"
    PK = "id"

    def __init__(self, store):
        self._store = store


    def create_book(self, book: models.Book = None, isbn: str = None) -> models.Book:
        """Creates a new book entry with the provided details. [crud:create: STANDARD_CRUD]"""
        values = {}
        values.update(_record_values(book, ['id', 'title', 'isbn', 'published_year', 'available_copies', 'author_id']))
        if isbn is not None:
            values['isbn'] = isbn
        unknown = [k for k in values if k not in ['id', 'title', 'isbn', 'published_year', 'available_copies', 'author_id']]
        if unknown:
            raise ValueError(f"cannot create Book from {unknown}")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[("author_id", "Author", "id", errors.AuthorNotFoundError)])
        return models.Book(**record)

    def read_one_book(self, book_id_or_isbn: Union[str, int] = None) -> models.Book | None:
        """Reads a single book by its ID or ISBN. [crud:read_one: STANDARD_CRUD]"""
        found = []
        if book_id_or_isbn is not None:
            for field, operator in [('id', 'eq'), ('isbn', 'eq')]:
                found.extend(self._store.select(self.ENTITY, [(field, operator, book_id_or_isbn)]))
        if len(found) != 1:
            raise errors.BookNotFoundError(f"Book lookup matched {len(found)} records")
        record = found[0]
        return models.Book(**record)

    def read_all_books(self) -> List[models.Book]:
        """Reads all books from the database. [crud:read_all: READ_ALL]"""
        criteria = []
        found = self._store.select(self.ENTITY, criteria)
        return [models.Book(**r) for r in found]

    def update_book(self, book_id_or_isbn: Union[str, int] = None, book: models.Book = None) -> models.Book:
        """Updates a book's details by its ID or ISBN. [crud:update: STANDARD_CRUD]"""
        found = []
        if book_id_or_isbn is not None:
            for field, operator in [('id', 'eq'), ('isbn', 'eq')]:
                found.extend(self._store.select(self.ENTITY, [(field, operator, book_id_or_isbn)]))
        if len(found) != 1:
            raise errors.BookNotFoundError(f"Book update matched {len(found)} records")
        patch = {}
        for key, value in _record_values(book, ['id', 'title', 'isbn', 'published_year', 'available_copies', 'author_id']).items():
            if value is not None:
                patch[key] = value
        if book_id_or_isbn is not None and 'book_id_or_isbn' in ['id', 'title', 'isbn', 'published_year', 'available_copies', 'author_id']:
            patch['book_id_or_isbn'] = book_id_or_isbn
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=errors.BookNotFoundError)
        return models.Book(**record)

    def delete_book(self, book_id_or_isbn: Union[str, int] = None) -> bool:
        """Deletes a book by its ID or ISBN. [crud:delete: STANDARD_CRUD]"""
        found = []
        if book_id_or_isbn is not None:
            for field, operator in [('id', 'eq'), ('isbn', 'eq')]:
                found.extend(self._store.select(self.ENTITY, [(field, operator, book_id_or_isbn)]))
        if not found:
            raise errors.BookNotFoundError(f"Book delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None

    def filter_books_by_available_copies(self, min_available_copies: int = None) -> List[models.Book]:
        """Filters books by available copies count. [crud:filter: FILTER_BY_FIELD]"""
        criteria = []
        if min_available_copies is not None:
            criteria.append(('available_copies', 'ge', min_available_copies))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Book(**r) for r in found]

    def search_books_by_title_author_isbn(self, query: str = None) -> List[models.Book]:
        """Searches books by title, author, or ISBN. [llm-written by Ministral-3-3B-Instruct-2512-Q4_K_M.gguf — review]"""
        books = self._store.all(self.ENTITY)
        found = []
        for book in books:
            record = models.Book(**book)
            if (query.lower() in record.title.lower() or
                query.lower() in record.author.name.lower() or
                query.lower() in record.isbn.lower()):
                found.append(record)
        return found


class AuthorRepository:
    ENTITY = "Author"
    PK = "id"

    def __init__(self, store):
        self._store = store


    def create_author(self, author: models.Author = None) -> models.Author:
        """Creates a new author entry with the provided details. [crud:create: STANDARD_CRUD]"""
        values = _record_values(author, ['id', 'name', 'birth_year', 'biography'])
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[])
        return models.Author(**record)

    def read_one_author(self, author_id: int = None) -> models.Author | None:
        """Reads a single author by its ID. [crud:read_one: STANDARD_CRUD]"""
        record = self._store.get(self.ENTITY, self.PK, author_id, error=errors.AuthorNotFoundError)
        return models.Author(**record)

    def read_all_authors(self) -> List[models.Author]:
        """Reads all authors from the database. [crud:read_all: READ_ALL]"""
        criteria = []
        found = self._store.select(self.ENTITY, criteria)
        return [models.Author(**r) for r in found]

    def update_author(self, author_id: int = None, author: models.Author = None) -> models.Author:
        """Updates an author's details by its ID. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if author_id is not None:
            criteria.append(('id', 'eq', author_id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise errors.AuthorNotFoundError(f"Author update matched {len(found)} records")
        patch = {}
        for key, value in _record_values(author, ['id', 'name', 'birth_year', 'biography']).items():
            if value is not None:
                patch[key] = value
        if author_id is not None and 'author_id' in ['id', 'name', 'birth_year', 'biography']:
            patch['author_id'] = author_id
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=errors.AuthorNotFoundError)
        return models.Author(**record)

    def delete_author(self, author_id: int = None) -> bool:
        """Deletes an author by its ID. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if author_id is not None:
            criteria.append(('id', 'eq', author_id))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise errors.AuthorNotFoundError(f"Author delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None

    def find_books_by_author(self, author_id: int = None) -> List[models.Book]:
        """Finds all books by a specific author. [crud:filter: FILTER_BY_FIELD]"""
        criteria = []
        if author_id is not None:
            criteria.append(('author_id', 'eq', author_id))
        found = self._store.select('Book', criteria)
        return [models.Book(**r) for r in found]


class MemberRepository:
    ENTITY = "Member"
    PK = "id"

    def __init__(self, store):
        self._store = store


    def create_member(self, member: models.Member = None, email: str = None) -> models.Member:
        """Creates a new member entry with the provided details. [crud:create: STANDARD_CRUD]"""
        values = {}
        values.update(_record_values(member, ['id', 'name', 'email', 'membership_date', 'is_active']))
        if email is not None:
            values['email'] = email
        unknown = [k for k in values if k not in ['id', 'name', 'email', 'membership_date', 'is_active']]
        if unknown:
            raise ValueError(f"cannot create Member from {unknown}")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[])
        return models.Member(**record)

    def read_one_member(self, member_id: int = None) -> models.Member | None:
        """Reads a single member by its ID. [crud:read_one: STANDARD_CRUD]"""
        record = self._store.get(self.ENTITY, self.PK, member_id, error=errors.MemberNotFoundError)
        return models.Member(**record)

    def read_all_members(self) -> List[models.Member]:
        """Reads all members from the database. [crud:read_all: READ_ALL]"""
        criteria = []
        found = self._store.select(self.ENTITY, criteria)
        return [models.Member(**r) for r in found]

    def update_member(self, member_id: int = None, member: models.Member = None) -> models.Member:
        """Updates a member's details by its ID. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if member_id is not None:
            criteria.append(('id', 'eq', member_id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise errors.MemberNotFoundError(f"Member update matched {len(found)} records")
        patch = {}
        for key, value in _record_values(member, ['id', 'name', 'email', 'membership_date', 'is_active']).items():
            if value is not None:
                patch[key] = value
        if member_id is not None and 'member_id' in ['id', 'name', 'email', 'membership_date', 'is_active']:
            patch['member_id'] = member_id
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=errors.MemberNotFoundError)
        return models.Member(**record)

    def delete_member(self, member_id: int = None) -> bool:
        """Deletes a member by its ID. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if member_id is not None:
            criteria.append(('id', 'eq', member_id))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise errors.MemberNotFoundError(f"Member delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None

    def find_active_members(self) -> List[models.Member]:
        """Finds all active members. [FILTER_CRITERION via answered slots: criterion_field=is_active, criterion_value=True]"""
        criteria = [('is_active', 'eq', True)]
        found = self._store.select(self.ENTITY, criteria)
        return [models.Member(**record) for record in found]

    def find_inactive_members(self) -> List[models.Member]:
        """Finds all inactive members. [FILTER_CRITERION via answered slots: criterion_field=is_active, criterion_value=False]"""
        criteria = [('is_active', 'eq', False)]
        found = self._store.select(self.ENTITY, criteria)
        return [models.Member(**record) for record in found]


class LoanRepository:
    ENTITY = "Loan"
    PK = "id"

    def __init__(self, store):
        self._store = store


    def create_loan(self, loan: models.Loan = None) -> models.Loan:
        """Creates a new loan entry with the provided details. [crud:create: STANDARD_CRUD]"""
        values = _record_values(loan, ['id', 'book_id', 'member_id', 'loan_date', 'due_date', 'return_date', 'status'])
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[("book_id", "Book", "id", errors.BookNotFoundError), ("member_id", "Member", "id", errors.MemberNotFoundError)])
        return models.Loan(**record)

    def read_one_loan(self, loan_id: int = None) -> models.Loan | None:
        """Reads a single loan by its ID. [crud:read_one: STANDARD_CRUD]"""
        record = self._store.get(self.ENTITY, self.PK, loan_id, error=errors.LoanNotFoundError)
        return models.Loan(**record)

    def read_all_loans(self) -> List[models.Loan]:
        """Reads all loans from the database. [crud:read_all: READ_ALL]"""
        criteria = []
        found = self._store.select(self.ENTITY, criteria)
        return [models.Loan(**r) for r in found]

    def update_loan(self, loan_id: int = None, loan: models.Loan = None) -> models.Loan:
        """Updates a loan's details by its ID. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if loan_id is not None:
            criteria.append(('id', 'eq', loan_id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise errors.LoanNotFoundError(f"Loan update matched {len(found)} records")
        patch = {}
        for key, value in _record_values(loan, ['id', 'book_id', 'member_id', 'loan_date', 'due_date', 'return_date', 'status']).items():
            if value is not None:
                patch[key] = value
        if loan_id is not None and 'loan_id' in ['id', 'book_id', 'member_id', 'loan_date', 'due_date', 'return_date', 'status']:
            patch['loan_id'] = loan_id
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=errors.LoanNotFoundError)
        return models.Loan(**record)

    def delete_loan(self, loan_id: int = None) -> bool:
        """Deletes a loan by its ID. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if loan_id is not None:
            criteria.append(('id', 'eq', loan_id))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise errors.LoanNotFoundError(f"Loan delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None

    def get_active_loans(self) -> List[models.Loan]:
        """Finds all active loans. [FILTER_CRITERION via answered slots: criterion_field=status, criterion_value=active]"""
        criteria = [('status', 'eq', 'active')]
        found = self._store.select(self.ENTITY, criteria)
        return [models.Loan(**record) for record in found]

    def get_overdue_loans(self) -> List[models.Loan]:
        """Finds all overdue loans. [THRESHOLD_SCAN via answered slots: comparison_field=due_date, operator=<, threshold=today]"""
        bound = datetime.date.today().isoformat()
        out = []
        for record in self._store.select(self.ENTITY, []):
            key = str(record.get('due_date') or '')[:10]
            hit = key < str(bound)[:10]
            if hit:
                out.append(models.Loan(**record))
        return out

    def get_member_loan_history(self, member_id: int = None) -> List[models.Loan]:
        """Finds all loans for a specific member. [crud:filter: FILTER_BY_FIELD: by parameter shape]"""
        criteria = []
        if member_id is not None:
            criteria.append(('member_id', 'eq', member_id))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Loan(**r) for r in found]

    def get_book_loan_history(self, book_id: int = None) -> List[models.Loan]:
        """Finds all loans for a specific book. [crud:filter: FILTER_BY_FIELD: by parameter shape]"""
        criteria = []
        if book_id is not None:
            criteria.append(('book_id', 'eq', book_id))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Loan(**r) for r in found]
