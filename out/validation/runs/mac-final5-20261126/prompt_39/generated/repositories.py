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



class UserRepository:
    ENTITY = "User"
    PK = "user_id"

    def __init__(self, store):
        self._store = store


    def create(self, email: str = None, password_hash: str = None, is_admin: bool = None) -> Any:
        """Creates a new User. [crud:create: STANDARD_CRUD]"""
        values = {}
        if email is not None:
            values['email'] = email
        if password_hash is not None:
            values['password_hash'] = password_hash
        if is_admin is not None:
            values['is_admin'] = is_admin
        unknown = [k for k in values if k not in ['user_id', 'email', 'password_hash', 'is_admin']]
        if unknown:
            raise ValueError(f"cannot create User from {unknown}")
        if values.get('is_admin') is None:
            values['is_admin'] = False
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[])
        return models.User(**record)

    def read_one(self, user_id: int = None) -> Any:
        """Reads one User by its key. [crud:read_one: READ_ONE_BY_ID]"""
        record = self._store.get(self.ENTITY, self.PK, user_id, error=errors.UserNotFoundError)
        return models.User(**record)

    def read_all(self, email: str = None, password_hash: str = None, is_admin: bool = None) -> list[models.User]:
        """Lists every User; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if email is not None:
            criteria.append(('email', 'eq', email))
        if password_hash is not None:
            criteria.append(('password_hash', 'eq', password_hash))
        if is_admin is not None:
            criteria.append(('is_admin', 'eq', is_admin))
        found = self._store.select(self.ENTITY, criteria)
        return [models.User(**r) for r in found]

    def update(self, user_id: int = None, email: str = None, password_hash: str = None, is_admin: bool = None) -> Any:
        """Updates an existing User. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if user_id is not None:
            criteria.append(('user_id', 'eq', user_id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise errors.UserNotFoundError(f"User update matched {len(found)} records")
        patch = {}
        if user_id is not None and 'user_id' in ['user_id', 'email', 'password_hash', 'is_admin']:
            patch['user_id'] = user_id
        if email is not None and 'email' in ['user_id', 'email', 'password_hash', 'is_admin']:
            patch['email'] = email
        if password_hash is not None and 'password_hash' in ['user_id', 'email', 'password_hash', 'is_admin']:
            patch['password_hash'] = password_hash
        if is_admin is not None and 'is_admin' in ['user_id', 'email', 'password_hash', 'is_admin']:
            patch['is_admin'] = is_admin
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=errors.UserNotFoundError)
        return models.User(**record)

    def delete(self, user_id: int = None, email: str = None, password_hash: str = None, is_admin: bool = None) -> None:
        """Deletes an existing User. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if user_id is not None:
            criteria.append(('user_id', 'eq', user_id))
        if email is not None:
            criteria.append(('email', 'eq', email))
        if password_hash is not None:
            criteria.append(('password_hash', 'eq', password_hash))
        if is_admin is not None:
            criteria.append(('is_admin', 'eq', is_admin))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise errors.UserNotFoundError(f"User delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None

    def find_user_by_email(self, email: str = None) -> models.User | None:
        """Retrieves a user record by their email address. [crud:read_one: READ_ONE_BY_ID]"""
        criteria = []
        if email is not None:
            criteria.append(('email', 'eq', email))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise errors.UserNotFoundError(f"User lookup matched {len(found)} records")
        record = found[0]
        return models.User(**record)

    def find_user_by_id(self, user_id: int = None) -> models.User | None:
        """Retrieves a user record by their primary key (user_id). [crud:read_one: READ_ONE_BY_ID]"""
        record = self._store.get(self.ENTITY, self.PK, user_id, error=errors.UserNotFoundError)
        return models.User(**record)

    def get_admin_users(self, user_id: int = None) -> list[models.User]:
        """Retrieves all users who have the is_admin flag set to True. [mechanical boolean filter]"""
        return _model_list(self._store.select(self.ENTITY, [('is_admin', 'eq', True)]), models.User)


class ProductRepository:
    ENTITY = "Product"
    PK = "product_id"

    def __init__(self, store):
        self._store = store


    def create(self, name: str = None, price: int = None, description: str = None) -> Any:
        """Creates a new Product. [crud:create: STANDARD_CRUD]"""
        values = {}
        if name is not None:
            values['name'] = name
        if price is not None:
            values['price'] = price
        if description is not None:
            values['description'] = description
        unknown = [k for k in values if k not in ['product_id', 'name', 'price', 'description']]
        if unknown:
            raise ValueError(f"cannot create Product from {unknown}")
        value = values.get('price')
        if value is not None and value <= 0:
            raise ValueError(f"Product.price must be > 0, got {value!r}")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[])
        return models.Product(**record)

    def read_one(self, product_id: int = None) -> Any:
        """Reads one Product by its key. [crud:read_one: READ_ONE_BY_ID]"""
        record = self._store.get(self.ENTITY, self.PK, product_id, error=errors.ProductNotFoundError)
        return models.Product(**record)

    def read_all(self, name: str = None, price: int = None, description: str = None) -> list[models.Product]:
        """Lists every Product; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if name is not None:
            criteria.append(('name', 'eq', name))
        if price is not None:
            criteria.append(('price', 'eq', price))
        if description is not None:
            criteria.append(('description', 'eq', description))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Product(**r) for r in found]

    def update(self, product_id: int = None, name: str = None, price: int = None, description: str = None) -> Any:
        """Updates an existing Product. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if product_id is not None:
            criteria.append(('product_id', 'eq', product_id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise errors.ProductNotFoundError(f"Product update matched {len(found)} records")
        patch = {}
        if product_id is not None and 'product_id' in ['product_id', 'name', 'price', 'description']:
            patch['product_id'] = product_id
        if name is not None and 'name' in ['product_id', 'name', 'price', 'description']:
            patch['name'] = name
        if price is not None and 'price' in ['product_id', 'name', 'price', 'description']:
            patch['price'] = price
        if description is not None and 'description' in ['product_id', 'name', 'price', 'description']:
            patch['description'] = description
        value = patch.get('price')
        if value is not None and value <= 0:
            raise ValueError(f"Product.price must be > 0, got {value!r}")
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=errors.ProductNotFoundError)
        return models.Product(**record)

    def delete(self, product_id: int = None, name: str = None, price: int = None, description: str = None) -> None:
        """Deletes an existing Product. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if product_id is not None:
            criteria.append(('product_id', 'eq', product_id))
        if name is not None:
            criteria.append(('name', 'eq', name))
        if price is not None:
            criteria.append(('price', 'eq', price))
        if description is not None:
            criteria.append(('description', 'eq', description))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise errors.ProductNotFoundError(f"Product delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None

    def find_product_by_name(self, name: str = None) -> models.Product | None:
        """Retrieves a product record by its name. [crud:read_one: READ_ONE_BY_ID]"""
        criteria = []
        if name is not None:
            criteria.append(('name', 'eq', name))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise errors.ProductNotFoundError(f"Product lookup matched {len(found)} records")
        record = found[0]
        return models.Product(**record)

    def find_product_by_id(self, product_id: int = None) -> models.Product | None:
        """Retrieves a product record by its primary key (product_id). [crud:read_one: READ_ONE_BY_ID]"""
        record = self._store.get(self.ENTITY, self.PK, product_id, error=errors.ProductNotFoundError)
        return models.Product(**record)

    def get_all_active_products(self) -> list[models.Product]:
        """Retrieves all products with a non-null and valid status (active). [crud:read_all: READ_ALL]"""
        criteria = []
        found = self._store.select(self.ENTITY, criteria)
        return [models.Product(**r) for r in found]


class OrderRepository:
    ENTITY = "Order"
    PK = "order_id"

    def __init__(self, store):
        self._store = store


    def create(self, user_id: int = None, order_date: Any = None, status: str = None) -> Any:
        """Creates a new Order. [crud:create: STANDARD_CRUD]"""
        values = {}
        if user_id is not None:
            values['user_id'] = user_id
        if order_date is not None:
            values['order_date'] = order_date
        if status is not None:
            values['status'] = status
        unknown = [k for k in values if k not in ['order_id', 'user_id', 'order_date', 'status']]
        if unknown:
            raise ValueError(f"cannot create Order from {unknown}")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[("user_id", "User", "user_id", errors.UserNotFoundError)])
        return models.Order(**record)

    def read_one(self, order_id: int = None) -> Any:
        """Reads one Order by its key. [crud:read_one: READ_ONE_BY_ID]"""
        record = self._store.get(self.ENTITY, self.PK, order_id, error=errors.OrderNotFoundError)
        return models.Order(**record)

    def read_all(self, user_id: int = None, order_date: Any = None, status: str = None) -> list[models.Order]:
        """Lists every Order; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if user_id is not None:
            criteria.append(('user_id', 'eq', user_id))
        if order_date is not None:
            criteria.append(('order_date', 'eq', order_date))
        if status is not None:
            criteria.append(('status', 'eq', status))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Order(**r) for r in found]

    def get_orders_by_user_id(self, user_id: int = None) -> list[models.Order]:
        """Lists the Order records belonging to one User. [crud:filter: FILTER_BY_FIELD: by parameter shape]"""
        criteria = []
        if user_id is not None:
            criteria.append(('user_id', 'eq', user_id))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Order(**r) for r in found]

    def find_order_by_user_id_and_date(self, user_id: int = None, order_date: datetime.datetime = None) -> models.Order | None:
        """Retrieves an order by user_id and order_date to allow users to view their own order history. [crud:read_one: READ_ONE_BY_ID]"""
        criteria = []
        if user_id is not None:
            criteria.append(('user_id', 'eq', user_id))
        if order_date is not None:
            criteria.append(('order_date', 'eq', order_date))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise errors.OrderNotFoundError(f"Order lookup matched {len(found)} records")
        record = found[0]
        return models.Order(**record)

    def get_user_orders(self, user_id: int = None) -> list[models.Order]:
        """Retrieves all orders for a specific user, ordered by order_date in descending order. [crud:filter: FILTER_BY_FIELD: by parameter shape]"""
        criteria = []
        if user_id is not None:
            criteria.append(('user_id', 'eq', user_id))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Order(**r) for r in found]

    def get_orders_by_status(self, status: str = None) -> list[models.Order]:
        """Retrieves all orders with a specific status (e.g., 'pending', 'shipped'). [crud:filter: FILTER_BY_FIELD: by parameter shape]"""
        criteria = []
        if status is not None:
            criteria.append(('status', 'eq', status))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Order(**r) for r in found]

    def update(self, order_id: int = None, user_id: int = None, order_date: Any = None, status: str = None) -> models.Order:
        """Updates an existing Order. [crud:update: name-only: step F never saw this method]"""
        criteria = []
        if order_id is not None:
            criteria.append(('order_id', 'eq', order_id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise errors.OrderNotFoundError(f"Order update matched {len(found)} records")
        patch = {}
        if order_id is not None and 'order_id' in ['order_id', 'user_id', 'order_date', 'status']:
            patch['order_id'] = order_id
        if user_id is not None and 'user_id' in ['order_id', 'user_id', 'order_date', 'status']:
            patch['user_id'] = user_id
        if order_date is not None and 'order_date' in ['order_id', 'user_id', 'order_date', 'status']:
            patch['order_date'] = order_date
        if status is not None and 'status' in ['order_id', 'user_id', 'order_date', 'status']:
            patch['status'] = status
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=errors.OrderNotFoundError)
        return models.Order(**record)
