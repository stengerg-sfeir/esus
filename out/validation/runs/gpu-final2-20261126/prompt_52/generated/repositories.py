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



class BookRepository:
    ENTITY = "Book"
    PK = "book_id"

    def __init__(self, store):
        self._store = store


    def borrow_book(self, book_id: int = None, member_id: int = None) -> None:
        """Borrows a Book. [mechanical named state update]"""
        record = self._store.get('Book', 'book_id', book_id)
        if record is None:
            return None
        self._store.update('Book', 'book_id', record.get('book_id'), {'available_status': False})
        return None

    def read_all(self, title: str = None, author: str = None, isbn: str = None, available_status: bool = None, borrow_status: str = None) -> list[models.Book]:
        """Lists every Book; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if title is not None:
            criteria.append(('title', 'eq', title))
        if author is not None:
            criteria.append(('author', 'eq', author))
        if isbn is not None:
            criteria.append(('isbn', 'eq', isbn))
        if available_status is not None:
            criteria.append(('available_status', 'eq', available_status))
        if borrow_status is not None:
            criteria.append(('borrow_status', 'eq', borrow_status))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Book(**r) for r in found]

    def read_all_available(self) -> list[models.Book]:
        """Returns a list of all books that are currently available (not currently borrowed). [mechanical boolean filter]"""
        return _model_list(self._store.select(self.ENTITY, [('available_status', 'eq', True)]), models.Book)

    def read_one(self, book_id: int = None) -> models.Book:
        """Reads one Book by its key. [crud:read_one: READ_ONE_BY_ID]"""
        record = self._store.get(self.ENTITY, self.PK, book_id, error=errors.BookNotFoundError)
        return models.Book(**record)

    def read_one_by_title(self, title: str = None) -> models.Book | None:
        """Fetches a book by its title, returning the book entity if found, otherwise null. [crud:read_one: READ_ONE_BY_ID]"""
        criteria = []
        if title is not None:
            criteria.append(('title', 'eq', title))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise errors.BookNotFoundError(f"Book lookup matched {len(found)} records")
        record = found[0]
        return models.Book(**record)

    def update(self, book_id: int = None, title: str = None, author: str = None, isbn: str = None, available_status: bool = None, borrow_status: str = None) -> models.Book:
        """Updates an existing Book. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if book_id is not None:
            criteria.append(('book_id', 'eq', book_id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise errors.BookNotFoundError(f"Book update matched {len(found)} records")
        patch = {}
        if book_id is not None and 'book_id' in ['book_id', 'title', 'author', 'isbn', 'available_status', 'borrow_status']:
            patch['book_id'] = book_id
        if title is not None and 'title' in ['book_id', 'title', 'author', 'isbn', 'available_status', 'borrow_status']:
            patch['title'] = title
        if author is not None and 'author' in ['book_id', 'title', 'author', 'isbn', 'available_status', 'borrow_status']:
            patch['author'] = author
        if isbn is not None and 'isbn' in ['book_id', 'title', 'author', 'isbn', 'available_status', 'borrow_status']:
            patch['isbn'] = isbn
        if available_status is not None and 'available_status' in ['book_id', 'title', 'author', 'isbn', 'available_status', 'borrow_status']:
            patch['available_status'] = available_status
        if borrow_status is not None and 'borrow_status' in ['book_id', 'title', 'author', 'isbn', 'available_status', 'borrow_status']:
            patch['borrow_status'] = borrow_status
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=errors.BookNotFoundError)
        return models.Book(**record)


class BorrowRecordRepository:
    ENTITY = "BorrowRecord"
    PK = "borrow_id"

    def __init__(self, store):
        self._store = store


    def create(self, book_id: int = None, member_id: int = None, borrow_date: Any = None, return_date: Any = None) -> models.BorrowRecord:
        """Creates a new BorrowRecord. [crud:create: STANDARD_CRUD]"""
        values = {}
        if book_id is not None:
            values['book_id'] = book_id
        if member_id is not None:
            values['member_id'] = member_id
        if borrow_date is not None:
            values['borrow_date'] = borrow_date
        if return_date is not None:
            values['return_date'] = return_date
        unknown = [k for k in values if k not in ['borrow_id', 'book_id', 'member_id', 'borrow_date', 'return_date']]
        if unknown:
            raise ValueError(f"cannot create BorrowRecord from {unknown}")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[("book_id", "Book", "book_id", errors.BookNotFoundError), ("member_id", "Member", "member_id", errors.MemberNotFoundError)])
        return models.BorrowRecord(**record)

    def create_borrow_record(self, book_id: int = None, member_id: int = None, borrow_date: datetime.datetime = None, return_date: datetime.datetime | None = None) -> models.BorrowRecord:
        """Creates a new borrow record linking a book to a member with a borrow date. Returns the created record if successful. [crud:create: STANDARD_CRUD]"""
        values = {}
        if book_id is not None:
            values['book_id'] = book_id
        if member_id is not None:
            values['member_id'] = member_id
        if borrow_date is not None:
            values['borrow_date'] = borrow_date
        if return_date is not None:
            values['return_date'] = return_date
        unknown = [k for k in values if k not in ['borrow_id', 'book_id', 'member_id', 'borrow_date', 'return_date']]
        if unknown:
            raise ValueError(f"cannot create BorrowRecord from {unknown}")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[("book_id", "Book", "book_id", errors.BookNotFoundError), ("member_id", "Member", "member_id", errors.MemberNotFoundError)])
        return models.BorrowRecord(**record)

    def delete(self, borrow_id: int = None, book_id: int = None, member_id: int = None, borrow_date: Any = None, return_date: Any = None) -> None:
        """Deletes an existing BorrowRecord. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if borrow_id is not None:
            criteria.append(('borrow_id', 'eq', borrow_id))
        if book_id is not None:
            criteria.append(('book_id', 'eq', book_id))
        if member_id is not None:
            criteria.append(('member_id', 'eq', member_id))
        if borrow_date is not None:
            criteria.append(('borrow_date', 'eq', borrow_date))
        if return_date is not None:
            criteria.append(('return_date', 'eq', return_date))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise errors.BorrowRecordNotFoundError(f"BorrowRecord delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None

    def get_borrow_records_by_book_id(self, book_id: int = None) -> list[models.BorrowRecord]:
        """Lists the BorrowRecord records belonging to one Book. [mechanical contained-name filter]"""
        criteria = []
        if book_id is not None:
            criteria.append(('book_id', 'eq', book_id))
        found = self._store.select(self.ENTITY, criteria)
        return _model_list([models.BorrowRecord(**row) for row in found], models.BorrowRecord)

    def read_all(self, book_id: int = None, member_id: int = None, borrow_date: Any = None, return_date: Any = None) -> list[models.BorrowRecord]:
        """Lists every BorrowRecord; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if book_id is not None:
            criteria.append(('book_id', 'eq', book_id))
        if member_id is not None:
            criteria.append(('member_id', 'eq', member_id))
        if borrow_date is not None:
            criteria.append(('borrow_date', 'eq', borrow_date))
        if return_date is not None:
            criteria.append(('return_date', 'eq', return_date))
        found = self._store.select(self.ENTITY, criteria)
        return [models.BorrowRecord(**r) for r in found]

    def read_all_borrow_records_by_member(self, member_id: int = None) -> list[models.BorrowRecord]:
        """Returns all borrow records for a specific member, including both borrowed and returned books. [mechanical contained-name filter]"""
        criteria = []
        if member_id is not None:
            criteria.append(('member_id', 'eq', member_id))
        found = self._store.select(self.ENTITY, criteria)
        return _model_list([models.BorrowRecord(**row) for row in found], models.BorrowRecord)

    def read_one(self, borrow_id: int = None) -> models.BorrowRecord:
        """Reads one BorrowRecord by its key. [crud:read_one: READ_ONE_BY_ID]"""
        record = self._store.get(self.ENTITY, self.PK, borrow_id, error=errors.BorrowRecordNotFoundError)
        return models.BorrowRecord(**record)

    def read_one_by_borrow_id(self, borrow_id: int = None) -> models.BorrowRecord | None:
        """Fetches a borrow record by its borrow_id, returning the record if found, otherwise null. [crud:read_one: READ_ONE_BY_ID]"""
        record = self._store.get(self.ENTITY, self.PK, borrow_id, error=errors.BorrowRecordNotFoundError)
        return models.BorrowRecord(**record)

    def update(self, borrow_id: int = None, book_id: int = None, member_id: int = None, borrow_date: Any = None, return_date: Any = None) -> models.BorrowRecord:
        """Updates an existing BorrowRecord. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if borrow_id is not None:
            criteria.append(('borrow_id', 'eq', borrow_id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise errors.BorrowRecordNotFoundError(f"BorrowRecord update matched {len(found)} records")
        patch = {}
        if borrow_id is not None and 'borrow_id' in ['borrow_id', 'book_id', 'member_id', 'borrow_date', 'return_date']:
            patch['borrow_id'] = borrow_id
        if book_id is not None and 'book_id' in ['borrow_id', 'book_id', 'member_id', 'borrow_date', 'return_date']:
            patch['book_id'] = book_id
        if member_id is not None and 'member_id' in ['borrow_id', 'book_id', 'member_id', 'borrow_date', 'return_date']:
            patch['member_id'] = member_id
        if borrow_date is not None and 'borrow_date' in ['borrow_id', 'book_id', 'member_id', 'borrow_date', 'return_date']:
            patch['borrow_date'] = borrow_date
        if return_date is not None and 'return_date' in ['borrow_id', 'book_id', 'member_id', 'borrow_date', 'return_date']:
            patch['return_date'] = return_date
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=errors.BorrowRecordNotFoundError)
        return models.BorrowRecord(**record)

    def update_return_date(self, borrow_id: int = None, return_date: datetime.datetime = None) -> models.BorrowRecord:
        """Updates the return date of a borrow record to indicate the book has been returned. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if borrow_id is not None:
            criteria.append(('borrow_id', 'eq', borrow_id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise errors.BorrowRecordNotFoundError(f"BorrowRecord update matched {len(found)} records")
        patch = {}
        if borrow_id is not None and 'borrow_id' in ['borrow_id', 'book_id', 'member_id', 'borrow_date', 'return_date']:
            patch['borrow_id'] = borrow_id
        if return_date is not None and 'return_date' in ['borrow_id', 'book_id', 'member_id', 'borrow_date', 'return_date']:
            patch['return_date'] = return_date
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=errors.BorrowRecordNotFoundError)
        return models.BorrowRecord(**record)


class MemberRepository:
    ENTITY = "Member"
    PK = "member_id"

    def __init__(self, store):
        self._store = store


    def read_all(self, name: str = None, email: str = None) -> list[models.Member]:
        """Lists every Member; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if name is not None:
            criteria.append(('name', 'eq', name))
        if email is not None:
            criteria.append(('email', 'eq', email))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Member(**r) for r in found]

    def read_one(self, member_id: int = None) -> models.Member:
        """Reads one Member by its key. [crud:read_one: READ_ONE_BY_ID]"""
        record = self._store.get(self.ENTITY, self.PK, member_id, error=errors.MemberNotFoundError)
        return models.Member(**record)

    def read_one_by_email(self, email: str = None) -> models.Member | None:
        """Fetches a member by their email address, returning the member entity if found, otherwise null. [crud:read_one: READ_ONE_BY_ID]"""
        criteria = []
        if email is not None:
            criteria.append(('email', 'eq', email))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise errors.MemberNotFoundError(f"Member lookup matched {len(found)} records")
        record = found[0]
        return models.Member(**record)
