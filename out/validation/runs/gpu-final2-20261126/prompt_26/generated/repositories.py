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
    PK = "id"

    def __init__(self, store):
        self._store = store


    def create(self, title: str = None, isbn: str = None, available: bool = None) -> Any:
        """Creates a new Book. [crud:create: STANDARD_CRUD]"""
        values = {}
        if title is not None:
            values['title'] = title
        if isbn is not None:
            values['isbn'] = isbn
        if available is not None:
            values['available'] = available
        unknown = [k for k in values if k not in ['id', 'title', 'isbn', 'available']]
        if unknown:
            raise ValueError(f"cannot create Book from {unknown}")
        if values.get('available') is None:
            values['available'] = False
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[])
        return models.Book(**record)

    def read_all(self, title: str = None, isbn: str = None, available: bool = None) -> list[models.Book]:
        """Lists every Book; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if title is not None:
            criteria.append(('title', 'eq', title))
        if isbn is not None:
            criteria.append(('isbn', 'eq', isbn))
        if available is not None:
            criteria.append(('available', 'eq', available))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Book(**r) for r in found]

    def read_one(self, id: int = None) -> Any:
        """Reads one Book by its key. [crud:read_one: READ_ONE_BY_ID]"""
        record = self._store.get(self.ENTITY, self.PK, id, error=errors.BookNotFoundError)
        return models.Book(**record)

    def read_all_available(self) -> List[models.Book]:
        """Returns a list of all books that are currently available (not currently loaned out). [mechanical boolean filter]"""
        return _model_list(self._store.select(self.ENTITY, [('available', 'eq', True)]), models.Book)


class MemberRepository:
    ENTITY = "Member"
    PK = "id"

    def __init__(self, store):
        self._store = store


    def create(self, name: str = None, email: str = None) -> Any:
        """Creates a new Member. [crud:create: STANDARD_CRUD]"""
        values = {}
        if name is not None:
            values['name'] = name
        if email is not None:
            values['email'] = email
        unknown = [k for k in values if k not in ['id', 'name', 'email']]
        if unknown:
            raise ValueError(f"cannot create Member from {unknown}")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[])
        return models.Member(**record)

    def read_all(self, name: str = None, email: str = None) -> list[models.Member]:
        """Lists every Member; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if name is not None:
            criteria.append(('name', 'eq', name))
        if email is not None:
            criteria.append(('email', 'eq', email))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Member(**r) for r in found]

    def read_one(self, id: int = None) -> Any:
        """Reads one Member by its key. [crud:read_one: READ_ONE_BY_ID]"""
        record = self._store.get(self.ENTITY, self.PK, id, error=errors.MemberNotFoundError)
        return models.Member(**record)


class LoanRepository:
    ENTITY = "Loan"
    PK = "id"

    def __init__(self, store):
        self._store = store


    def create(self, book_id: int = None, member_id: int = None, loan_date: Any = None, due_date: Any = None, closed: bool = None) -> Any:
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
        if closed is not None:
            values['closed'] = closed
        unknown = [k for k in values if k not in ['id', 'book_id', 'member_id', 'loan_date', 'due_date', 'closed']]
        if unknown:
            raise ValueError(f"cannot create Loan from {unknown}")
        if values.get('closed') is None:
            values['closed'] = False
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[("book_id", "Book", "id", errors.BookNotFoundError), ("member_id", "Member", "id", errors.MemberNotFoundError)])
        return models.Loan(**record)

    def read_one(self, id: int = None) -> Any:
        """Reads one Loan by its key. [crud:read_one: READ_ONE_BY_ID]"""
        record = self._store.get(self.ENTITY, self.PK, id, error=errors.LoanNotFoundError)
        return models.Loan(**record)

    def delete(self, id: int = None, book_id: int = None, member_id: int = None, loan_date: Any = None, due_date: Any = None, closed: bool = None) -> None:
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
        if closed is not None:
            criteria.append(('closed', 'eq', closed))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise errors.LoanNotFoundError(f"Loan delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None

    def close_loan_by_id(self, loan_id: int = None) -> bool:
        """Closes a loan record by its ID, marking it as closed and updating the book's availability status accordingly. [llm-written by server — review]"""
        record = self._store.get(self.ENTITY, self.PK, loan_id, error=errors.LoanNotFoundError)
        book_id = record.get("book_id")
        if book_id is None:
            return False
        book = self._store.get("Book", 'id', book_id, error=errors.BookNotFoundError)
        book_available = book.get("available")
        if book_available is None:
            book_available = False
        if book_available:
            book["available"] = False
        self._store.update("Book", self.PK, book)
        record["closed"] = True
        self._store.update(self.ENTITY, self.PK, record)
        return True

    def get_active_loans_for_member(self, member_id: int = None) -> List[models.Loan]:
        """Returns a list of active loan records for a specific member, including book title and loan date. [crud:filter: FILTER_BY_FIELD: by parameter shape]"""
        criteria = []
        if member_id is not None:
            criteria.append(('member_id', 'eq', member_id))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Loan(**r) for r in found]
