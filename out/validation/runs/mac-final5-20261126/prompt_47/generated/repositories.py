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

    def update(self, id: int = None, name: str = None, description: str = None, created_at: Any = None, updated_at: Any = None) -> Any:
        """Updates an existing Project. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if id is not None:
            criteria.append(('id', 'eq', id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise LookupError(f"Project update matched {len(found)} records")
        patch = {}
        if id is not None and 'id' in ['id', 'name', 'description', 'created_at', 'updated_at']:
            patch['id'] = id
        if name is not None and 'name' in ['id', 'name', 'description', 'created_at', 'updated_at']:
            patch['name'] = name
        if description is not None and 'description' in ['id', 'name', 'description', 'created_at', 'updated_at']:
            patch['description'] = description
        if created_at is not None and 'created_at' in ['id', 'name', 'description', 'created_at', 'updated_at']:
            patch['created_at'] = created_at
        if updated_at is not None and 'updated_at' in ['id', 'name', 'description', 'created_at', 'updated_at']:
            patch['updated_at'] = updated_at
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=LookupError)
        return models.Project(**record)

    def delete(self, id: int = None, name: str = None, description: str = None, created_at: Any = None, updated_at: Any = None) -> None:
        """Deletes an existing Project. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if id is not None:
            criteria.append(('id', 'eq', id))
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


