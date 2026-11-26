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


    def create(self, sku: str = None, category: str = None, name: str = None, description: str = None, price: int = None) -> Any:
        """Creates a new Product. [crud:create: STANDARD_CRUD]"""
        values = {}
        if sku is not None:
            values['sku'] = sku
        if category is not None:
            values['category'] = category
        if name is not None:
            values['name'] = name
        if description is not None:
            values['description'] = description
        if price is not None:
            values['price'] = price
        unknown = [k for k in values if k not in ['id', 'sku', 'category', 'name', 'description', 'price']]
        if unknown:
            raise ValueError(f"cannot create Product from {unknown}")
        for unique_field in ['sku']:
            value = values.get(unique_field)
            if value is not None and self._store.select(self.ENTITY, [(unique_field, 'eq', value)]):
                raise ValueError(f"Product with {unique_field}={value!r} already exists")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[])
        return models.Product(**record)

    def read_one(self, id: int = None) -> Any:
        """Reads one Product by its key. [crud:read_one: READ_ONE_BY_ID]"""
        found = self._store.select(self.ENTITY, [(self.PK, 'eq', id)])
        if not found:
            return None
        record = found[0]
        return models.Product(**record)

    def read_all(self, sku: str = None, category: str = None, name: str = None, description: str = None, price: int = None) -> list[models.Product]:
        """Lists every Product; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if sku is not None:
            criteria.append(('sku', 'eq', sku))
        if category is not None:
            criteria.append(('category', 'eq', category))
        if name is not None:
            criteria.append(('name', 'eq', name))
        if description is not None:
            criteria.append(('description', 'eq', description))
        if price is not None:
            criteria.append(('price', 'eq', price))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Product(**r) for r in found]

    def update(self, id: int = None, sku: str = None, category: str = None, name: str = None, description: str = None, price: int = None) -> Any:
        """Updates an existing Product. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if id is not None:
            criteria.append(('id', 'eq', id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise LookupError(f"Product update matched {len(found)} records")
        patch = {}
        if id is not None and 'id' in ['id', 'sku', 'category', 'name', 'description', 'price']:
            patch['id'] = id
        if sku is not None and 'sku' in ['id', 'sku', 'category', 'name', 'description', 'price']:
            patch['sku'] = sku
        if category is not None and 'category' in ['id', 'sku', 'category', 'name', 'description', 'price']:
            patch['category'] = category
        if name is not None and 'name' in ['id', 'sku', 'category', 'name', 'description', 'price']:
            patch['name'] = name
        if description is not None and 'description' in ['id', 'sku', 'category', 'name', 'description', 'price']:
            patch['description'] = description
        if price is not None and 'price' in ['id', 'sku', 'category', 'name', 'description', 'price']:
            patch['price'] = price
        for unique_field in ['sku']:
            value = patch.get(unique_field)
            if value is not None and any(row.get(self.PK) != found[0][self.PK] for row in self._store.select(self.ENTITY, [(unique_field, 'eq', value)])):
                raise ValueError(f"Product with {unique_field}={value!r} already exists")
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=LookupError)
        return models.Product(**record)

    def delete(self, id: int = None, sku: str = None, category: str = None, name: str = None, description: str = None, price: int = None) -> None:
        """Deletes an existing Product. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if id is not None:
            criteria.append(('id', 'eq', id))
        if sku is not None:
            criteria.append(('sku', 'eq', sku))
        if category is not None:
            criteria.append(('category', 'eq', category))
        if name is not None:
            criteria.append(('name', 'eq', name))
        if description is not None:
            criteria.append(('description', 'eq', description))
        if price is not None:
            criteria.append(('price', 'eq', price))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise LookupError(f"Product delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None
