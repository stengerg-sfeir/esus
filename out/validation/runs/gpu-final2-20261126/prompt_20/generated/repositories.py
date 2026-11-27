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



class ProductRepository:
    ENTITY = "Product"
    PK = "product_id"

    def __init__(self, store):
        self._store = store


    def create(self, name: str = None, price: int = None) -> models.Product:
        """Creates a new Product. [crud:create: STANDARD_CRUD]"""
        values = {}
        if name is not None:
            values['name'] = name
        if price is not None:
            values['price'] = price
        unknown = [k for k in values if k not in ['product_id', 'name', 'price']]
        if unknown:
            raise ValueError(f"cannot create Product from {unknown}")
        value = values.get('price')
        if value is not None and value <= 0:
            raise ValueError(f"Product.price must be > 0, got {value!r}")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[])
        return models.Product(**record)

    def delete(self, product_id: int = None, name: str = None, price: int = None) -> None:
        """Deletes an existing Product. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if product_id is not None:
            criteria.append(('product_id', 'eq', product_id))
        if name is not None:
            criteria.append(('name', 'eq', name))
        if price is not None:
            criteria.append(('price', 'eq', price))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise LookupError(f"Product delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None

    def read_all(self, name: str = None, price: int = None) -> list[models.Product]:
        """Lists every Product; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if name is not None:
            criteria.append(('name', 'eq', name))
        if price is not None:
            criteria.append(('price', 'eq', price))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Product(**r) for r in found]

    def read_one(self, product_id: int = None) -> models.Product:
        """Reads one Product by its key. [crud:read_one: READ_ONE_BY_ID]"""
        found = self._store.select(self.ENTITY, [(self.PK, 'eq', product_id)])
        if not found:
            return None
        record = found[0]
        return models.Product(**record)

    def update(self, product_id: int = None, name: str = None, price: int = None) -> models.Product:
        """Updates an existing Product. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if product_id is not None:
            criteria.append(('product_id', 'eq', product_id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise LookupError(f"Product update matched {len(found)} records")
        patch = {}
        if product_id is not None and 'product_id' in ['product_id', 'name', 'price']:
            patch['product_id'] = product_id
        if name is not None and 'name' in ['product_id', 'name', 'price']:
            patch['name'] = name
        if price is not None and 'price' in ['product_id', 'name', 'price']:
            patch['price'] = price
        value = patch.get('price')
        if value is not None and value <= 0:
            raise ValueError(f"Product.price must be > 0, got {value!r}")
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=LookupError)
        return models.Product(**record)


class SalesRecordRepository:
    ENTITY = "SalesRecord"
    PK = "sales_id"

    def __init__(self, store):
        self._store = store


    def create(self, product_id: int = None, quantity: int = None, sale_date: Any = None) -> models.SalesRecord:
        """Creates a new SalesRecord. [crud:create: STANDARD_CRUD]"""
        values = {}
        if product_id is not None:
            values['product_id'] = product_id
        if quantity is not None:
            values['quantity'] = quantity
        if sale_date is not None:
            values['sale_date'] = sale_date
        unknown = [k for k in values if k not in ['sales_id', 'product_id', 'quantity', 'sale_date']]
        if unknown:
            raise ValueError(f"cannot create SalesRecord from {unknown}")
        value = values.get('quantity')
        if value is not None and value <= 0:
            raise ValueError(f"SalesRecord.quantity must be > 0, got {value!r}")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[("product_id", "Product", "product_id", None)])
        return models.SalesRecord(**record)

    def delete(self, sales_id: int = None, product_id: int = None, quantity: int = None, sale_date: Any = None) -> None:
        """Deletes an existing SalesRecord. [crud:delete: name-only: step F never saw this method]"""
        criteria = []
        if sales_id is not None:
            criteria.append(('sales_id', 'eq', sales_id))
        if product_id is not None:
            criteria.append(('product_id', 'eq', product_id))
        if quantity is not None:
            criteria.append(('quantity', 'eq', quantity))
        if sale_date is not None:
            criteria.append(('sale_date', 'eq', sale_date))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise LookupError(f"SalesRecord delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None

    def get_sales_records_by_product_id(self, product_id: int = None) -> list[models.SalesRecord]:
        """Lists the SalesRecord records belonging to one Product. [mechanical contained-name filter]"""
        criteria = []
        if product_id is not None:
            criteria.append(('product_id', 'eq', product_id))
        found = self._store.select(self.ENTITY, criteria)
        return _model_list([models.SalesRecord(**row) for row in found], models.SalesRecord)

    def read_all(self, product_id: int = None, quantity: int = None, sale_date: Any = None) -> list[models.SalesRecord]:
        """Lists every SalesRecord; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if product_id is not None:
            criteria.append(('product_id', 'eq', product_id))
        if quantity is not None:
            criteria.append(('quantity', 'eq', quantity))
        if sale_date is not None:
            criteria.append(('sale_date', 'eq', sale_date))
        found = self._store.select(self.ENTITY, criteria)
        return [models.SalesRecord(**r) for r in found]

    def read_one(self, sales_id: int = None) -> models.SalesRecord:
        """Reads one SalesRecord by its key. [crud:read_one: READ_ONE_BY_ID]"""
        found = self._store.select(self.ENTITY, [(self.PK, 'eq', sales_id)])
        if not found:
            return None
        record = found[0]
        return models.SalesRecord(**record)

    def update(self, sales_id: int = None, product_id: int = None, quantity: int = None, sale_date: Any = None) -> models.SalesRecord:
        """Updates an existing SalesRecord. [crud:update: name-only: step F never saw this method]"""
        criteria = []
        if sales_id is not None:
            criteria.append(('sales_id', 'eq', sales_id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise LookupError(f"SalesRecord update matched {len(found)} records")
        patch = {}
        if sales_id is not None and 'sales_id' in ['sales_id', 'product_id', 'quantity', 'sale_date']:
            patch['sales_id'] = sales_id
        if product_id is not None and 'product_id' in ['sales_id', 'product_id', 'quantity', 'sale_date']:
            patch['product_id'] = product_id
        if quantity is not None and 'quantity' in ['sales_id', 'product_id', 'quantity', 'sale_date']:
            patch['quantity'] = quantity
        if sale_date is not None and 'sale_date' in ['sales_id', 'product_id', 'quantity', 'sale_date']:
            patch['sale_date'] = sale_date
        value = patch.get('quantity')
        if value is not None and value <= 0:
            raise ValueError(f"SalesRecord.quantity must be > 0, got {value!r}")
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=LookupError)
        return models.SalesRecord(**record)
