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



class NoteRepository:
    ENTITY = "Note"
    PK = "id"

    def __init__(self, store):
        self._store = store


    def create(self, title: str = None, content: str = None, creation_date: Any = None) -> models.Note:
        """Creates a new Note. [crud:create: STANDARD_CRUD]"""
        values = {}
        if title is not None:
            values['title'] = title
        if content is not None:
            values['content'] = content
        if creation_date is not None:
            values['creation_date'] = creation_date
        unknown = [k for k in values if k not in ['id', 'title', 'content', 'creation_date']]
        if unknown:
            raise ValueError(f"cannot create Note from {unknown}")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[])
        return models.Note(**record)

    def delete(self, id: int = None, title: str = None, content: str = None, creation_date: Any = None) -> None:
        """Deletes an existing Note. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if id is not None:
            criteria.append(('id', 'eq', id))
        if title is not None:
            criteria.append(('title', 'eq', title))
        if content is not None:
            criteria.append(('content', 'eq', content))
        if creation_date is not None:
            criteria.append(('creation_date', 'eq', creation_date))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise LookupError(f"Note delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None

    def read_all(self, title: str = None, content: str = None, creation_date: Any = None) -> list[models.Note]:
        """Lists every Note; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if title is not None:
            criteria.append(('title', 'eq', title))
        if content is not None:
            criteria.append(('content', 'eq', content))
        if creation_date is not None:
            criteria.append(('creation_date', 'eq', creation_date))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Note(**r) for r in found]

    def read_one(self, id: int = None) -> models.Note:
        """Reads one Note by its key. [crud:read_one: READ_ONE_BY_ID]"""
        found = self._store.select(self.ENTITY, [(self.PK, 'eq', id)])
        if not found:
            return None
        record = found[0]
        return models.Note(**record)

    def update(self, id: int = None, title: str = None, content: str = None, creation_date: Any = None) -> models.Note:
        """Updates an existing Note. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if id is not None:
            criteria.append(('id', 'eq', id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise LookupError(f"Note update matched {len(found)} records")
        patch = {}
        if id is not None and 'id' in ['id', 'title', 'content', 'creation_date']:
            patch['id'] = id
        if title is not None and 'title' in ['id', 'title', 'content', 'creation_date']:
            patch['title'] = title
        if content is not None and 'content' in ['id', 'title', 'content', 'creation_date']:
            patch['content'] = content
        if creation_date is not None and 'creation_date' in ['id', 'title', 'content', 'creation_date']:
            patch['creation_date'] = creation_date
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=LookupError)
        return models.Note(**record)
