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



class CustomerRepository:
    ENTITY = "Customer"
    PK = "customer_id"

    def __init__(self, store):
        self._store = store


    def create(self, name: str = None, email: str = None) -> models.Customer:
        """Creates a new Customer. [crud:create: STANDARD_CRUD]"""
        values = {}
        if name is not None:
            values['name'] = name
        if email is not None:
            values['email'] = email
        unknown = [k for k in values if k not in ['customer_id', 'name', 'email']]
        if unknown:
            raise ValueError(f"cannot create Customer from {unknown}")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[])
        return models.Customer(**record)

    def delete(self, customer_id: int = None, name: str = None, email: str = None) -> None:
        """Deletes an existing Customer. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if customer_id is not None:
            criteria.append(('customer_id', 'eq', customer_id))
        if name is not None:
            criteria.append(('name', 'eq', name))
        if email is not None:
            criteria.append(('email', 'eq', email))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise errors.CustomerNotFoundError(f"Customer delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None

    def find_by_email(self, email: str = None) -> models.Customer | None:
        """Retrieve a customer by their email address. [crud:read_one: READ_ONE_BY_ID]"""
        criteria = []
        if email is not None:
            criteria.append(('email', 'eq', email))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise errors.CustomerNotFoundError(f"Customer lookup matched {len(found)} records")
        record = found[0]
        return models.Customer(**record)

    def find_by_name(self, name: str = None) -> models.Customer | None:
        """Retrieve a customer by their name, matching partially or fully. [crud:read_one: READ_ONE_BY_ID]"""
        criteria = []
        if name is not None:
            criteria.append(('name', 'eq', name))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise errors.CustomerNotFoundError(f"Customer lookup matched {len(found)} records")
        record = found[0]
        return models.Customer(**record)

    def read_all(self, name: str = None, email: str = None) -> list[models.Customer]:
        """Lists every Customer; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if name is not None:
            criteria.append(('name', 'eq', name))
        if email is not None:
            criteria.append(('email', 'eq', email))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Customer(**r) for r in found]

    def read_one(self, customer_id: int = None) -> models.Customer:
        """Reads one Customer by its key. [crud:read_one: READ_ONE_BY_ID]"""
        record = self._store.get(self.ENTITY, self.PK, customer_id, error=errors.CustomerNotFoundError)
        return models.Customer(**record)

    def update(self, customer_id: int = None, name: str = None, email: str = None) -> models.Customer:
        """Updates an existing Customer. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if customer_id is not None:
            criteria.append(('customer_id', 'eq', customer_id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise errors.CustomerNotFoundError(f"Customer update matched {len(found)} records")
        patch = {}
        if customer_id is not None and 'customer_id' in ['customer_id', 'name', 'email']:
            patch['customer_id'] = customer_id
        if name is not None and 'name' in ['customer_id', 'name', 'email']:
            patch['name'] = name
        if email is not None and 'email' in ['customer_id', 'name', 'email']:
            patch['email'] = email
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=errors.CustomerNotFoundError)
        return models.Customer(**record)


class OrderProductRepository:
    ENTITY = "OrderProduct"
    PK = "order_product_id"

    def __init__(self, store):
        self._store = store


    def create(self, product_id: int = None, quantity: int = None, order_id: int = None) -> models.OrderProduct:
        """Creates a new OrderProduct. [crud:create: STANDARD_CRUD]"""
        values = {}
        if product_id is not None:
            values['product_id'] = product_id
        if quantity is not None:
            values['quantity'] = quantity
        if order_id is not None:
            values['order_id'] = order_id
        unknown = [k for k in values if k not in ['order_product_id', 'order_id', 'product_id', 'quantity']]
        if unknown:
            raise ValueError(f"cannot create OrderProduct from {unknown}")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[("order_id", "Order", "order_id", errors.OrderNotFoundError), ("product_id", "Product", "product_id", errors.ProductNotFoundError)])
        return models.OrderProduct(**record)

    def get_by_order_id(self, order_id: int = None) -> list[models.OrderProduct]:
        """Retrieve all order product entries for a given order ID. [mechanical contained-name filter]"""
        criteria = []
        if order_id is not None:
            criteria.append(('order_id', 'eq', order_id))
        found = self._store.select(self.ENTITY, criteria)
        return _model_list([models.OrderProduct(**row) for row in found], models.OrderProduct)

    def get_order_products_by_order_id(self, order_id: int = None) -> list[models.OrderProduct]:
        """Lists the OrderProduct records belonging to one Order. [mechanical contained-name filter]"""
        criteria = []
        if order_id is not None:
            criteria.append(('order_id', 'eq', order_id))
        found = self._store.select(self.ENTITY, criteria)
        return _model_list([models.OrderProduct(**row) for row in found], models.OrderProduct)

    def get_order_products_by_product_id(self, product_id: int = None) -> list[models.OrderProduct]:
        """Lists the OrderProduct records belonging to one Product. [mechanical contained-name filter]"""
        criteria = []
        if product_id is not None:
            criteria.append(('product_id', 'eq', product_id))
        found = self._store.select(self.ENTITY, criteria)
        return _model_list([models.OrderProduct(**row) for row in found], models.OrderProduct)

    def read_all(self, product_id: int = None, quantity: int = None) -> list[models.OrderProduct]:
        """Lists every OrderProduct; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if product_id is not None:
            criteria.append(('product_id', 'eq', product_id))
        if quantity is not None:
            criteria.append(('quantity', 'eq', quantity))
        found = self._store.select(self.ENTITY, criteria)
        return [models.OrderProduct(**r) for r in found]

    def read_one(self, order_product_id: int = None) -> models.OrderProduct:
        """Reads one OrderProduct by its key. [crud:read_one: READ_ONE_BY_ID]"""
        found = self._store.select(self.ENTITY, [(self.PK, 'eq', order_product_id)])
        if not found:
            return None
        record = found[0]
        return models.OrderProduct(**record)


