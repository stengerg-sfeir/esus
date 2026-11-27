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


    def create(self, title: str = None, author: str = None, isbn: str = None, created_at: Any = None, updated_at: Any = None) -> Any:
        """Creates a new Book. [crud:create: STANDARD_CRUD]"""
        values = {}
        if title is not None:
            values['title'] = title
        if author is not None:
            values['author'] = author
        if isbn is not None:
            values['isbn'] = isbn
        if created_at is not None:
            values['created_at'] = created_at
        if updated_at is not None:
            values['updated_at'] = updated_at
        unknown = [k for k in values if k not in ['id', 'title', 'author', 'isbn', 'created_at', 'updated_at']]
        if unknown:
            raise ValueError(f"cannot create Book from {unknown}")
        if values.get('created_at') is None:
            values['created_at'] = datetime.datetime.now()
        if values.get('updated_at') is None:
            values['updated_at'] = datetime.datetime.now()
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[])
        return models.Book(**record)

    def read_all(self, title: str = None, author: str = None, isbn: str = None, created_at: Any = None, updated_at: Any = None) -> list[models.Book]:
        """Lists every Book; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if title is not None:
            criteria.append(('title', 'eq', title))
        if author is not None:
            criteria.append(('author', 'eq', author))
        if isbn is not None:
            criteria.append(('isbn', 'eq', isbn))
        if created_at is not None:
            criteria.append(('created_at', 'eq', created_at))
        if updated_at is not None:
            criteria.append(('updated_at', 'eq', updated_at))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Book(**r) for r in found]

    def read_one(self, id: int = None) -> Any:
        """Reads one Book by its key. [crud:read_one: READ_ONE_BY_ID]"""
        found = self._store.select(self.ENTITY, [(self.PK, 'eq', id)])
        if not found:
            return None
        record = found[0]
        return models.Book(**record)

    def update(self, id: int = None, title: str = None, author: str = None, isbn: str = None, created_at: Any = None, updated_at: Any = None) -> Any:
        """Updates an existing Book. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if id is not None:
            criteria.append(('id', 'eq', id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise LookupError(f"Book update matched {len(found)} records")
        patch = {}
        if id is not None and 'id' in ['id', 'title', 'author', 'isbn', 'created_at', 'updated_at']:
            patch['id'] = id
        if title is not None and 'title' in ['id', 'title', 'author', 'isbn', 'created_at', 'updated_at']:
            patch['title'] = title
        if author is not None and 'author' in ['id', 'title', 'author', 'isbn', 'created_at', 'updated_at']:
            patch['author'] = author
        if isbn is not None and 'isbn' in ['id', 'title', 'author', 'isbn', 'created_at', 'updated_at']:
            patch['isbn'] = isbn
        if created_at is not None and 'created_at' in ['id', 'title', 'author', 'isbn', 'created_at', 'updated_at']:
            patch['created_at'] = created_at
        if updated_at is not None and 'updated_at' in ['id', 'title', 'author', 'isbn', 'created_at', 'updated_at']:
            patch['updated_at'] = updated_at
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=LookupError)
        return models.Book(**record)

    def delete(self, id: int = None, title: str = None, author: str = None, isbn: str = None, created_at: Any = None, updated_at: Any = None) -> None:
        """Deletes an existing Book. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if id is not None:
            criteria.append(('id', 'eq', id))
        if title is not None:
            criteria.append(('title', 'eq', title))
        if author is not None:
            criteria.append(('author', 'eq', author))
        if isbn is not None:
            criteria.append(('isbn', 'eq', isbn))
        if created_at is not None:
            criteria.append(('created_at', 'eq', created_at))
        if updated_at is not None:
            criteria.append(('updated_at', 'eq', updated_at))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise LookupError(f"Book delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None

    def search_by_title(self, title: str = None) -> list[models.Book]:
        """Search for books by a partial match of the title, returning a list of books that contain the title string. [mechanical text search]"""
        if not title:
            return []
        query = str(title).lower()
        result = []
        for row in self._store.select(self.ENTITY, []):
            values = [row.get('title'), row.get('author'), row.get('isbn')]
            if any(value is not None and query in str(value).lower() for value in values):
                result.append(row)
        return _model_list([models.Book(**row) for row in result], models.Book)
