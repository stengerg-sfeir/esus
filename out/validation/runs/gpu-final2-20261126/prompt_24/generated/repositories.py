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


    def create(self, title: str = None, description: str = None, created_at: Any = None, updated_at: Any = None) -> models.Project:
        """Creates a new Project. [crud:create: STANDARD_CRUD]"""
        values = {}
        if title is not None:
            values['title'] = title
        if description is not None:
            values['description'] = description
        if created_at is not None:
            values['created_at'] = created_at
        if updated_at is not None:
            values['updated_at'] = updated_at
        unknown = [k for k in values if k not in ['project_id', 'title', 'description', 'created_at', 'updated_at']]
        if unknown:
            raise ValueError(f"cannot create Project from {unknown}")
        if values.get('created_at') is None:
            values['created_at'] = datetime.datetime.now()
        if values.get('updated_at') is None:
            values['updated_at'] = datetime.datetime.now()
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[])
        return models.Project(**record)

    def delete(self, project_id: int = None, title: str = None, description: str = None, created_at: Any = None, updated_at: Any = None) -> None:
        """Deletes an existing Project. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if project_id is not None:
            criteria.append(('project_id', 'eq', project_id))
        if title is not None:
            criteria.append(('title', 'eq', title))
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

    def find_project_by_title(self, title: str = None) -> models.Project | None:
        """Retrieves a project by its title, returning the project object if found, otherwise None. [crud:read_one: READ_ONE_BY_ID]"""
        criteria = []
        if title is not None:
            criteria.append(('title', 'eq', title))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            return None
        record = found[0]
        return models.Project(**record)

    def read_all(self, title: str = None, description: str = None, created_at: Any = None, updated_at: Any = None) -> list[models.Project]:
        """Lists every Project; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if title is not None:
            criteria.append(('title', 'eq', title))
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

    def update(self, project_id: int = None, title: str = None, description: str = None, created_at: Any = None, updated_at: Any = None) -> models.Project:
        """Updates an existing Project. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if project_id is not None:
            criteria.append(('project_id', 'eq', project_id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise LookupError(f"Project update matched {len(found)} records")
        patch = {}
        if project_id is not None and 'project_id' in ['project_id', 'title', 'description', 'created_at', 'updated_at']:
            patch['project_id'] = project_id
        if title is not None and 'title' in ['project_id', 'title', 'description', 'created_at', 'updated_at']:
            patch['title'] = title
        if description is not None and 'description' in ['project_id', 'title', 'description', 'created_at', 'updated_at']:
            patch['description'] = description
        if created_at is not None and 'created_at' in ['project_id', 'title', 'description', 'created_at', 'updated_at']:
            patch['created_at'] = created_at
        if updated_at is not None and 'updated_at' in ['project_id', 'title', 'description', 'created_at', 'updated_at']:
            patch['updated_at'] = updated_at
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=LookupError)
        return models.Project(**record)


class TaskRepository:
    ENTITY = "Task"
    PK = "task_id"

    def __init__(self, store):
        self._store = store


    def count_tasks_by_priority(self, priority: str = None) -> int:
        """Returns the number of tasks with a specific priority (e.g., 'high', 'medium', 'low'). [llm-written by server — review]"""
        criteria = []
        if priority is not None:
            criteria.append(('priority', 'eq', priority))
        found = self._store.select(self.ENTITY, criteria)
        return len(found)

    def create(self, title: str = None, description: str = None, status: str = None, priority: str = None, project_id: int = None, created_at: Any = None, updated_at: Any = None) -> models.Task:
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
        if created_at is not None:
            values['created_at'] = created_at
        if updated_at is not None:
            values['updated_at'] = updated_at
        unknown = [k for k in values if k not in ['task_id', 'title', 'description', 'status', 'priority', 'project_id', 'created_at', 'updated_at']]
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

    def delete(self, task_id: int = None, title: str = None, description: str = None, status: str = None, priority: str = None, project_id: int = None, created_at: Any = None, updated_at: Any = None) -> None:
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

    def find_task_by_title_and_project_id(self, title: str = None, project_id: int = None) -> models.Task | None:
        """Retrieves a task by its title and the project it belongs to, returning the task object if found, otherwise None. [crud:read_one: READ_ONE_BY_ID]"""
        criteria = []
        if title is not None:
            criteria.append(('title', 'eq', title))
        if project_id is not None:
            criteria.append(('project_id', 'eq', project_id))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            return None
        record = found[0]
        return models.Task(**record)

    def get_tasks_by_project_id(self, project_id: int = None) -> list[models.Task]:
        """Lists the Task records belonging to one Project. [mechanical contained-name filter]"""
        criteria = []
        if project_id is not None:
            criteria.append(('project_id', 'eq', project_id))
        found = self._store.select(self.ENTITY, criteria)
        return _model_list([models.Task(**row) for row in found], models.Task)

    def get_tasks_with_status_and_project_id(self, status: str = None, project_id: int = None) -> list[models.Task]:
        """Returns a list of tasks that match a specific status and belong to a given project ID. [crud:filter: FILTER_BY_FIELD: by parameter shape]"""
        criteria = []
        if status is not None:
            criteria.append(('status', 'eq', status))
        if project_id is not None:
            criteria.append(('project_id', 'eq', project_id))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Task(**r) for r in found]

    def read_all(self, title: str = None, description: str = None, status: str = None, priority: str = None, project_id: int = None, created_at: Any = None, updated_at: Any = None) -> list[models.Task]:
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

    def update(self, task_id: int = None, title: str = None, description: str = None, status: str = None, priority: str = None, project_id: int = None, created_at: Any = None, updated_at: Any = None) -> models.Task:
        """Updates an existing Task. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if task_id is not None:
            criteria.append(('task_id', 'eq', task_id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise LookupError(f"Task update matched {len(found)} records")
        patch = {}
        if task_id is not None and 'task_id' in ['task_id', 'title', 'description', 'status', 'priority', 'project_id', 'created_at', 'updated_at']:
            patch['task_id'] = task_id
        if title is not None and 'title' in ['task_id', 'title', 'description', 'status', 'priority', 'project_id', 'created_at', 'updated_at']:
            patch['title'] = title
        if description is not None and 'description' in ['task_id', 'title', 'description', 'status', 'priority', 'project_id', 'created_at', 'updated_at']:
            patch['description'] = description
        if status is not None and 'status' in ['task_id', 'title', 'description', 'status', 'priority', 'project_id', 'created_at', 'updated_at']:
            patch['status'] = status
        if priority is not None and 'priority' in ['task_id', 'title', 'description', 'status', 'priority', 'project_id', 'created_at', 'updated_at']:
            patch['priority'] = priority
        if project_id is not None and 'project_id' in ['task_id', 'title', 'description', 'status', 'priority', 'project_id', 'created_at', 'updated_at']:
            patch['project_id'] = project_id
        if created_at is not None and 'created_at' in ['task_id', 'title', 'description', 'status', 'priority', 'project_id', 'created_at', 'updated_at']:
            patch['created_at'] = created_at
        if updated_at is not None and 'updated_at' in ['task_id', 'title', 'description', 'status', 'priority', 'project_id', 'created_at', 'updated_at']:
            patch['updated_at'] = updated_at
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=LookupError)
        return models.Task(**record)
