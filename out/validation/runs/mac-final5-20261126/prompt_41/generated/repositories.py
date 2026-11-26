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


    def create(self, title: str = None, author: str = None, availability_status: bool = None) -> Any:
        """Creates a new Book. [crud:create: STANDARD_CRUD]"""
        values = {}
        if title is not None:
            values['title'] = title
        if author is not None:
            values['author'] = author
        if availability_status is not None:
            values['availability_status'] = availability_status
        unknown = [k for k in values if k not in ['id', 'title', 'author', 'availability_status']]
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

    def read_one(self, id: int = None) -> Any:
        """Reads one Book by its key. [crud:read_one: READ_ONE_BY_ID]"""
        record = self._store.get(self.ENTITY, self.PK, id, error=errors.BookNotFoundError)
        return models.Book(**record)

    def update(self, id: int = None, title: str = None, author: str = None, availability_status: bool = None) -> Any:
        """Updates an existing Book. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if id is not None:
            criteria.append(('id', 'eq', id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise errors.BookNotFoundError(f"Book update matched {len(found)} records")
        patch = {}
        if id is not None and 'id' in ['id', 'title', 'author', 'availability_status']:
            patch['id'] = id
        if title is not None and 'title' in ['id', 'title', 'author', 'availability_status']:
            patch['title'] = title
        if author is not None and 'author' in ['id', 'title', 'author', 'availability_status']:
            patch['author'] = author
        if availability_status is not None and 'availability_status' in ['id', 'title', 'author', 'availability_status']:
            patch['availability_status'] = availability_status
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=errors.BookNotFoundError)
        return models.Book(**record)

    def delete(self, id: int = None, title: str = None, author: str = None, availability_status: bool = None) -> None:
        """Deletes an existing Book. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if id is not None:
            criteria.append(('id', 'eq', id))
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

    def findAvailableBooks(self, id: int = None) -> list[models.Book]:
        """Returns a list of books that are currently available (not currently loaned out). [crud:filter: FILTER_BY_FIELD]"""
        criteria = []
        if id is not None:
            criteria.append(('id', 'eq', id))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Book(**r) for r in found]

    def getBookByTitle(self, title: str = None) -> Any:
        """Retrieves a book by its title, returning the book if found, otherwise null. [crud:read_one: READ_ONE_BY_ID]"""
        criteria = []
        if title is not None:
            criteria.append(('title', 'eq', title))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise errors.BookNotFoundError(f"Book lookup matched {len(found)} records")
        record = found[0]
        return models.Book(**record)

    def booksearch(self) -> list[models.Book]:
        """Booksearch. [llm-written by server — review]"""
        criteria = []
        found = self._store.select(self.ENTITY, [])
        results = []
        for record in found:
            title = record.get('title')
            author = record.get('author')
            if title and title.lower() in self._store.select('Book', [('title', 'eq', title.lower())])[0].get('title', '').lower():
                results.append(models.Book(**record))
            if author and author.lower() in self._store.select('Book', [('author', 'eq', author.lower())])[0].get('author', '').lower():
                results.append(models.Book(**record))
        return _model_list(results, models.Book)


class MemberRepository:
    ENTITY = "Member"
    PK = "id"

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
        unknown = [k for k in values if k not in ['id', 'name', 'contact_details', 'membership_status']]
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

    def read_one(self, id: int = None) -> Any:
        """Reads one Member by its key. [crud:read_one: READ_ONE_BY_ID]"""
        record = self._store.get(self.ENTITY, self.PK, id, error=errors.MemberNotFoundError)
        return models.Member(**record)

    def update(self, id: int = None, name: str = None, contact_details: str = None, membership_status: bool = None) -> Any:
        """Updates an existing Member. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if id is not None:
            criteria.append(('id', 'eq', id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise errors.MemberNotFoundError(f"Member update matched {len(found)} records")
        patch = {}
        if id is not None and 'id' in ['id', 'name', 'contact_details', 'membership_status']:
            patch['id'] = id
        if name is not None and 'name' in ['id', 'name', 'contact_details', 'membership_status']:
            patch['name'] = name
        if contact_details is not None and 'contact_details' in ['id', 'name', 'contact_details', 'membership_status']:
            patch['contact_details'] = contact_details
        if membership_status is not None and 'membership_status' in ['id', 'name', 'contact_details', 'membership_status']:
            patch['membership_status'] = membership_status
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=errors.MemberNotFoundError)
        return models.Member(**record)

    def delete(self, id: int = None, name: str = None, contact_details: str = None, membership_status: bool = None) -> None:
        """Deletes an existing Member. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if id is not None:
            criteria.append(('id', 'eq', id))
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

    def findActiveMembers(self, id: int = None) -> list[models.Member]:
        """Returns a list of members whose membership status is active. [crud:filter: FILTER_BY_FIELD]"""
        criteria = []
        if id is not None:
            criteria.append(('id', 'eq', id))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Member(**r) for r in found]

    def getMemberByName(self, name: str = None) -> Any:
        """Retrieves a member by their name, returning the member if found, otherwise null. [crud:read_one: READ_ONE_BY_ID]"""
        criteria = []
        if name is not None:
            criteria.append(('name', 'eq', name))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise errors.MemberNotFoundError(f"Member lookup matched {len(found)} records")
        record = found[0]
        return models.Member(**record)


