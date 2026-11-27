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



class TaskRepository:
    ENTITY = "Task"
    PK = "id"

    def __init__(self, store):
        self._store = store


    def complete_task(self, id: int = None) -> None:
        """Completes a Task. [mechanical boolean filter]"""
        return _model_list(self._store.select(self.ENTITY, [('is_complete', 'eq', True)]), models.Task)

    def create(self, description: str = None, is_complete: bool = None, created_at: Any = None, updated_at: Any = None) -> models.Task:
        """Creates a new Task. [crud:create: STANDARD_CRUD]"""
        values = {}
        if description is not None:
            values['description'] = description
        if is_complete is not None:
            values['is_complete'] = is_complete
        if created_at is not None:
            values['created_at'] = created_at
        if updated_at is not None:
            values['updated_at'] = updated_at
        unknown = [k for k in values if k not in ['id', 'description', 'is_complete', 'created_at', 'updated_at']]
        if unknown:
            raise ValueError(f"cannot create Task from {unknown}")
        if values.get('created_at') is None:
            values['created_at'] = datetime.datetime.now()
        if values.get('updated_at') is None:
            values['updated_at'] = datetime.datetime.now()
        if values.get('is_complete') is None:
            values['is_complete'] = False
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[])
        return models.Task(**record)

    def delete(self, id: int = None, description: str = None, is_complete: bool = None, created_at: Any = None, updated_at: Any = None) -> None:
        """Deletes an existing Task. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if id is not None:
            criteria.append(('id', 'eq', id))
        if description is not None:
            criteria.append(('description', 'eq', description))
        if is_complete is not None:
            criteria.append(('is_complete', 'eq', is_complete))
        if created_at is not None:
            criteria.append(('created_at', 'eq', created_at))
        if updated_at is not None:
            criteria.append(('updated_at', 'eq', updated_at))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise LookupError(f"Task delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None

    def read_all(self, description: str = None, is_complete: bool = None, created_at: Any = None, updated_at: Any = None) -> list[models.Task]:
        """Lists every Task; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if description is not None:
            criteria.append(('description', 'eq', description))
        if is_complete is not None:
            criteria.append(('is_complete', 'eq', is_complete))
        if created_at is not None:
            criteria.append(('created_at', 'eq', created_at))
        if updated_at is not None:
            criteria.append(('updated_at', 'eq', updated_at))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Task(**r) for r in found]

    def read_one(self, id: int = None) -> models.Task:
        """Reads one Task by its key. [crud:read_one: READ_ONE_BY_ID]"""
        found = self._store.select(self.ENTITY, [(self.PK, 'eq', id)])
        if not found:
            return None
        record = found[0]
        return models.Task(**record)

    def update(self, id: int = None, description: str = None, is_complete: bool = None, created_at: Any = None, updated_at: Any = None) -> models.Task:
        """Updates an existing Task. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if id is not None:
            criteria.append(('id', 'eq', id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise LookupError(f"Task update matched {len(found)} records")
        patch = {}
        if id is not None and 'id' in ['id', 'description', 'is_complete', 'created_at', 'updated_at']:
            patch['id'] = id
        if description is not None and 'description' in ['id', 'description', 'is_complete', 'created_at', 'updated_at']:
            patch['description'] = description
        if is_complete is not None and 'is_complete' in ['id', 'description', 'is_complete', 'created_at', 'updated_at']:
            patch['is_complete'] = is_complete
        if created_at is not None and 'created_at' in ['id', 'description', 'is_complete', 'created_at', 'updated_at']:
            patch['created_at'] = created_at
        if updated_at is not None and 'updated_at' in ['id', 'description', 'is_complete', 'created_at', 'updated_at']:
            patch['updated_at'] = updated_at
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=LookupError)
        return models.Task(**record)
