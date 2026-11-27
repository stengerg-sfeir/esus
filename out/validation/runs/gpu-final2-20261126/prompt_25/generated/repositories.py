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



class DepartmentRepository:
    ENTITY = "Department"
    PK = "department_id"

    def __init__(self, store):
        self._store = store


    def create(self, department_name: str = None) -> models.Department:
        """Creates a new Department. [crud:create: STANDARD_CRUD]"""
        values = {}
        if department_name is not None:
            values['department_name'] = department_name
        unknown = [k for k in values if k not in ['department_id', 'department_name']]
        if unknown:
            raise ValueError(f"cannot create Department from {unknown}")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[])
        return models.Department(**record)

    def create_department(self, department_name: str = None) -> None:
        """Creates a new department with the specified department name. [crud:create: STANDARD_CRUD]"""
        values = {}
        if department_name is not None:
            values['department_name'] = department_name
        unknown = [k for k in values if k not in ['department_id', 'department_name']]
        if unknown:
            raise ValueError(f"cannot create Department from {unknown}")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[])
        return None

    def read_all(self, department_name: str = None) -> list[models.Department]:
        """Lists every Department; optional fields narrow the result. [mechanical contained-name filter]"""
        criteria = []
        if department_name is not None:
            criteria.append(('department_name', 'eq', department_name))
        found = self._store.select(self.ENTITY, criteria)
        return _model_list([models.Department(**row) for row in found], models.Department)

    def read_all_departments(self) -> list[dict]:
        """Retrieves a list of all departments with their names. [crud:read_all: READ_ALL]"""
        criteria = []
        found = self._store.select(self.ENTITY, criteria)
        return [models.Department(**r) for r in found]

    def read_department_by_id(self, department_id: int = None) -> Dict[str, Any] | None:
        """Retrieves a department record by department ID. [llm-written by server — review]"""
        record = self._store.get(self.ENTITY, self.PK, department_id)
        if record is None:
            return None
        return record

    def read_one(self, department_id: int = None) -> models.Department:
        """Reads one Department by its key. [crud:read_one: READ_ONE_BY_ID]"""
        found = self._store.select(self.ENTITY, [(self.PK, 'eq', department_id)])
        if not found:
            return None
        record = found[0]
        return models.Department(**record)


