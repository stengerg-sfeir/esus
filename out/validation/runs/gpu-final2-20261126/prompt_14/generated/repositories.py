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


    def create(self, name: str = None, description: str = None, status: str = None, is_deleted: bool = None) -> models.Project:
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
        if values.get('status') is None:
            values['status'] = 'pending'
        if values.get('is_deleted') is None:
            values['is_deleted'] = False
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[])
        return models.Project(**record)

    def create_project(self, name: str = None, description: str = None, status: str = None) -> models.Project:
        """Creates a new project with the specified name, description, and status. The project is persisted in the database with a generated project_id. [crud:create: STANDARD_CRUD]"""
        values = {}
        if name is not None:
            values['name'] = name
        if description is not None:
            values['description'] = description
        if status is not None:
            values['status'] = status
        unknown = [k for k in values if k not in ['project_id', 'name', 'description', 'status', 'is_deleted']]
        if unknown:
            raise ValueError(f"cannot create Project from {unknown}")
        if values.get('status') is None:
            values['status'] = 'pending'
        if values.get('is_deleted') is None:
            values['is_deleted'] = False
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[])
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

    def read_all_projects(self) -> List[models.Project]:
        """Retrieves a list of all active projects (where is_deleted is false). Projects are returned in ascending order by project_id. [crud:read_all: READ_ALL]"""
        criteria = []
        criteria.append(('is_deleted', 'eq', False))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Project(**r) for r in found]

    def read_one(self, project_id: int = None) -> models.Project:
        """Reads one Project by its key. [crud:read_one: READ_ONE_BY_ID]"""
        found = self._store.select(self.ENTITY, [(self.PK, 'eq', project_id)])
        if not found:
            return None
        record = found[0]
        return models.Project(**record)

    def read_project_by_id(self, project_id: int = None) -> models.Project:
        """Retrieves a single project by its project_id. Returns None if the project does not exist or is soft-deleted. [crud:read_one: READ_ONE_BY_ID]"""
        found = self._store.select(self.ENTITY, [(self.PK, 'eq', project_id)])
        if not found:
            return None
        record = found[0]
        return models.Project(**record)

    def soft_delete_project(self, project_id: int = None) -> bool:
        """Marks a project as soft-deleted by setting the is_deleted field to True. The project remains in the database but is no longer visible in read_all operations. [llm-written by server — review]"""
        criteria = [('project_id', 'eq', project_id)]
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            return False
        record = found[0]
        self._store.update(self.ENTITY, self.PK, record[self.PK], {'is_deleted': True})
        return True

    def update(self, project_id: int = None, name: str = None, description: str = None, status: str = None, is_deleted: bool = None) -> models.Project:
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

    def update_project(self, project_id: int = None, name: str = None, description: str = None, status: str = None) -> models.Project:
        """Updates the name, description, and status of an existing project. The project must exist and be active (not soft-deleted). [crud:update: STANDARD_CRUD]"""
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
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=LookupError)
        return models.Project(**record)
