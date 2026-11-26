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


    def create(self, name: str = None, description: str = None, created_at: Any = None, updated_at: Any = None) -> Any:
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
        unknown = [k for k in values if k not in ['id', 'name', 'description', 'created_at', 'updated_at']]
        if unknown:
            raise ValueError(f"cannot create Project from {unknown}")
        if values.get('created_at') is None:
            values['created_at'] = datetime.datetime.now()
        if values.get('updated_at') is None:
            values['updated_at'] = datetime.datetime.now()
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[])
        return models.Project(**record)

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

    def find_project_by_name(self, name: str = None) -> models.Project | None:
        """Retrieves a project by its name, returning the project if found, otherwise null. [crud:read_one: READ_ONE_BY_ID]"""
        criteria = []
        if name is not None:
            criteria.append(('name', 'eq', name))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            return None
        record = found[0]
        return models.Project(**record)

    def count_projects_with_pending_tasks(self) -> int:
        """Returns the number of projects that have at least one task with status 'pending'. [llm-written by server — review]"""
        pending_tasks = self._store.select(self.ENTITY, [])
        count = 0
        for project in pending_tasks:
            project_id = project.get('id')
            if project_id is None:
                continue
            tasks = self._store.select("Task", [("project_id", "eq", project_id)])
            for task in tasks:
                if task.get('status') == 'pending':
                    count += 1
        return count


class TaskRepository:
    ENTITY = "Task"
    PK = "id"

    def __init__(self, store):
        self._store = store


    def create(self, title: str = None, description: str = None, priority: str = None, status: str = None, project_id: int = None, created_at: Any = None, updated_at: Any = None) -> Any:
        """Creates a new Task. [crud:create: STANDARD_CRUD]"""
        values = {}
        if title is not None:
            values['title'] = title
        if description is not None:
            values['description'] = description
        if priority is not None:
            values['priority'] = priority
        if status is not None:
            values['status'] = status
        if project_id is not None:
            values['project_id'] = project_id
        if created_at is not None:
            values['created_at'] = created_at
        if updated_at is not None:
            values['updated_at'] = updated_at
        unknown = [k for k in values if k not in ['id', 'title', 'description', 'priority', 'status', 'project_id', 'created_at', 'updated_at']]
        if unknown:
            raise ValueError(f"cannot create Task from {unknown}")
        if values.get('created_at') is None:
            values['created_at'] = datetime.datetime.now()
        if values.get('updated_at') is None:
            values['updated_at'] = datetime.datetime.now()
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[("project_id", "Project", "id", None)])
        return models.Task(**record)

    def read_all(self, title: str = None, description: str = None, priority: str = None, status: str = None, project_id: int = None, created_at: Any = None, updated_at: Any = None) -> list[models.Task]:
        """Lists every Task; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if title is not None:
            criteria.append(('title', 'eq', title))
        if description is not None:
            criteria.append(('description', 'eq', description))
        if priority is not None:
            criteria.append(('priority', 'eq', priority))
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

    def read_one(self, id: int = None) -> Any:
        """Reads one Task by its key. [crud:read_one: READ_ONE_BY_ID]"""
        found = self._store.select(self.ENTITY, [(self.PK, 'eq', id)])
        if not found:
            return None
        record = found[0]
        return models.Task(**record)

    def update(self, id: int = None, title: str = None, description: str = None, priority: str = None, status: str = None, project_id: int = None, created_at: Any = None, updated_at: Any = None) -> Any:
        """Updates an existing Task. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if id is not None:
            criteria.append(('id', 'eq', id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise LookupError(f"Task update matched {len(found)} records")
        patch = {}
        if id is not None and 'id' in ['id', 'title', 'description', 'priority', 'status', 'project_id', 'created_at', 'updated_at']:
            patch['id'] = id
        if title is not None and 'title' in ['id', 'title', 'description', 'priority', 'status', 'project_id', 'created_at', 'updated_at']:
            patch['title'] = title
        if description is not None and 'description' in ['id', 'title', 'description', 'priority', 'status', 'project_id', 'created_at', 'updated_at']:
            patch['description'] = description
        if priority is not None and 'priority' in ['id', 'title', 'description', 'priority', 'status', 'project_id', 'created_at', 'updated_at']:
            patch['priority'] = priority
        if status is not None and 'status' in ['id', 'title', 'description', 'priority', 'status', 'project_id', 'created_at', 'updated_at']:
            patch['status'] = status
        if project_id is not None and 'project_id' in ['id', 'title', 'description', 'priority', 'status', 'project_id', 'created_at', 'updated_at']:
            patch['project_id'] = project_id
        if created_at is not None and 'created_at' in ['id', 'title', 'description', 'priority', 'status', 'project_id', 'created_at', 'updated_at']:
            patch['created_at'] = created_at
        if updated_at is not None and 'updated_at' in ['id', 'title', 'description', 'priority', 'status', 'project_id', 'created_at', 'updated_at']:
            patch['updated_at'] = updated_at
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=LookupError)
        return models.Task(**record)

    def delete(self, id: int = None, title: str = None, description: str = None, priority: str = None, status: str = None, project_id: int = None, created_at: Any = None, updated_at: Any = None) -> None:
        """Deletes an existing Task. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if id is not None:
            criteria.append(('id', 'eq', id))
        if title is not None:
            criteria.append(('title', 'eq', title))
        if description is not None:
            criteria.append(('description', 'eq', description))
        if priority is not None:
            criteria.append(('priority', 'eq', priority))
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

    def find_task_by_priority_and_status(self, priority: str = None, status: str = None) -> list[models.Task]:
        """Retrieves all tasks with a specific priority and status, useful for identifying high-priority pending tasks. [crud:filter: FILTER_BY_FIELD]"""
        criteria = []
        if priority is not None:
            criteria.append(('priority', 'eq', priority))
        if status is not None:
            criteria.append(('status', 'eq', status))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Task(**r) for r in found]

    def count_tasks_by_status(self) -> dict[str, int]:
        """Returns a map of task status to the count of tasks in that status (e.g., {"pending": 5, "completed": 3}). [mechanical count by field]"""
        counts = {}
        for row in self._store.select(self.ENTITY, []):
            key = row.get('status')
            if key is not None:
                counts[key] = counts.get(key, 0) + 1
        return counts
