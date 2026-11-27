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
    PK = "project_id"

    def __init__(self, store):
        self._store = store


    def create(self, name: str = None, description: str = None, created_at: Any = None, updated_at: Any = None) -> models.Project:
        """Creates a new Project. [crud:create: STANDARD_CRUD]"""
        values = {}
        if name is not None:
            values['name'] = name
        if description is not None:
            values['description'] = description
        if created_at is not None:
            values['created_at'] = created_at
        if updated_at is not None:
            values['updated_at'] = updated_at
        unknown = [k for k in values if k not in ['project_id', 'name', 'description', 'created_at', 'updated_at']]
        if unknown:
            raise ValueError(f"cannot create Project from {unknown}")
        if values.get('created_at') is None:
            values['created_at'] = datetime.datetime.now()
        if values.get('updated_at') is None:
            values['updated_at'] = datetime.datetime.now()
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[])
        return models.Project(**record)

    def delete(self, project_id: int = None, name: str = None, description: str = None, created_at: Any = None, updated_at: Any = None) -> None:
        """Deletes an existing Project. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if project_id is not None:
            criteria.append(('project_id', 'eq', project_id))
        if name is not None:
            criteria.append(('name', 'eq', name))
        if description is not None:
            criteria.append(('description', 'eq', description))
        if created_at is not None:
            criteria.append(('created_at', 'eq', created_at))
        if updated_at is not None:
            criteria.append(('updated_at', 'eq', updated_at))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise LookupError(f"Project delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None

    def delete_project_with_tasks(self, project_id: int = None) -> bool:
        """Deletes a project and all associated tasks in a single atomic operation, ensuring data consistency and integrity. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if project_id is not None:
            criteria.append(('project_id', 'eq', project_id))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise LookupError(f"Project delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None

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

    def read_one(self, project_id: int = None) -> models.Project:
        """Reads one Project by its key. [crud:read_one: READ_ONE_BY_ID]"""
        found = self._store.select(self.ENTITY, [(self.PK, 'eq', project_id)])
        if not found:
            return None
        record = found[0]
        return models.Project(**record)


class TaskRepository:
    ENTITY = "Task"
    PK = "task_id"

    def __init__(self, store):
        self._store = store


    def create(self, title: str = None, description: str = None, status: str = None, project_id: int = None, created_at: Any = None, updated_at: Any = None) -> models.Task:
        """Creates a new Task. [crud:create: STANDARD_CRUD]"""
        values = {}
        if title is not None:
            values['title'] = title
        if description is not None:
            values['description'] = description
        if status is not None:
            values['status'] = status
        if project_id is not None:
            values['project_id'] = project_id
        if created_at is not None:
            values['created_at'] = created_at
        if updated_at is not None:
            values['updated_at'] = updated_at
        unknown = [k for k in values if k not in ['task_id', 'title', 'description', 'status', 'project_id', 'created_at', 'updated_at']]
        if unknown:
            raise ValueError(f"cannot create Task from {unknown}")
        if values.get('created_at') is None:
            values['created_at'] = datetime.datetime.now()
        if values.get('updated_at') is None:
            values['updated_at'] = datetime.datetime.now()
        if values.get('status') is None:
            values['status'] = 'pending'
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[("project_id", "Project", "project_id", None)])
        return models.Task(**record)

    def delete(self, task_id: int = None, title: str = None, description: str = None, status: str = None, project_id: int = None, created_at: Any = None, updated_at: Any = None) -> None:
        """Deletes an existing Task. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if task_id is not None:
            criteria.append(('task_id', 'eq', task_id))
        if title is not None:
            criteria.append(('title', 'eq', title))
        if description is not None:
            criteria.append(('description', 'eq', description))
        if status is not None:
            criteria.append(('status', 'eq', status))
        if project_id is not None:
            criteria.append(('project_id', 'eq', project_id))
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

    def get_tasks_by_project_id(self, project_id: int = None) -> list[models.Task]:
        """Lists the Task records belonging to one Project. [mechanical contained-name filter]"""
        criteria = []
        if project_id is not None:
            criteria.append(('project_id', 'eq', project_id))
        found = self._store.select(self.ENTITY, criteria)
        return _model_list([models.Task(**row) for row in found], models.Task)

    def read_all(self, title: str = None, description: str = None, status: str = None, project_id: int = None, created_at: Any = None, updated_at: Any = None) -> list[models.Task]:
        """Lists every Task; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if title is not None:
            criteria.append(('title', 'eq', title))
        if description is not None:
            criteria.append(('description', 'eq', description))
        if status is not None:
            criteria.append(('status', 'eq', status))
        if project_id is not None:
            criteria.append(('project_id', 'eq', project_id))
        if created_at is not None:
            criteria.append(('created_at', 'eq', created_at))
        if updated_at is not None:
            criteria.append(('updated_at', 'eq', updated_at))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Task(**r) for r in found]

    def read_one(self, task_id: int = None) -> models.Task:
        """Reads one Task by its key. [crud:read_one: READ_ONE_BY_ID]"""
        found = self._store.select(self.ENTITY, [(self.PK, 'eq', task_id)])
        if not found:
            return None
        record = found[0]
        return models.Task(**record)

    def read_tasks_by_project_id(self, project_id: int = None) -> list[models.Task]:
        """Retrieves all tasks belonging to a specific project, enabling project-level task visibility and management. [mechanical contained-name filter]"""
        criteria = []
        if project_id is not None:
            criteria.append(('project_id', 'eq', project_id))
        found = self._store.select(self.ENTITY, criteria)
        return _model_list([models.Task(**row) for row in found], models.Task)

    def update(self, task_id: int = None, title: str = None, description: str = None, status: str = None, project_id: int = None, created_at: Any = None, updated_at: Any = None) -> models.Task:
        """Updates an existing Task. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if task_id is not None:
            criteria.append(('task_id', 'eq', task_id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise LookupError(f"Task update matched {len(found)} records")
        patch = {}
        if task_id is not None and 'task_id' in ['task_id', 'title', 'description', 'status', 'project_id', 'created_at', 'updated_at']:
            patch['task_id'] = task_id
        if title is not None and 'title' in ['task_id', 'title', 'description', 'status', 'project_id', 'created_at', 'updated_at']:
            patch['title'] = title
        if description is not None and 'description' in ['task_id', 'title', 'description', 'status', 'project_id', 'created_at', 'updated_at']:
            patch['description'] = description
        if status is not None and 'status' in ['task_id', 'title', 'description', 'status', 'project_id', 'created_at', 'updated_at']:
            patch['status'] = status
        if project_id is not None and 'project_id' in ['task_id', 'title', 'description', 'status', 'project_id', 'created_at', 'updated_at']:
            patch['project_id'] = project_id
        if created_at is not None and 'created_at' in ['task_id', 'title', 'description', 'status', 'project_id', 'created_at', 'updated_at']:
            patch['created_at'] = created_at
        if updated_at is not None and 'updated_at' in ['task_id', 'title', 'description', 'status', 'project_id', 'created_at', 'updated_at']:
            patch['updated_at'] = updated_at
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=LookupError)
        return models.Task(**record)
