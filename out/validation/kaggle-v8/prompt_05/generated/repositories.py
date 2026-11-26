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



class ContactRepository:
    ENTITY = "Contact"
    PK = "id"

    def __init__(self, store):
        self._store = store


    def create(self, name: str = None, email: str = None, phone_number: str = None) -> Any:
        """Creates a new Contact. [crud:create: STANDARD_CRUD]"""
        values = {}
        if name is not None:
            values['name'] = name
        if email is not None:
            values['email'] = email
        if phone_number is not None:
            values['phone_number'] = phone_number
        unknown = [k for k in values if k not in ['id', 'name', 'email', 'phone_number']]
        if unknown:
            raise ValueError(f"cannot create Contact from {unknown}")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[])
        return models.Contact(**record)

    def read_all(self, name: str = None, email: str = None, phone_number: str = None) -> list[models.Contact]:
        """Lists every Contact; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if name is not None:
            criteria.append(('name', 'eq', name))
        if email is not None:
            criteria.append(('email', 'eq', email))
        if phone_number is not None:
            criteria.append(('phone_number', 'eq', phone_number))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Contact(**r) for r in found]

    def update(self, id: int = None, name: str = None, email: str = None, phone_number: str = None) -> Any:
        """Updates an existing Contact. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if id is not None:
            criteria.append(('id', 'eq', id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise LookupError(f"Contact update matched {len(found)} records")
        patch = {}
        if id is not None and 'id' in ['id', 'name', 'email', 'phone_number']:
            patch['id'] = id
        if name is not None and 'name' in ['id', 'name', 'email', 'phone_number']:
            patch['name'] = name
        if email is not None and 'email' in ['id', 'name', 'email', 'phone_number']:
            patch['email'] = email
        if phone_number is not None and 'phone_number' in ['id', 'name', 'email', 'phone_number']:
            patch['phone_number'] = phone_number
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=LookupError)
        return models.Contact(**record)

    def delete(self, id: int = None, name: str = None, email: str = None, phone_number: str = None) -> None:
        """Deletes an existing Contact. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if id is not None:
            criteria.append(('id', 'eq', id))
        if name is not None:
            criteria.append(('name', 'eq', name))
        if email is not None:
            criteria.append(('email', 'eq', email))
        if phone_number is not None:
            criteria.append(('phone_number', 'eq', phone_number))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise LookupError(f"Contact delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None
