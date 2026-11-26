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
    PK = "id"

    def __init__(self, store):
        self._store = store


    def create(self, name: str = None, email: str = None, age: int = None, salary: int = None) -> Any:
        """Creates a new Employee. [crud:create: STANDARD_CRUD]"""
        values = {}
        if name is not None:
            values['name'] = name
        if email is not None:
            values['email'] = email
        if age is not None:
            values['age'] = age
        if salary is not None:
            values['salary'] = salary
        unknown = [k for k in values if k not in ['id', 'name', 'email', 'age', 'salary']]
        if unknown:
            raise ValueError(f"cannot create Employee from {unknown}")
        value = values.get('age')
        if value is not None and value <= 0:
            raise ValueError(f"Employee.age must be > 0, got {value!r}")
        value = values.get('salary')
        if value is not None and value <= 0:
            raise ValueError(f"Employee.salary must be > 0, got {value!r}")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[])
        return models.Employee(**record)

    def read_one(self, id: int = None) -> Any:
        """Reads one Employee by its key. [crud:read_one: READ_ONE_BY_ID]"""
        record = self._store.get(self.ENTITY, self.PK, id, error=errors.EmployeeNotFoundError)
        return models.Employee(**record)

    def read_all(self, name: str = None, email: str = None, age: int = None, salary: int = None) -> list[models.Employee]:
        """Lists every Employee; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if name is not None:
            criteria.append(('name', 'eq', name))
        if email is not None:
            criteria.append(('email', 'eq', email))
        if age is not None:
            criteria.append(('age', 'eq', age))
        if salary is not None:
            criteria.append(('salary', 'eq', salary))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Employee(**r) for r in found]

    def update(self, id: int = None, name: str = None, email: str = None, age: int = None, salary: int = None) -> Any:
        """Updates an existing Employee. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if id is not None:
            criteria.append(('id', 'eq', id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise errors.EmployeeNotFoundError(f"Employee update matched {len(found)} records")
        patch = {}
        if id is not None and 'id' in ['id', 'name', 'email', 'age', 'salary']:
            patch['id'] = id
        if name is not None and 'name' in ['id', 'name', 'email', 'age', 'salary']:
            patch['name'] = name
        if email is not None and 'email' in ['id', 'name', 'email', 'age', 'salary']:
            patch['email'] = email
        if age is not None and 'age' in ['id', 'name', 'email', 'age', 'salary']:
            patch['age'] = age
        if salary is not None and 'salary' in ['id', 'name', 'email', 'age', 'salary']:
            patch['salary'] = salary
        value = patch.get('age')
        if value is not None and value <= 0:
            raise ValueError(f"Employee.age must be > 0, got {value!r}")
        value = patch.get('salary')
        if value is not None and value <= 0:
            raise ValueError(f"Employee.salary must be > 0, got {value!r}")
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=errors.EmployeeNotFoundError)
        return models.Employee(**record)

    def delete(self, id: int = None, name: str = None, email: str = None, age: int = None, salary: int = None) -> None:
        """Deletes an existing Employee. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if id is not None:
            criteria.append(('id', 'eq', id))
        if name is not None:
            criteria.append(('name', 'eq', name))
        if email is not None:
            criteria.append(('email', 'eq', email))
        if age is not None:
            criteria.append(('age', 'eq', age))
        if salary is not None:
            criteria.append(('salary', 'eq', salary))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise errors.EmployeeNotFoundError(f"Employee delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None
