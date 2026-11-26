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
        found = self._store.select(self.ENTITY, [(self.PK, 'eq', order_id)])
        if not found:
            return None
        record = found[0]
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
            raise LookupError(f"Order update matched {len(found)} records")
        patch = {}
        if order_id is not None and 'order_id' in ['order_id', 'created_at', 'updated_at']:
            patch['order_id'] = order_id
        if created_at is not None and 'created_at' in ['order_id', 'created_at', 'updated_at']:
            patch['created_at'] = created_at
        if updated_at is not None and 'updated_at' in ['order_id', 'created_at', 'updated_at']:
            patch['updated_at'] = updated_at
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=LookupError)
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
            raise LookupError(f"Order delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None

    def calculate_total_order_amount(self, order_id: int = None) -> float:
        """Calculates the total amount of an order by summing up the product of quantity and unit price for all order items associated with the order. [llm-written by server — review]"""
        found = self._store.select(self.ENTITY, [])
        total = 0.0
        for record in found:
            if order_id is not None and record.get('order_id') != order_id:
                continue
            order_items = self._store.select("OrderItem", [("order_id", "eq", record.get('order_id'))])
            for item in order_items:
                quantity = item.get('quantity')
                unit_price = item.get('unit_price')
                if quantity is not None and unit_price is not None:
                    total += quantity * unit_price
        return total


class ProductRepository:
    ENTITY = "Product"
    PK = "product_id"

    def __init__(self, store):
        self._store = store


    def create(self, name: str = None, description: str = None) -> Any:
        """Creates a new Product. [crud:create: STANDARD_CRUD]"""
        values = {}
        if name is not None:
            values['name'] = name
        if description is not None:
            values['description'] = description
        unknown = [k for k in values if k not in ['product_id', 'name', 'description']]
        if unknown:
            raise ValueError(f"cannot create Product from {unknown}")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[])
        return models.Product(**record)

    def read_one(self, product_id: int = None) -> Any:
        """Reads one Product by its key. [crud:read_one: READ_ONE_BY_ID]"""
        found = self._store.select(self.ENTITY, [(self.PK, 'eq', product_id)])
        if not found:
            return None
        record = found[0]
        return models.Product(**record)

    def read_all(self, name: str = None, description: str = None) -> list[models.Product]:
        """Lists every Product; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if name is not None:
            criteria.append(('name', 'eq', name))
        if description is not None:
            criteria.append(('description', 'eq', description))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Product(**r) for r in found]

    def update(self, product_id: int = None, name: str = None, description: str = None) -> Any:
        """Updates an existing Product. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if product_id is not None:
            criteria.append(('product_id', 'eq', product_id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise LookupError(f"Product update matched {len(found)} records")
        patch = {}
        if product_id is not None and 'product_id' in ['product_id', 'name', 'description']:
            patch['product_id'] = product_id
        if name is not None and 'name' in ['product_id', 'name', 'description']:
            patch['name'] = name
        if description is not None and 'description' in ['product_id', 'name', 'description']:
            patch['description'] = description
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=LookupError)
        return models.Product(**record)

    def delete(self, product_id: int = None, name: str = None, description: str = None) -> None:
        """Deletes an existing Product. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if product_id is not None:
            criteria.append(('product_id', 'eq', product_id))
        if name is not None:
            criteria.append(('name', 'eq', name))
        if description is not None:
            criteria.append(('description', 'eq', description))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise LookupError(f"Product delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None


class OrderItemRepository:
    ENTITY = "OrderItem"
    PK = "order_item_id"

    def __init__(self, store):
        self._store = store


    def create(self, order_id: int = None, product_id: int = None, quantity: int = None, unit_price: int = None) -> Any:
        """Creates a new OrderItem. [crud:create: STANDARD_CRUD]"""
        values = {}
        if order_id is not None:
            values['order_id'] = order_id
        if product_id is not None:
            values['product_id'] = product_id
        if quantity is not None:
            values['quantity'] = quantity
        if unit_price is not None:
            values['unit_price'] = unit_price
        unknown = [k for k in values if k not in ['order_item_id', 'order_id', 'product_id', 'quantity', 'unit_price']]
        if unknown:
            raise ValueError(f"cannot create OrderItem from {unknown}")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[("order_id", "Order", "order_id", None), ("product_id", "Product", "product_id", None)])
        return models.OrderItem(**record)

    def read_all(self, order_id: int = None, product_id: int = None, quantity: int = None, unit_price: int = None) -> list[models.OrderItem]:
        """Lists every OrderItem; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if order_id is not None:
            criteria.append(('order_id', 'eq', order_id))
        if product_id is not None:
            criteria.append(('product_id', 'eq', product_id))
        if quantity is not None:
            criteria.append(('quantity', 'eq', quantity))
        if unit_price is not None:
            criteria.append(('unit_price', 'eq', unit_price))
        found = self._store.select(self.ENTITY, criteria)
        return [models.OrderItem(**r) for r in found]

    def update(self, order_item_id: int = None, order_id: int = None, product_id: int = None, quantity: int = None, unit_price: int = None) -> Any:
        """Updates an existing OrderItem. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if order_item_id is not None:
            criteria.append(('order_item_id', 'eq', order_item_id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise LookupError(f"OrderItem update matched {len(found)} records")
        patch = {}
        if order_item_id is not None and 'order_item_id' in ['order_item_id', 'order_id', 'product_id', 'quantity', 'unit_price']:
            patch['order_item_id'] = order_item_id
        if order_id is not None and 'order_id' in ['order_item_id', 'order_id', 'product_id', 'quantity', 'unit_price']:
            patch['order_id'] = order_id
        if product_id is not None and 'product_id' in ['order_item_id', 'order_id', 'product_id', 'quantity', 'unit_price']:
            patch['product_id'] = product_id
        if quantity is not None and 'quantity' in ['order_item_id', 'order_id', 'product_id', 'quantity', 'unit_price']:
            patch['quantity'] = quantity
        if unit_price is not None and 'unit_price' in ['order_item_id', 'order_id', 'product_id', 'quantity', 'unit_price']:
            patch['unit_price'] = unit_price
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=LookupError)
        return models.OrderItem(**record)

    def delete(self, order_item_id: int = None, order_id: int = None, product_id: int = None, quantity: int = None, unit_price: int = None) -> None:
        """Deletes an existing OrderItem. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if order_item_id is not None:
            criteria.append(('order_item_id', 'eq', order_item_id))
        if order_id is not None:
            criteria.append(('order_id', 'eq', order_id))
        if product_id is not None:
            criteria.append(('product_id', 'eq', product_id))
        if quantity is not None:
            criteria.append(('quantity', 'eq', quantity))
        if unit_price is not None:
            criteria.append(('unit_price', 'eq', unit_price))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise LookupError(f"OrderItem delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None

    def read_one(self, order_item_id: int = None) -> Any:
        """Reads one OrderItem by its key. [crud:read_one: READ_ONE_BY_ID]"""
        found = self._store.select(self.ENTITY, [(self.PK, 'eq', order_item_id)])
        if not found:
            return None
        record = found[0]
        return models.OrderItem(**record)

    def get_order_items_by_order_id(self, order_id: int = None) -> list[models.OrderItem]:
        """Lists the OrderItem records belonging to one Order. [crud:filter: FILTER_BY_FIELD: by parameter shape]"""
        criteria = []
        if order_id is not None:
            criteria.append(('order_id', 'eq', order_id))
        found = self._store.select(self.ENTITY, criteria)
        return [models.OrderItem(**r) for r in found]

    def get_total_quantity_for_product(self, product_id: int = None) -> int:
        """Returns the total quantity of a product across all orders, based on the product_id. [AGGREGATE_BY_FK via answered slots: fk_field=product_id, target_field=quantity, aggregate_func=SUM]"""
        total = 0
        for record in self._store.select(self.ENTITY, []):
            if product_id is not None and record.get('product_id') != product_id:
                continue
            total += record.get('quantity') or 0
        return total
