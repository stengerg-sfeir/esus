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


    def create(self, name: str = None, description: str = None, status: str = None, is_deleted: bool = None) -> Any:
        """Creates a new Project. [crud:create: STANDARD_CRUD]"""
        values = {}
        if name is not None:
            values['name'] = name
        if description is not None:
            values['description'] = description
        if status is not None:
            values['status'] = status
        if is_deleted is not None:
            values['is_deleted'] = is_deleted
        unknown = [k for k in values if k not in ['project_id', 'name', 'description', 'status', 'is_deleted']]
        if unknown:
            raise ValueError(f"cannot create Project from {unknown}")
        if values.get('is_deleted') is None:
            values['is_deleted'] = False
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[])
        return models.Project(**record)

    def read_all(self, name: str = None, description: str = None, status: str = None, is_deleted: bool = None) -> list[models.Project]:
        """Lists every Project; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if name is not None:
            criteria.append(('name', 'eq', name))
        if description is not None:
            criteria.append(('description', 'eq', description))
        if status is not None:
            criteria.append(('status', 'eq', status))
        if is_deleted is not None:
            criteria.append(('is_deleted', 'eq', is_deleted))
        if is_deleted is None:
            criteria.append(('is_deleted', 'eq', False))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Project(**r) for r in found]

    def update(self, project_id: int = None, name: str = None, description: str = None, status: str = None, is_deleted: bool = None) -> Any:
        """Updates an existing Project. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if project_id is not None:
            criteria.append(('project_id', 'eq', project_id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise LookupError(f"Project update matched {len(found)} records")
        patch = {}
        if project_id is not None and 'project_id' in ['project_id', 'name', 'description', 'status', 'is_deleted']:
            patch['project_id'] = project_id
        if name is not None and 'name' in ['project_id', 'name', 'description', 'status', 'is_deleted']:
            patch['name'] = name
        if description is not None and 'description' in ['project_id', 'name', 'description', 'status', 'is_deleted']:
            patch['description'] = description
        if status is not None and 'status' in ['project_id', 'name', 'description', 'status', 'is_deleted']:
            patch['status'] = status
        if is_deleted is not None and 'is_deleted' in ['project_id', 'name', 'description', 'status', 'is_deleted']:
            patch['is_deleted'] = is_deleted
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=LookupError)
        return models.Project(**record)

    def delete(self, project_id: int = None, name: str = None, description: str = None, status: str = None, is_deleted: bool = None) -> None:
        """Deletes an existing Project. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if project_id is not None:
            criteria.append(('project_id', 'eq', project_id))
        if name is not None:
            criteria.append(('name', 'eq', name))
        if description is not None:
            criteria.append(('description', 'eq', description))
        if status is not None:
            criteria.append(('status', 'eq', status))
        if is_deleted is not None:
            criteria.append(('is_deleted', 'eq', is_deleted))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise LookupError(f"Project delete matched no records")
        for record in found:
            self._store.update(self.ENTITY, self.PK, record[self.PK], {'is_deleted': True})
        return None

    def find_project_by_name(self, name: str = None) -> models.Project | None:
        """Retrieves a project by its name, returning the project if found; returns None if no project with the given name exists. [crud:read_one: READ_ONE_BY_ID]"""
        criteria = []
        if name is not None:
            criteria.append(('name', 'eq', name))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            return None
        record = found[0]
        return models.Project(**record)

    def find_project_by_status(self, status: str = None) -> list[models.Project]:
        """Retrieves all projects that have a specific status, filtering out deleted projects. [crud:filter: FILTER_BY_FIELD]"""
        criteria = []
        if status is not None:
            criteria.append(('status', 'eq', status))
        criteria.append(('is_deleted', 'eq', False))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Project(**r) for r in found]

    def count_active_projects(self) -> int:
        """Returns the number of active projects (projects with is_deleted = False). [llm-written by server — review]"""
        criteria = [('is_deleted', 'eq', False)]
        found = self._store.select(self.ENTITY, criteria)
        return len(found)
