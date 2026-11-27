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



class OrderItemRepository:
    ENTITY = "OrderItem"
    PK = "order_item_id"

    def __init__(self, store):
        self._store = store


    def create(self, order_id: int = None, product_id: int = None, quantity: int = None, unit_price: int = None) -> models.OrderItem:
        """Creates a new OrderItem. [crud:create: STANDARD_CRUD]"""
        values = {}
        if order_id is not None:
            values['order_id'] = order_id
        if product_id is not None:
            values['product_id'] = product_id
        if quantity is not None:
            values['quantity'] = quantity
        if unit_price is not None:
            values['unit_price'] = unit_price
        unknown = [k for k in values if k not in ['order_item_id', 'order_id', 'product_id', 'quantity', 'unit_price']]
        if unknown:
            raise ValueError(f"cannot create OrderItem from {unknown}")
        value = values.get('quantity')
        if value is not None and value < 0:
            raise ValueError(f"OrderItem.quantity must be >= 0, got {value!r}")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[("order_id", "Order", "order_id", None), ("product_id", "Product", "product_id", None)])
        return models.OrderItem(**record)

    def find_order_item_by_product_id_and_order_id(self, order_id: int = None, product_id: int = None) -> models.OrderItem | None:
        """Retrieve a specific order item by order_id and product_id, used for inventory and order validation. [crud:read_one: READ_ONE_BY_ID]"""
        criteria = []
        if order_id is not None:
            criteria.append(('order_id', 'eq', order_id))
        if product_id is not None:
            criteria.append(('product_id', 'eq', product_id))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            return None
        record = found[0]
        return models.OrderItem(**record)

    def find_order_items_by_order_id(self, order_id: int = None) -> list[models.OrderItem]:
        """Retrieve all order items belonging to a specific order, used for order detail and inventory tracking. [mechanical contained-name filter]"""
        criteria = []
        if order_id is not None:
            criteria.append(('order_id', 'eq', order_id))
        found = self._store.select(self.ENTITY, criteria)
        return _model_list([models.OrderItem(**row) for row in found], models.OrderItem)

    def get_order_items_by_order_id(self, order_id: int = None) -> list[models.OrderItem]:
        """Lists the OrderItem records belonging to one Order. [mechanical contained-name filter]"""
        criteria = []
        if order_id is not None:
            criteria.append(('order_id', 'eq', order_id))
        found = self._store.select(self.ENTITY, criteria)
        return _model_list([models.OrderItem(**row) for row in found], models.OrderItem)

    def read_all(self, order_id: int = None, product_id: int = None, quantity: int = None, unit_price: int = None) -> list[models.OrderItem]:
        """Lists every OrderItem; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if order_id is not None:
            criteria.append(('order_id', 'eq', order_id))
        if product_id is not None:
            criteria.append(('product_id', 'eq', product_id))
        if quantity is not None:
            criteria.append(('quantity', 'eq', quantity))
        if unit_price is not None:
            criteria.append(('unit_price', 'eq', unit_price))
        found = self._store.select(self.ENTITY, criteria)
        return [models.OrderItem(**r) for r in found]

    def read_one(self, order_item_id: int = None) -> models.OrderItem:
        """Reads one OrderItem by its key. [crud:read_one: READ_ONE_BY_ID]"""
        found = self._store.select(self.ENTITY, [(self.PK, 'eq', order_item_id)])
        if not found:
            return None
        record = found[0]
        return models.OrderItem(**record)


class OrderRepository:
    ENTITY = "Order"
    PK = "order_id"

    def __init__(self, store):
        self._store = store


    def create(self, user_id: int = None, order_date: Any = None, total_amount: int = None, status: str = None) -> models.Order:
        """Creates a new Order. [crud:create: STANDARD_CRUD]"""
        values = {}
        if user_id is not None:
            values['user_id'] = user_id
        if order_date is not None:
            values['order_date'] = order_date
        if total_amount is not None:
            values['total_amount'] = total_amount
        if status is not None:
            values['status'] = status
        unknown = [k for k in values if k not in ['order_id', 'user_id', 'order_date', 'total_amount', 'status']]
        if unknown:
            raise ValueError(f"cannot create Order from {unknown}")
        if values.get('status') is None:
            values['status'] = 'pending'
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[("user_id", "User", "user_id", None)])
        return models.Order(**record)

    def find_order_by_id(self, order_id: int = None) -> models.Order | None:
        """Retrieve a specific order by its order_id, used for order detail viewing and processing. [crud:read_one: READ_ONE_BY_ID]"""
        found = self._store.select(self.ENTITY, [(self.PK, 'eq', order_id)])
        if not found:
            return None
        record = found[0]
        return models.Order(**record)

    def find_order_by_user_id(self, user_id: int = None) -> list[models.Order]:
        """Retrieve all orders placed by a specific user, used for user order history access. [mechanical contained-name filter]"""
        criteria = []
        if user_id is not None:
            criteria.append(('user_id', 'eq', user_id))
        found = self._store.select(self.ENTITY, criteria)
        return _model_list([models.Order(**row) for row in found], models.Order)

    def get_active_orders_count(self, order_id: int = None) -> int:
        """Count the number of orders with status 'active' or 'pending', used for real-time order monitoring. [llm-written by server — review]"""
        criteria = []
        if order_id is not None:
            criteria.append(('order_id', 'eq', order_id))
        criteria.append(('status', 'eq', 'pending'))
        criteria.append(('status', 'eq', 'active'))
        found = self._store.select(self.ENTITY, criteria)
        return len(found)

    def get_orders_by_user_id(self, user_id: int = None) -> list[models.Order]:
        """Lists the Order records belonging to one User. [mechanical contained-name filter]"""
        criteria = []
        if user_id is not None:
            criteria.append(('user_id', 'eq', user_id))
        found = self._store.select(self.ENTITY, criteria)
        return _model_list([models.Order(**row) for row in found], models.Order)

    def read_all(self, user_id: int = None, order_date: Any = None, total_amount: int = None, status: str = None) -> list[models.Order]:
        """Lists every Order; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if user_id is not None:
            criteria.append(('user_id', 'eq', user_id))
        if order_date is not None:
            criteria.append(('order_date', 'eq', order_date))
        if total_amount is not None:
            criteria.append(('total_amount', 'eq', total_amount))
        if status is not None:
            criteria.append(('status', 'eq', status))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Order(**r) for r in found]

    def read_one(self, order_id: int = None) -> models.Order:
        """Reads one Order by its key. [crud:read_one: READ_ONE_BY_ID]"""
        found = self._store.select(self.ENTITY, [(self.PK, 'eq', order_id)])
        if not found:
            return None
        record = found[0]
        return models.Order(**record)


