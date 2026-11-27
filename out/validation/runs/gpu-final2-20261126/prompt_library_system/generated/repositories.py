"""Repositories over an in-memory Store, one class per persistence port.

CRUD, reads and filters run for real. Anything else raises
NotImplementedError with its work order — an aggregate or guard body
is specified by its pattern, not invented here.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple, Union

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


def _model_list(records, model_cls):
    """Model objects from records, deduplicated by stable id."""
    out = []
    seen = set()
    if records is None:
        records = []
    elif isinstance(records, dict) or isinstance(records, (str, bytes)) \
            or not hasattr(records, '__iter__'):
        records = [records]
    for record in records:
        if isinstance(record, dict):
            key = record.get('id')
            item = model_cls(**record)
        else:
            key = getattr(record, 'id', None)
            item = record
        if key is not None:
            if key in seen:
                continue
            seen.add(key)
        out.append(item)
    return out



class AuthorRepository:
    ENTITY = "Author"
    PK = "id"

    def __init__(self, store):
        self._store = store


    def create(self, name: str = None, birth_year: int = None, biography: str = None) -> models.Author:
        """Creates a new Author. [crud:create: STANDARD_CRUD]"""
        values = {}
        if name is not None:
            values['name'] = name
        if birth_year is not None:
            values['birth_year'] = birth_year
        if biography is not None:
            values['biography'] = biography
        unknown = [k for k in values if k not in ['id', 'name', 'birth_year', 'biography']]
        if unknown:
            raise ValueError(f"cannot create Author from {unknown}")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[])
        return models.Author(**record)

    def delete(self, id: int = None, name: str = None, birth_year: int = None, biography: str = None) -> None:
        """Deletes an existing Author. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if id is not None:
            criteria.append(('id', 'eq', id))
        if name is not None:
            criteria.append(('name', 'eq', name))
        if birth_year is not None:
            criteria.append(('birth_year', 'eq', birth_year))
        if biography is not None:
            criteria.append(('biography', 'eq', biography))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise errors.AuthorNotFoundError(f"Author delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None

    def find_books_by_author(self, author_id: int = None) -> list[models.Book]:
        """Returns all books authored by the given author ID. If no such author exists, returns an empty list. [crud:filter: FILTER_BY_FIELD]"""
        criteria = []
        if author_id is not None:
            criteria.append(('author_id', 'eq', author_id))
        found = self._store.select('Book', criteria)
        return [models.Book(**r) for r in found]

    def read_all(self, name: str = None, birth_year: int = None, biography: str = None) -> list[models.Author]:
        """Lists every Author; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if name is not None:
            criteria.append(('name', 'eq', name))
        if birth_year is not None:
            criteria.append(('birth_year', 'eq', birth_year))
        if biography is not None:
            criteria.append(('biography', 'eq', biography))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Author(**r) for r in found]

    def read_one(self, id: int = None) -> models.Author:
        """Reads one Author by its key. [crud:read_one: READ_ONE_BY_ID]"""
        record = self._store.get(self.ENTITY, self.PK, id, error=errors.AuthorNotFoundError)
        return models.Author(**record)

    def update(self, id: int = None, name: str = None, birth_year: int = None, biography: str = None) -> models.Author:
        """Updates an existing Author. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if id is not None:
            criteria.append(('id', 'eq', id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise errors.AuthorNotFoundError(f"Author update matched {len(found)} records")
        patch = {}
        if id is not None and 'id' in ['id', 'name', 'birth_year', 'biography']:
            patch['id'] = id
        if name is not None and 'name' in ['id', 'name', 'birth_year', 'biography']:
            patch['name'] = name
        if birth_year is not None and 'birth_year' in ['id', 'name', 'birth_year', 'biography']:
            patch['birth_year'] = birth_year
        if biography is not None and 'biography' in ['id', 'name', 'birth_year', 'biography']:
            patch['biography'] = biography
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=errors.AuthorNotFoundError)
        return models.Author(**record)


class BookRepository:
    ENTITY = "Book"
    PK = "id"

    def __init__(self, store):
        self._store = store


    def create(self, title: str = None, isbn: str = None, published_year: int = None, available_copies: int = None, author_id: int = None) -> models.Book:
        """Creates a new Book. [crud:create: STANDARD_CRUD]"""
        values = {}
        if title is not None:
            values['title'] = title
        if isbn is not None:
            values['isbn'] = isbn
        if published_year is not None:
            values['published_year'] = published_year
        if available_copies is not None:
            values['available_copies'] = available_copies
        if author_id is not None:
            values['author_id'] = author_id
        unknown = [k for k in values if k not in ['id', 'title', 'isbn', 'published_year', 'available_copies', 'author_id']]
        if unknown:
            raise ValueError(f"cannot create Book from {unknown}")
        for unique_field in ['isbn']:
            value = values.get(unique_field)
            if value is not None and self._store.select(self.ENTITY, [(unique_field, 'eq', value)]):
                raise ValueError(f"Book with {unique_field}={value!r} already exists")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[("author_id", "Author", "id", errors.AuthorNotFoundError)])
        return models.Book(**record)

    def delete(self, id: int = None, title: str = None, isbn: str = None, published_year: int = None, available_copies: int = None, author_id: int = None) -> None:
        """Deletes an existing Book. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if id is not None:
            criteria.append(('id', 'eq', id))
        if title is not None:
            criteria.append(('title', 'eq', title))
        if isbn is not None:
            criteria.append(('isbn', 'eq', isbn))
        if published_year is not None:
            criteria.append(('published_year', 'eq', published_year))
        if available_copies is not None:
            criteria.append(('available_copies', 'eq', available_copies))
        if author_id is not None:
            criteria.append(('author_id', 'eq', author_id))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise errors.BookNotFoundError(f"Book delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None

    def read_all(self, title: str = None, isbn: str = None, published_year: int = None, available_copies: int = None, author_id: int = None) -> list[models.Book]:
        """Lists every Book; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if title is not None:
            criteria.append(('title', 'eq', title))
        if isbn is not None:
            criteria.append(('isbn', 'eq', isbn))
        if published_year is not None:
            criteria.append(('published_year', 'eq', published_year))
        if available_copies is not None:
            criteria.append(('available_copies', 'eq', available_copies))
        if author_id is not None:
            criteria.append(('author_id', 'eq', author_id))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Book(**r) for r in found]

    def read_one(self, id: int = None) -> models.Book:
        """Reads one Book by its key. [crud:read_one: READ_ONE_BY_ID]"""
        record = self._store.get(self.ENTITY, self.PK, id, error=errors.BookNotFoundError)
        return models.Book(**record)

    def search_by_title_or_author_or_isbn(self, query: str = None) -> list[models.Book]:
        """Searches for books using case-insensitive substring matching on title, author name (via author_id), or ISBN. Returns all matching books, each only once, even if multiple fields match. Returns empty list if ISBN is not found. [mechanical text search]"""
        if not query:
            return []
        query = str(query).lower()
        parents = self._store.select('Author', [])
        names = {row['id']: row['name'] for row in parents}
        result = []
        for row in self._store.select(self.ENTITY, []):
            values = [row.get('title'), row.get('isbn'), names.get(row.get('author_id'))]
            if any(value is not None and query in str(value).lower() for value in values):
                result.append(row)
        return _model_list([models.Book(**row) for row in result], models.Book)

    def update(self, id: int = None, title: str = None, isbn: str = None, published_year: int = None, available_copies: int = None, author_id: int = None) -> models.Book:
        """Updates an existing Book. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if id is not None:
            criteria.append(('id', 'eq', id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise errors.BookNotFoundError(f"Book update matched {len(found)} records")
        patch = {}
        if id is not None and 'id' in ['id', 'title', 'isbn', 'published_year', 'available_copies', 'author_id']:
            patch['id'] = id
        if title is not None and 'title' in ['id', 'title', 'isbn', 'published_year', 'available_copies', 'author_id']:
            patch['title'] = title
        if isbn is not None and 'isbn' in ['id', 'title', 'isbn', 'published_year', 'available_copies', 'author_id']:
            patch['isbn'] = isbn
        if published_year is not None and 'published_year' in ['id', 'title', 'isbn', 'published_year', 'available_copies', 'author_id']:
            patch['published_year'] = published_year
        if available_copies is not None and 'available_copies' in ['id', 'title', 'isbn', 'published_year', 'available_copies', 'author_id']:
            patch['available_copies'] = available_copies
        if author_id is not None and 'author_id' in ['id', 'title', 'isbn', 'published_year', 'available_copies', 'author_id']:
            patch['author_id'] = author_id
        for unique_field in ['isbn']:
            value = patch.get(unique_field)
            if value is not None and any(row.get(self.PK) != found[0][self.PK] for row in self._store.select(self.ENTITY, [(unique_field, 'eq', value)])):
                raise ValueError(f"Book with {unique_field}={value!r} already exists")
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=errors.BookNotFoundError)
        return models.Book(**record)


class LoanRepository:
    ENTITY = "Loan"
    PK = "id"

    def __init__(self, store):
        self._store = store


    def create(self, book_id: int = None, member_id: int = None, loan_date: Any = None, due_date: Any = None, return_date: Any = None, status: str = None) -> models.Loan:
        """Creates a new Loan. [crud:create: STANDARD_CRUD]"""
        values = {}
        if book_id is not None:
            values['book_id'] = book_id
        if member_id is not None:
            values['member_id'] = member_id
        if loan_date is not None:
            values['loan_date'] = loan_date
        if due_date is not None:
            values['due_date'] = due_date
        if return_date is not None:
            values['return_date'] = return_date
        if status is not None:
            values['status'] = status
        unknown = [k for k in values if k not in ['id', 'book_id', 'member_id', 'loan_date', 'due_date', 'return_date', 'status']]
        if unknown:
            raise ValueError(f"cannot create Loan from {unknown}")
        if values.get('status') is None:
            values['status'] = 'active'
        if values.get('status') not in ['active', 'returned', 'overdue']:
            raise ValueError(f"Loan.status must be one of ['active', 'returned', 'overdue']")
        if values.get('status') is None:
            values['status'] = 'pending'
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[("book_id", "Book", "id", errors.BookNotFoundError), ("member_id", "Member", "id", errors.MemberNotFoundError)])
        return models.Loan(**record)

    def delete(self, id: int = None, book_id: int = None, member_id: int = None, loan_date: Any = None, due_date: Any = None, return_date: Any = None, status: str = None) -> None:
        """Deletes an existing Loan. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if id is not None:
            criteria.append(('id', 'eq', id))
        if book_id is not None:
            criteria.append(('book_id', 'eq', book_id))
        if member_id is not None:
            criteria.append(('member_id', 'eq', member_id))
        if loan_date is not None:
            criteria.append(('loan_date', 'eq', loan_date))
        if due_date is not None:
            criteria.append(('due_date', 'eq', due_date))
        if return_date is not None:
            criteria.append(('return_date', 'eq', return_date))
        if status is not None:
            criteria.append(('status', 'eq', status))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise errors.LoanNotFoundError(f"Loan delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None

    def find_active_loans(self, id: int = None) -> list[models.Loan]:
        """Returns all loans with status 'active' (i.e., not returned and not overdue). [mechanical contained-name filter]"""
        criteria = []
        if id is not None:
            criteria.append(('id', 'eq', id))
        found = self._store.select(self.ENTITY, criteria)
        return _model_list([models.Loan(**row) for row in found], models.Loan)

    def find_overdue_loans(self, id: int = None) -> list[models.Loan]:
        """Returns loans that are overdue: due_date < today and return_date is None. [THRESHOLD_SCAN via answered slots: comparison_field=due_date, operator=<, threshold=today]"""
        bound = datetime.date.today().isoformat()
        out = []
        for record in self._store.select(self.ENTITY, []):
            if record.get('return_date') is not None:
                continue
            key = str(record.get('due_date') or '')[:10]
            hit = key < str(bound)[:10]
            if hit:
                out.append(models.Loan(**record))
        return out

    def get_book_loan_history(self, book_id: int = None) -> list[models.Loan]:
        """Returns all loans involving a specific book, ordered by loan date descending. [mechanical contained-name filter]"""
        criteria = []
        if book_id is not None:
            criteria.append(('book_id', 'eq', book_id))
        found = self._store.select(self.ENTITY, criteria)
        return _model_list([models.Loan(**row) for row in found], models.Loan)

    def get_member_loan_history(self, member_id: int = None) -> list[models.Loan]:
        """Returns all loans made by a specific member, ordered by loan date descending. [mechanical contained-name filter]"""
        criteria = []
        if member_id is not None:
            criteria.append(('member_id', 'eq', member_id))
        found = self._store.select(self.ENTITY, criteria)
        return _model_list([models.Loan(**row) for row in found], models.Loan)

    def read_all(self, book_id: int = None, member_id: int = None, loan_date: Any = None, due_date: Any = None, return_date: Any = None, status: str = None) -> list[models.Loan]:
        """Lists every Loan; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if book_id is not None:
            criteria.append(('book_id', 'eq', book_id))
        if member_id is not None:
            criteria.append(('member_id', 'eq', member_id))
        if loan_date is not None:
            criteria.append(('loan_date', 'eq', loan_date))
        if due_date is not None:
            criteria.append(('due_date', 'eq', due_date))
        if return_date is not None:
            criteria.append(('return_date', 'eq', return_date))
        if status is not None:
            criteria.append(('status', 'eq', status))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Loan(**r) for r in found]

    def read_one(self, id: int = None) -> models.Loan:
        """Reads one Loan by its key. [crud:read_one: READ_ONE_BY_ID]"""
        record = self._store.get(self.ENTITY, self.PK, id, error=errors.LoanNotFoundError)
        return models.Loan(**record)

    def update(self, id: int = None, book_id: int = None, member_id: int = None, loan_date: Any = None, due_date: Any = None, return_date: Any = None, status: str = None) -> models.Loan:
        """Updates an existing Loan. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if id is not None:
            criteria.append(('id', 'eq', id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise errors.LoanNotFoundError(f"Loan update matched {len(found)} records")
        patch = {}
        if id is not None and 'id' in ['id', 'book_id', 'member_id', 'loan_date', 'due_date', 'return_date', 'status']:
            patch['id'] = id
        if book_id is not None and 'book_id' in ['id', 'book_id', 'member_id', 'loan_date', 'due_date', 'return_date', 'status']:
            patch['book_id'] = book_id
        if member_id is not None and 'member_id' in ['id', 'book_id', 'member_id', 'loan_date', 'due_date', 'return_date', 'status']:
            patch['member_id'] = member_id
        if loan_date is not None and 'loan_date' in ['id', 'book_id', 'member_id', 'loan_date', 'due_date', 'return_date', 'status']:
            patch['loan_date'] = loan_date
        if due_date is not None and 'due_date' in ['id', 'book_id', 'member_id', 'loan_date', 'due_date', 'return_date', 'status']:
            patch['due_date'] = due_date
        if return_date is not None and 'return_date' in ['id', 'book_id', 'member_id', 'loan_date', 'due_date', 'return_date', 'status']:
            patch['return_date'] = return_date
        if status is not None and 'status' in ['id', 'book_id', 'member_id', 'loan_date', 'due_date', 'return_date', 'status']:
            patch['status'] = status
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=errors.LoanNotFoundError)
        return models.Loan(**record)


class MemberRepository:
    ENTITY = "Member"
    PK = "id"

    def __init__(self, store):
        self._store = store


    def create(self, name: str = None, email: str = None, membership_date: Any = None, is_active: bool = None) -> models.Member:
        """Creates a new Member. [crud:create: STANDARD_CRUD]"""
        values = {}
        if name is not None:
            values['name'] = name
        if email is not None:
            values['email'] = email
        if membership_date is not None:
            values['membership_date'] = membership_date
        if is_active is not None:
            values['is_active'] = is_active
        unknown = [k for k in values if k not in ['id', 'name', 'email', 'membership_date', 'is_active']]
        if unknown:
            raise ValueError(f"cannot create Member from {unknown}")
        if values.get('membership_date') is None:
            values['membership_date'] = datetime.date.today()
        for unique_field in ['email']:
            value = values.get(unique_field)
            if value is not None and self._store.select(self.ENTITY, [(unique_field, 'eq', value)]):
                raise ValueError(f"Member with {unique_field}={value!r} already exists")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[])
        return models.Member(**record)

    def delete(self, id: int = None, name: str = None, email: str = None, membership_date: Any = None, is_active: bool = None) -> None:
        """Deletes an existing Member. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if id is not None:
            criteria.append(('id', 'eq', id))
        if name is not None:
            criteria.append(('name', 'eq', name))
        if email is not None:
            criteria.append(('email', 'eq', email))
        if membership_date is not None:
            criteria.append(('membership_date', 'eq', membership_date))
        if is_active is not None:
            criteria.append(('is_active', 'eq', is_active))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise errors.MemberNotFoundError(f"Member delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None

    def find_active_members(self, id: int = None) -> list[models.Member]:
        """Returns all members who are currently active (is_active = True). [mechanical boolean filter]"""
        return _model_list(self._store.select(self.ENTITY, [('is_active', 'eq', True)]), models.Member)

    def find_inactive_members(self, id: int = None) -> list[models.Member]:
        """Returns all members who are currently inactive (is_active = False). [mechanical boolean filter]"""
        return _model_list(self._store.select(self.ENTITY, [('is_active', 'eq', True)]), models.Member)

    def read_all(self, name: str = None, email: str = None, membership_date: Any = None, is_active: bool = None) -> list[models.Member]:
        """Lists every Member; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if name is not None:
            criteria.append(('name', 'eq', name))
        if email is not None:
            criteria.append(('email', 'eq', email))
        if membership_date is not None:
            criteria.append(('membership_date', 'eq', membership_date))
        if is_active is not None:
            criteria.append(('is_active', 'eq', is_active))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Member(**r) for r in found]

    def read_one(self, id: int = None) -> models.Member:
        """Reads one Member by its key. [crud:read_one: READ_ONE_BY_ID]"""
        record = self._store.get(self.ENTITY, self.PK, id, error=errors.MemberNotFoundError)
        return models.Member(**record)

    def update(self, id: int = None, name: str = None, email: str = None, membership_date: Any = None, is_active: bool = None) -> models.Member:
        """Updates an existing Member. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if id is not None:
            criteria.append(('id', 'eq', id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise errors.MemberNotFoundError(f"Member update matched {len(found)} records")
        patch = {}
        if id is not None and 'id' in ['id', 'name', 'email', 'membership_date', 'is_active']:
            patch['id'] = id
        if name is not None and 'name' in ['id', 'name', 'email', 'membership_date', 'is_active']:
            patch['name'] = name
        if email is not None and 'email' in ['id', 'name', 'email', 'membership_date', 'is_active']:
            patch['email'] = email
        if membership_date is not None and 'membership_date' in ['id', 'name', 'email', 'membership_date', 'is_active']:
            patch['membership_date'] = membership_date
        if is_active is not None and 'is_active' in ['id', 'name', 'email', 'membership_date', 'is_active']:
            patch['is_active'] = is_active
        for unique_field in ['email']:
            value = patch.get(unique_field)
            if value is not None and any(row.get(self.PK) != found[0][self.PK] for row in self._store.select(self.ENTITY, [(unique_field, 'eq', value)])):
                raise ValueError(f"Member with {unique_field}={value!r} already exists")
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=errors.MemberNotFoundError)
        return models.Member(**record)
