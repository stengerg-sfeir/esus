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


    def create(self, title: str = None, author: str = None, isbn: str = None, publication_year: int = None) -> models.Book:
        """Creates a new Book. [crud:create: STANDARD_CRUD]"""
        values = {}
        if title is not None:
            values['title'] = title
        if author is not None:
            values['author'] = author
        if isbn is not None:
            values['isbn'] = isbn
        if publication_year is not None:
            values['publication_year'] = publication_year
        unknown = [k for k in values if k not in ['id', 'title', 'author', 'isbn', 'publication_year']]
        if unknown:
            raise ValueError(f"cannot create Book from {unknown}")
        for unique_field in ['isbn']:
            value = values.get(unique_field)
            if value is not None and self._store.select(self.ENTITY, [(unique_field, 'eq', value)]):
                raise errors.BookIsbnDuplicateError(f"Book with {unique_field}={value!r} already exists")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[])
        return models.Book(**record)

    def delete(self, id: int = None, title: str = None, author: str = None, isbn: str = None, publication_year: int = None) -> None:
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
        if publication_year is not None:
            criteria.append(('publication_year', 'eq', publication_year))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise errors.BookNotFoundError(f"Book delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None

    def read_all(self, title: str = None, author: str = None, isbn: str = None, publication_year: int = None) -> list[models.Book]:
        """Lists every Book; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if title is not None:
            criteria.append(('title', 'eq', title))
        if author is not None:
            criteria.append(('author', 'eq', author))
        if isbn is not None:
            criteria.append(('isbn', 'eq', isbn))
        if publication_year is not None:
            criteria.append(('publication_year', 'eq', publication_year))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Book(**r) for r in found]

    def read_one(self, id: int = None) -> models.Book:
        """Reads one Book by its key. [crud:read_one: READ_ONE_BY_ID]"""
        record = self._store.get(self.ENTITY, self.PK, id, error=errors.BookNotFoundError)
        return models.Book(**record)

    def search_books(self, query: str = None) -> list[models.Book]:
        """Searches Book records across their text fields. [mechanical text search]"""
        if not query:
            return []
        query = str(query).lower()
        result = []
        for row in self._store.select(self.ENTITY, []):
            values = [row.get('title'), row.get('author'), row.get('isbn')]
            if any(value is not None and query in str(value).lower() for value in values):
                result.append(row)
        return _model_list([models.Book(**row) for row in result], models.Book)

    def update(self, id: int = None, title: str = None, author: str = None, isbn: str = None, publication_year: int = None) -> models.Book:
        """Updates an existing Book. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if id is not None:
            criteria.append(('id', 'eq', id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise errors.BookNotFoundError(f"Book update matched {len(found)} records")
        patch = {}
        if id is not None and 'id' in ['id', 'title', 'author', 'isbn', 'publication_year']:
            patch['id'] = id
        if title is not None and 'title' in ['id', 'title', 'author', 'isbn', 'publication_year']:
            patch['title'] = title
        if author is not None and 'author' in ['id', 'title', 'author', 'isbn', 'publication_year']:
            patch['author'] = author
        if isbn is not None and 'isbn' in ['id', 'title', 'author', 'isbn', 'publication_year']:
            patch['isbn'] = isbn
        if publication_year is not None and 'publication_year' in ['id', 'title', 'author', 'isbn', 'publication_year']:
            patch['publication_year'] = publication_year
        for unique_field in ['isbn']:
            value = patch.get(unique_field)
            if value is not None and any(row.get(self.PK) != found[0][self.PK] for row in self._store.select(self.ENTITY, [(unique_field, 'eq', value)])):
                raise errors.BookIsbnDuplicateError(f"Book with {unique_field}={value!r} already exists")
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=errors.BookNotFoundError)
        return models.Book(**record)
