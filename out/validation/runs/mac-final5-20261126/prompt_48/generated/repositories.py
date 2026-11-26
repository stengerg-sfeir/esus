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


    def create(self, title: str = None, author: str = None, genre: str = None, publication_date: Any = None, isbn: str = None) -> Any:
        """Creates a new Book. [crud:create: STANDARD_CRUD]"""
        values = {}
        if title is not None:
            values['title'] = title
        if author is not None:
            values['author'] = author
        if genre is not None:
            values['genre'] = genre
        if publication_date is not None:
            values['publication_date'] = publication_date
        if isbn is not None:
            values['isbn'] = isbn
        unknown = [k for k in values if k not in ['book_id', 'title', 'author', 'genre', 'publication_date', 'isbn']]
        if unknown:
            raise ValueError(f"cannot create Book from {unknown}")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[])
        return models.Book(**record)

    def read_all(self, title: str = None, author: str = None, genre: str = None, publication_date: Any = None, isbn: str = None) -> list[models.Book]:
        """Lists every Book; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if title is not None:
            criteria.append(('title', 'eq', title))
        if author is not None:
            criteria.append(('author', 'eq', author))
        if genre is not None:
            criteria.append(('genre', 'eq', genre))
        if publication_date is not None:
            criteria.append(('publication_date', 'eq', publication_date))
        if isbn is not None:
            criteria.append(('isbn', 'eq', isbn))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Book(**r) for r in found]

    def read_one(self, book_id: int = None) -> Any:
        """Reads one Book by its key. [crud:read_one: READ_ONE_BY_ID]"""
        found = self._store.select(self.ENTITY, [(self.PK, 'eq', book_id)])
        if not found:
            return None
        record = found[0]
        return models.Book(**record)

    def update(self, book_id: int = None, title: str = None, author: str = None, genre: str = None, publication_date: Any = None, isbn: str = None) -> Any:
        """Updates an existing Book. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if book_id is not None:
            criteria.append(('book_id', 'eq', book_id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise LookupError(f"Book update matched {len(found)} records")
        patch = {}
        if book_id is not None and 'book_id' in ['book_id', 'title', 'author', 'genre', 'publication_date', 'isbn']:
            patch['book_id'] = book_id
        if title is not None and 'title' in ['book_id', 'title', 'author', 'genre', 'publication_date', 'isbn']:
            patch['title'] = title
        if author is not None and 'author' in ['book_id', 'title', 'author', 'genre', 'publication_date', 'isbn']:
            patch['author'] = author
        if genre is not None and 'genre' in ['book_id', 'title', 'author', 'genre', 'publication_date', 'isbn']:
            patch['genre'] = genre
        if publication_date is not None and 'publication_date' in ['book_id', 'title', 'author', 'genre', 'publication_date', 'isbn']:
            patch['publication_date'] = publication_date
        if isbn is not None and 'isbn' in ['book_id', 'title', 'author', 'genre', 'publication_date', 'isbn']:
            patch['isbn'] = isbn
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=LookupError)
        return models.Book(**record)

    def delete(self, book_id: int = None, title: str = None, author: str = None, genre: str = None, publication_date: Any = None, isbn: str = None) -> None:
        """Deletes an existing Book. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if book_id is not None:
            criteria.append(('book_id', 'eq', book_id))
        if title is not None:
            criteria.append(('title', 'eq', title))
        if author is not None:
            criteria.append(('author', 'eq', author))
        if genre is not None:
            criteria.append(('genre', 'eq', genre))
        if publication_date is not None:
            criteria.append(('publication_date', 'eq', publication_date))
        if isbn is not None:
            criteria.append(('isbn', 'eq', isbn))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise LookupError(f"Book delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None

    def find_books(self, title: str = None, author: str = None, genre: str = None, publication_date: datetime.date = None, isbn: str = None) -> list[models.Book]:
        """Find books. [crud:filter: name-only: step F never saw this method]"""
        criteria = []
        if title is not None:
            criteria.append(('title', 'eq', title))
        if author is not None:
            criteria.append(('author', 'eq', author))
        if genre is not None:
            criteria.append(('genre', 'eq', genre))
        if publication_date is not None:
            criteria.append(('publication_date', 'eq', publication_date))
        if isbn is not None:
            criteria.append(('isbn', 'eq', isbn))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Book(**r) for r in found]
