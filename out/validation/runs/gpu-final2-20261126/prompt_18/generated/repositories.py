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


    def create(self, first_name: str = None, last_name: str = None, email: str = None, phone: str = None, address: str = None, created_at: Any = None, updated_at: Any = None) -> models.Contact:
        """Creates a new Contact. [crud:create: STANDARD_CRUD]"""
        values = {}
        if first_name is not None:
            values['first_name'] = first_name
        if last_name is not None:
            values['last_name'] = last_name
        if email is not None:
            values['email'] = email
        if phone is not None:
            values['phone'] = phone
        if address is not None:
            values['address'] = address
        if created_at is not None:
            values['created_at'] = created_at
        if updated_at is not None:
            values['updated_at'] = updated_at
        unknown = [k for k in values if k not in ['id', 'first_name', 'last_name', 'email', 'phone', 'address', 'created_at', 'updated_at']]
        if unknown:
            raise ValueError(f"cannot create Contact from {unknown}")
        if values.get('created_at') is None:
            values['created_at'] = datetime.datetime.now()
        if values.get('updated_at') is None:
            values['updated_at'] = datetime.datetime.now()
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[])
        return models.Contact(**record)

    def delete(self, id: int = None, first_name: str = None, last_name: str = None, email: str = None, phone: str = None, address: str = None, created_at: Any = None, updated_at: Any = None) -> None:
        """Deletes an existing Contact. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if id is not None:
            criteria.append(('id', 'eq', id))
        if first_name is not None:
            criteria.append(('first_name', 'eq', first_name))
        if last_name is not None:
            criteria.append(('last_name', 'eq', last_name))
        if email is not None:
            criteria.append(('email', 'eq', email))
        if phone is not None:
            criteria.append(('phone', 'eq', phone))
        if address is not None:
            criteria.append(('address', 'eq', address))
        if created_at is not None:
            criteria.append(('created_at', 'eq', created_at))
        if updated_at is not None:
            criteria.append(('updated_at', 'eq', updated_at))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise LookupError(f"Contact delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None

    def read_all(self, first_name: str = None, last_name: str = None, email: str = None, phone: str = None, address: str = None, created_at: Any = None, updated_at: Any = None) -> list[models.Contact]:
        """Lists every Contact; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if first_name is not None:
            criteria.append(('first_name', 'eq', first_name))
        if last_name is not None:
            criteria.append(('last_name', 'eq', last_name))
        if email is not None:
            criteria.append(('email', 'eq', email))
        if phone is not None:
            criteria.append(('phone', 'eq', phone))
        if address is not None:
            criteria.append(('address', 'eq', address))
        if created_at is not None:
            criteria.append(('created_at', 'eq', created_at))
        if updated_at is not None:
            criteria.append(('updated_at', 'eq', updated_at))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Contact(**r) for r in found]

    def read_one(self, id: int = None) -> models.Contact:
        """Reads one Contact by its key. [crud:read_one: READ_ONE_BY_ID]"""
        found = self._store.select(self.ENTITY, [(self.PK, 'eq', id)])
        if not found:
            return None
        record = found[0]
        return models.Contact(**record)

    def update(self, id: int = None, first_name: str = None, last_name: str = None, email: str = None, phone: str = None, address: str = None, created_at: Any = None, updated_at: Any = None) -> models.Contact:
        """Updates an existing Contact. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if id is not None:
            criteria.append(('id', 'eq', id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise LookupError(f"Contact update matched {len(found)} records")
        patch = {}
        if id is not None and 'id' in ['id', 'first_name', 'last_name', 'email', 'phone', 'address', 'created_at', 'updated_at']:
            patch['id'] = id
        if first_name is not None and 'first_name' in ['id', 'first_name', 'last_name', 'email', 'phone', 'address', 'created_at', 'updated_at']:
            patch['first_name'] = first_name
        if last_name is not None and 'last_name' in ['id', 'first_name', 'last_name', 'email', 'phone', 'address', 'created_at', 'updated_at']:
            patch['last_name'] = last_name
        if email is not None and 'email' in ['id', 'first_name', 'last_name', 'email', 'phone', 'address', 'created_at', 'updated_at']:
            patch['email'] = email
        if phone is not None and 'phone' in ['id', 'first_name', 'last_name', 'email', 'phone', 'address', 'created_at', 'updated_at']:
            patch['phone'] = phone
        if address is not None and 'address' in ['id', 'first_name', 'last_name', 'email', 'phone', 'address', 'created_at', 'updated_at']:
            patch['address'] = address
        if created_at is not None and 'created_at' in ['id', 'first_name', 'last_name', 'email', 'phone', 'address', 'created_at', 'updated_at']:
            patch['created_at'] = created_at
        if updated_at is not None and 'updated_at' in ['id', 'first_name', 'last_name', 'email', 'phone', 'address', 'created_at', 'updated_at']:
            patch['updated_at'] = updated_at
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=LookupError)
        return models.Contact(**record)
