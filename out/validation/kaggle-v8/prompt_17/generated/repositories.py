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


    def read_all(self, name: str = None, category: str = None, price: int = None, quantity: int = None) -> list[models.Product]:
        """Lists every Product; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if name is not None:
            criteria.append(('name', 'eq', name))
        if category is not None:
            criteria.append(('category', 'eq', category))
        if price is not None:
            criteria.append(('price', 'eq', price))
        if quantity is not None:
            criteria.append(('quantity', 'eq', quantity))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Product(**r) for r in found]

    def read_one(self, id: int = None) -> Any:
        """Reads one Product by its key. [crud:read_one: READ_ONE_BY_ID]"""
        found = self._store.select(self.ENTITY, [(self.PK, 'eq', id)])
        if not found:
            return None
        record = found[0]
        return models.Product(**record)

    def find_products_by_name_and_category_and_price_range_and_quantity_range(self, name: str = None, category: str = None, max_price: float = None, min_quantity: int = None) -> list[models.Product]:
        """Retrieves a list of products that match the specified name, category, maximum price, and minimum quantity. All filters are combinable and applied together. [crud:filter: FILTER_WITH_PAGINATION: by parameter shape]"""
        criteria = []
        if name is not None:
            criteria.append(('name', 'eq', name))
        if category is not None:
            criteria.append(('category', 'eq', category))
        if max_price is not None:
            criteria.append(('price', 'le', max_price))
        if min_quantity is not None:
            criteria.append(('quantity', 'ge', min_quantity))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Product(**r) for r in found]

    def search_products(self, name: str = None, category: str = None, max_price: str = None, min_quantity: str = None) -> list[models.Product]:
        """Search products. [crud:filter: name-only: step F never saw this method]"""
        criteria = []
        if name is not None:
            criteria.append(('name', 'eq', name))
        if category is not None:
            criteria.append(('category', 'eq', category))
        if max_price is not None:
            criteria.append(('price', 'le', max_price))
        if min_quantity is not None:
            criteria.append(('quantity', 'ge', min_quantity))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Product(**r) for r in found]