class EmployeeRepository:
    ENTITY = "Employee"
    PK = "employee_id"

    def __init__(self, store):
        self._store = store


    def create(self, first_name: str = None, last_name: str = None, email: str = None, department_id: int = None) -> models.Employee:
        """Creates a new Employee. [crud:create: STANDARD_CRUD]"""
        values = {}
        if first_name is not None:
            values['first_name'] = first_name
        if last_name is not None:
            values['last_name'] = last_name
        if email is not None:
            values['email'] = email
        if department_id is not None:
            values['department_id'] = department_id
        unknown = [k for k in values if k not in ['employee_id', 'first_name', 'last_name', 'email', 'department_id']]
        if unknown:
            raise ValueError(f"cannot create Employee from {unknown}")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[("department_id", "Department", "department_id", None)])
        return models.Employee(**record)

    def create_employee(self, first_name: str = None, last_name: str = None, email: str = None, department_id: int = None) -> None:
        """Creates a new employee record with the specified first name, last name, email, and department ID. [crud:create: STANDARD_CRUD]"""
        values = {}
        if first_name is not None:
            values['first_name'] = first_name
        if last_name is not None:
            values['last_name'] = last_name
        if email is not None:
            values['email'] = email
        if department_id is not None:
            values['department_id'] = department_id
        unknown = [k for k in values if k not in ['employee_id', 'first_name', 'last_name', 'email', 'department_id']]
        if unknown:
            raise ValueError(f"cannot create Employee from {unknown}")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[("department_id", "Department", "department_id", None)])
        return None

    def delete(self, employee_id: int = None, first_name: str = None, last_name: str = None, email: str = None, department_id: int = None) -> None:
        """Deletes an existing Employee. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if employee_id is not None:
            criteria.append(('employee_id', 'eq', employee_id))
        if first_name is not None:
            criteria.append(('first_name', 'eq', first_name))
        if last_name is not None:
            criteria.append(('last_name', 'eq', last_name))
        if email is not None:
            criteria.append(('email', 'eq', email))
        if department_id is not None:
            criteria.append(('department_id', 'eq', department_id))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise LookupError(f"Employee delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None

    def delete_employee(self, employee_id: int = None) -> None:
        """Deletes an employee record by employee ID. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if employee_id is not None:
            criteria.append(('employee_id', 'eq', employee_id))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise LookupError(f"Employee delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None

    def get_employees_by_department_id(self, department_id: int = None) -> list[models.Employee]:
        """Lists the Employee records belonging to one Department. [mechanical contained-name filter]"""
        criteria = []
        if department_id is not None:
            criteria.append(('department_id', 'eq', department_id))
        found = self._store.select(self.ENTITY, criteria)
        return _model_list([models.Employee(**row) for row in found], models.Employee)

    def read_all(self, first_name: str = None, last_name: str = None, email: str = None, department_id: int = None) -> list[models.Employee]:
        """Lists every Employee; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if first_name is not None:
            criteria.append(('first_name', 'eq', first_name))
        if last_name is not None:
            criteria.append(('last_name', 'eq', last_name))
        if email is not None:
            criteria.append(('email', 'eq', email))
        if department_id is not None:
            criteria.append(('department_id', 'eq', department_id))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Employee(**r) for r in found]

    def read_all_employees(self) -> list[dict]:
        """Retrieves a list of all employees with their associated department names. [crud:read_all: READ_ALL]"""
        criteria = []
        found = self._store.select(self.ENTITY, criteria)
        return [models.Employee(**r) for r in found]

    def read_employee_by_id(self, employee_id: int = None) -> Dict[str, Any] | None:
        """Retrieves an employee record by employee ID. [llm-written by server — review]"""
        record = self._store.get(self.ENTITY, self.PK, employee_id)
        if record is None:
            return None
        return record

    def read_one(self, employee_id: int = None) -> models.Employee:
        """Reads one Employee by its key. [crud:read_one: READ_ONE_BY_ID]"""
        found = self._store.select(self.ENTITY, [(self.PK, 'eq', employee_id)])
        if not found:
            return None
        record = found[0]
        return models.Employee(**record)

    def update(self, employee_id: int = None, first_name: str = None, last_name: str = None, email: str = None, department_id: int = None) -> models.Employee:
        """Updates an existing Employee. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if employee_id is not None:
            criteria.append(('employee_id', 'eq', employee_id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise LookupError(f"Employee update matched {len(found)} records")
        patch = {}
        if employee_id is not None and 'employee_id' in ['employee_id', 'first_name', 'last_name', 'email', 'department_id']:
            patch['employee_id'] = employee_id
        if first_name is not None and 'first_name' in ['employee_id', 'first_name', 'last_name', 'email', 'department_id']:
            patch['first_name'] = first_name
        if last_name is not None and 'last_name' in ['employee_id', 'first_name', 'last_name', 'email', 'department_id']:
            patch['last_name'] = last_name
        if email is not None and 'email' in ['employee_id', 'first_name', 'last_name', 'email', 'department_id']:
            patch['email'] = email
        if department_id is not None and 'department_id' in ['employee_id', 'first_name', 'last_name', 'email', 'department_id']:
            patch['department_id'] = department_id
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=LookupError)
        return models.Employee(**record)

    def update_employee(self, employee_id: int = None, first_name: str = None, last_name: str = None, email: str = None, department_id: int = None) -> None:
        """Updates an existing employee's first name, last name, email, or department ID. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if employee_id is not None:
            criteria.append(('employee_id', 'eq', employee_id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise LookupError(f"Employee update matched {len(found)} records")
        patch = {}
        if employee_id is not None and 'employee_id' in ['employee_id', 'first_name', 'last_name', 'email', 'department_id']:
            patch['employee_id'] = employee_id
        if first_name is not None and 'first_name' in ['employee_id', 'first_name', 'last_name', 'email', 'department_id']:
            patch['first_name'] = first_name
        if last_name is not None and 'last_name' in ['employee_id', 'first_name', 'last_name', 'email', 'department_id']:
            patch['last_name'] = last_name
        if email is not None and 'email' in ['employee_id', 'first_name', 'last_name', 'email', 'department_id']:
            patch['email'] = email
        if department_id is not None and 'department_id' in ['employee_id', 'first_name', 'last_name', 'email', 'department_id']:
            patch['department_id'] = department_id
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=LookupError)
        return models.Employee(**record)
