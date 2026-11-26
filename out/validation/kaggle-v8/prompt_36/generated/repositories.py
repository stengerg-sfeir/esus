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
    PK = "category_id"

    def __init__(self, store):
        self._store = store


    def create(self, name: str = None) -> Any:
        """Creates a new Category. [crud:create: STANDARD_CRUD]"""
        values = {}
        if name is not None:
            values['name'] = name
        unknown = [k for k in values if k not in ['category_id', 'name']]
        if unknown:
            raise ValueError(f"cannot create Category from {unknown}")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[])
        return models.Category(**record)

    def read_all(self, name: str = None) -> list[models.Category]:
        """Lists every Category; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if name is not None:
            criteria.append(('name', 'eq', name))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Category(**r) for r in found]

    def read_one(self, category_id: int = None) -> Any:
        """Reads one Category by its key. [crud:read_one: READ_ONE_BY_ID]"""
        record = self._store.get(self.ENTITY, self.PK, category_id, error=errors.CategoryNotFoundError)
        return models.Category(**record)

    def delete(self, category_id: int = None, name: str = None) -> None:
        """Deletes an existing Category. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if category_id is not None:
            criteria.append(('category_id', 'eq', category_id))
        if name is not None:
            criteria.append(('name', 'eq', name))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise errors.CategoryNotFoundError(f"Category delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None

    def find_category_by_name(self, name: str = None) -> models.Category | None:
        """Finds a category by its name, returning the category if found, otherwise None. [crud:read_one: READ_ONE_BY_ID]"""
        criteria = []
        if name is not None:
            criteria.append(('name', 'eq', name))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise errors.CategoryNotFoundError(f"Category lookup matched {len(found)} records")
        record = found[0]
        return models.Category(**record)

    def get_category_count(self) -> int:
        """Returns the total number of categories in the system. [llm-written by server — review]"""
        return len(self._store.select(self.ENTITY, []))


class ProductRepository:
    ENTITY = "Product"
    PK = "product_id"

    def __init__(self, store):
        self._store = store


    def create(self, name: str = None, category_id: int = None) -> Any:
        """Creates a new Product. [crud:create: STANDARD_CRUD]"""
        values = {}
        if name is not None:
            values['name'] = name
        if category_id is not None:
            values['category_id'] = category_id
        unknown = [k for k in values if k not in ['product_id', 'name', 'category_id']]
        if unknown:
            raise ValueError(f"cannot create Product from {unknown}")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[("category_id", "Category", "category_id", errors.CategoryNotFoundError)])
        return models.Product(**record)

    def read_one(self, product_id: int = None) -> Any:
        """Reads one Product by its key. [crud:read_one: READ_ONE_BY_ID]"""
        record = self._store.get(self.ENTITY, self.PK, product_id, error=errors.ProductNotFoundError)
        return models.Product(**record)

    def read_all(self, name: str = None, category_id: int = None) -> list[models.Product]:
        """Lists every Product; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if name is not None:
            criteria.append(('name', 'eq', name))
        if category_id is not None:
            criteria.append(('category_id', 'eq', category_id))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Product(**r) for r in found]

    def get_products_by_category_id(self, category_id: int = None) -> list[models.Product]:
        """Lists the Product records belonging to one Category. [crud:filter: FILTER_BY_FIELD: by parameter shape]"""
        criteria = []
        if category_id is not None:
            criteria.append(('category_id', 'eq', category_id))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Product(**r) for r in found]

    def find_product_by_name(self, name: str = None) -> models.Product | None:
        """Finds a product by its name, returning the product if found, otherwise None. [crud:read_one: READ_ONE_BY_ID]"""
        criteria = []
        if name is not None:
            criteria.append(('name', 'eq', name))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise errors.ProductNotFoundError(f"Product lookup matched {len(found)} records")
        record = found[0]
        return models.Product(**record)

    def find_product_by_category_id(self, category_id: int = None) -> list[models.Product]:
        """Finds all products belonging to a specific category by category_id. [crud:filter: FILTER_BY_FIELD]"""
        criteria = []
        if category_id is not None:
            criteria.append(('category_id', 'eq', category_id))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Product(**r) for r in found]

    def get_product_count_in_category(self, category_id: int = None) -> int:
        """Returns the number of products belonging to a given category. [llm-written by server — review]"""
        criteria = []
        if category_id is not None:
            criteria.append(('category_id', 'eq', category_id))
        found = self._store.select(self.ENTITY, criteria)
        return len(found)
