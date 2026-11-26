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

    def find_by_name(self, name: str = None) -> List[models.Product]:
        """Search products by name using partial matching; returns a list of products whose name contains the given string. [crud:filter: FILTER_WITH_PAGINATION: by parameter shape]"""
        criteria = []
        if name is not None:
            criteria.append(('name', 'eq', name))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Product(**r) for r in found]

    def filter_by_category(self, category: str = None) -> List[models.Product]:
        """Filter products by category; returns a list of products that match the specified category. [crud:filter: FILTER_BY_FIELD]"""
        criteria = []
        if category is not None:
            criteria.append(('category', 'eq', category))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Product(**r) for r in found]

    def filter_by_max_price(self, max_price: float = None) -> List[models.Product]:
        """Filter products with price less than or equal to the specified maximum price; returns a list of products within the price limit. [FILTER_BY_NAMED_FIELD: filter_by_max_price]"""
        criteria = [('price', 'ge', 1)] if max_price is not False else []
        found = self._store.select(self.ENTITY, criteria)
        return [models.Product(**record) for record in found]

    def filter_by_min_quantity(self, min_quantity: int = None) -> List[models.Product]:
        """Filter products with quantity greater than or equal to the specified minimum quantity; returns a list of products meeting the quantity threshold. [FILTER_BY_NAMED_FIELD: filter_by_min_quantity]"""
        criteria = [('quantity', 'ge', 1)] if min_quantity is not False else []
        found = self._store.select(self.ENTITY, criteria)
        return [models.Product(**record) for record in found]

    def find_all_with_filters(self, name: str = None, category: str = None, max_price: float = None, min_quantity: int = None) -> List[models.Product]:
        """Combine multiple filters (name, category, max price, min quantity) to return products that satisfy all specified conditions simultaneously. [crud:filter: FILTER_BY_FIELD]"""
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

    def search_product_by_name(self, name: str = None) -> list[models.Product]:
        """Search product by name. [mechanical text search]"""
        if not name:
            return []
        query = str(name).lower()
        result = []
        for row in self._store.select(self.ENTITY, []):
            values = [row.get('name'), row.get('category')]
            if any(value is not None and query in str(value).lower() for value in values):
                result.append(row)
        return _model_list([models.Product(**row) for row in result], models.Product)

    def find_all_products_with_filters(self, name: str = None, category: str = None, max_price: str = None, min_quantity: str = None) -> list[models.Product]:
        """Find all products with filters. [crud:filter: name-only: step F never saw this method]"""
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