class ProductRepository:
    ENTITY = "Product"
    PK = "product_id"

    def __init__(self, store):
        self._store = store


    def create(self, name: str = None, description: str = None, price: int = None, stock_quantity: int = None, created_at: Any = None) -> models.Product:
        """Creates a new Product. [crud:create: STANDARD_CRUD]"""
        values = {}
        if name is not None:
            values['name'] = name
        if description is not None:
            values['description'] = description
        if price is not None:
            values['price'] = price
        if stock_quantity is not None:
            values['stock_quantity'] = stock_quantity
        if created_at is not None:
            values['created_at'] = created_at
        unknown = [k for k in values if k not in ['product_id', 'name', 'description', 'price', 'stock_quantity', 'created_at']]
        if unknown:
            raise ValueError(f"cannot create Product from {unknown}")
        if values.get('created_at') is None:
            values['created_at'] = datetime.datetime.now()
        value = values.get('stock_quantity')
        if value is not None and value < 0:
            raise ValueError(f"Product.stock_quantity must be >= 0, got {value!r}")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[])
        return models.Product(**record)

    def delete(self, product_id: int = None, name: str = None, description: str = None, price: int = None, stock_quantity: int = None, created_at: Any = None) -> None:
        """Deletes an existing Product. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if product_id is not None:
            criteria.append(('product_id', 'eq', product_id))
        if name is not None:
            criteria.append(('name', 'eq', name))
        if description is not None:
            criteria.append(('description', 'eq', description))
        if price is not None:
            criteria.append(('price', 'eq', price))
        if stock_quantity is not None:
            criteria.append(('stock_quantity', 'eq', stock_quantity))
        if created_at is not None:
            criteria.append(('created_at', 'eq', created_at))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise LookupError(f"Product delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None

    def find_product_by_id(self, product_id: int = None) -> models.Product | None:
        """Retrieve a product by its product_id, used for detailed product access and management. [crud:read_one: READ_ONE_BY_ID]"""
        found = self._store.select(self.ENTITY, [(self.PK, 'eq', product_id)])
        if not found:
            return None
        record = found[0]
        return models.Product(**record)

    def find_product_by_name(self, name: str = None) -> models.Product | None:
        """Retrieve a product by its name, used for search and product lookup by users and admins. [crud:read_one: READ_ONE_BY_ID]"""
        criteria = []
        if name is not None:
            criteria.append(('name', 'eq', name))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            return None
        record = found[0]
        return models.Product(**record)

    def get_product_count(self) -> int:
        """Count the total number of products in the system, used for inventory reporting. [llm-written by server — review]"""
        found = self._store.select(self.ENTITY, [])
        return len(found)

    def get_products_by_price_range(self, min_price: float = None, max_price: float = None) -> list[models.Product]:
        """Retrieve all products within a specified price range, used for filtering and catalog display. [crud:filter: FILTER_BY_FIELD: by parameter shape]"""
        criteria = []
        if min_price is not None:
            criteria.append(('price', 'ge', min_price))
        if max_price is not None:
            criteria.append(('price', 'le', max_price))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Product(**r) for r in found]

    def read_all(self, name: str = None, description: str = None, price: int = None, stock_quantity: int = None, created_at: Any = None) -> list[models.Product]:
        """Lists every Product; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if name is not None:
            criteria.append(('name', 'eq', name))
        if description is not None:
            criteria.append(('description', 'eq', description))
        if price is not None:
            criteria.append(('price', 'eq', price))
        if stock_quantity is not None:
            criteria.append(('stock_quantity', 'eq', stock_quantity))
        if created_at is not None:
            criteria.append(('created_at', 'eq', created_at))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Product(**r) for r in found]

    def read_one(self, product_id: int = None) -> models.Product:
        """Reads one Product by its key. [crud:read_one: READ_ONE_BY_ID]"""
        found = self._store.select(self.ENTITY, [(self.PK, 'eq', product_id)])
        if not found:
            return None
        record = found[0]
        return models.Product(**record)

    def update(self, product_id: int = None, name: str = None, description: str = None, price: int = None, stock_quantity: int = None, created_at: Any = None) -> models.Product:
        """Updates an existing Product. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if product_id is not None:
            criteria.append(('product_id', 'eq', product_id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise LookupError(f"Product update matched {len(found)} records")
        patch = {}
        if product_id is not None and 'product_id' in ['product_id', 'name', 'description', 'price', 'stock_quantity', 'created_at']:
            patch['product_id'] = product_id
        if name is not None and 'name' in ['product_id', 'name', 'description', 'price', 'stock_quantity', 'created_at']:
            patch['name'] = name
        if description is not None and 'description' in ['product_id', 'name', 'description', 'price', 'stock_quantity', 'created_at']:
            patch['description'] = description
        if price is not None and 'price' in ['product_id', 'name', 'description', 'price', 'stock_quantity', 'created_at']:
            patch['price'] = price
        if stock_quantity is not None and 'stock_quantity' in ['product_id', 'name', 'description', 'price', 'stock_quantity', 'created_at']:
            patch['stock_quantity'] = stock_quantity
        if created_at is not None and 'created_at' in ['product_id', 'name', 'description', 'price', 'stock_quantity', 'created_at']:
            patch['created_at'] = created_at
        value = patch.get('stock_quantity')
        if value is not None and value < 0:
            raise ValueError(f"Product.stock_quantity must be >= 0, got {value!r}")
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=LookupError)
        return models.Product(**record)


class UserRepository:
    ENTITY = "User"
    PK = "user_id"

    def __init__(self, store):
        self._store = store


    def create(self, email: str = None, password_hash: str = None, is_admin: bool = None, created_at: Any = None) -> models.User:
        """Creates a new User. [crud:create: STANDARD_CRUD]"""
        values = {}
        if email is not None:
            values['email'] = email
        if password_hash is not None:
            values['password_hash'] = password_hash
        if is_admin is not None:
            values['is_admin'] = is_admin
        if created_at is not None:
            values['created_at'] = created_at
        unknown = [k for k in values if k not in ['user_id', 'email', 'password_hash', 'is_admin', 'created_at']]
        if unknown:
            raise ValueError(f"cannot create User from {unknown}")
        if values.get('created_at') is None:
            values['created_at'] = datetime.datetime.now()
        if values.get('is_admin') is None:
            values['is_admin'] = False
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[])
        return models.User(**record)

    def delete(self, user_id: int = None, email: str = None, password_hash: str = None, is_admin: bool = None, created_at: Any = None) -> None:
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
        if created_at is not None:
            criteria.append(('created_at', 'eq', created_at))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise LookupError(f"User delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None

    def find_user_by_email(self, email: str = None) -> models.User | None:
        """Retrieve a user by their email address, used for authentication and login. [crud:read_one: READ_ONE_BY_ID]"""
        criteria = []
        if email is not None:
            criteria.append(('email', 'eq', email))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            return None
        record = found[0]
        return models.User(**record)

    def find_user_by_id(self, user_id: int = None) -> models.User | None:
        """Retrieve a user by their unique user_id, used for detailed user access and management. [crud:read_one: READ_ONE_BY_ID]"""
        found = self._store.select(self.ENTITY, [(self.PK, 'eq', user_id)])
        if not found:
            return None
        record = found[0]
        return models.User(**record)

    def get_user_count(self) -> int:
        """Count the total number of users in the system, used for reporting and analytics. [llm-written by server — review]"""
        found = self._store.select(self.ENTITY, [])
        return len(found)

    def read_all(self, email: str = None, password_hash: str = None, is_admin: bool = None, created_at: Any = None) -> list[models.User]:
        """Lists every User; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if email is not None:
            criteria.append(('email', 'eq', email))
        if password_hash is not None:
            criteria.append(('password_hash', 'eq', password_hash))
        if is_admin is not None:
            criteria.append(('is_admin', 'eq', is_admin))
        if created_at is not None:
            criteria.append(('created_at', 'eq', created_at))
        found = self._store.select(self.ENTITY, criteria)
        return [models.User(**r) for r in found]

    def read_one(self, user_id: int = None) -> models.User:
        """Reads one User by its key. [crud:read_one: READ_ONE_BY_ID]"""
        found = self._store.select(self.ENTITY, [(self.PK, 'eq', user_id)])
        if not found:
            return None
        record = found[0]
        return models.User(**record)

    def update(self, user_id: int = None, email: str = None, password_hash: str = None, is_admin: bool = None, created_at: Any = None) -> models.User:
        """Updates an existing User. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if user_id is not None:
            criteria.append(('user_id', 'eq', user_id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise LookupError(f"User update matched {len(found)} records")
        patch = {}
        if user_id is not None and 'user_id' in ['user_id', 'email', 'password_hash', 'is_admin', 'created_at']:
            patch['user_id'] = user_id
        if email is not None and 'email' in ['user_id', 'email', 'password_hash', 'is_admin', 'created_at']:
            patch['email'] = email
        if password_hash is not None and 'password_hash' in ['user_id', 'email', 'password_hash', 'is_admin', 'created_at']:
            patch['password_hash'] = password_hash
        if is_admin is not None and 'is_admin' in ['user_id', 'email', 'password_hash', 'is_admin', 'created_at']:
            patch['is_admin'] = is_admin
        if created_at is not None and 'created_at' in ['user_id', 'email', 'password_hash', 'is_admin', 'created_at']:
            patch['created_at'] = created_at
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=LookupError)
        return models.User(**record)
