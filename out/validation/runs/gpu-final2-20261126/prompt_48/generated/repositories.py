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


    def create(self, title: str = None, author: str = None, genre: str = None, isbn: str = None, publication_year: int = None, category: str = None) -> Any:
        """Creates a new Book. [crud:create: STANDARD_CRUD]"""
        values = {}
        if title is not None:
            values['title'] = title
        if author is not None:
            values['author'] = author
        if genre is not None:
            values['genre'] = genre
        if isbn is not None:
            values['isbn'] = isbn
        if publication_year is not None:
            values['publication_year'] = publication_year
        if category is not None:
            values['category'] = category
        unknown = [k for k in values if k not in ['id', 'title', 'author', 'genre', 'isbn', 'publication_year', 'category']]
        if unknown:
            raise ValueError(f"cannot create Book from {unknown}")
        value = values.get('publication_year')
        if value is not None and value <= 0:
            raise ValueError(f"Book.publication_year must be > 0, got {value!r}")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[])
        return models.Book(**record)

    def read_all(self, title: str = None, author: str = None, genre: str = None, isbn: str = None, publication_year: int = None, category: str = None) -> list[models.Book]:
        """Lists every Book; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if title is not None:
            criteria.append(('title', 'eq', title))
        if author is not None:
            criteria.append(('author', 'eq', author))
        if genre is not None:
            criteria.append(('genre', 'eq', genre))
        if isbn is not None:
            criteria.append(('isbn', 'eq', isbn))
        if publication_year is not None:
            criteria.append(('publication_year', 'eq', publication_year))
        if category is not None:
            criteria.append(('category', 'eq', category))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Book(**r) for r in found]

    def read_one(self, id: int = None) -> Any:
        """Reads one Book by its key. [crud:read_one: READ_ONE_BY_ID]"""
        found = self._store.select(self.ENTITY, [(self.PK, 'eq', id)])
        if not found:
            return None
        record = found[0]
        return models.Book(**record)
