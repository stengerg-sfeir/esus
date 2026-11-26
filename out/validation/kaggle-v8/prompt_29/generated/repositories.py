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


    def create(self, name: str = None, email: str = None) -> Any:
        """Creates a new Customer. [crud:create: STANDARD_CRUD]"""
        values = {}
        if name is not None:
            values['name'] = name
        if email is not None:
            values['email'] = email
        unknown = [k for k in values if k not in ['customer_id', 'name', 'email']]
        if unknown:
            raise ValueError(f"cannot create Customer from {unknown}")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[])
        return models.Customer(**record)

    def read_one(self, customer_id: int = None) -> Any:
        """Reads one Customer by its key. [crud:read_one: READ_ONE_BY_ID]"""
        found = self._store.select(self.ENTITY, [(self.PK, 'eq', customer_id)])
        if not found:
            return None
        record = found[0]
        return models.Customer(**record)

    def read_all(self, name: str = None, email: str = None) -> list[models.Customer]:
        """Lists every Customer; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if name is not None:
            criteria.append(('name', 'eq', name))
        if email is not None:
            criteria.append(('email', 'eq', email))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Customer(**r) for r in found]

    def update(self, customer_id: int = None, name: str = None, email: str = None) -> Any:
        """Updates an existing Customer. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if customer_id is not None:
            criteria.append(('customer_id', 'eq', customer_id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise LookupError(f"Customer update matched {len(found)} records")
        patch = {}
        if customer_id is not None and 'customer_id' in ['customer_id', 'name', 'email']:
            patch['customer_id'] = customer_id
        if name is not None and 'name' in ['customer_id', 'name', 'email']:
            patch['name'] = name
        if email is not None and 'email' in ['customer_id', 'name', 'email']:
            patch['email'] = email
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=LookupError)
        return models.Customer(**record)


class OrderRepository:
    ENTITY = "Order"
    PK = "order_id"

    def __init__(self, store):
        self._store = store


    def create(self, customer_id: int = None, items: str = None, status: str = None, created_at: Any = None) -> Any:
        """Creates a new Order. [crud:create: STANDARD_CRUD]"""
        values = {}
        if customer_id is not None:
            values['customer_id'] = customer_id
        if items is not None:
            values['items'] = items
        if status is not None:
            values['status'] = status
        if created_at is not None:
            values['created_at'] = created_at
        unknown = [k for k in values if k not in ['order_id', 'customer_id', 'items', 'status', 'created_at']]
        if unknown:
            raise ValueError(f"cannot create Order from {unknown}")
        if values.get('created_at') is None:
            values['created_at'] = datetime.datetime.now()
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[("customer_id", "Customer", "customer_id", None)])
        return models.Order(**record)

    def read_one(self, order_id: int = None) -> Any:
        """Reads one Order by its key. [crud:read_one: READ_ONE_BY_ID]"""
        found = self._store.select(self.ENTITY, [(self.PK, 'eq', order_id)])
        if not found:
            return None
        record = found[0]
        return models.Order(**record)

    def read_all(self, customer_id: int = None, items: str = None, status: str = None, created_at: Any = None) -> list[models.Order]:
        """Lists every Order; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if customer_id is not None:
            criteria.append(('customer_id', 'eq', customer_id))
        if items is not None:
            criteria.append(('items', 'eq', items))
        if status is not None:
            criteria.append(('status', 'eq', status))
        if created_at is not None:
            criteria.append(('created_at', 'eq', created_at))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Order(**r) for r in found]

    def update(self, order_id: int = None, customer_id: int = None, items: str = None, status: str = None, created_at: Any = None) -> Any:
        """Updates an existing Order. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if order_id is not None:
            criteria.append(('order_id', 'eq', order_id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise LookupError(f"Order update matched {len(found)} records")
        patch = {}
        if order_id is not None and 'order_id' in ['order_id', 'customer_id', 'items', 'status', 'created_at']:
            patch['order_id'] = order_id
        if customer_id is not None and 'customer_id' in ['order_id', 'customer_id', 'items', 'status', 'created_at']:
            patch['customer_id'] = customer_id
        if items is not None and 'items' in ['order_id', 'customer_id', 'items', 'status', 'created_at']:
            patch['items'] = items
        if status is not None and 'status' in ['order_id', 'customer_id', 'items', 'status', 'created_at']:
            patch['status'] = status
        if created_at is not None and 'created_at' in ['order_id', 'customer_id', 'items', 'status', 'created_at']:
            patch['created_at'] = created_at
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=LookupError)
        return models.Order(**record)

    def delete(self, order_id: int = None, customer_id: int = None, items: str = None, status: str = None, created_at: Any = None) -> None:
        """Deletes an existing Order. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if order_id is not None:
            criteria.append(('order_id', 'eq', order_id))
        if customer_id is not None:
            criteria.append(('customer_id', 'eq', customer_id))
        if items is not None:
            criteria.append(('items', 'eq', items))
        if status is not None:
            criteria.append(('status', 'eq', status))
        if created_at is not None:
            criteria.append(('created_at', 'eq', created_at))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise LookupError(f"Order delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None

    def get_orders_by_customer_id(self, customer_id: int = None) -> list[models.Order]:
        """Lists the Order records belonging to one Customer. [crud:filter: FILTER_BY_FIELD: by parameter shape]"""
        criteria = []
        if customer_id is not None:
            criteria.append(('customer_id', 'eq', customer_id))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Order(**r) for r in found]

    def count_orders_by_status(self) -> Dict[str, int]:
        """Returns the count of orders grouped by status (e.g., 'pending', 'completed'). [mechanical count by field]"""
        counts = {}
        for row in self._store.select(self.ENTITY, []):
            key = row.get('status')
            if key is not None:
                counts[key] = counts.get(key, 0) + 1
        return counts
