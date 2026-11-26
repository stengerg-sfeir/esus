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


    def create(self, name: str = None, email: str = None) -> Any:
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

    def read_all(self, name: str = None, email: str = None) -> list[models.Customer]:
        """Lists every Customer; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if name is not None:
            criteria.append(('name', 'eq', name))
        if email is not None:
            criteria.append(('email', 'eq', email))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Customer(**r) for r in found]

    def read_one(self, customer_id: int = None) -> Any:
        """Reads one Customer by its key. [crud:read_one: READ_ONE_BY_ID]"""
        record = self._store.get(self.ENTITY, self.PK, customer_id, error=errors.CustomerNotFoundError)
        return models.Customer(**record)

    def update(self, customer_id: int = None, name: str = None, email: str = None) -> Any:
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

    def find_customer_by_email(self, email: str = None) -> models.Customer | None:
        """Retrieves a customer record by their email address. [crud:read_one: READ_ONE_BY_ID]"""
        criteria = []
        if email is not None:
            criteria.append(('email', 'eq', email))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise errors.CustomerNotFoundError(f"Customer lookup matched {len(found)} records")
        record = found[0]
        return models.Customer(**record)


class ProductRepository:
    ENTITY = "Product"
    PK = "product_id"

    def __init__(self, store):
        self._store = store


    def create(self, name: str = None, price: int = None, stock_quantity: int = None, category: str = None) -> Any:
        """Creates a new Product. [crud:create: STANDARD_CRUD]"""
        values = {}
        if name is not None:
            values['name'] = name
        if price is not None:
            values['price'] = price
        if stock_quantity is not None:
            values['stock_quantity'] = stock_quantity
        if category is not None:
            values['category'] = category
        unknown = [k for k in values if k not in ['product_id', 'name', 'price', 'stock_quantity', 'category']]
        if unknown:
            raise ValueError(f"cannot create Product from {unknown}")
        value = values.get('stock_quantity')
        if value is not None and value < 0:
            raise ValueError(f"Product.stock_quantity must be >= 0, got {value!r}")
        value = values.get('price')
        if value is not None and value < 0:
            raise ValueError(f"Product.price must be >= 0, got {value!r}")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[])
        return models.Product(**record)

    def read_all(self, name: str = None, price: int = None, stock_quantity: int = None, category: str = None) -> list[models.Product]:
        """Lists every Product; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if name is not None:
            criteria.append(('name', 'eq', name))
        if price is not None:
            criteria.append(('price', 'eq', price))
        if stock_quantity is not None:
            criteria.append(('stock_quantity', 'eq', stock_quantity))
        if category is not None:
            criteria.append(('category', 'eq', category))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Product(**r) for r in found]

    def read_one(self, product_id: int = None) -> Any:
        """Reads one Product by its key. [crud:read_one: READ_ONE_BY_ID]"""
        record = self._store.get(self.ENTITY, self.PK, product_id, error=errors.ProductNotFoundError)
        return models.Product(**record)

    def update(self, product_id: int = None, name: str = None, price: int = None, stock_quantity: int = None, category: str = None) -> Any:
        """Updates an existing Product. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if product_id is not None:
            criteria.append(('product_id', 'eq', product_id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise errors.ProductNotFoundError(f"Product update matched {len(found)} records")
        patch = {}
        if product_id is not None and 'product_id' in ['product_id', 'name', 'price', 'stock_quantity', 'category']:
            patch['product_id'] = product_id
        if name is not None and 'name' in ['product_id', 'name', 'price', 'stock_quantity', 'category']:
            patch['name'] = name
        if price is not None and 'price' in ['product_id', 'name', 'price', 'stock_quantity', 'category']:
            patch['price'] = price
        if stock_quantity is not None and 'stock_quantity' in ['product_id', 'name', 'price', 'stock_quantity', 'category']:
            patch['stock_quantity'] = stock_quantity
        if category is not None and 'category' in ['product_id', 'name', 'price', 'stock_quantity', 'category']:
            patch['category'] = category
        value = patch.get('stock_quantity')
        if value is not None and value < 0:
            raise ValueError(f"Product.stock_quantity must be >= 0, got {value!r}")
        value = patch.get('price')
        if value is not None and value < 0:
            raise ValueError(f"Product.price must be >= 0, got {value!r}")
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=errors.ProductNotFoundError)
        return models.Product(**record)

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

    def find_products_by_category(self, category: str = None) -> list[models.Product]:
        """Retrieves a list of products belonging to a specific category. [crud:filter: FILTER_BY_FIELD]"""
        criteria = []
        if category is not None:
            criteria.append(('category', 'eq', category))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Product(**r) for r in found]

    def find_products_by_price_range(self, min_price: float = None, max_price: float = None) -> list[models.Product]:
        """Retrieves a list of products within a specified price range (inclusive). [crud:filter: FILTER_BY_FIELD]"""
        criteria = []
        if min_price is not None:
            criteria.append(('price', 'ge', min_price))
        if max_price is not None:
            criteria.append(('price', 'le', max_price))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Product(**r) for r in found]


class OrderRepository:
    ENTITY = "Order"
    PK = "order_id"

    def __init__(self, store):
        self._store = store


    def create(self, customer_id: int = None, order_date: Any = None, status: str = None) -> Any:
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
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[("customer_id", "Customer", "customer_id", errors.CustomerNotFoundError)])
        return models.Order(**record)

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

    def read_one(self, order_id: int = None) -> Any:
        """Reads one Order by its key. [crud:read_one: READ_ONE_BY_ID]"""
        record = self._store.get(self.ENTITY, self.PK, order_id, error=errors.OrderNotFoundError)
        return models.Order(**record)

    def update(self, order_id: int = None, customer_id: int = None, order_date: Any = None, status: str = None) -> Any:
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

    def get_orders_by_customer_id(self, customer_id: int = None) -> list[models.Order]:
        """Lists the Order records belonging to one Customer. [crud:filter: FILTER_BY_FIELD: by parameter shape]"""
        criteria = []
        if customer_id is not None:
            criteria.append(('customer_id', 'eq', customer_id))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Order(**r) for r in found]

    def find_order_by_id(self, order_id: int = None) -> models.Order | None:
        """Retrieves an order record by its order ID. [crud:read_one: READ_ONE_BY_ID]"""
        record = self._store.get(self.ENTITY, self.PK, order_id, error=errors.OrderNotFoundError)
        return models.Order(**record)

    def find_orders_by_customer_id(self, customer_id: int = None) -> list[models.Order]:
        """Retrieves a list of orders associated with a specific customer ID. [crud:filter: FILTER_BY_FIELD]"""
        criteria = []
        if customer_id is not None:
            criteria.append(('customer_id', 'eq', customer_id))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Order(**r) for r in found]

    def find_orders_by_status(self, status: str = None) -> list[models.Order]:
        """Retrieves a list of orders with a specific status (e.g., 'pending', 'cancelled'). [crud:filter: FILTER_BY_FIELD]"""
        criteria = []
        if status is not None:
            criteria.append(('status', 'eq', status))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Order(**r) for r in found]

    def cancel_order(self, order_id: int = None) -> bool:
        """Cancels an order and restores the stock quantities of all products in that order. The operation must be atomic and update both the order status and product stock. [mechanical cancel with stock restoration]"""
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


class OrderProductRepository:
    ENTITY = "OrderProduct"
    PK = "order_id"

    def __init__(self, store):
        self._store = store


    def create(self, product_id: int = None, quantity: int = None) -> Any:
        """Creates a new OrderProduct. [crud:create: STANDARD_CRUD]"""
        values = {}
        if product_id is not None:
            values['product_id'] = product_id
        if quantity is not None:
            values['quantity'] = quantity
        unknown = [k for k in values if k not in ['order_id', 'product_id', 'quantity']]
        if unknown:
            raise ValueError(f"cannot create OrderProduct from {unknown}")
        value = values.get('quantity')
        if value is not None and value < 0:
            raise ValueError(f"OrderProduct.quantity must be >= 0, got {value!r}")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[("product_id", "Product", "product_id", errors.ProductNotFoundError)])
        return models.OrderProduct(**record)

    def read_all(self, product_id: int = None, quantity: int = None) -> list[models.OrderProduct]:
        """Lists every OrderProduct; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if product_id is not None:
            criteria.append(('product_id', 'eq', product_id))
        if quantity is not None:
            criteria.append(('quantity', 'eq', quantity))
        found = self._store.select(self.ENTITY, criteria)
        return [models.OrderProduct(**r) for r in found]

    def read_one(self, order_id: int = None) -> Any:
        """Reads one OrderProduct by its key. [crud:read_one: READ_ONE_BY_ID]"""
        found = self._store.select(self.ENTITY, [(self.PK, 'eq', order_id)])
        if not found:
            return None
        record = found[0]
        return models.OrderProduct(**record)

    def update(self, order_id: int = None, product_id: int = None, quantity: int = None) -> Any:
        """Updates an existing OrderProduct. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if order_id is not None:
            criteria.append(('order_id', 'eq', order_id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise LookupError(f"OrderProduct update matched {len(found)} records")
        patch = {}
        if order_id is not None and 'order_id' in ['order_id', 'product_id', 'quantity']:
            patch['order_id'] = order_id
        if product_id is not None and 'product_id' in ['order_id', 'product_id', 'quantity']:
            patch['product_id'] = product_id
        if quantity is not None and 'quantity' in ['order_id', 'product_id', 'quantity']:
            patch['quantity'] = quantity
        value = patch.get('quantity')
        if value is not None and value < 0:
            raise ValueError(f"OrderProduct.quantity must be >= 0, got {value!r}")
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=LookupError)
        return models.OrderProduct(**record)

    def delete(self, order_id: int = None, product_id: int = None, quantity: int = None) -> None:
        """Deletes an existing OrderProduct. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if order_id is not None:
            criteria.append(('order_id', 'eq', order_id))
        if product_id is not None:
            criteria.append(('product_id', 'eq', product_id))
        if quantity is not None:
            criteria.append(('quantity', 'eq', quantity))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise LookupError(f"OrderProduct delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None

    def get_order_products_by_product_id(self, product_id: int = None) -> list[models.OrderProduct]:
        """Lists the OrderProduct records belonging to one Product. [crud:filter: FILTER_BY_FIELD: by parameter shape]"""
        criteria = []
        if product_id is not None:
            criteria.append(('product_id', 'eq', product_id))
        found = self._store.select(self.ENTITY, criteria)
        return [models.OrderProduct(**r) for r in found]

    def get_order_product_details(self, order_id: int = None, product_id: int = None) -> int | None:
        """Retrieves the quantity of a product in a specific order, by order and product ID. [llm-written by server — review]"""
        records = self._store.select(self.ENTITY, [('order_id', 'eq', order_id), ('product_id', 'eq', product_id)])
        if not records:
            return None
        record = records[0]
        return record.get('quantity')
