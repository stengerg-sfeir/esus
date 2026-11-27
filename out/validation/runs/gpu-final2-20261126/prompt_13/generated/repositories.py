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
    PK = "id"

    def __init__(self, store):
        self._store = store


    def create(self, name: str = None, category: str = None, price: int = None, stock_quantity: int = None, sku: str = None) -> models.Product:
        """Creates a new Product. [crud:create: STANDARD_CRUD]"""
        values = {}
        if name is not None:
            values['name'] = name
        if category is not None:
            values['category'] = category
        if price is not None:
            values['price'] = price
        if stock_quantity is not None:
            values['stock_quantity'] = stock_quantity
        if sku is not None:
            values['sku'] = sku
        unknown = [k for k in values if k not in ['id', 'name', 'category', 'price', 'stock_quantity', 'sku']]
        if unknown:
            raise ValueError(f"cannot create Product from {unknown}")
        value = values.get('price')
        if value is not None and value < 0:
            raise ValueError(f"Product.price must be >= 0, got {value!r}")
        value = values.get('stock_quantity')
        if value is not None and value < 0:
            raise ValueError(f"Product.stock_quantity must be >= 0, got {value!r}")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[])
        return models.Product(**record)

    def delete(self, id: int = None, name: str = None, category: str = None, price: int = None, stock_quantity: int = None) -> None:
        """Deletes an existing Product. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if id is not None:
            criteria.append(('id', 'eq', id))
        if name is not None:
            criteria.append(('name', 'eq', name))
        if category is not None:
            criteria.append(('category', 'eq', category))
        if price is not None:
            criteria.append(('price', 'eq', price))
        if stock_quantity is not None:
            criteria.append(('stock_quantity', 'eq', stock_quantity))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise errors.ProductNotFoundError(f"Product delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None

    def filter_by_category(self, category: str = None) -> list[models.Product]:
        """Filters Product records by category. [mechanical contained-name filter]"""
        criteria = []
        if category is not None:
            criteria.append(('category', 'eq', category))
        found = self._store.select(self.ENTITY, criteria)
        return _model_list([models.Product(**row) for row in found], models.Product)

    def read_all(self, name: str = None, category: str = None, price: int = None, stock_quantity: int = None) -> list[models.Product]:
        """Lists every Product; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if name is not None:
            criteria.append(('name', 'eq', name))
        if category is not None:
            criteria.append(('category', 'eq', category))
        if price is not None:
            criteria.append(('price', 'eq', price))
        if stock_quantity is not None:
            criteria.append(('stock_quantity', 'eq', stock_quantity))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Product(**r) for r in found]

    def read_one(self, id: int = None) -> models.Product:
        """Reads one Product by its key. [crud:read_one: READ_ONE_BY_ID]"""
        record = self._store.get(self.ENTITY, self.PK, id, error=errors.ProductNotFoundError)
        return models.Product(**record)

    def report_low_stock(self) -> list[models.Product]:
        """Reports Product records whose stock_quantity is below the threshold. [mechanical low-stock scan]"""
        threshold = 10
        result = []
        for row in self._store.select(self.ENTITY, []):
            stock = row.get('stock_quantity')
            if stock is not None and stock < threshold:
                result.append(row)
        return _model_list([models.Product(**row) for row in result], models.Product)

    def search_products(self, query: str = None) -> list[models.Product]:
        """Searches Product records across their text fields. [mechanical text search]"""
        if not query:
            return []
        query = str(query).lower()
        result = []
        for row in self._store.select(self.ENTITY, []):
            values = [row.get('name'), row.get('category'), row.get('sku')]
            if any(value is not None and query in str(value).lower() for value in values):
                result.append(row)
        return _model_list([models.Product(**row) for row in result], models.Product)

    def update(self, id: int = None, name: str = None, category: str = None, price: int = None, stock_quantity: int = None) -> models.Product:
        """Updates an existing Product. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if id is not None:
            criteria.append(('id', 'eq', id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise errors.ProductNotFoundError(f"Product update matched {len(found)} records")
        patch = {}
        if id is not None and 'id' in ['id', 'name', 'category', 'price', 'stock_quantity', 'sku']:
            patch['id'] = id
        if name is not None and 'name' in ['id', 'name', 'category', 'price', 'stock_quantity', 'sku']:
            patch['name'] = name
        if category is not None and 'category' in ['id', 'name', 'category', 'price', 'stock_quantity', 'sku']:
            patch['category'] = category
        if price is not None and 'price' in ['id', 'name', 'category', 'price', 'stock_quantity', 'sku']:
            patch['price'] = price
        if stock_quantity is not None and 'stock_quantity' in ['id', 'name', 'category', 'price', 'stock_quantity', 'sku']:
            patch['stock_quantity'] = stock_quantity
        value = patch.get('price')
        if value is not None and value < 0:
            raise ValueError(f"Product.price must be >= 0, got {value!r}")
        value = patch.get('stock_quantity')
        if value is not None and value < 0:
            raise ValueError(f"Product.stock_quantity must be >= 0, got {value!r}")
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=errors.ProductNotFoundError)
        return models.Product(**record)