class TaskRepository:
    ENTITY = "Task"
    PK = "id"

    def __init__(self, store):
        self._store = store


    def create(self, title: str = None, description: str = None, project_id: int = None, created_at: Any = None, updated_at: Any = None) -> Any:
        """Creates a new Task. [crud:create: STANDARD_CRUD]"""
        values = {}
        if title is not None:
            values['title'] = title
        if description is not None:
            values['description'] = description
        if project_id is not None:
            values['project_id'] = project_id
        if created_at is not None:
            values['created_at'] = created_at
        if updated_at is not None:
            values['updated_at'] = updated_at
        unknown = [k for k in values if k not in ['id', 'title', 'description', 'project_id', 'created_at', 'updated_at']]
        if unknown:
            raise ValueError(f"cannot create Task from {unknown}")
        if values.get('created_at') is None:
            values['created_at'] = datetime.datetime.now()
        if values.get('updated_at') is None:
            values['updated_at'] = datetime.datetime.now()
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[("project_id", "Project", "id", None)])
        return models.Task(**record)

    def read_all(self, title: str = None, description: str = None, project_id: int = None, created_at: Any = None, updated_at: Any = None) -> list[models.Task]:
        """Lists every Task; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if title is not None:
            criteria.append(('title', 'eq', title))
        if description is not None:
            criteria.append(('description', 'eq', description))
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

    def update(self, id: int = None, title: str = None, description: str = None, project_id: int = None, created_at: Any = None, updated_at: Any = None) -> Any:
        """Updates an existing Task. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if id is not None:
            criteria.append(('id', 'eq', id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise LookupError(f"Task update matched {len(found)} records")
        patch = {}
        if id is not None and 'id' in ['id', 'title', 'description', 'project_id', 'created_at', 'updated_at']:
            patch['id'] = id
        if title is not None and 'title' in ['id', 'title', 'description', 'project_id', 'created_at', 'updated_at']:
            patch['title'] = title
        if description is not None and 'description' in ['id', 'title', 'description', 'project_id', 'created_at', 'updated_at']:
            patch['description'] = description
        if project_id is not None and 'project_id' in ['id', 'title', 'description', 'project_id', 'created_at', 'updated_at']:
            patch['project_id'] = project_id
        if created_at is not None and 'created_at' in ['id', 'title', 'description', 'project_id', 'created_at', 'updated_at']:
            patch['created_at'] = created_at
        if updated_at is not None and 'updated_at' in ['id', 'title', 'description', 'project_id', 'created_at', 'updated_at']:
            patch['updated_at'] = updated_at
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=LookupError)
        return models.Task(**record)

    def delete(self, id: int = None, title: str = None, description: str = None, project_id: int = None, created_at: Any = None, updated_at: Any = None) -> None:
        """Deletes an existing Task. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if id is not None:
            criteria.append(('id', 'eq', id))
        if title is not None:
            criteria.append(('title', 'eq', title))
        if description is not None:
            criteria.append(('description', 'eq', description))
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


class TeamMemberRepository:
    ENTITY = "TeamMember"
    PK = "id"

    def __init__(self, store):
        self._store = store


    def create(self, name: str = None, email: str = None, role: str = None, created_at: Any = None) -> Any:
        """Creates a new TeamMember. [crud:create: STANDARD_CRUD]"""
        values = {}
        if name is not None:
            values['name'] = name
        if email is not None:
            values['email'] = email
        if role is not None:
            values['role'] = role
        if created_at is not None:
            values['created_at'] = created_at
        unknown = [k for k in values if k not in ['id', 'name', 'email', 'role', 'created_at']]
        if unknown:
            raise ValueError(f"cannot create TeamMember from {unknown}")
        if values.get('created_at') is None:
            values['created_at'] = datetime.datetime.now()
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[])
        return models.TeamMember(**record)

    def read_all(self, name: str = None, email: str = None, role: str = None, created_at: Any = None) -> list[models.TeamMember]:
        """Lists every TeamMember; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if name is not None:
            criteria.append(('name', 'eq', name))
        if email is not None:
            criteria.append(('email', 'eq', email))
        if role is not None:
            criteria.append(('role', 'eq', role))
        if created_at is not None:
            criteria.append(('created_at', 'eq', created_at))
        found = self._store.select(self.ENTITY, criteria)
        return [models.TeamMember(**r) for r in found]

    def read_one(self, id: int = None) -> Any:
        """Reads one TeamMember by its key. [crud:read_one: READ_ONE_BY_ID]"""
        found = self._store.select(self.ENTITY, [(self.PK, 'eq', id)])
        if not found:
            return None
        record = found[0]
        return models.TeamMember(**record)

    def update(self, id: int = None, name: str = None, email: str = None, role: str = None, created_at: Any = None) -> Any:
        """Updates an existing TeamMember. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if id is not None:
            criteria.append(('id', 'eq', id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise LookupError(f"TeamMember update matched {len(found)} records")
        patch = {}
        if id is not None and 'id' in ['id', 'name', 'email', 'role', 'created_at']:
            patch['id'] = id
        if name is not None and 'name' in ['id', 'name', 'email', 'role', 'created_at']:
            patch['name'] = name
        if email is not None and 'email' in ['id', 'name', 'email', 'role', 'created_at']:
            patch['email'] = email
        if role is not None and 'role' in ['id', 'name', 'email', 'role', 'created_at']:
            patch['role'] = role
        if created_at is not None and 'created_at' in ['id', 'name', 'email', 'role', 'created_at']:
            patch['created_at'] = created_at
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=LookupError)
        return models.TeamMember(**record)

    def delete(self, id: int = None, name: str = None, email: str = None, role: str = None, created_at: Any = None) -> None:
        """Deletes an existing TeamMember. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if id is not None:
            criteria.append(('id', 'eq', id))
        if name is not None:
            criteria.append(('name', 'eq', name))
        if email is not None:
            criteria.append(('email', 'eq', email))
        if role is not None:
            criteria.append(('role', 'eq', role))
        if created_at is not None:
            criteria.append(('created_at', 'eq', created_at))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise LookupError(f"TeamMember delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None


class TaskAssignmentRepository:
    ENTITY = "TaskAssignment"
    PK = "id"

    def __init__(self, store):
        self._store = store


    def create(self, task_id: int = None, member_id: int = None, responsibility_type: str = None, assigned_at: Any = None, updated_at: Any = None) -> Any:
        """Creates a new TaskAssignment. [crud:create: STANDARD_CRUD]"""
        values = {}
        if task_id is not None:
            values['task_id'] = task_id
        if member_id is not None:
            values['member_id'] = member_id
        if responsibility_type is not None:
            values['responsibility_type'] = responsibility_type
        if assigned_at is not None:
            values['assigned_at'] = assigned_at
        if updated_at is not None:
            values['updated_at'] = updated_at
        unknown = [k for k in values if k not in ['id', 'task_id', 'member_id', 'responsibility_type', 'assigned_at', 'updated_at']]
        if unknown:
            raise ValueError(f"cannot create TaskAssignment from {unknown}")
        if values.get('updated_at') is None:
            values['updated_at'] = datetime.datetime.now()
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[("task_id", "Task", "id", None), ("member_id", "TeamMember", "id", None)])
        return models.TaskAssignment(**record)

    def read_all(self, task_id: int = None, member_id: int = None, responsibility_type: str = None, assigned_at: Any = None, updated_at: Any = None) -> list[models.TaskAssignment]:
        """Lists every TaskAssignment; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if task_id is not None:
            criteria.append(('task_id', 'eq', task_id))
        if member_id is not None:
            criteria.append(('member_id', 'eq', member_id))
        if responsibility_type is not None:
            criteria.append(('responsibility_type', 'eq', responsibility_type))
        if assigned_at is not None:
            criteria.append(('assigned_at', 'eq', assigned_at))
        if updated_at is not None:
            criteria.append(('updated_at', 'eq', updated_at))
        found = self._store.select(self.ENTITY, criteria)
        return [models.TaskAssignment(**r) for r in found]

    def read_one(self, id: int = None) -> Any:
        """Reads one TaskAssignment by its key. [crud:read_one: READ_ONE_BY_ID]"""
        found = self._store.select(self.ENTITY, [(self.PK, 'eq', id)])
        if not found:
            return None
        record = found[0]
        return models.TaskAssignment(**record)

    def update(self, id: int = None, task_id: int = None, member_id: int = None, responsibility_type: str = None, assigned_at: Any = None, updated_at: Any = None) -> Any:
        """Updates an existing TaskAssignment. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if id is not None:
            criteria.append(('id', 'eq', id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise LookupError(f"TaskAssignment update matched {len(found)} records")
        patch = {}
        if id is not None and 'id' in ['id', 'task_id', 'member_id', 'responsibility_type', 'assigned_at', 'updated_at']:
            patch['id'] = id
        if task_id is not None and 'task_id' in ['id', 'task_id', 'member_id', 'responsibility_type', 'assigned_at', 'updated_at']:
            patch['task_id'] = task_id
        if member_id is not None and 'member_id' in ['id', 'task_id', 'member_id', 'responsibility_type', 'assigned_at', 'updated_at']:
            patch['member_id'] = member_id
        if responsibility_type is not None and 'responsibility_type' in ['id', 'task_id', 'member_id', 'responsibility_type', 'assigned_at', 'updated_at']:
            patch['responsibility_type'] = responsibility_type
        if assigned_at is not None and 'assigned_at' in ['id', 'task_id', 'member_id', 'responsibility_type', 'assigned_at', 'updated_at']:
            patch['assigned_at'] = assigned_at
        if updated_at is not None and 'updated_at' in ['id', 'task_id', 'member_id', 'responsibility_type', 'assigned_at', 'updated_at']:
            patch['updated_at'] = updated_at
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=LookupError)
        return models.TaskAssignment(**record)

    def delete(self, id: int = None, task_id: int = None, member_id: int = None, responsibility_type: str = None, assigned_at: Any = None, updated_at: Any = None) -> None:
        """Deletes an existing TaskAssignment. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if id is not None:
            criteria.append(('id', 'eq', id))
        if task_id is not None:
            criteria.append(('task_id', 'eq', task_id))
        if member_id is not None:
            criteria.append(('member_id', 'eq', member_id))
        if responsibility_type is not None:
            criteria.append(('responsibility_type', 'eq', responsibility_type))
        if assigned_at is not None:
            criteria.append(('assigned_at', 'eq', assigned_at))
        if updated_at is not None:
            criteria.append(('updated_at', 'eq', updated_at))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise LookupError(f"TaskAssignment delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None

    def findTaskAssignmentsByTaskId(self, taskId: int = None) -> list[models.TaskAssignment]:
        """Retrieves all task assignments associated with a specific task, including the team member's name and role. [crud:filter: FILTER_BY_FIELD]"""
        criteria = []
        if taskId is not None:
            criteria.append(('task_id', 'eq', taskId))
        found = self._store.select(self.ENTITY, criteria)
        return [models.TaskAssignment(**r) for r in found]

    def findTaskAssignmentsByMemberId(self, memberId: int = None) -> list[models.TaskAssignment]:
        """Retrieves all task assignments where a specific team member is assigned, including the task title and responsibility type. [crud:filter: FILTER_BY_FIELD]"""
        criteria = []
        if memberId is not None:
            criteria.append(('member_id', 'eq', memberId))
        found = self._store.select(self.ENTITY, criteria)
        return [models.TaskAssignment(**r) for r in found]

    def findTaskAssignmentsByResponsibilityType(self, responsibilityType: str = None) -> list[models.TaskAssignment]:
        """Retrieves all task assignments with a specific responsibility type, such as 'designer' or 'developer'. [crud:filter: FILTER_BY_FIELD]"""
        criteria = []
        if responsibilityType is not None:
            criteria.append(('responsibility_type', 'eq', responsibilityType))
        found = self._store.select(self.ENTITY, criteria)
        return [models.TaskAssignment(**r) for r in found]

    def getTaskAssignmentCountByProject(self, id: int = None) -> dict[str, int]:
        """Returns the total number of task assignments linked to each project, grouped by project name. [AGGREGATE_BY_FK_AND_DATE via answered slots: date_field=assigned_at, aggregate_func=COUNT]"""
        result = {}
        for record in self._store.select(self.ENTITY, []):
            key = record.get('task_id')
            result[key] = result.get(key, 0) + 1
        return result
