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


class MemberRepository:
    ENTITY = "Member"
    PK = "id"

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

    def read_one(self, id: int = None) -> Any:
        """Reads one Member by its key. [crud:read_one: READ_ONE_BY_ID]"""
        record = self._store.get(self.ENTITY, self.PK, id, error=errors.MemberNotFoundError)
        return models.Member(**record)


class LoanRepository:
    ENTITY = "Loan"
    PK = "id"

    def __init__(self, store):
        self._store = store


    def create(self, book_id: int = None, member_id: int = None, loan_date: Any = None, due_date: Any = None, is_active: bool = None) -> Any:
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
        if is_active is not None:
            values['is_active'] = is_active
        unknown = [k for k in values if k not in ['id', 'book_id', 'member_id', 'loan_date', 'due_date', 'is_active']]
        if unknown:
            raise ValueError(f"cannot create Loan from {unknown}")
        if values.get('is_active') is None:
            values['is_active'] = False
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[("book_id", "Book", "id", errors.BookNotFoundError), ("member_id", "Member", "id", errors.MemberNotFoundError)])
        return models.Loan(**record)

    def update(self, id: int = None, book_id: int = None, member_id: int = None, loan_date: Any = None, due_date: Any = None, is_active: bool = None) -> Any:
        """Updates an existing Loan. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if id is not None:
            criteria.append(('id', 'eq', id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise errors.LoanNotFoundError(f"Loan update matched {len(found)} records")
        patch = {}
        if id is not None and 'id' in ['id', 'book_id', 'member_id', 'loan_date', 'due_date', 'is_active']:
            patch['id'] = id
        if book_id is not None and 'book_id' in ['id', 'book_id', 'member_id', 'loan_date', 'due_date', 'is_active']:
            patch['book_id'] = book_id
        if member_id is not None and 'member_id' in ['id', 'book_id', 'member_id', 'loan_date', 'due_date', 'is_active']:
            patch['member_id'] = member_id
        if loan_date is not None and 'loan_date' in ['id', 'book_id', 'member_id', 'loan_date', 'due_date', 'is_active']:
            patch['loan_date'] = loan_date
        if due_date is not None and 'due_date' in ['id', 'book_id', 'member_id', 'loan_date', 'due_date', 'is_active']:
            patch['due_date'] = due_date
        if is_active is not None and 'is_active' in ['id', 'book_id', 'member_id', 'loan_date', 'due_date', 'is_active']:
            patch['is_active'] = is_active
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=errors.LoanNotFoundError)
        return models.Loan(**record)

    def delete(self, id: int = None, book_id: int = None, member_id: int = None, loan_date: Any = None, due_date: Any = None, is_active: bool = None) -> None:
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
        if is_active is not None:
            criteria.append(('is_active', 'eq', is_active))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise errors.LoanNotFoundError(f"Loan delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None

    def read_one(self, id: int = None) -> Any:
        """Reads one Loan by its key. [crud:read_one: READ_ONE_BY_ID]"""
        record = self._store.get(self.ENTITY, self.PK, id, error=errors.LoanNotFoundError)
        return models.Loan(**record)
