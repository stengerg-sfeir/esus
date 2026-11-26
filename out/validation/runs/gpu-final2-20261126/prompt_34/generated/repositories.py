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



class OrderRepository:
    ENTITY = "Order"
    PK = "order_id"

    def __init__(self, store):
        self._store = store


    def create(self, created_at: Any = None, updated_at: Any = None) -> Any:
        """Creates a new Order. [crud:create: STANDARD_CRUD]"""
        values = {}
        if created_at is not None:
            values['created_at'] = created_at
        if updated_at is not None:
            values['updated_at'] = updated_at
        unknown = [k for k in values if k not in ['order_id', 'created_at', 'updated_at']]
        if unknown:
            raise ValueError(f"cannot create Order from {unknown}")
        if values.get('created_at') is None:
            values['created_at'] = datetime.datetime.now()
        if values.get('updated_at') is None:
            values['updated_at'] = datetime.datetime.now()
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[])
        return models.Order(**record)

    def read_one(self, order_id: int = None) -> Any:
        """Reads one Order by its key. [crud:read_one: READ_ONE_BY_ID]"""
        record = self._store.get(self.ENTITY, self.PK, order_id, error=errors.OrderLineNotFoundError)
        return models.Order(**record)

    def read_all(self, created_at: Any = None, updated_at: Any = None) -> list[models.Order]:
        """Lists every Order; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if created_at is not None:
            criteria.append(('created_at', 'eq', created_at))
        if updated_at is not None:
            criteria.append(('updated_at', 'eq', updated_at))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Order(**r) for r in found]

    def update(self, order_id: int = None, created_at: Any = None, updated_at: Any = None) -> Any:
        """Updates an existing Order. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if order_id is not None:
            criteria.append(('order_id', 'eq', order_id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise errors.OrderLineNotFoundError(f"Order update matched {len(found)} records")
        patch = {}
        if order_id is not None and 'order_id' in ['order_id', 'created_at', 'updated_at']:
            patch['order_id'] = order_id
        if created_at is not None and 'created_at' in ['order_id', 'created_at', 'updated_at']:
            patch['created_at'] = created_at
        if updated_at is not None and 'updated_at' in ['order_id', 'created_at', 'updated_at']:
            patch['updated_at'] = updated_at
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=errors.OrderLineNotFoundError)
        return models.Order(**record)

    def delete(self, order_id: int = None, created_at: Any = None, updated_at: Any = None) -> None:
        """Deletes an existing Order. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if order_id is not None:
            criteria.append(('order_id', 'eq', order_id))
        if created_at is not None:
            criteria.append(('created_at', 'eq', created_at))
        if updated_at is not None:
            criteria.append(('updated_at', 'eq', updated_at))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise errors.OrderLineNotFoundError(f"Order delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None


class OrderLineRepository:
    ENTITY = "OrderLine"
    PK = "order_line_id"

    def __init__(self, store):
        self._store = store


    def create(self, order_id: int = None, product_id: str = None, quantity: int = None, unit_price: int = None, total_price: int = None) -> Any:
        """Creates a new OrderLine. [crud:create: STANDARD_CRUD]"""
        values = {}
        if order_id is not None:
            values['order_id'] = order_id
        if product_id is not None:
            values['product_id'] = product_id
        if quantity is not None:
            values['quantity'] = quantity
        if unit_price is not None:
            values['unit_price'] = unit_price
        if total_price is not None:
            values['total_price'] = total_price
        unknown = [k for k in values if k not in ['order_line_id', 'order_id', 'product_id', 'quantity', 'unit_price', 'total_price']]
        if unknown:
            raise ValueError(f"cannot create OrderLine from {unknown}")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[("order_id", "Order", "order_id", errors.OrderLineNotFoundError)])
        return models.OrderLine(**record)

    def read_one(self, order_line_id: int = None) -> Any:
        """Reads one OrderLine by its key. [crud:read_one: READ_ONE_BY_ID]"""
        record = self._store.get(self.ENTITY, self.PK, order_line_id, error=errors.OrderLineNotFoundError)
        return models.OrderLine(**record)

    def read_all(self, order_id: int = None, product_id: str = None, quantity: int = None, unit_price: int = None, total_price: int = None) -> list[models.OrderLine]:
        """Lists every OrderLine; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if order_id is not None:
            criteria.append(('order_id', 'eq', order_id))
        if product_id is not None:
            criteria.append(('product_id', 'eq', product_id))
        if quantity is not None:
            criteria.append(('quantity', 'eq', quantity))
        if unit_price is not None:
            criteria.append(('unit_price', 'eq', unit_price))
        if total_price is not None:
            criteria.append(('total_price', 'eq', total_price))
        found = self._store.select(self.ENTITY, criteria)
        return [models.OrderLine(**r) for r in found]

    def update(self, order_line_id: int = None, order_id: int = None, product_id: str = None, quantity: int = None, unit_price: int = None, total_price: int = None) -> Any:
        """Updates an existing OrderLine. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if order_line_id is not None:
            criteria.append(('order_line_id', 'eq', order_line_id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise errors.OrderLineNotFoundError(f"OrderLine update matched {len(found)} records")
        patch = {}
        if order_line_id is not None and 'order_line_id' in ['order_line_id', 'order_id', 'product_id', 'quantity', 'unit_price', 'total_price']:
            patch['order_line_id'] = order_line_id
        if order_id is not None and 'order_id' in ['order_line_id', 'order_id', 'product_id', 'quantity', 'unit_price', 'total_price']:
            patch['order_id'] = order_id
        if product_id is not None and 'product_id' in ['order_line_id', 'order_id', 'product_id', 'quantity', 'unit_price', 'total_price']:
            patch['product_id'] = product_id
        if quantity is not None and 'quantity' in ['order_line_id', 'order_id', 'product_id', 'quantity', 'unit_price', 'total_price']:
            patch['quantity'] = quantity
        if unit_price is not None and 'unit_price' in ['order_line_id', 'order_id', 'product_id', 'quantity', 'unit_price', 'total_price']:
            patch['unit_price'] = unit_price
        if total_price is not None and 'total_price' in ['order_line_id', 'order_id', 'product_id', 'quantity', 'unit_price', 'total_price']:
            patch['total_price'] = total_price
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=errors.OrderLineNotFoundError)
        return models.OrderLine(**record)

    def delete(self, order_line_id: int = None, order_id: int = None, product_id: str = None, quantity: int = None, unit_price: int = None, total_price: int = None) -> None:
        """Deletes an existing OrderLine. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if order_line_id is not None:
            criteria.append(('order_line_id', 'eq', order_line_id))
        if order_id is not None:
            criteria.append(('order_id', 'eq', order_id))
        if product_id is not None:
            criteria.append(('product_id', 'eq', product_id))
        if quantity is not None:
            criteria.append(('quantity', 'eq', quantity))
        if unit_price is not None:
            criteria.append(('unit_price', 'eq', unit_price))
        if total_price is not None:
            criteria.append(('total_price', 'eq', total_price))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise errors.OrderLineNotFoundError(f"OrderLine delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None

    def get_order_lines_by_order_id(self, order_id: int = None) -> list[models.OrderLine]:
        """Lists the OrderLine records belonging to one Order. [crud:filter: FILTER_BY_FIELD: by parameter shape]"""
        criteria = []
        if order_id is not None:
            criteria.append(('order_id', 'eq', order_id))
        found = self._store.select(self.ENTITY, criteria)
        return [models.OrderLine(**r) for r in found]
