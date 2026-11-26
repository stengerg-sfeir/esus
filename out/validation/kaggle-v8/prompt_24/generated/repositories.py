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


    def create(self, title: str = None, description: str = None) -> Any:
        """Creates a new Project. [crud:create: STANDARD_CRUD]"""
        values = {}
        if title is not None:
            values['title'] = title
        if description is not None:
            values['description'] = description
        unknown = [k for k in values if k not in ['project_id', 'title', 'description']]
        if unknown:
            raise ValueError(f"cannot create Project from {unknown}")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[])
        return models.Project(**record)

    def read_all(self, title: str = None, description: str = None) -> list[models.Project]:
        """Lists every Project; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if title is not None:
            criteria.append(('title', 'eq', title))
        if description is not None:
            criteria.append(('description', 'eq', description))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Project(**r) for r in found]

    def read_one(self, project_id: int = None) -> Any:
        """Reads one Project by its key. [crud:read_one: READ_ONE_BY_ID]"""
        found = self._store.select(self.ENTITY, [(self.PK, 'eq', project_id)])
        if not found:
            return None
        record = found[0]
        return models.Project(**record)

    def update(self, project_id: int = None, title: str = None, description: str = None) -> Any:
        """Updates an existing Project. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if project_id is not None:
            criteria.append(('project_id', 'eq', project_id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise LookupError(f"Project update matched {len(found)} records")
        patch = {}
        if project_id is not None and 'project_id' in ['project_id', 'title', 'description']:
            patch['project_id'] = project_id
        if title is not None and 'title' in ['project_id', 'title', 'description']:
            patch['title'] = title
        if description is not None and 'description' in ['project_id', 'title', 'description']:
            patch['description'] = description
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=LookupError)
        return models.Project(**record)

    def delete(self, project_id: int = None, title: str = None, description: str = None) -> None:
        """Deletes an existing Project. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if project_id is not None:
            criteria.append(('project_id', 'eq', project_id))
        if title is not None:
            criteria.append(('title', 'eq', title))
        if description is not None:
            criteria.append(('description', 'eq', description))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise LookupError(f"Project delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None

    def get_project_with_tasks(self, project_id: int = None) -> tuple[models.Project, list[models.Task]]:
        """Retrieves a project along with all its associated tasks, including task details like title, description, status, and priority. [mechanical parent + children]"""
        parent = self._store.get(self.ENTITY, self.PK, project_id, error=None)
        rows = self._store.select('Task', [('project_id', 'eq', project_id)])
        return (models.Project(**parent), [models.Task(**row) for row in rows])


class TaskRepository:
    ENTITY = "Task"
    PK = "task_id"

    def __init__(self, store):
        self._store = store


    def create(self, title: str = None, description: str = None, status: str = None, priority: str = None, project_id: int = None) -> Any:
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
        if project_id is not None:
            values['project_id'] = project_id
        unknown = [k for k in values if k not in ['task_id', 'title', 'description', 'status', 'priority', 'project_id']]
        if unknown:
            raise ValueError(f"cannot create Task from {unknown}")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[("project_id", "Project", "project_id", None)])
        return models.Task(**record)

    def read_all(self, title: str = None, description: str = None, status: str = None, priority: str = None, project_id: int = None) -> list[models.Task]:
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
        if project_id is not None:
            criteria.append(('project_id', 'eq', project_id))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Task(**r) for r in found]

    def read_one(self, task_id: int = None) -> Any:
        """Reads one Task by its key. [crud:read_one: READ_ONE_BY_ID]"""
        found = self._store.select(self.ENTITY, [(self.PK, 'eq', task_id)])
        if not found:
            return None
        record = found[0]
        return models.Task(**record)

    def update(self, task_id: int = None, title: str = None, description: str = None, status: str = None, priority: str = None, project_id: int = None) -> Any:
        """Updates an existing Task. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if task_id is not None:
            criteria.append(('task_id', 'eq', task_id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise LookupError(f"Task update matched {len(found)} records")
        patch = {}
        if task_id is not None and 'task_id' in ['task_id', 'title', 'description', 'status', 'priority', 'project_id']:
            patch['task_id'] = task_id
        if title is not None and 'title' in ['task_id', 'title', 'description', 'status', 'priority', 'project_id']:
            patch['title'] = title
        if description is not None and 'description' in ['task_id', 'title', 'description', 'status', 'priority', 'project_id']:
            patch['description'] = description
        if status is not None and 'status' in ['task_id', 'title', 'description', 'status', 'priority', 'project_id']:
            patch['status'] = status
        if priority is not None and 'priority' in ['task_id', 'title', 'description', 'status', 'priority', 'project_id']:
            patch['priority'] = priority
        if project_id is not None and 'project_id' in ['task_id', 'title', 'description', 'status', 'priority', 'project_id']:
            patch['project_id'] = project_id
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=LookupError)
        return models.Task(**record)

    def delete(self, task_id: int = None, title: str = None, description: str = None, status: str = None, priority: str = None, project_id: int = None) -> None:
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
        if priority is not None:
            criteria.append(('priority', 'eq', priority))
        if project_id is not None:
            criteria.append(('project_id', 'eq', project_id))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise LookupError(f"Task delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None

    def get_tasks_by_project_id(self, project_id: int = None) -> list[models.Task]:
        """Lists the Task records belonging to one Project. [crud:filter: FILTER_BY_FIELD: by parameter shape]"""
        criteria = []
        if project_id is not None:
            criteria.append(('project_id', 'eq', project_id))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Task(**r) for r in found]

    def get_tasks_by_priority(self, priority: str = None) -> list[models.Task]:
        """Retrieves all tasks that have a specific priority level, such as 'high', 'medium', or 'low'. [crud:filter: FILTER_BY_FIELD: by parameter shape]"""
        criteria = []
        if priority is not None:
            criteria.append(('priority', 'eq', priority))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Task(**r) for r in found]

    def get_tasks_by_status_and_project(self, status: str = None, project_id: int = None) -> list[models.Task]:
        """Retrieves tasks that match a specific status and belong to a specific project. [crud:filter: FILTER_BY_FIELD: by parameter shape]"""
        criteria = []
        if status is not None:
            criteria.append(('status', 'eq', status))
        if project_id is not None:
            criteria.append(('project_id', 'eq', project_id))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Task(**r) for r in found]
