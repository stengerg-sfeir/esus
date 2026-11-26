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



class EmployeeRepository:
    ENTITY = "Employee"
    PK = "employee_id"

    def __init__(self, store):
        self._store = store


    def create(self, name: str = None, department_id: int = None, email: str = None) -> Any:
        """Creates a new Employee. [crud:create: STANDARD_CRUD]"""
        values = {}
        if name is not None:
            values['name'] = name
        if department_id is not None:
            values['department_id'] = department_id
        if email is not None:
            values['email'] = email
        unknown = [k for k in values if k not in ['employee_id', 'name', 'department_id', 'email']]
        if unknown:
            raise ValueError(f"cannot create Employee from {unknown}")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[("department_id", "Department", "department_id", None)])
        return models.Employee(**record)

    def read_one(self, employee_id: int = None) -> Any:
        """Reads one Employee by its key. [crud:read_one: READ_ONE_BY_ID]"""
        found = self._store.select(self.ENTITY, [(self.PK, 'eq', employee_id)])
        if not found:
            return None
        record = found[0]
        return models.Employee(**record)

    def read_all(self, name: str = None, department_id: int = None, email: str = None) -> list[models.Employee]:
        """Lists every Employee; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if name is not None:
            criteria.append(('name', 'eq', name))
        if department_id is not None:
            criteria.append(('department_id', 'eq', department_id))
        if email is not None:
            criteria.append(('email', 'eq', email))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Employee(**r) for r in found]

    def update(self, employee_id: int = None, name: str = None, department_id: int = None, email: str = None) -> Any:
        """Updates an existing Employee. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if employee_id is not None:
            criteria.append(('employee_id', 'eq', employee_id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise LookupError(f"Employee update matched {len(found)} records")
        patch = {}
        if employee_id is not None and 'employee_id' in ['employee_id', 'name', 'department_id', 'email']:
            patch['employee_id'] = employee_id
        if name is not None and 'name' in ['employee_id', 'name', 'department_id', 'email']:
            patch['name'] = name
        if department_id is not None and 'department_id' in ['employee_id', 'name', 'department_id', 'email']:
            patch['department_id'] = department_id
        if email is not None and 'email' in ['employee_id', 'name', 'department_id', 'email']:
            patch['email'] = email
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=LookupError)
        return models.Employee(**record)

    def delete(self, employee_id: int = None, name: str = None, department_id: int = None, email: str = None) -> None:
        """Deletes an existing Employee. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if employee_id is not None:
            criteria.append(('employee_id', 'eq', employee_id))
        if name is not None:
            criteria.append(('name', 'eq', name))
        if department_id is not None:
            criteria.append(('department_id', 'eq', department_id))
        if email is not None:
            criteria.append(('email', 'eq', email))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise LookupError(f"Employee delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None

    def get_employees_by_department_id(self, department_id: int = None) -> list[models.Employee]:
        """Lists the Employee records belonging to one Department. [crud:filter: FILTER_BY_FIELD: by parameter shape]"""
        criteria = []
        if department_id is not None:
            criteria.append(('department_id', 'eq', department_id))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Employee(**r) for r in found]

    def create_employee(self, name: str = None, department_id: int = None, email: str = None) -> Any:
        """Creates a new employee record with the provided name, department ID, and email. [crud:create: STANDARD_CRUD]"""
        values = {}
        if name is not None:
            values['name'] = name
        if department_id is not None:
            values['department_id'] = department_id
        if email is not None:
            values['email'] = email
        unknown = [k for k in values if k not in ['employee_id', 'name', 'department_id', 'email']]
        if unknown:
            raise ValueError(f"cannot create Employee from {unknown}")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[("department_id", "Department", "department_id", None)])
        return models.Employee(**record)

    def read_employee_by_id(self, employee_id: int = None) -> models.Employee | None:
        """Retrieves an employee record by their unique employee ID. [crud:read_one: READ_ONE_BY_ID]"""
        found = self._store.select(self.ENTITY, [(self.PK, 'eq', employee_id)])
        if not found:
            return None
        record = found[0]
        return models.Employee(**record)

    def read_all_employees(self) -> list[models.Employee]:
        """Returns a list of all employee records. [crud:read_all: READ_ALL]"""
        criteria = []
        found = self._store.select(self.ENTITY, criteria)
        return [models.Employee(**r) for r in found]

    def update_employee(self, employee_id: int = None, name: str = None, department_id: int = None, email: str = None) -> bool:
        """Updates an existing employee's name, department ID, and email based on the provided employee ID. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if employee_id is not None:
            criteria.append(('employee_id', 'eq', employee_id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise LookupError(f"Employee update matched {len(found)} records")
        patch = {}
        if employee_id is not None and 'employee_id' in ['employee_id', 'name', 'department_id', 'email']:
            patch['employee_id'] = employee_id
        if name is not None and 'name' in ['employee_id', 'name', 'department_id', 'email']:
            patch['name'] = name
        if department_id is not None and 'department_id' in ['employee_id', 'name', 'department_id', 'email']:
            patch['department_id'] = department_id
        if email is not None and 'email' in ['employee_id', 'name', 'department_id', 'email']:
            patch['email'] = email
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=LookupError)
        return models.Employee(**record)

    def delete_employee(self, employee_id: int = None) -> bool:
        """Deletes an employee record by their employee ID. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if employee_id is not None:
            criteria.append(('employee_id', 'eq', employee_id))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise LookupError(f"Employee delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None


class DepartmentRepository:
    ENTITY = "Department"
    PK = "department_id"

    def __init__(self, store):
        self._store = store


    def read_all(self, name: str = None) -> list[models.Department]:
        """Lists every Department; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if name is not None:
            criteria.append(('name', 'eq', name))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Department(**r) for r in found]

    def read_one(self, department_id: int = None) -> Any:
        """Reads one Department by its key. [crud:read_one: READ_ONE_BY_ID]"""
        found = self._store.select(self.ENTITY, [(self.PK, 'eq', department_id)])
        if not found:
            return None
        record = found[0]
        return models.Department(**record)

    def read_department_by_id(self, department_id: int = None) -> models.Department | None:
        """Retrieves a department record by its unique department ID. [crud:read_one: READ_ONE_BY_ID]"""
        found = self._store.select(self.ENTITY, [(self.PK, 'eq', department_id)])
        if not found:
            return None
        record = found[0]
        return models.Department(**record)

    def read_all_departments(self) -> list[models.Department]:
        """Returns a list of all department records. [crud:read_all: READ_ALL]"""
        criteria = []
        found = self._store.select(self.ENTITY, criteria)
        return [models.Department(**r) for r in found]
