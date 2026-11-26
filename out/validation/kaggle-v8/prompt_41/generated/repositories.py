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


    def create(self, title: str = None, author: str = None, availability_status: bool = None) -> Any:
        """Creates a new Book. [crud:create: STANDARD_CRUD]"""
        values = {}
        if title is not None:
            values['title'] = title
        if author is not None:
            values['author'] = author
        if availability_status is not None:
            values['availability_status'] = availability_status
        unknown = [k for k in values if k not in ['book_id', 'title', 'author', 'availability_status']]
        if unknown:
            raise ValueError(f"cannot create Book from {unknown}")
        if values.get('availability_status') is None:
            values['availability_status'] = False
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[])
        return models.Book(**record)

    def read_all(self, title: str = None, author: str = None, availability_status: bool = None) -> list[models.Book]:
        """Lists every Book; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if title is not None:
            criteria.append(('title', 'eq', title))
        if author is not None:
            criteria.append(('author', 'eq', author))
        if availability_status is not None:
            criteria.append(('availability_status', 'eq', availability_status))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Book(**r) for r in found]

    def read_one(self, book_id: int = None) -> Any:
        """Reads one Book by its key. [crud:read_one: READ_ONE_BY_ID]"""
        record = self._store.get(self.ENTITY, self.PK, book_id, error=errors.BookNotFoundError)
        return models.Book(**record)

    def update(self, book_id: int = None, title: str = None, author: str = None, availability_status: bool = None) -> Any:
        """Updates an existing Book. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if book_id is not None:
            criteria.append(('book_id', 'eq', book_id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise errors.BookNotFoundError(f"Book update matched {len(found)} records")
        patch = {}
        if book_id is not None and 'book_id' in ['book_id', 'title', 'author', 'availability_status']:
            patch['book_id'] = book_id
        if title is not None and 'title' in ['book_id', 'title', 'author', 'availability_status']:
            patch['title'] = title
        if author is not None and 'author' in ['book_id', 'title', 'author', 'availability_status']:
            patch['author'] = author
        if availability_status is not None and 'availability_status' in ['book_id', 'title', 'author', 'availability_status']:
            patch['availability_status'] = availability_status
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=errors.BookNotFoundError)
        return models.Book(**record)

    def delete(self, book_id: int = None, title: str = None, author: str = None, availability_status: bool = None) -> None:
        """Deletes an existing Book. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if book_id is not None:
            criteria.append(('book_id', 'eq', book_id))
        if title is not None:
            criteria.append(('title', 'eq', title))
        if author is not None:
            criteria.append(('author', 'eq', author))
        if availability_status is not None:
            criteria.append(('availability_status', 'eq', availability_status))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise errors.BookNotFoundError(f"Book delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None


class MemberRepository:
    ENTITY = "Member"
    PK = "member_id"

    def __init__(self, store):
        self._store = store


    def create(self, name: str = None, contact_details: str = None, membership_status: bool = None) -> Any:
        """Creates a new Member. [crud:create: STANDARD_CRUD]"""
        values = {}
        if name is not None:
            values['name'] = name
        if contact_details is not None:
            values['contact_details'] = contact_details
        if membership_status is not None:
            values['membership_status'] = membership_status
        unknown = [k for k in values if k not in ['member_id', 'name', 'contact_details', 'membership_status']]
        if unknown:
            raise ValueError(f"cannot create Member from {unknown}")
        if values.get('membership_status') is None:
            values['membership_status'] = False
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[])
        return models.Member(**record)

    def read_all(self, name: str = None, contact_details: str = None, membership_status: bool = None) -> list[models.Member]:
        """Lists every Member; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if name is not None:
            criteria.append(('name', 'eq', name))
        if contact_details is not None:
            criteria.append(('contact_details', 'eq', contact_details))
        if membership_status is not None:
            criteria.append(('membership_status', 'eq', membership_status))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Member(**r) for r in found]

    def read_one(self, member_id: int = None) -> Any:
        """Reads one Member by its key. [crud:read_one: READ_ONE_BY_ID]"""
        record = self._store.get(self.ENTITY, self.PK, member_id, error=errors.MemberNotFoundError)
        return models.Member(**record)

    def update(self, member_id: int = None, name: str = None, contact_details: str = None, membership_status: bool = None) -> Any:
        """Updates an existing Member. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if member_id is not None:
            criteria.append(('member_id', 'eq', member_id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise errors.MemberNotFoundError(f"Member update matched {len(found)} records")
        patch = {}
        if member_id is not None and 'member_id' in ['member_id', 'name', 'contact_details', 'membership_status']:
            patch['member_id'] = member_id
        if name is not None and 'name' in ['member_id', 'name', 'contact_details', 'membership_status']:
            patch['name'] = name
        if contact_details is not None and 'contact_details' in ['member_id', 'name', 'contact_details', 'membership_status']:
            patch['contact_details'] = contact_details
        if membership_status is not None and 'membership_status' in ['member_id', 'name', 'contact_details', 'membership_status']:
            patch['membership_status'] = membership_status
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=errors.MemberNotFoundError)
        return models.Member(**record)

    def delete(self, member_id: int = None, name: str = None, contact_details: str = None, membership_status: bool = None) -> None:
        """Deletes an existing Member. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if member_id is not None:
            criteria.append(('member_id', 'eq', member_id))
        if name is not None:
            criteria.append(('name', 'eq', name))
        if contact_details is not None:
            criteria.append(('contact_details', 'eq', contact_details))
        if membership_status is not None:
            criteria.append(('membership_status', 'eq', membership_status))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise errors.MemberNotFoundError(f"Member delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None


class LoanRepository:
    ENTITY = "Loan"
    PK = "loan_id"

    def __init__(self, store):
        self._store = store


    def create(self, member_id: int = None, book_id: int = None, loan_date: Any = None, return_date: Any = None) -> Any:
        """Creates a new Loan. [crud:create: STANDARD_CRUD]"""
        values = {}
        if member_id is not None:
            values['member_id'] = member_id
        if book_id is not None:
            values['book_id'] = book_id
        if loan_date is not None:
            values['loan_date'] = loan_date
        if return_date is not None:
            values['return_date'] = return_date
        unknown = [k for k in values if k not in ['loan_id', 'member_id', 'book_id', 'loan_date', 'return_date']]
        if unknown:
            raise ValueError(f"cannot create Loan from {unknown}")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[("member_id", "Member", "member_id", errors.MemberNotFoundError), ("book_id", "Book", "book_id", errors.BookNotFoundError)])
        return models.Loan(**record)

    def read_all(self, member_id: int = None, book_id: int = None, loan_date: Any = None, return_date: Any = None) -> list[models.Loan]:
        """Lists every Loan; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if member_id is not None:
            criteria.append(('member_id', 'eq', member_id))
        if book_id is not None:
            criteria.append(('book_id', 'eq', book_id))
        if loan_date is not None:
            criteria.append(('loan_date', 'eq', loan_date))
        if return_date is not None:
            criteria.append(('return_date', 'eq', return_date))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Loan(**r) for r in found]

    def read_one(self, loan_id: int = None) -> Any:
        """Reads one Loan by its key. [crud:read_one: READ_ONE_BY_ID]"""
        record = self._store.get(self.ENTITY, self.PK, loan_id, error=errors.LoanNotFoundError)
        return models.Loan(**record)

    def update(self, loan_id: int = None, member_id: int = None, book_id: int = None, loan_date: Any = None, return_date: Any = None) -> Any:
        """Updates an existing Loan. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if loan_id is not None:
            criteria.append(('loan_id', 'eq', loan_id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise errors.LoanNotFoundError(f"Loan update matched {len(found)} records")
        patch = {}
        if loan_id is not None and 'loan_id' in ['loan_id', 'member_id', 'book_id', 'loan_date', 'return_date']:
            patch['loan_id'] = loan_id
        if member_id is not None and 'member_id' in ['loan_id', 'member_id', 'book_id', 'loan_date', 'return_date']:
            patch['member_id'] = member_id
        if book_id is not None and 'book_id' in ['loan_id', 'member_id', 'book_id', 'loan_date', 'return_date']:
            patch['book_id'] = book_id
        if loan_date is not None and 'loan_date' in ['loan_id', 'member_id', 'book_id', 'loan_date', 'return_date']:
            patch['loan_date'] = loan_date
        if return_date is not None and 'return_date' in ['loan_id', 'member_id', 'book_id', 'loan_date', 'return_date']:
            patch['return_date'] = return_date
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=errors.LoanNotFoundError)
        return models.Loan(**record)

    def delete(self, loan_id: int = None, member_id: int = None, book_id: int = None, loan_date: Any = None, return_date: Any = None) -> None:
        """Deletes an existing Loan. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if loan_id is not None:
            criteria.append(('loan_id', 'eq', loan_id))
        if member_id is not None:
            criteria.append(('member_id', 'eq', member_id))
        if book_id is not None:
            criteria.append(('book_id', 'eq', book_id))
        if loan_date is not None:
            criteria.append(('loan_date', 'eq', loan_date))
        if return_date is not None:
            criteria.append(('return_date', 'eq', return_date))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise errors.LoanNotFoundError(f"Loan delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None

    def get_loans_by_member_id(self, member_id: int = None) -> list[models.Loan]:
        """Lists the Loan records belonging to one Member. [crud:filter: FILTER_BY_FIELD: by parameter shape]"""
        criteria = []
        if member_id is not None:
            criteria.append(('member_id', 'eq', member_id))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Loan(**r) for r in found]

    def findLoansByMember(self, memberId: int = None) -> list[models.Loan]:
        """Returns all loan records for a specific member, including book title and loan date. [crud:filter: FILTER_BY_FIELD]"""
        criteria = []
        if memberId is not None:
            criteria.append(('member_id', 'eq', memberId))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Loan(**r) for r in found]

    def findLoansByBook(self, bookId: int = None) -> list[models.Loan]:
        """Returns all loan records for a specific book, including member name and loan date. [crud:filter: FILTER_BY_FIELD]"""
        criteria = []
        if bookId is not None:
            criteria.append(('book_id', 'eq', bookId))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Loan(**r) for r in found]
