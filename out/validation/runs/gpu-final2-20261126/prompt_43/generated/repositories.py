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



class ProjectRepository:
    ENTITY = "Project"
    PK = "id"

    def __init__(self, store):
        self._store = store


    def read_all(self, name: str = None, description: str = None, created_at: Any = None, updated_at: Any = None) -> list[models.Project]:
        """Lists every Project; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if name is not None:
            criteria.append(('name', 'eq', name))
        if description is not None:
            criteria.append(('description', 'eq', description))
        if created_at is not None:
            criteria.append(('created_at', 'eq', created_at))
        if updated_at is not None:
            criteria.append(('updated_at', 'eq', updated_at))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Project(**r) for r in found]

    def read_one(self, id: int = None) -> Any:
        """Reads one Project by its key. [crud:read_one: READ_ONE_BY_ID]"""
        found = self._store.select(self.ENTITY, [(self.PK, 'eq', id)])
        if not found:
            return None
        record = found[0]
        return models.Project(**record)


class TaskRepository:
    ENTITY = "Task"
    PK = "id"

    def __init__(self, store):
        self._store = store


    def read_all(self, title: str = None, description: str = None, project_id: int = None, priority: str = None, status: str = None, due_date: Any = None, created_at: Any = None, updated_at: Any = None) -> list[models.Task]:
        """Lists every Task; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if title is not None:
            criteria.append(('title', 'eq', title))
        if description is not None:
            criteria.append(('description', 'eq', description))
        if project_id is not None:
            criteria.append(('project_id', 'eq', project_id))
        if priority is not None:
            criteria.append(('priority', 'eq', priority))
        if status is not None:
            criteria.append(('status', 'eq', status))
        if due_date is not None:
            criteria.append(('due_date', 'eq', due_date))
        if created_at is not None:
            criteria.append(('created_at', 'eq', created_at))
        if updated_at is not None:
            criteria.append(('updated_at', 'eq', updated_at))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Task(**r) for r in found]

    def read_one(self, id: int = None) -> Any:
        """Reads one Task by its key. [crud:read_one: READ_ONE_BY_ID]"""
        found = self._store.select(self.ENTITY, [(self.PK, 'eq', id)])
        if not found:
            return None
        record = found[0]
        return models.Task(**record)

    def create(self, title: str = None, description: str = None, project_id: int = None, priority: str = None, status: str = None, due_date: Any = None, created_at: Any = None, updated_at: Any = None) -> Any:
        """Creates a new Task. [crud:create: STANDARD_CRUD]"""
        values = {}
        if title is not None:
            values['title'] = title
        if description is not None:
            values['description'] = description
        if project_id is not None:
            values['project_id'] = project_id
        if priority is not None:
            values['priority'] = priority
        if status is not None:
            values['status'] = status
        if due_date is not None:
            values['due_date'] = due_date
        if created_at is not None:
            values['created_at'] = created_at
        if updated_at is not None:
            values['updated_at'] = updated_at
        unknown = [k for k in values if k not in ['id', 'title', 'description', 'project_id', 'priority', 'status', 'due_date', 'created_at', 'updated_at']]
        if unknown:
            raise ValueError(f"cannot create Task from {unknown}")
        if values.get('created_at') is None:
            values['created_at'] = datetime.datetime.now()
        if values.get('updated_at') is None:
            values['updated_at'] = datetime.datetime.now()
        if values.get('status') is None:
            values['status'] = 'pending'
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[("project_id", "Project", "id", None)])
        return models.Task(**record)

    def update(self, id: int = None, title: str = None, description: str = None, project_id: int = None, priority: str = None, status: str = None, due_date: Any = None, created_at: Any = None, updated_at: Any = None) -> Any:
        """Updates an existing Task. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if id is not None:
            criteria.append(('id', 'eq', id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise LookupError(f"Task update matched {len(found)} records")
        patch = {}
        if id is not None and 'id' in ['id', 'title', 'description', 'project_id', 'priority', 'status', 'due_date', 'created_at', 'updated_at']:
            patch['id'] = id
        if title is not None and 'title' in ['id', 'title', 'description', 'project_id', 'priority', 'status', 'due_date', 'created_at', 'updated_at']:
            patch['title'] = title
        if description is not None and 'description' in ['id', 'title', 'description', 'project_id', 'priority', 'status', 'due_date', 'created_at', 'updated_at']:
            patch['description'] = description
        if project_id is not None and 'project_id' in ['id', 'title', 'description', 'project_id', 'priority', 'status', 'due_date', 'created_at', 'updated_at']:
            patch['project_id'] = project_id
        if priority is not None and 'priority' in ['id', 'title', 'description', 'project_id', 'priority', 'status', 'due_date', 'created_at', 'updated_at']:
            patch['priority'] = priority
        if status is not None and 'status' in ['id', 'title', 'description', 'project_id', 'priority', 'status', 'due_date', 'created_at', 'updated_at']:
            patch['status'] = status
        if due_date is not None and 'due_date' in ['id', 'title', 'description', 'project_id', 'priority', 'status', 'due_date', 'created_at', 'updated_at']:
            patch['due_date'] = due_date
        if created_at is not None and 'created_at' in ['id', 'title', 'description', 'project_id', 'priority', 'status', 'due_date', 'created_at', 'updated_at']:
            patch['created_at'] = created_at
        if updated_at is not None and 'updated_at' in ['id', 'title', 'description', 'project_id', 'priority', 'status', 'due_date', 'created_at', 'updated_at']:
            patch['updated_at'] = updated_at
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=LookupError)
        return models.Task(**record)


class StatusRepository:
    ENTITY = "Status"
    PK = "id"

    def __init__(self, store):
        self._store = store


    def read_all(self, name: str = None) -> list[models.Status]:
        """Lists every Status; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if name is not None:
            criteria.append(('name', 'eq', name))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Status(**r) for r in found]

    def read_one(self, id: int = None) -> Any:
        """Reads one Status by its key. [crud:read_one: READ_ONE_BY_ID]"""
        found = self._store.select(self.ENTITY, [(self.PK, 'eq', id)])
        if not found:
            return None
        record = found[0]
        return models.Status(**record)


class PriorityRepository:
    ENTITY = "Priority"
    PK = "id"

    def __init__(self, store):
        self._store = store


    def read_all(self, name: str = None) -> list[models.Priority]:
        """Lists every Priority; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if name is not None:
            criteria.append(('name', 'eq', name))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Priority(**r) for r in found]

    def read_one(self, id: int = None) -> Any:
        """Reads one Priority by its key. [crud:read_one: READ_ONE_BY_ID]"""
        found = self._store.select(self.ENTITY, [(self.PK, 'eq', id)])
        if not found:
            return None
        record = found[0]
        return models.Priority(**record)