class OrderRepository:
    ENTITY = "Order"
    PK = "order_id"

    def __init__(self, store):
        self._store = store


    def cancel_order(self, order_id: int = None) -> bool:
        """Cancel an order and restore the stock quantities of all products in that order. [mechanical cancel with stock restoration]"""
        Order = self._store.get(self.ENTITY, self.PK, order_id, error=errors.OrderNotFoundError)
        if Order is None:
            raise errors.OrderNotFoundError
        self._store.update(self.ENTITY, self.PK, order_id, {'status': 'cancelled'})
        lines = self._store.select('OrderProduct', [('order_id', 'eq', order_id)])
        for line in lines:
            product_id = line.get('product_id')
            quantity = line.get('quantity')
            if product_id is None or quantity is None:
                continue
            product = self._store.get('Product', 'product_id', product_id, error=errors.ProductNotFoundError)
            if product is None:
                continue
            stock = product.get('stock_quantity', 0) + quantity
            self._store.update('Product', 'product_id', product_id, {'stock_quantity': stock})
        return True

    def create(self, customer_id: int = None, order_date: Any = None, status: str = None) -> models.Order:
        """Creates a new Order. [crud:create: STANDARD_CRUD]"""
        values = {}
        if customer_id is not None:
            values['customer_id'] = customer_id
        if order_date is not None:
            values['order_date'] = order_date
        if status is not None:
            values['status'] = status
        unknown = [k for k in values if k not in ['order_id', 'customer_id', 'order_date', 'status']]
        if unknown:
            raise ValueError(f"cannot create Order from {unknown}")
        if values.get('status') is None:
            values['status'] = 'pending'
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[("customer_id", "Customer", "customer_id", errors.CustomerNotFoundError)])
        return models.Order(**record)

    def delete(self, order_id: int = None, customer_id: int = None, order_date: Any = None, status: str = None) -> None:
        """Deletes an existing Order. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if order_id is not None:
            criteria.append(('order_id', 'eq', order_id))
        if customer_id is not None:
            criteria.append(('customer_id', 'eq', customer_id))
        if order_date is not None:
            criteria.append(('order_date', 'eq', order_date))
        if status is not None:
            criteria.append(('status', 'eq', status))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise errors.OrderNotFoundError(f"Order delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None

    def get_order_with_products(self, order_id: int = None) -> models.Order | None:
        """Retrieve an order with its associated products and quantities. [crud:read_one: READ_ONE_BY_ID]"""
        record = self._store.get(self.ENTITY, self.PK, order_id, error=errors.OrderNotFoundError)
        return models.Order(**record)

    def get_orders_by_customer_id(self, customer_id: int = None) -> list[models.Order]:
        """Lists the Order records belonging to one Customer. [mechanical contained-name filter]"""
        criteria = []
        if customer_id is not None:
            criteria.append(('customer_id', 'eq', customer_id))
        found = self._store.select(self.ENTITY, criteria)
        return _model_list([models.Order(**row) for row in found], models.Order)

    def read_all(self, customer_id: int = None, order_date: Any = None, status: str = None) -> list[models.Order]:
        """Lists every Order; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if customer_id is not None:
            criteria.append(('customer_id', 'eq', customer_id))
        if order_date is not None:
            criteria.append(('order_date', 'eq', order_date))
        if status is not None:
            criteria.append(('status', 'eq', status))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Order(**r) for r in found]

    def read_one(self, order_id: int = None) -> models.Order:
        """Reads one Order by its key. [crud:read_one: READ_ONE_BY_ID]"""
        record = self._store.get(self.ENTITY, self.PK, order_id, error=errors.OrderNotFoundError)
        return models.Order(**record)

    def update(self, order_id: int = None, customer_id: int = None, order_date: Any = None, status: str = None) -> models.Order:
        """Updates an existing Order. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if order_id is not None:
            criteria.append(('order_id', 'eq', order_id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise errors.OrderNotFoundError(f"Order update matched {len(found)} records")
        patch = {}
        if order_id is not None and 'order_id' in ['order_id', 'customer_id', 'order_date', 'status']:
            patch['order_id'] = order_id
        if customer_id is not None and 'customer_id' in ['order_id', 'customer_id', 'order_date', 'status']:
            patch['customer_id'] = customer_id
        if order_date is not None and 'order_date' in ['order_id', 'customer_id', 'order_date', 'status']:
            patch['order_date'] = order_date
        if status is not None and 'status' in ['order_id', 'customer_id', 'order_date', 'status']:
            patch['status'] = status
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=errors.OrderNotFoundError)
        return models.Order(**record)


class ProductRepository:
    ENTITY = "Product"
    PK = "product_id"

    def __init__(self, store):
        self._store = store


    def create(self, name: str = None, description: str = None, stock_quantity: int = None) -> models.Product:
        """Creates a new Product. [crud:create: STANDARD_CRUD]"""
        values = {}
        if name is not None:
            values['name'] = name
        if description is not None:
            values['description'] = description
        if stock_quantity is not None:
            values['stock_quantity'] = stock_quantity
        unknown = [k for k in values if k not in ['product_id', 'name', 'description', 'stock_quantity']]
        if unknown:
            raise ValueError(f"cannot create Product from {unknown}")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[])
        return models.Product(**record)

    def delete(self, product_id: int = None, name: str = None, description: str = None, stock_quantity: int = None) -> None:
        """Deletes an existing Product. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if product_id is not None:
            criteria.append(('product_id', 'eq', product_id))
        if name is not None:
            criteria.append(('name', 'eq', name))
        if description is not None:
            criteria.append(('description', 'eq', description))
        if stock_quantity is not None:
            criteria.append(('stock_quantity', 'eq', stock_quantity))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise errors.ProductNotFoundError(f"Product delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None

    def read_all(self, name: str = None, description: str = None, stock_quantity: int = None) -> list[models.Product]:
        """Lists every Product; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if name is not None:
            criteria.append(('name', 'eq', name))
        if description is not None:
            criteria.append(('description', 'eq', description))
        if stock_quantity is not None:
            criteria.append(('stock_quantity', 'eq', stock_quantity))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Product(**r) for r in found]

    def read_one(self, product_id: int = None) -> models.Product:
        """Reads one Product by its key. [crud:read_one: READ_ONE_BY_ID]"""
        record = self._store.get(self.ENTITY, self.PK, product_id, error=errors.ProductNotFoundError)
        return models.Product(**record)

    def search_by_name(self, name: str = None) -> list[models.Product]:
        """Search for products by name, returning all matching products. [mechanical text search]"""
        if not name:
            return []
        query = str(name).lower()
        result = []
        for row in self._store.select(self.ENTITY, []):
            values = [row.get('name'), row.get('description')]
            if any(value is not None and query in str(value).lower() for value in values):
                result.append(row)
        return _model_list([models.Product(**row) for row in result], models.Product)

    def update(self, product_id: int = None, name: str = None, description: str = None, stock_quantity: int = None) -> models.Product:
        """Updates an existing Product. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if product_id is not None:
            criteria.append(('product_id', 'eq', product_id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise errors.ProductNotFoundError(f"Product update matched {len(found)} records")
        patch = {}
        if product_id is not None and 'product_id' in ['product_id', 'name', 'description', 'stock_quantity']:
            patch['product_id'] = product_id
        if name is not None and 'name' in ['product_id', 'name', 'description', 'stock_quantity']:
            patch['name'] = name
        if description is not None and 'description' in ['product_id', 'name', 'description', 'stock_quantity']:
            patch['description'] = description
        if stock_quantity is not None and 'stock_quantity' in ['product_id', 'name', 'description', 'stock_quantity']:
            patch['stock_quantity'] = stock_quantity
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=errors.ProductNotFoundError)
        return models.Product(**record)
