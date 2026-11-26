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


    def create(self, sku: str = None, category_id: int = None, product_name: str = None, description: str = None, price: int = None, created_at: Any = None, updated_at: Any = None) -> Any:
        """Creates a new Product. [crud:create: STANDARD_CRUD]"""
        values = {}
        if sku is not None:
            values['sku'] = sku
        if category_id is not None:
            values['category_id'] = category_id
        if product_name is not None:
            values['product_name'] = product_name
        if description is not None:
            values['description'] = description
        if price is not None:
            values['price'] = price
        if created_at is not None:
            values['created_at'] = created_at
        if updated_at is not None:
            values['updated_at'] = updated_at
        unknown = [k for k in values if k not in ['product_id', 'sku', 'category_id', 'product_name', 'description', 'price', 'created_at', 'updated_at']]
        if unknown:
            raise ValueError(f"cannot create Product from {unknown}")
        if values.get('created_at') is None:
            values['created_at'] = datetime.datetime.now()
        if values.get('updated_at') is None:
            values['updated_at'] = datetime.datetime.now()
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[("category_id", "Category", "category_id", None)])
        return models.Product(**record)

    def read_all(self, sku: str = None, category_id: int = None, product_name: str = None, description: str = None, price: int = None, created_at: Any = None, updated_at: Any = None) -> list[models.Product]:
        """Lists every Product; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if sku is not None:
            criteria.append(('sku', 'eq', sku))
        if category_id is not None:
            criteria.append(('category_id', 'eq', category_id))
        if product_name is not None:
            criteria.append(('product_name', 'eq', product_name))
        if description is not None:
            criteria.append(('description', 'eq', description))
        if price is not None:
            criteria.append(('price', 'eq', price))
        if created_at is not None:
            criteria.append(('created_at', 'eq', created_at))
        if updated_at is not None:
            criteria.append(('updated_at', 'eq', updated_at))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Product(**r) for r in found]

    def read_one(self, product_id: int = None) -> Any:
        """Reads one Product by its key. [crud:read_one: READ_ONE_BY_ID]"""
        found = self._store.select(self.ENTITY, [(self.PK, 'eq', product_id)])
        if not found:
            return None
        record = found[0]
        return models.Product(**record)

    def update(self, product_id: int = None, sku: str = None, category_id: int = None, product_name: str = None, description: str = None, price: int = None, created_at: Any = None, updated_at: Any = None) -> Any:
        """Updates an existing Product. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if product_id is not None:
            criteria.append(('product_id', 'eq', product_id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise LookupError(f"Product update matched {len(found)} records")
        patch = {}
        if product_id is not None and 'product_id' in ['product_id', 'sku', 'category_id', 'product_name', 'description', 'price', 'created_at', 'updated_at']:
            patch['product_id'] = product_id
        if sku is not None and 'sku' in ['product_id', 'sku', 'category_id', 'product_name', 'description', 'price', 'created_at', 'updated_at']:
            patch['sku'] = sku
        if category_id is not None and 'category_id' in ['product_id', 'sku', 'category_id', 'product_name', 'description', 'price', 'created_at', 'updated_at']:
            patch['category_id'] = category_id
        if product_name is not None and 'product_name' in ['product_id', 'sku', 'category_id', 'product_name', 'description', 'price', 'created_at', 'updated_at']:
            patch['product_name'] = product_name
        if description is not None and 'description' in ['product_id', 'sku', 'category_id', 'product_name', 'description', 'price', 'created_at', 'updated_at']:
            patch['description'] = description
        if price is not None and 'price' in ['product_id', 'sku', 'category_id', 'product_name', 'description', 'price', 'created_at', 'updated_at']:
            patch['price'] = price
        if created_at is not None and 'created_at' in ['product_id', 'sku', 'category_id', 'product_name', 'description', 'price', 'created_at', 'updated_at']:
            patch['created_at'] = created_at
        if updated_at is not None and 'updated_at' in ['product_id', 'sku', 'category_id', 'product_name', 'description', 'price', 'created_at', 'updated_at']:
            patch['updated_at'] = updated_at
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=LookupError)
        return models.Product(**record)

    def delete(self, product_id: int = None, sku: str = None, category_id: int = None, product_name: str = None, description: str = None, price: int = None, created_at: Any = None, updated_at: Any = None) -> None:
        """Deletes an existing Product. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if product_id is not None:
            criteria.append(('product_id', 'eq', product_id))
        if sku is not None:
            criteria.append(('sku', 'eq', sku))
        if category_id is not None:
            criteria.append(('category_id', 'eq', category_id))
        if product_name is not None:
            criteria.append(('product_name', 'eq', product_name))
        if description is not None:
            criteria.append(('description', 'eq', description))
        if price is not None:
            criteria.append(('price', 'eq', price))
        if created_at is not None:
            criteria.append(('created_at', 'eq', created_at))
        if updated_at is not None:
            criteria.append(('updated_at', 'eq', updated_at))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise LookupError(f"Product delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None

    def get_products_by_category_id(self, category_id: int = None) -> list[models.Product]:
        """Lists the Product records belonging to one Category. [crud:filter: FILTER_BY_FIELD: by parameter shape]"""
        criteria = []
        if category_id is not None:
            criteria.append(('category_id', 'eq', category_id))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Product(**r) for r in found]

    def findProductBySkuAndCategory(self, sku: str = None, category_id: int = None) -> Any:
        """Find a product by its SKU and the category it belongs to, ensuring uniqueness within categories. [crud:read_one: READ_ONE_BY_ID]"""
        criteria = []
        if sku is not None:
            criteria.append(('sku', 'eq', sku))
        if category_id is not None:
            criteria.append(('category_id', 'eq', category_id))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            return None
        record = found[0]
        return models.Product(**record)


class CategoryRepository:
    ENTITY = "Category"
    PK = "category_id"

    def __init__(self, store):
        self._store = store


    def create(self, category_name: str = None, description: str = None) -> Any:
        """Creates a new Category. [crud:create: STANDARD_CRUD]"""
        values = {}
        if category_name is not None:
            values['category_name'] = category_name
        if description is not None:
            values['description'] = description
        unknown = [k for k in values if k not in ['category_id', 'category_name', 'description']]
        if unknown:
            raise ValueError(f"cannot create Category from {unknown}")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[])
        return models.Category(**record)

    def read_all(self, category_name: str = None, description: str = None) -> list[models.Category]:
        """Lists every Category; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if category_name is not None:
            criteria.append(('category_name', 'eq', category_name))
        if description is not None:
            criteria.append(('description', 'eq', description))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Category(**r) for r in found]

    def read_one(self, category_id: int = None) -> Any:
        """Reads one Category by its key. [crud:read_one: READ_ONE_BY_ID]"""
        found = self._store.select(self.ENTITY, [(self.PK, 'eq', category_id)])
        if not found:
            return None
        record = found[0]
        return models.Category(**record)
