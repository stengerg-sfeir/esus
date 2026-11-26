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

    def read_one(self, customer_id: int = None) -> Any:
        """Reads one Customer by its key. [crud:read_one: READ_ONE_BY_ID]"""
        record = self._store.get(self.ENTITY, self.PK, customer_id, error=errors.CustomerNotFoundError)
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


class ProductRepository:
    ENTITY = "Product"
    PK = "product_id"

    def __init__(self, store):
        self._store = store


    def create(self, name: str = None, price: int = None, stock_level: int = None) -> Any:
        """Creates a new Product. [crud:create: STANDARD_CRUD]"""
        values = {}
        if name is not None:
            values['name'] = name
        if price is not None:
            values['price'] = price
        if stock_level is not None:
            values['stock_level'] = stock_level
        unknown = [k for k in values if k not in ['product_id', 'name', 'price', 'stock_level']]
        if unknown:
            raise ValueError(f"cannot create Product from {unknown}")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[])
        return models.Product(**record)

    def read_one(self, product_id: int = None) -> Any:
        """Reads one Product by its key. [crud:read_one: READ_ONE_BY_ID]"""
        record = self._store.get(self.ENTITY, self.PK, product_id, error=errors.ProductNotFoundError)
        return models.Product(**record)

    def read_all(self, name: str = None, price: int = None, stock_level: int = None) -> list[models.Product]:
        """Lists every Product; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if name is not None:
            criteria.append(('name', 'eq', name))
        if price is not None:
            criteria.append(('price', 'eq', price))
        if stock_level is not None:
            criteria.append(('stock_level', 'eq', stock_level))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Product(**r) for r in found]

    def update(self, product_id: int = None, name: str = None, price: int = None, stock_level: int = None) -> Any:
        """Updates an existing Product. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if product_id is not None:
            criteria.append(('product_id', 'eq', product_id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise errors.ProductNotFoundError(f"Product update matched {len(found)} records")
        patch = {}
        if product_id is not None and 'product_id' in ['product_id', 'name', 'price', 'stock_level']:
            patch['product_id'] = product_id
        if name is not None and 'name' in ['product_id', 'name', 'price', 'stock_level']:
            patch['name'] = name
        if price is not None and 'price' in ['product_id', 'name', 'price', 'stock_level']:
            patch['price'] = price
        if stock_level is not None and 'stock_level' in ['product_id', 'name', 'price', 'stock_level']:
            patch['stock_level'] = stock_level
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=errors.ProductNotFoundError)
        return models.Product(**record)

    def delete(self, product_id: int = None, name: str = None, price: int = None, stock_level: int = None) -> None:
        """Deletes an existing Product. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if product_id is not None:
            criteria.append(('product_id', 'eq', product_id))
        if name is not None:
            criteria.append(('name', 'eq', name))
        if price is not None:
            criteria.append(('price', 'eq', price))
        if stock_level is not None:
            criteria.append(('stock_level', 'eq', stock_level))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise errors.ProductNotFoundError(f"Product delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None


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

    def read_one(self, order_id: int = None) -> Any:
        """Reads one Order by its key. [crud:read_one: READ_ONE_BY_ID]"""
        record = self._store.get(self.ENTITY, self.PK, order_id, error=errors.OrderNotFoundError)
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

    def cancel_order(self, order_id: int = None) -> bool:
        """Marks an order as canceled and updates its status. Triggers stock restoration for all products in the order lines. [mechanical cancel with stock restoration]"""
        Order = self._store.get(self.ENTITY, self.PK, order_id, error=errors.OrderNotFoundError)
        if Order is None:
            raise errors.OrderNotFoundError
        self._store.update(self.ENTITY, self.PK, order_id, {'status': 'cancelled'})
        lines = self._store.select('OrderLine', [('order_id', 'eq', order_id)])
        for line in lines:
            product_id = line.get('product_id')
            quantity = line.get('quantity')
            if product_id is None or quantity is None:
                continue
            product = self._store.get('Product', 'product_id', product_id, error=errors.ProductNotFoundError)
            if product is None:
                continue
            stock = product.get('stock_level', 0) + quantity
            self._store.update('Product', 'product_id', product_id, {'stock_level': stock})
        return True

    def restore_stock_after_cancellation(self, order_id: int = None) -> bool:
        """Restores the stock level for all products in the order lines of a canceled order, based on the original quantities. [mechanical cancel with stock restoration]"""
        Order = self._store.get(self.ENTITY, self.PK, order_id, error=errors.OrderNotFoundError)
        if Order is None:
            raise errors.OrderNotFoundError
        self._store.update(self.ENTITY, self.PK, order_id, {'status': 'cancelled'})
        lines = self._store.select('OrderLine', [('order_id', 'eq', order_id)])
        for line in lines:
            product_id = line.get('product_id')
            quantity = line.get('quantity')
            if product_id is None or quantity is None:
                continue
            product = self._store.get('Product', 'product_id', product_id, error=errors.ProductNotFoundError)
            if product is None:
                continue
            stock = product.get('stock_level', 0) + quantity
            self._store.update('Product', 'product_id', product_id, {'stock_level': stock})
        return True


class OrderLineRepository:
    ENTITY = "OrderLine"
    PK = "order_line_id"

    def __init__(self, store):
        self._store = store


    def create(self, order_id: int = None, product_id: int = None, quantity: int = None, unit_price: int = None) -> Any:
        """Creates a new OrderLine. [crud:create: STANDARD_CRUD]"""
        values = {}
        if order_id is not None:
            values['order_id'] = order_id
        if product_id is not None:
            values['product_id'] = product_id
        if quantity is not None:
            values['quantity'] = quantity
        if unit_price is not None:
            values['unit_price'] = unit_price
        unknown = [k for k in values if k not in ['order_line_id', 'order_id', 'product_id', 'quantity', 'unit_price']]
        if unknown:
            raise ValueError(f"cannot create OrderLine from {unknown}")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[("order_id", "Order", "order_id", errors.OrderNotFoundError), ("product_id", "Product", "product_id", errors.ProductNotFoundError)])
        return models.OrderLine(**record)

    def read_one(self, order_line_id: int = None) -> Any:
        """Reads one OrderLine by its key. [crud:read_one: READ_ONE_BY_ID]"""
        record = self._store.get(self.ENTITY, self.PK, order_line_id, error=errors.OrderLineNotFoundError)
        return models.OrderLine(**record)

    def read_all(self, order_id: int = None, product_id: int = None, quantity: int = None, unit_price: int = None) -> list[models.OrderLine]:
        """Lists every OrderLine; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
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
        return [models.OrderLine(**r) for r in found]

    def update(self, order_line_id: int = None, order_id: int = None, product_id: int = None, quantity: int = None, unit_price: int = None) -> Any:
        """Updates an existing OrderLine. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if order_line_id is not None:
            criteria.append(('order_line_id', 'eq', order_line_id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise errors.OrderLineNotFoundError(f"OrderLine update matched {len(found)} records")
        patch = {}
        if order_line_id is not None and 'order_line_id' in ['order_line_id', 'order_id', 'product_id', 'quantity', 'unit_price']:
            patch['order_line_id'] = order_line_id
        if order_id is not None and 'order_id' in ['order_line_id', 'order_id', 'product_id', 'quantity', 'unit_price']:
            patch['order_id'] = order_id
        if product_id is not None and 'product_id' in ['order_line_id', 'order_id', 'product_id', 'quantity', 'unit_price']:
            patch['product_id'] = product_id
        if quantity is not None and 'quantity' in ['order_line_id', 'order_id', 'product_id', 'quantity', 'unit_price']:
            patch['quantity'] = quantity
        if unit_price is not None and 'unit_price' in ['order_line_id', 'order_id', 'product_id', 'quantity', 'unit_price']:
            patch['unit_price'] = unit_price
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=errors.OrderLineNotFoundError)
        return models.OrderLine(**record)

    def delete(self, order_line_id: int = None, order_id: int = None, product_id: int = None, quantity: int = None, unit_price: int = None) -> None:
        """Deletes an existing OrderLine. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if order_line_id is not None:
            criteria.append(('order_line_id', 'eq', order_line_id))
        if order_id is not None:
            criteria.append(('order_id', 'eq', order_id))
        if product_id is not None:
            criteria.append(('product_id', 'eq', product_id))
        if quantity is not None:
            criteria.append(('quantity', 'eq', quantity))
        if unit_price is not None:
            criteria.append(('unit_price', 'eq', unit_price))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise errors.OrderLineNotFoundError(f"OrderLine delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None

    def get_order_lines_by_order_id(self, order_id: int = None) -> list[models.OrderLine]:
        """Lists the OrderLine records belonging to one Order. [crud:filter: FILTER_BY_FIELD: by parameter shape]"""
        criteria = []
        if order_id is not None:
            criteria.append(('order_id', 'eq', order_id))
        found = self._store.select(self.ENTITY, criteria)
        return [models.OrderLine(**r) for r in found]


class DiscountRepository:
    ENTITY = "Discount"
    PK = "discount_id"

    def __init__(self, store):
        self._store = store


    def create(self, name: str = None, value: int = None, type: str = None) -> Any:
        """Creates a new Discount. [crud:create: STANDARD_CRUD]"""
        values = {}
        if name is not None:
            values['name'] = name
        if value is not None:
            values['value'] = value
        if type is not None:
            values['type'] = type
        unknown = [k for k in values if k not in ['discount_id', 'name', 'value', 'type']]
        if unknown:
            raise ValueError(f"cannot create Discount from {unknown}")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[])
        return models.Discount(**record)

    def read_one(self, discount_id: int = None) -> Any:
        """Reads one Discount by its key. [crud:read_one: READ_ONE_BY_ID]"""
        record = self._store.get(self.ENTITY, self.PK, discount_id, error=errors.DiscountNotFoundError)
        return models.Discount(**record)

    def read_all(self, name: str = None, value: int = None, type: str = None) -> list[models.Discount]:
        """Lists every Discount; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if name is not None:
            criteria.append(('name', 'eq', name))
        if value is not None:
            criteria.append(('value', 'eq', value))
        if type is not None:
            criteria.append(('type', 'eq', type))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Discount(**r) for r in found]

    def update(self, discount_id: int = None, name: str = None, value: int = None, type: str = None) -> Any:
        """Updates an existing Discount. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if discount_id is not None:
            criteria.append(('discount_id', 'eq', discount_id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise errors.DiscountNotFoundError(f"Discount update matched {len(found)} records")
        patch = {}
        if discount_id is not None and 'discount_id' in ['discount_id', 'name', 'value', 'type']:
            patch['discount_id'] = discount_id
        if name is not None and 'name' in ['discount_id', 'name', 'value', 'type']:
            patch['name'] = name
        if value is not None and 'value' in ['discount_id', 'name', 'value', 'type']:
            patch['value'] = value
        if type is not None and 'type' in ['discount_id', 'name', 'value', 'type']:
            patch['type'] = type
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=errors.DiscountNotFoundError)
        return models.Discount(**record)

    def delete(self, discount_id: int = None, name: str = None, value: int = None, type: str = None) -> None:
        """Deletes an existing Discount. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if discount_id is not None:
            criteria.append(('discount_id', 'eq', discount_id))
        if name is not None:
            criteria.append(('name', 'eq', name))
        if value is not None:
            criteria.append(('value', 'eq', value))
        if type is not None:
            criteria.append(('type', 'eq', type))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise errors.DiscountNotFoundError(f"Discount delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None


class TaxRepository:
    ENTITY = "Tax"
    PK = "tax_id"

    def __init__(self, store):
        self._store = store


    def create(self, name: str = None, rate: int = None) -> Any:
        """Creates a new Tax. [crud:create: STANDARD_CRUD]"""
        values = {}
        if name is not None:
            values['name'] = name
        if rate is not None:
            values['rate'] = rate
        unknown = [k for k in values if k not in ['tax_id', 'name', 'rate']]
        if unknown:
            raise ValueError(f"cannot create Tax from {unknown}")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[])
        return models.Tax(**record)

    def read_one(self, tax_id: int = None) -> Any:
        """Reads one Tax by its key. [crud:read_one: READ_ONE_BY_ID]"""
        record = self._store.get(self.ENTITY, self.PK, tax_id, error=errors.TaxNotFoundError)
        return models.Tax(**record)

    def read_all(self, name: str = None, rate: int = None) -> list[models.Tax]:
        """Lists every Tax; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if name is not None:
            criteria.append(('name', 'eq', name))
        if rate is not None:
            criteria.append(('rate', 'eq', rate))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Tax(**r) for r in found]

    def update(self, tax_id: int = None, name: str = None, rate: int = None) -> Any:
        """Updates an existing Tax. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if tax_id is not None:
            criteria.append(('tax_id', 'eq', tax_id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise errors.TaxNotFoundError(f"Tax update matched {len(found)} records")
        patch = {}
        if tax_id is not None and 'tax_id' in ['tax_id', 'name', 'rate']:
            patch['tax_id'] = tax_id
        if name is not None and 'name' in ['tax_id', 'name', 'rate']:
            patch['name'] = name
        if rate is not None and 'rate' in ['tax_id', 'name', 'rate']:
            patch['rate'] = rate
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=errors.TaxNotFoundError)
        return models.Tax(**record)

    def delete(self, tax_id: int = None, name: str = None, rate: int = None) -> None:
        """Deletes an existing Tax. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if tax_id is not None:
            criteria.append(('tax_id', 'eq', tax_id))
        if name is not None:
            criteria.append(('name', 'eq', name))
        if rate is not None:
            criteria.append(('rate', 'eq', rate))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise errors.TaxNotFoundError(f"Tax delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None
