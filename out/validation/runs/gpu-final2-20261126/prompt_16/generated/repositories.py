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



class CustomerRepository:
    ENTITY = "Customer"
    PK = "customer_id"

    def __init__(self, store):
        self._store = store


    def create(self, first_name: str = None, last_name: str = None, email: str = None, phone: str = None, created_at: Any = None, updated_at: Any = None) -> models.Customer:
        """Creates a new Customer. [crud:create: STANDARD_CRUD]"""
        values = {}
        if first_name is not None:
            values['first_name'] = first_name
        if last_name is not None:
            values['last_name'] = last_name
        if email is not None:
            values['email'] = email
        if phone is not None:
            values['phone'] = phone
        if created_at is not None:
            values['created_at'] = created_at
        if updated_at is not None:
            values['updated_at'] = updated_at
        unknown = [k for k in values if k not in ['customer_id', 'first_name', 'last_name', 'email', 'phone', 'created_at', 'updated_at']]
        if unknown:
            raise ValueError(f"cannot create Customer from {unknown}")
        if values.get('created_at') is None:
            values['created_at'] = datetime.datetime.now()
        if values.get('updated_at') is None:
            values['updated_at'] = datetime.datetime.now()
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[])
        return models.Customer(**record)

    def delete(self, customer_id: int = None, first_name: str = None, last_name: str = None, email: str = None, phone: str = None, created_at: Any = None, updated_at: Any = None) -> None:
        """Deletes an existing Customer. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if customer_id is not None:
            criteria.append(('customer_id', 'eq', customer_id))
        if first_name is not None:
            criteria.append(('first_name', 'eq', first_name))
        if last_name is not None:
            criteria.append(('last_name', 'eq', last_name))
        if email is not None:
            criteria.append(('email', 'eq', email))
        if phone is not None:
            criteria.append(('phone', 'eq', phone))
        if created_at is not None:
            criteria.append(('created_at', 'eq', created_at))
        if updated_at is not None:
            criteria.append(('updated_at', 'eq', updated_at))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise LookupError(f"Customer delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None

    def read_all(self, first_name: str = None, last_name: str = None, email: str = None, phone: str = None, created_at: Any = None, updated_at: Any = None) -> list[models.Customer]:
        """Lists every Customer; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if first_name is not None:
            criteria.append(('first_name', 'eq', first_name))
        if last_name is not None:
            criteria.append(('last_name', 'eq', last_name))
        if email is not None:
            criteria.append(('email', 'eq', email))
        if phone is not None:
            criteria.append(('phone', 'eq', phone))
        if created_at is not None:
            criteria.append(('created_at', 'eq', created_at))
        if updated_at is not None:
            criteria.append(('updated_at', 'eq', updated_at))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Customer(**r) for r in found]

    def read_all_paginated(self, page_number: int = None, page_size: int = None) -> list[models.Customer]:
        """Lists Customer records with the requested page number and page size. [mechanical pagination]"""
        criteria = []
        records = self._store.select(self.ENTITY, criteria)
        total = len(records)
        page_number = page_number if page_number is not None else 1
        page_size = page_size if page_size is not None else 10
        if page_size <= 0:
            page_size = 10
        total_pages = (total + page_size - 1) // page_size
        start = max(0, (page_number - 1) * page_size)
        end = start + page_size
        page_records = records[start:end]
        items = [models.Customer(**row) for row in page_records]
        return items

    def read_one(self, customer_id: int = None) -> models.Customer:
        """Reads one Customer by its key. [crud:read_one: READ_ONE_BY_ID]"""
        found = self._store.select(self.ENTITY, [(self.PK, 'eq', customer_id)])
        if not found:
            return None
        record = found[0]
        return models.Customer(**record)

    def update(self, customer_id: int = None, first_name: str = None, last_name: str = None, email: str = None, phone: str = None, created_at: Any = None, updated_at: Any = None) -> models.Customer:
        """Updates an existing Customer. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if customer_id is not None:
            criteria.append(('customer_id', 'eq', customer_id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise LookupError(f"Customer update matched {len(found)} records")
        patch = {}
        if customer_id is not None and 'customer_id' in ['customer_id', 'first_name', 'last_name', 'email', 'phone', 'created_at', 'updated_at']:
            patch['customer_id'] = customer_id
        if first_name is not None and 'first_name' in ['customer_id', 'first_name', 'last_name', 'email', 'phone', 'created_at', 'updated_at']:
            patch['first_name'] = first_name
        if last_name is not None and 'last_name' in ['customer_id', 'first_name', 'last_name', 'email', 'phone', 'created_at', 'updated_at']:
            patch['last_name'] = last_name
        if email is not None and 'email' in ['customer_id', 'first_name', 'last_name', 'email', 'phone', 'created_at', 'updated_at']:
            patch['email'] = email
        if phone is not None and 'phone' in ['customer_id', 'first_name', 'last_name', 'email', 'phone', 'created_at', 'updated_at']:
            patch['phone'] = phone
        if created_at is not None and 'created_at' in ['customer_id', 'first_name', 'last_name', 'email', 'phone', 'created_at', 'updated_at']:
            patch['created_at'] = created_at
        if updated_at is not None and 'updated_at' in ['customer_id', 'first_name', 'last_name', 'email', 'phone', 'created_at', 'updated_at']:
            patch['updated_at'] = updated_at
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=LookupError)
        return models.Customer(**record)
