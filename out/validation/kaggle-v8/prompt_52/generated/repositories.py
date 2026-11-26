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


    def read_all(self, title: str = None, author: str = None, isbn: str = None, available_status: bool = None) -> list[models.Book]:
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
        found = self._store.select(self.ENTITY, criteria)
        return [models.Book(**r) for r in found]

    def read_one(self, book_id: int = None) -> Any:
        """Reads one Book by its key. [crud:read_one: READ_ONE_BY_ID]"""
        record = self._store.get(self.ENTITY, self.PK, book_id, error=errors.BookNotFoundError)
        return models.Book(**record)

    def update(self, book_id: int = None, title: str = None, author: str = None, isbn: str = None, available_status: bool = None) -> Any:
        """Updates an existing Book. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if book_id is not None:
            criteria.append(('book_id', 'eq', book_id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise errors.BookNotFoundError(f"Book update matched {len(found)} records")
        patch = {}
        if book_id is not None and 'book_id' in ['book_id', 'title', 'author', 'isbn', 'available_status']:
            patch['book_id'] = book_id
        if title is not None and 'title' in ['book_id', 'title', 'author', 'isbn', 'available_status']:
            patch['title'] = title
        if author is not None and 'author' in ['book_id', 'title', 'author', 'isbn', 'available_status']:
            patch['author'] = author
        if isbn is not None and 'isbn' in ['book_id', 'title', 'author', 'isbn', 'available_status']:
            patch['isbn'] = isbn
        if available_status is not None and 'available_status' in ['book_id', 'title', 'author', 'isbn', 'available_status']:
            patch['available_status'] = available_status
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=errors.BookNotFoundError)
        return models.Book(**record)

    def search_books(self, title: str = None, author: str = None, isbn: str = None, available_status: bool = None) -> list[models.Book]:
        """Search books. [crud:filter: name-only: step F never saw this method]"""
        criteria = []
        if title is not None:
            criteria.append(('title', 'eq', title))
        if author is not None:
            criteria.append(('author', 'eq', author))
        if isbn is not None:
            criteria.append(('isbn', 'eq', isbn))
        if available_status is not None:
            criteria.append(('available_status', 'eq', available_status))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Book(**r) for r in found]


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

    def read_one(self, member_id: int = None) -> Any:
        """Reads one Member by its key. [crud:read_one: READ_ONE_BY_ID]"""
        record = self._store.get(self.ENTITY, self.PK, member_id, error=errors.MemberNotFoundError)
        return models.Member(**record)

    def create(self, name: str = None, email: str = None) -> Any:
        """Creates a new Member. [crud:create: STANDARD_CRUD]"""
        values = {}
        if name is not None:
            values['name'] = name
        if email is not None:
            values['email'] = email
        unknown = [k for k in values if k not in ['member_id', 'name', 'email']]
        if unknown:
            raise ValueError(f"cannot create Member from {unknown}")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[])
        return models.Member(**record)

    def search_members(self, name: str = None, email: str = None) -> list[models.Member]:
        """Search members. [crud:filter: name-only: step F never saw this method]"""
        criteria = []
        if name is not None:
            criteria.append(('name', 'eq', name))
        if email is not None:
            criteria.append(('email', 'eq', email))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Member(**r) for r in found]

    def update(self, member_id: int = None, name: str = None, email: str = None) -> models.Member:
        """Updates an existing Member. [crud:update: name-only: step F never saw this method]"""
        criteria = []
        if member_id is not None:
            criteria.append(('member_id', 'eq', member_id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise errors.MemberNotFoundError(f"Member update matched {len(found)} records")
        patch = {}
        if member_id is not None and 'member_id' in ['member_id', 'name', 'email']:
            patch['member_id'] = member_id
        if name is not None and 'name' in ['member_id', 'name', 'email']:
            patch['name'] = name
        if email is not None and 'email' in ['member_id', 'name', 'email']:
            patch['email'] = email
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=errors.MemberNotFoundError)
        return models.Member(**record)


class BorrowRecordRepository:
    ENTITY = "BorrowRecord"
    PK = "borrow_id"

    def __init__(self, store):
        self._store = store


    def create(self, book_id: int = None, member_id: int = None, borrow_date: Any = None, return_date: Any = None, is_returned: bool = None) -> Any:
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
        if is_returned is not None:
            values['is_returned'] = is_returned
        unknown = [k for k in values if k not in ['borrow_id', 'book_id', 'member_id', 'borrow_date', 'return_date', 'is_returned']]
        if unknown:
            raise ValueError(f"cannot create BorrowRecord from {unknown}")
        if values.get('is_returned') is None:
            values['is_returned'] = False
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[("book_id", "Book", "book_id", errors.BookNotFoundError), ("member_id", "Member", "member_id", errors.MemberNotFoundError)])
        return models.BorrowRecord(**record)

    def read_all(self, book_id: int = None, member_id: int = None, borrow_date: Any = None, return_date: Any = None, is_returned: bool = None) -> list[models.BorrowRecord]:
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
        if is_returned is not None:
            criteria.append(('is_returned', 'eq', is_returned))
        found = self._store.select(self.ENTITY, criteria)
        return [models.BorrowRecord(**r) for r in found]

    def update(self, borrow_id: int = None, book_id: int = None, member_id: int = None, borrow_date: Any = None, return_date: Any = None, is_returned: bool = None) -> Any:
        """Updates an existing BorrowRecord. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if borrow_id is not None:
            criteria.append(('borrow_id', 'eq', borrow_id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise errors.BorrowRecordNotFoundError(f"BorrowRecord update matched {len(found)} records")
        patch = {}
        if borrow_id is not None and 'borrow_id' in ['borrow_id', 'book_id', 'member_id', 'borrow_date', 'return_date', 'is_returned']:
            patch['borrow_id'] = borrow_id
        if book_id is not None and 'book_id' in ['borrow_id', 'book_id', 'member_id', 'borrow_date', 'return_date', 'is_returned']:
            patch['book_id'] = book_id
        if member_id is not None and 'member_id' in ['borrow_id', 'book_id', 'member_id', 'borrow_date', 'return_date', 'is_returned']:
            patch['member_id'] = member_id
        if borrow_date is not None and 'borrow_date' in ['borrow_id', 'book_id', 'member_id', 'borrow_date', 'return_date', 'is_returned']:
            patch['borrow_date'] = borrow_date
        if return_date is not None and 'return_date' in ['borrow_id', 'book_id', 'member_id', 'borrow_date', 'return_date', 'is_returned']:
            patch['return_date'] = return_date
        if is_returned is not None and 'is_returned' in ['borrow_id', 'book_id', 'member_id', 'borrow_date', 'return_date', 'is_returned']:
            patch['is_returned'] = is_returned
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=errors.BorrowRecordNotFoundError)
        return models.BorrowRecord(**record)

    def get_borrow_records_by_book_id(self, book_id: int = None) -> list[models.BorrowRecord]:
        """Lists the BorrowRecord records belonging to one Book. [crud:filter: FILTER_BY_FIELD: by parameter shape]"""
        criteria = []
        if book_id is not None:
            criteria.append(('book_id', 'eq', book_id))
        found = self._store.select(self.ENTITY, criteria)
        return [models.BorrowRecord(**r) for r in found]