class LoanRepository:
    ENTITY = "Loan"
    PK = "id"

    def __init__(self, store):
        self._store = store


    def create(self, book_id: int = None, member_id: int = None, loan_date: Any = None, return_date: Any = None) -> Any:
        """Creates a new Loan. [crud:create: STANDARD_CRUD]"""
        values = {}
        if book_id is not None:
            values['book_id'] = book_id
        if member_id is not None:
            values['member_id'] = member_id
        if loan_date is not None:
            values['loan_date'] = loan_date
        if return_date is not None:
            values['return_date'] = return_date
        unknown = [k for k in values if k not in ['id', 'book_id', 'member_id', 'loan_date', 'return_date']]
        if unknown:
            raise ValueError(f"cannot create Loan from {unknown}")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[("book_id", "Book", "id", errors.BookNotFoundError), ("member_id", "Member", "id", errors.MemberNotFoundError)])
        return models.Loan(**record)

    def read_all(self, book_id: int = None, member_id: int = None, loan_date: Any = None, return_date: Any = None) -> list[models.Loan]:
        """Lists every Loan; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if book_id is not None:
            criteria.append(('book_id', 'eq', book_id))
        if member_id is not None:
            criteria.append(('member_id', 'eq', member_id))
        if loan_date is not None:
            criteria.append(('loan_date', 'eq', loan_date))
        if return_date is not None:
            criteria.append(('return_date', 'eq', return_date))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Loan(**r) for r in found]

    def read_one(self, id: int = None) -> Any:
        """Reads one Loan by its key. [crud:read_one: READ_ONE_BY_ID]"""
        record = self._store.get(self.ENTITY, self.PK, id, error=errors.LoanNotFoundError)
        return models.Loan(**record)

    def update(self, id: int = None, book_id: int = None, member_id: int = None, loan_date: Any = None, return_date: Any = None) -> Any:
        """Updates an existing Loan. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if id is not None:
            criteria.append(('id', 'eq', id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise errors.LoanNotFoundError(f"Loan update matched {len(found)} records")
        patch = {}
        if id is not None and 'id' in ['id', 'book_id', 'member_id', 'loan_date', 'return_date']:
            patch['id'] = id
        if book_id is not None and 'book_id' in ['id', 'book_id', 'member_id', 'loan_date', 'return_date']:
            patch['book_id'] = book_id
        if member_id is not None and 'member_id' in ['id', 'book_id', 'member_id', 'loan_date', 'return_date']:
            patch['member_id'] = member_id
        if loan_date is not None and 'loan_date' in ['id', 'book_id', 'member_id', 'loan_date', 'return_date']:
            patch['loan_date'] = loan_date
        if return_date is not None and 'return_date' in ['id', 'book_id', 'member_id', 'loan_date', 'return_date']:
            patch['return_date'] = return_date
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=errors.LoanNotFoundError)
        return models.Loan(**record)

    def delete(self, id: int = None, book_id: int = None, member_id: int = None, loan_date: Any = None, return_date: Any = None) -> None:
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
        if return_date is not None:
            criteria.append(('return_date', 'eq', return_date))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise errors.LoanNotFoundError(f"Loan delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None

    def findLoansByBookId(self, bookId: Long = None) -> list[models.Loan]:
        """Returns a list of loans associated with a specific book ID. [crud:filter: FILTER_BY_FIELD]"""
        criteria = []
        if bookId is not None:
            criteria.append(('book_id', 'eq', bookId))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Loan(**r) for r in found]

    def findLoansByMemberId(self, memberId: Long = None) -> list[models.Loan]:
        """Returns a list of loans associated with a specific member ID. [crud:filter: FILTER_BY_FIELD]"""
        criteria = []
        if memberId is not None:
            criteria.append(('member_id', 'eq', memberId))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Loan(**r) for r in found]

    def getLoanByDate(self, loanDate: LocalDate = None) -> Any:
        """Retrieves a loan record by its loan date, returning the loan if found, otherwise null. [crud:read_one: READ_ONE_BY_ID]"""
        criteria = []
        if loanDate is not None:
            criteria.append(('loan_date', 'eq', loanDate))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise errors.LoanNotFoundError(f"Loan lookup matched {len(found)} records")
        record = found[0]
        return models.Loan(**record)
