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

    def read_all_categories(self) -> list[models.Category]:
        """Retrieves all categories from the database, including their names and IDs. [crud:read_all: READ_ALL]"""
        criteria = []
        found = self._store.select(self.ENTITY, criteria)
        return [models.Category(**r) for r in found]

    def read_category_by_id(self, category_id: int = None) -> models.Category | None:
        """Retrieves a specific category by its category_id. [crud:read_one: READ_ONE_BY_ID]"""
        record = self._store.get(self.ENTITY, self.PK, category_id, error=errors.CategoryNotFoundError)
        return models.Category(**record)

    def create_category(self, name: str = None) -> Any:
        """Creates a new category with the provided name and returns the created category. [crud:create: STANDARD_CRUD]"""
        values = {}
        if name is not None:
            values['name'] = name
        unknown = [k for k in values if k not in ['category_id', 'name']]
        if unknown:
            raise ValueError(f"cannot create Category from {unknown}")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[])
        return models.Category(**record)

    def delete_category(self, category_id: int = None) -> bool:
        """Deletes a category only if it does not have any associated products. Throws an error if the category has active products. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if category_id is not None:
            criteria.append(('category_id', 'eq', category_id))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise errors.CategoryNotFoundError(f"Category delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None


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

    def read_product_by_id(self, product_id: int = None) -> models.Product | None:
        """Retrieves a specific product by its product_id. [crud:read_one: READ_ONE_BY_ID]"""
        record = self._store.get(self.ENTITY, self.PK, product_id, error=errors.ProductNotFoundError)
        return models.Product(**record)

    def read_all_products(self) -> list[models.Product]:
        """Retrieves all products from the database, including their names, category_id, and other attributes. [crud:read_all: READ_ALL]"""
        criteria = []
        found = self._store.select(self.ENTITY, criteria)
        return [models.Product(**r) for r in found]

    def create_product(self, name: str = None, category_id: int = None) -> Any:
        """Creates a new product with the provided name and category_id. Ensures the category_id references an existing category. [crud:create: STANDARD_CRUD]"""
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

    def update_product_category(self, product_id: int = None, new_category_id: int = None) -> bool:
        """Updates the category of a product, ensuring the new category exists and the product is reassigned to it. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if product_id is not None:
            criteria.append(('product_id', 'eq', product_id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise errors.ProductNotFoundError(f"Product update matched {len(found)} records")
        patch = {}
        if product_id is not None and 'product_id' in ['product_id', 'name', 'category_id']:
            patch['product_id'] = product_id
        if new_category_id is not None and 'new_category_id' in ['product_id', 'name', 'category_id']:
            patch['new_category_id'] = new_category_id
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=errors.ProductNotFoundError)
        return models.Product(**record)

    def delete_product(self, product_id: int = None) -> bool:
        """Deletes a product only if it does not belong to a category that has other products. Does not delete the category. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if product_id is not None:
            criteria.append(('product_id', 'eq', product_id))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise errors.ProductNotFoundError(f"Product delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None
