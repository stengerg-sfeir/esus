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


    def create(self, title: str = None, description: str = None, status: str = None, priority: str = None, due_date: Any = None, created_at: Any = None, updated_at: Any = None) -> Any:
        """Creates a new Task. [crud:create: STANDARD_CRUD]"""
        values = {}
        if title is not None:
            values['title'] = title
        if description is not None:
            values['description'] = description
        if status is not None:
            values['status'] = status
        if priority is not None:
            values['priority'] = priority
        if due_date is not None:
            values['due_date'] = due_date
        if created_at is not None:
            values['created_at'] = created_at
        if updated_at is not None:
            values['updated_at'] = updated_at
        unknown = [k for k in values if k not in ['id', 'title', 'description', 'status', 'priority', 'due_date', 'created_at', 'updated_at']]
        if unknown:
            raise ValueError(f"cannot create Task from {unknown}")
        if values.get('created_at') is None:
            values['created_at'] = datetime.datetime.now()
        if values.get('updated_at') is None:
            values['updated_at'] = datetime.datetime.now()
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[])
        return models.Task(**record)

    def read_all(self, title: str = None, description: str = None, status: str = None, priority: str = None, due_date: Any = None, created_at: Any = None, updated_at: Any = None) -> list[models.Task]:
        """Lists every Task; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if title is not None:
            criteria.append(('title', 'eq', title))
        if description is not None:
            criteria.append(('description', 'eq', description))
        if status is not None:
            criteria.append(('status', 'eq', status))
        if priority is not None:
            criteria.append(('priority', 'eq', priority))
        if due_date is not None:
            criteria.append(('due_date', 'eq', due_date))
        if created_at is not None:
            criteria.append(('created_at', 'eq', created_at))
        if updated_at is not None:
            criteria.append(('updated_at', 'eq', updated_at))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Task(**r) for r in found]

    def update(self, id: int = None, title: str = None, description: str = None, status: str = None, priority: str = None, due_date: Any = None, created_at: Any = None, updated_at: Any = None) -> Any:
        """Updates an existing Task. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if id is not None:
            criteria.append(('id', 'eq', id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise LookupError(f"Task update matched {len(found)} records")
        patch = {}
        if id is not None and 'id' in ['id', 'title', 'description', 'status', 'priority', 'due_date', 'created_at', 'updated_at']:
            patch['id'] = id
        if title is not None and 'title' in ['id', 'title', 'description', 'status', 'priority', 'due_date', 'created_at', 'updated_at']:
            patch['title'] = title
        if description is not None and 'description' in ['id', 'title', 'description', 'status', 'priority', 'due_date', 'created_at', 'updated_at']:
            patch['description'] = description
        if status is not None and 'status' in ['id', 'title', 'description', 'status', 'priority', 'due_date', 'created_at', 'updated_at']:
            patch['status'] = status
        if priority is not None and 'priority' in ['id', 'title', 'description', 'status', 'priority', 'due_date', 'created_at', 'updated_at']:
            patch['priority'] = priority
        if due_date is not None and 'due_date' in ['id', 'title', 'description', 'status', 'priority', 'due_date', 'created_at', 'updated_at']:
            patch['due_date'] = due_date
        if created_at is not None and 'created_at' in ['id', 'title', 'description', 'status', 'priority', 'due_date', 'created_at', 'updated_at']:
            patch['created_at'] = created_at
        if updated_at is not None and 'updated_at' in ['id', 'title', 'description', 'status', 'priority', 'due_date', 'created_at', 'updated_at']:
            patch['updated_at'] = updated_at
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=LookupError)
        return models.Task(**record)

    def delete(self, id: int = None, title: str = None, description: str = None, status: str = None, priority: str = None, due_date: Any = None, created_at: Any = None, updated_at: Any = None) -> None:
        """Deletes an existing Task. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if id is not None:
            criteria.append(('id', 'eq', id))
        if title is not None:
            criteria.append(('title', 'eq', title))
        if description is not None:
            criteria.append(('description', 'eq', description))
        if status is not None:
            criteria.append(('status', 'eq', status))
        if priority is not None:
            criteria.append(('priority', 'eq', priority))
        if due_date is not None:
            criteria.append(('due_date', 'eq', due_date))
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

    def find_task_by_title(self, title: str = None) -> models.Task | None:
        """Retrieves a task by its title, returning the task object if found, otherwise None. [crud:read_one: READ_ONE_BY_ID]"""
        criteria = []
        if title is not None:
            criteria.append(('title', 'eq', title))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            return None
        record = found[0]
        return models.Task(**record)

    def find_task_by_status(self, status: str = None) -> list[models.Task]:
        """Retrieves all tasks with a specific status, returning a list of task objects. [crud:filter: FILTER_BY_FIELD]"""
        criteria = []
        if status is not None:
            criteria.append(('status', 'eq', status))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Task(**r) for r in found]

    def count_tasks_by_priority(self) -> dict[str, int]:
        """Returns the count of tasks grouped by priority level (e.g., low, medium, high). [mechanical count by field]"""
        counts = {}
        for row in self._store.select(self.ENTITY, []):
            key = row.get('priority')
            if key is not None:
                counts[key] = counts.get(key, 0) + 1
        return counts

    def get_tasks_with_due_date_in_range(self, start_date: Any = None, end_date: Any = None) -> list[models.Task]:
        """Returns all tasks whose due_date falls within a specified date range (inclusive). [crud:filter: FILTER_BY_FIELD: by parameter shape]"""
        criteria = []
        if start_date is not None:
            criteria.append(('due_date', 'ge', start_date))
        if end_date is not None:
            criteria.append(('due_date', 'le', end_date))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Task(**r) for r in found]
