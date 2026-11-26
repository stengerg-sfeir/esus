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


    def read_one(self, employee_id: int = None) -> Any:
        """Reads one Employee by its key. [crud:read_one: READ_ONE_BY_ID]"""
        found = self._store.select(self.ENTITY, [(self.PK, 'eq', employee_id)])
        if not found:
            return None
        record = found[0]
        return models.Employee(**record)

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

    def get_employees_by_department_id(self, department_id: int = None) -> list[models.Employee]:
        """Lists the Employee records belonging to one Department. [crud:filter: FILTER_BY_FIELD: by parameter shape]"""
        criteria = []
        if department_id is not None:
            criteria.append(('department_id', 'eq', department_id))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Employee(**r) for r in found]

    def find_employee_by_email(self, email: str = None) -> Any:
        """Retrieve an employee record by their email address. [crud:read_one: READ_ONE_BY_ID]"""
        criteria = []
        if email is not None:
            criteria.append(('email', 'eq', email))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            return None
        record = found[0]
        return models.Employee(**record)

    def find_employees_by_department(self, department_id: int = None) -> list[models.Employee]:
        """Retrieve a list of employees belonging to a specific department by department ID. [crud:filter: FILTER_BY_FIELD]"""
        criteria = []
        if department_id is not None:
            criteria.append(('department_id', 'eq', department_id))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Employee(**r) for r in found]


class DepartmentRepository:
    ENTITY = "Department"
    PK = "department_id"

    def __init__(self, store):
        self._store = store


    def read_all(self, department_name: str = None) -> list[models.Department]:
        """Lists every Department; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if department_name is not None:
            criteria.append(('department_name', 'eq', department_name))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Department(**r) for r in found]

    def read_one(self, department_id: int = None) -> Any:
        """Reads one Department by its key. [crud:read_one: READ_ONE_BY_ID]"""
        found = self._store.select(self.ENTITY, [(self.PK, 'eq', department_id)])
        if not found:
            return None
        record = found[0]
        return models.Department(**record)

    def find_department_by_name(self, department_name: str = None) -> Any:
        """Retrieve a department record by its name. [crud:read_one: READ_ONE_BY_ID]"""
        criteria = []
        if department_name is not None:
            criteria.append(('department_name', 'eq', department_name))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            return None
        record = found[0]
        return models.Department(**record)
