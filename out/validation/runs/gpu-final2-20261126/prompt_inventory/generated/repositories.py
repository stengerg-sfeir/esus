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



class CategoryRepository:
    ENTITY = "Category"
    PK = "id"

    def __init__(self, store):
        self._store = store


    def create(self, name: str = None, description: str = None, reorder_threshold: int = None) -> models.Category:
        """Creates a new Category. [crud:create: STANDARD_CRUD]"""
        values = {}
        if name is not None:
            values['name'] = name
        if description is not None:
            values['description'] = description
        if reorder_threshold is not None:
            values['reorder_threshold'] = reorder_threshold
        unknown = [k for k in values if k not in ['id', 'name', 'description', 'reorder_threshold']]
        if unknown:
            raise ValueError(f"cannot create Category from {unknown}")
        for unique_field in ['name']:
            value = values.get(unique_field)
            if value is not None and self._store.select(self.ENTITY, [(unique_field, 'eq', value)]):
                raise ValueError(f"Category with {unique_field}={value!r} already exists")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[])
        return models.Category(**record)

    def delete(self, id: int = None, name: str = None, description: str = None, reorder_threshold: int = None) -> None:
        """Deletes an existing Category. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if id is not None:
            criteria.append(('id', 'eq', id))
        if name is not None:
            criteria.append(('name', 'eq', name))
        if description is not None:
            criteria.append(('description', 'eq', description))
        if reorder_threshold is not None:
            criteria.append(('reorder_threshold', 'eq', reorder_threshold))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise errors.CategoryNotFoundError(f"Category delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None

    def find_products_by_category(self, category_id: int = None) -> list[models.Product]:
        """Returns a list of products that belong to a given category ID. [crud:filter: FILTER_BY_FIELD]"""
        criteria = []
        if category_id is not None:
            criteria.append(('category_id', 'eq', category_id))
        found = self._store.select('Product', criteria)
        return [models.Product(**r) for r in found]

    def read_all(self, name: str = None, description: str = None, reorder_threshold: int = None) -> list[models.Category]:
        """Lists every Category; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if name is not None:
            criteria.append(('name', 'eq', name))
        if description is not None:
            criteria.append(('description', 'eq', description))
        if reorder_threshold is not None:
            criteria.append(('reorder_threshold', 'eq', reorder_threshold))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Category(**r) for r in found]

    def read_one(self, id: int = None) -> models.Category:
        """Reads one Category by its key. [crud:read_one: READ_ONE_BY_ID]"""
        record = self._store.get(self.ENTITY, self.PK, id, error=errors.CategoryNotFoundError)
        return models.Category(**record)

    def update(self, id: int = None, name: str = None, description: str = None, reorder_threshold: int = None) -> models.Category:
        """Updates an existing Category. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if id is not None:
            criteria.append(('id', 'eq', id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise errors.CategoryNotFoundError(f"Category update matched {len(found)} records")
        patch = {}
        if id is not None and 'id' in ['id', 'name', 'description', 'reorder_threshold']:
            patch['id'] = id
        if name is not None and 'name' in ['id', 'name', 'description', 'reorder_threshold']:
            patch['name'] = name
        if description is not None and 'description' in ['id', 'name', 'description', 'reorder_threshold']:
            patch['description'] = description
        if reorder_threshold is not None and 'reorder_threshold' in ['id', 'name', 'description', 'reorder_threshold']:
            patch['reorder_threshold'] = reorder_threshold
        for unique_field in ['name']:
            value = patch.get(unique_field)
            if value is not None and any(row.get(self.PK) != found[0][self.PK] for row in self._store.select(self.ENTITY, [(unique_field, 'eq', value)])):
                raise ValueError(f"Category with {unique_field}={value!r} already exists")
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=errors.CategoryNotFoundError)
        return models.Category(**record)


class ProductRepository:
    ENTITY = "Product"
    PK = "id"

    def __init__(self, store):
        self._store = store


    def aggregate_stock_value_by_category(self) -> dict[int, int]:
        """Returns a dictionary mapping each category ID to the total value (price_cents * stock_qty) of all products in that category. [mechanical stock value]"""
        parents = self._store.select('Category', [])
        values = {row['id']: 0 for row in parents}
        for row in self._store.select(self.ENTITY, []):
            parent_id = row.get('category_id')
            if parent_id is None:
                continue
            values[parent_id] = values.get(parent_id, 0) + (row.get('price_cents') or 0) * (row.get('stock_qty') or 0)
        return values

    def create(self, sku: str = None, name: str = None, category_id: int = None, price_cents: int = None, stock_qty: int = None, low_active: bool = None) -> models.Product:
        """Creates a new Product. [crud:create: STANDARD_CRUD]"""
        values = {}
        if sku is not None:
            values['sku'] = sku
        if name is not None:
            values['name'] = name
        if category_id is not None:
            values['category_id'] = category_id
        if price_cents is not None:
            values['price_cents'] = price_cents
        if stock_qty is not None:
            values['stock_qty'] = stock_qty
        if low_active is not None:
            values['low_active'] = low_active
        unknown = [k for k in values if k not in ['id', 'sku', 'name', 'category_id', 'price_cents', 'stock_qty', 'low_active']]
        if unknown:
            raise ValueError(f"cannot create Product from {unknown}")
        value = values.get('stock_qty')
        if value is not None and value < 0:
            raise ValueError(f"Product.stock_qty must be >= 0, got {value!r}")
        for unique_field in ['sku']:
            value = values.get(unique_field)
            if value is not None and self._store.select(self.ENTITY, [(unique_field, 'eq', value)]):
                raise ValueError(f"Product with {unique_field}={value!r} already exists")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[("category_id", "Category", "id", errors.CategoryNotFoundError)])
        return models.Product(**record)

    def delete(self, id: int = None, sku: str = None, name: str = None, category_id: int = None, price_cents: int = None, stock_qty: int = None, low_active: bool = None) -> None:
        """Deletes an existing Product. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if id is not None:
            criteria.append(('id', 'eq', id))
        if sku is not None:
            criteria.append(('sku', 'eq', sku))
        if name is not None:
            criteria.append(('name', 'eq', name))
        if category_id is not None:
            criteria.append(('category_id', 'eq', category_id))
        if price_cents is not None:
            criteria.append(('price_cents', 'eq', price_cents))
        if stock_qty is not None:
            criteria.append(('stock_qty', 'eq', stock_qty))
        if low_active is not None:
            criteria.append(('low_active', 'eq', low_active))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise errors.ProductNotFoundError(f"Product delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None

    def find_low_stock_products(self, id: int = None) -> list[models.Product]:
        """Returns a list of products whose stock_qty is below the reorder_threshold of their category. [mechanical boolean filter]"""
        return _model_list(self._store.select(self.ENTITY, [('low_active', 'eq', True)]), models.Product)

    def find_products_by_category(self, category_id: int = None) -> list[models.Product]:
        """Returns a list of products that belong to a given category ID. [mechanical contained-name filter]"""
        criteria = []
        if category_id is not None:
            criteria.append(('category_id', 'eq', category_id))
        found = self._store.select(self.ENTITY, criteria)
        return _model_list([models.Product(**row) for row in found], models.Product)

    def read_all(self, sku: str = None, name: str = None, category_id: int = None, price_cents: int = None, stock_qty: int = None, low_active: bool = None) -> list[models.Product]:
        """Lists every Product; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if sku is not None:
            criteria.append(('sku', 'eq', sku))
        if name is not None:
            criteria.append(('name', 'eq', name))
        if category_id is not None:
            criteria.append(('category_id', 'eq', category_id))
        if price_cents is not None:
            criteria.append(('price_cents', 'eq', price_cents))
        if stock_qty is not None:
            criteria.append(('stock_qty', 'eq', stock_qty))
        if low_active is not None:
            criteria.append(('low_active', 'eq', low_active))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Product(**r) for r in found]

    def read_one(self, id: int = None) -> models.Product:
        """Reads one Product by its key. [crud:read_one: READ_ONE_BY_ID]"""
        record = self._store.get(self.ENTITY, self.PK, id, error=errors.ProductNotFoundError)
        return models.Product(**record)

    def update(self, id: int = None, sku: str = None, name: str = None, category_id: int = None, price_cents: int = None, stock_qty: int = None, low_active: bool = None) -> models.Product:
        """Updates an existing Product. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if id is not None:
            criteria.append(('id', 'eq', id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise errors.ProductNotFoundError(f"Product update matched {len(found)} records")
        patch = {}
        if id is not None and 'id' in ['id', 'sku', 'name', 'category_id', 'price_cents', 'stock_qty', 'low_active']:
            patch['id'] = id
        if sku is not None and 'sku' in ['id', 'sku', 'name', 'category_id', 'price_cents', 'stock_qty', 'low_active']:
            patch['sku'] = sku
        if name is not None and 'name' in ['id', 'sku', 'name', 'category_id', 'price_cents', 'stock_qty', 'low_active']:
            patch['name'] = name
        if category_id is not None and 'category_id' in ['id', 'sku', 'name', 'category_id', 'price_cents', 'stock_qty', 'low_active']:
            patch['category_id'] = category_id
        if price_cents is not None and 'price_cents' in ['id', 'sku', 'name', 'category_id', 'price_cents', 'stock_qty', 'low_active']:
            patch['price_cents'] = price_cents
        if stock_qty is not None and 'stock_qty' in ['id', 'sku', 'name', 'category_id', 'price_cents', 'stock_qty', 'low_active']:
            patch['stock_qty'] = stock_qty
        if low_active is not None and 'low_active' in ['id', 'sku', 'name', 'category_id', 'price_cents', 'stock_qty', 'low_active']:
            patch['low_active'] = low_active
        value = patch.get('stock_qty')
        if value is not None and value < 0:
            raise ValueError(f"Product.stock_qty must be >= 0, got {value!r}")
        for unique_field in ['sku']:
            value = patch.get(unique_field)
            if value is not None and any(row.get(self.PK) != found[0][self.PK] for row in self._store.select(self.ENTITY, [(unique_field, 'eq', value)])):
                raise ValueError(f"Product with {unique_field}={value!r} already exists")
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=errors.ProductNotFoundError)
        return models.Product(**record)
