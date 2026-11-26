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


    def create(self, name: str = None, stock_quantity: int = None) -> Any:
        """Creates a new Product. [crud:create: STANDARD_CRUD]"""
        values = {}
        if name is not None:
            values['name'] = name
        if stock_quantity is not None:
            values['stock_quantity'] = stock_quantity
        unknown = [k for k in values if k not in ['product_id', 'name', 'stock_quantity']]
        if unknown:
            raise ValueError(f"cannot create Product from {unknown}")
        value = values.get('stock_quantity')
        if value is not None and value < 0:
            raise ValueError(f"Product.stock_quantity must be >= 0, got {value!r}")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[])
        return models.Product(**record)

    def read_all(self, name: str = None, stock_quantity: int = None) -> list[models.Product]:
        """Lists every Product; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if name is not None:
            criteria.append(('name', 'eq', name))
        if stock_quantity is not None:
            criteria.append(('stock_quantity', 'eq', stock_quantity))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Product(**r) for r in found]

    def read_one(self, product_id: int = None) -> Any:
        """Reads one Product by its key. [crud:read_one: READ_ONE_BY_ID]"""
        found = self._store.select(self.ENTITY, [(self.PK, 'eq', product_id)])
        if not found:
            return None
        record = found[0]
        return models.Product(**record)

    def update(self, product_id: int = None, name: str = None, stock_quantity: int = None) -> Any:
        """Updates an existing Product. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if product_id is not None:
            criteria.append(('product_id', 'eq', product_id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise LookupError(f"Product update matched {len(found)} records")
        patch = {}
        if product_id is not None and 'product_id' in ['product_id', 'name', 'stock_quantity']:
            patch['product_id'] = product_id
        if name is not None and 'name' in ['product_id', 'name', 'stock_quantity']:
            patch['name'] = name
        if stock_quantity is not None and 'stock_quantity' in ['product_id', 'name', 'stock_quantity']:
            patch['stock_quantity'] = stock_quantity
        value = patch.get('stock_quantity')
        if value is not None and value < 0:
            raise ValueError(f"Product.stock_quantity must be >= 0, got {value!r}")
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=LookupError)
        return models.Product(**record)

    def delete(self, product_id: int = None, name: str = None, stock_quantity: int = None) -> None:
        """Deletes an existing Product. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if product_id is not None:
            criteria.append(('product_id', 'eq', product_id))
        if name is not None:
            criteria.append(('name', 'eq', name))
        if stock_quantity is not None:
            criteria.append(('stock_quantity', 'eq', stock_quantity))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise LookupError(f"Product delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None

    def get_product_by_name(self, name: str = None) -> Any:
        """Retrieves a product by its name, ensuring accurate inventory tracking through consistent product identification. [crud:read_one: READ_ONE_BY_ID]"""
        criteria = []
        if name is not None:
            criteria.append(('name', 'eq', name))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            return None
        record = found[0]
        return models.Product(**record)

    def get_product_by_stock_quantity(self, stock_quantity: int = None) -> Any:
        """Finds a product with a specific stock quantity, useful for identifying low-stock items to trigger reordering. [crud:read_one: READ_ONE_BY_ID]"""
        criteria = []
        if stock_quantity is not None:
            criteria.append(('stock_quantity', 'eq', stock_quantity))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            return None
        record = found[0]
        return models.Product(**record)


class UserRepository:
    ENTITY = "User"
    PK = "user_id"

    def __init__(self, store):
        self._store = store


    def create(self, name: str = None, email: str = None) -> Any:
        """Creates a new User. [crud:create: STANDARD_CRUD]"""
        values = {}
        if name is not None:
            values['name'] = name
        if email is not None:
            values['email'] = email
        unknown = [k for k in values if k not in ['user_id', 'name', 'email']]
        if unknown:
            raise ValueError(f"cannot create User from {unknown}")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[])
        return models.User(**record)

    def read_all(self, name: str = None, email: str = None) -> list[models.User]:
        """Lists every User; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if name is not None:
            criteria.append(('name', 'eq', name))
        if email is not None:
            criteria.append(('email', 'eq', email))
        found = self._store.select(self.ENTITY, criteria)
        return [models.User(**r) for r in found]

    def read_one(self, user_id: int = None) -> Any:
        """Reads one User by its key. [crud:read_one: READ_ONE_BY_ID]"""
        found = self._store.select(self.ENTITY, [(self.PK, 'eq', user_id)])
        if not found:
            return None
        record = found[0]
        return models.User(**record)

    def update(self, user_id: int = None, name: str = None, email: str = None) -> Any:
        """Updates an existing User. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if user_id is not None:
            criteria.append(('user_id', 'eq', user_id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise LookupError(f"User update matched {len(found)} records")
        patch = {}
        if user_id is not None and 'user_id' in ['user_id', 'name', 'email']:
            patch['user_id'] = user_id
        if name is not None and 'name' in ['user_id', 'name', 'email']:
            patch['name'] = name
        if email is not None and 'email' in ['user_id', 'name', 'email']:
            patch['email'] = email
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=LookupError)
        return models.User(**record)

    def delete(self, user_id: int = None, name: str = None, email: str = None) -> None:
        """Deletes an existing User. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if user_id is not None:
            criteria.append(('user_id', 'eq', user_id))
        if name is not None:
            criteria.append(('name', 'eq', name))
        if email is not None:
            criteria.append(('email', 'eq', email))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise LookupError(f"User delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None

    def get_user_by_email(self, email: str = None) -> Any:
        """Retrieves a user by their email address, enabling secure and accurate user authentication and access control. [crud:read_one: READ_ONE_BY_ID]"""
        criteria = []
        if email is not None:
            criteria.append(('email', 'eq', email))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            return None
        record = found[0]
        return models.User(**record)


class SaleRepository:
    ENTITY = "Sale"
    PK = "sale_id"

    def __init__(self, store):
        self._store = store


    def create(self, product_id: int = None, user_id: int = None, quantity: int = None, sale_date: Any = None) -> Any:
        """Creates a new Sale. [crud:create: STANDARD_CRUD]"""
        values = {}
        if product_id is not None:
            values['product_id'] = product_id
        if user_id is not None:
            values['user_id'] = user_id
        if quantity is not None:
            values['quantity'] = quantity
        if sale_date is not None:
            values['sale_date'] = sale_date
        unknown = [k for k in values if k not in ['sale_id', 'product_id', 'user_id', 'quantity', 'sale_date']]
        if unknown:
            raise ValueError(f"cannot create Sale from {unknown}")
        value = values.get('quantity')
        if value is not None and value < 0:
            raise ValueError(f"Sale.quantity must be >= 0, got {value!r}")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[("product_id", "Product", "product_id", None), ("user_id", "User", "user_id", None)])
        return models.Sale(**record)

    def read_all(self, product_id: int = None, user_id: int = None, quantity: int = None, sale_date: Any = None) -> list[models.Sale]:
        """Lists every Sale; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if product_id is not None:
            criteria.append(('product_id', 'eq', product_id))
        if user_id is not None:
            criteria.append(('user_id', 'eq', user_id))
        if quantity is not None:
            criteria.append(('quantity', 'eq', quantity))
        if sale_date is not None:
            criteria.append(('sale_date', 'eq', sale_date))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Sale(**r) for r in found]

    def read_one(self, sale_id: int = None) -> Any:
        """Reads one Sale by its key. [crud:read_one: READ_ONE_BY_ID]"""
        found = self._store.select(self.ENTITY, [(self.PK, 'eq', sale_id)])
        if not found:
            return None
        record = found[0]
        return models.Sale(**record)

    def get_sales_by_product_id(self, product_id: int = None) -> list[models.Sale]:
        """Lists the Sale records belonging to one Product. [crud:filter: FILTER_BY_FIELD: by parameter shape]"""
        criteria = []
        if product_id is not None:
            criteria.append(('product_id', 'eq', product_id))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Sale(**r) for r in found]
