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
            raise LookupError(f"Customer delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None

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
        found = self._store.select(self.ENTITY, [(self.PK, 'eq', customer_id)])
        if not found:
            return None
        record = found[0]
        return models.Customer(**record)

    def update(self, customer_id: int = None, name: str = None, email: str = None) -> models.Customer:
        """Updates an existing Customer. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if customer_id is not None:
            criteria.append(('customer_id', 'eq', customer_id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise LookupError(f"Customer update matched {len(found)} records")
        patch = {}
        if customer_id is not None and 'customer_id' in ['customer_id', 'name', 'email']:
            patch['customer_id'] = customer_id
        if name is not None and 'name' in ['customer_id', 'name', 'email']:
            patch['name'] = name
        if email is not None and 'email' in ['customer_id', 'name', 'email']:
            patch['email'] = email
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=LookupError)
        return models.Customer(**record)


class DiscountRepository:
    ENTITY = "Discount"
    PK = "discount_id"

    def __init__(self, store):
        self._store = store


    def create(self, name: str = None, value: int = None, applies_to: str = None) -> models.Discount:
        """Creates a new Discount. [crud:create: STANDARD_CRUD]"""
        values = {}
        if name is not None:
            values['name'] = name
        if value is not None:
            values['value'] = value
        if applies_to is not None:
            values['applies_to'] = applies_to
        unknown = [k for k in values if k not in ['discount_id', 'name', 'value', 'applies_to']]
        if unknown:
            raise ValueError(f"cannot create Discount from {unknown}")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[])
        return models.Discount(**record)

    def delete(self, discount_id: int = None, name: str = None, value: int = None, applies_to: str = None) -> None:
        """Deletes an existing Discount. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if discount_id is not None:
            criteria.append(('discount_id', 'eq', discount_id))
        if name is not None:
            criteria.append(('name', 'eq', name))
        if value is not None:
            criteria.append(('value', 'eq', value))
        if applies_to is not None:
            criteria.append(('applies_to', 'eq', applies_to))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise LookupError(f"Discount delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None

    def read_all(self, name: str = None, value: int = None, applies_to: str = None) -> list[models.Discount]:
        """Lists every Discount; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if name is not None:
            criteria.append(('name', 'eq', name))
        if value is not None:
            criteria.append(('value', 'eq', value))
        if applies_to is not None:
            criteria.append(('applies_to', 'eq', applies_to))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Discount(**r) for r in found]

    def read_one(self, discount_id: int = None) -> models.Discount:
        """Reads one Discount by its key. [crud:read_one: READ_ONE_BY_ID]"""
        found = self._store.select(self.ENTITY, [(self.PK, 'eq', discount_id)])
        if not found:
            return None
        record = found[0]
        return models.Discount(**record)

    def update(self, discount_id: int = None, name: str = None, value: int = None, applies_to: str = None) -> models.Discount:
        """Updates an existing Discount. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if discount_id is not None:
            criteria.append(('discount_id', 'eq', discount_id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise LookupError(f"Discount update matched {len(found)} records")
        patch = {}
        if discount_id is not None and 'discount_id' in ['discount_id', 'name', 'value', 'applies_to']:
            patch['discount_id'] = discount_id
        if name is not None and 'name' in ['discount_id', 'name', 'value', 'applies_to']:
            patch['name'] = name
        if value is not None and 'value' in ['discount_id', 'name', 'value', 'applies_to']:
            patch['value'] = value
        if applies_to is not None and 'applies_to' in ['discount_id', 'name', 'value', 'applies_to']:
            patch['applies_to'] = applies_to
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=LookupError)
        return models.Discount(**record)


class OrderLineRepository:
    ENTITY = "OrderLine"
    PK = "order_line_id"

    def __init__(self, store):
        self._store = store


    def create(self, order_id: int = None, product_id: int = None, quantity: int = None, unit_price: int = None) -> models.OrderLine:
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
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[("order_id", "Order", "order_id", None), ("product_id", "Product", "product_id", None)])
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
            raise LookupError(f"OrderLine delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None

    def get_order_lines_by_order_id(self, order_id: int = None) -> list[models.OrderLine]:
        """Lists the OrderLine records belonging to one Order. [mechanical contained-name filter]"""
        criteria = []
        if order_id is not None:
            criteria.append(('order_id', 'eq', order_id))
        found = self._store.select(self.ENTITY, criteria)
        return _model_list([models.OrderLine(**row) for row in found], models.OrderLine)

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

    def read_one(self, order_line_id: int = None) -> models.OrderLine:
        """Reads one OrderLine by its key. [crud:read_one: READ_ONE_BY_ID]"""
        found = self._store.select(self.ENTITY, [(self.PK, 'eq', order_line_id)])
        if not found:
            return None
        record = found[0]
        return models.OrderLine(**record)

    def update(self, order_line_id: int = None, order_id: int = None, product_id: int = None, quantity: int = None, unit_price: int = None) -> models.OrderLine:
        """Updates an existing OrderLine. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if order_line_id is not None:
            criteria.append(('order_line_id', 'eq', order_line_id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise LookupError(f"OrderLine update matched {len(found)} records")
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
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=LookupError)
        return models.OrderLine(**record)


class OrderRepository:
    ENTITY = "Order"
    PK = "order_id"

    def __init__(self, store):
        self._store = store


    def cancel_order(self, order_id: int = None) -> bool:
        """Marks an order as canceled and updates its status. Triggers stock restoration for all products in the order. [mechanical named state update]"""
        record = self._store.get('Order', 'order_id', order_id)
        if record is None:
            return True
        self._store.update('Order', 'order_id', record.get('order_id'), {'status': 'cancelled'})
        return True

    def create(self, customer_id: int = None, order_date: Any = None, status: str = None, total_amount: int = None) -> models.Order:
        """Creates a new Order. [crud:create: STANDARD_CRUD]"""
        values = {}
        if customer_id is not None:
            values['customer_id'] = customer_id
        if order_date is not None:
            values['order_date'] = order_date
        if status is not None:
            values['status'] = status
        if total_amount is not None:
            values['total_amount'] = total_amount
        unknown = [k for k in values if k not in ['order_id', 'customer_id', 'order_date', 'status', 'total_amount']]
        if unknown:
            raise ValueError(f"cannot create Order from {unknown}")
        if values.get('status') is None:
            values['status'] = 'pending'
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[("customer_id", "Customer", "customer_id", None)])
        return models.Order(**record)

    def delete(self, order_id: int = None, customer_id: int = None, order_date: Any = None, status: str = None, total_amount: int = None) -> None:
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
        if total_amount is not None:
            criteria.append(('total_amount', 'eq', total_amount))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise LookupError(f"Order delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None

    def get_order_with_lines_and_customer(self, order_id: int = None) -> Dict[str, Any]:
        """Retrieves an order with its associated customer and order lines, including product details and quantities. [llm-written by server — review]"""
        record = self._store.get('Order', 'order_id', order_id)
        if not record:
            return {}
        order = models.Order(**record)
        order_lines = self._store.select('OrderLine', [('order_id', 'eq', record['order_id'])])
        product_details = {}
        for line in order_lines:
            product_id = line.get('product_id')
            if product_id is not None:
                product_record = self._store.get('Product', 'product_id', product_id)
                if product_record:
                    product_details[product_id] = models.Product(**product_record)
        customer_id = record.get('customer_id')
        customer = {}
        if customer_id is not None:
            customer_record = self._store.get('Customer', 'customer_id', customer_id)
            if customer_record:
                customer = models.Customer(**customer_record)
        return {
            'order': order,
            'order_lines': [models.OrderLine(**line) for line in order_lines],
            'customer': customer,
            'product_details': product_details
        }

    def get_orders_by_customer_id(self, customer_id: int = None) -> list[models.Order]:
        """Lists the Order records belonging to one Customer. [mechanical contained-name filter]"""
        criteria = []
        if customer_id is not None:
            criteria.append(('customer_id', 'eq', customer_id))
        found = self._store.select(self.ENTITY, criteria)
        return _model_list([models.Order(**row) for row in found], models.Order)

    def read_all(self, customer_id: int = None, order_date: Any = None, status: str = None, total_amount: int = None) -> list[models.Order]:
        """Lists every Order; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if customer_id is not None:
            criteria.append(('customer_id', 'eq', customer_id))
        if order_date is not None:
            criteria.append(('order_date', 'eq', order_date))
        if status is not None:
            criteria.append(('status', 'eq', status))
        if total_amount is not None:
            criteria.append(('total_amount', 'eq', total_amount))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Order(**r) for r in found]

    def read_one(self, order_id: int = None) -> models.Order:
        """Reads one Order by its key. [crud:read_one: READ_ONE_BY_ID]"""
        found = self._store.select(self.ENTITY, [(self.PK, 'eq', order_id)])
        if not found:
            return None
        record = found[0]
        return models.Order(**record)

    def update(self, order_id: int = None, customer_id: int = None, order_date: Any = None, status: str = None, total_amount: int = None) -> models.Order:
        """Updates an existing Order. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if order_id is not None:
            criteria.append(('order_id', 'eq', order_id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise LookupError(f"Order update matched {len(found)} records")
        patch = {}
        if order_id is not None and 'order_id' in ['order_id', 'customer_id', 'order_date', 'status', 'total_amount']:
            patch['order_id'] = order_id
        if customer_id is not None and 'customer_id' in ['order_id', 'customer_id', 'order_date', 'status', 'total_amount']:
            patch['customer_id'] = customer_id
        if order_date is not None and 'order_date' in ['order_id', 'customer_id', 'order_date', 'status', 'total_amount']:
            patch['order_date'] = order_date
        if status is not None and 'status' in ['order_id', 'customer_id', 'order_date', 'status', 'total_amount']:
            patch['status'] = status
        if total_amount is not None and 'total_amount' in ['order_id', 'customer_id', 'order_date', 'status', 'total_amount']:
            patch['total_amount'] = total_amount
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=LookupError)
        return models.Order(**record)


class ProductRepository:
    ENTITY = "Product"
    PK = "product_id"

    def __init__(self, store):
        self._store = store


    def create(self, name: str = None, price: int = None, stock_quantity: int = None) -> models.Product:
        """Creates a new Product. [crud:create: STANDARD_CRUD]"""
        values = {}
        if name is not None:
            values['name'] = name
        if price is not None:
            values['price'] = price
        if stock_quantity is not None:
            values['stock_quantity'] = stock_quantity
        unknown = [k for k in values if k not in ['product_id', 'name', 'price', 'stock_quantity']]
        if unknown:
            raise ValueError(f"cannot create Product from {unknown}")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[])
        return models.Product(**record)

    def delete(self, product_id: int = None, name: str = None, price: int = None, stock_quantity: int = None) -> None:
        """Deletes an existing Product. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if product_id is not None:
            criteria.append(('product_id', 'eq', product_id))
        if name is not None:
            criteria.append(('name', 'eq', name))
        if price is not None:
            criteria.append(('price', 'eq', price))
        if stock_quantity is not None:
            criteria.append(('stock_quantity', 'eq', stock_quantity))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise LookupError(f"Product delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None

    def read_all(self, name: str = None, price: int = None, stock_quantity: int = None) -> list[models.Product]:
        """Lists every Product; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if name is not None:
            criteria.append(('name', 'eq', name))
        if price is not None:
            criteria.append(('price', 'eq', price))
        if stock_quantity is not None:
            criteria.append(('stock_quantity', 'eq', stock_quantity))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Product(**r) for r in found]

    def read_one(self, product_id: int = None) -> models.Product:
        """Reads one Product by its key. [crud:read_one: READ_ONE_BY_ID]"""
        found = self._store.select(self.ENTITY, [(self.PK, 'eq', product_id)])
        if not found:
            return None
        record = found[0]
        return models.Product(**record)

    def update(self, product_id: int = None, name: str = None, price: int = None, stock_quantity: int = None) -> models.Product:
        """Updates an existing Product. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if product_id is not None:
            criteria.append(('product_id', 'eq', product_id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise LookupError(f"Product update matched {len(found)} records")
        patch = {}
        if product_id is not None and 'product_id' in ['product_id', 'name', 'price', 'stock_quantity']:
            patch['product_id'] = product_id
        if name is not None and 'name' in ['product_id', 'name', 'price', 'stock_quantity']:
            patch['name'] = name
        if price is not None and 'price' in ['product_id', 'name', 'price', 'stock_quantity']:
            patch['price'] = price
        if stock_quantity is not None and 'stock_quantity' in ['product_id', 'name', 'price', 'stock_quantity']:
            patch['stock_quantity'] = stock_quantity
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=LookupError)
        return models.Product(**record)


class TaxRepository:
    ENTITY = "Tax"
    PK = "tax_id"

    def __init__(self, store):
        self._store = store


    def create(self, name: str = None, rate: int = None) -> models.Tax:
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
            raise LookupError(f"Tax delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None

    def read_all(self, name: str = None, rate: int = None) -> list[models.Tax]:
        """Lists every Tax; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if name is not None:
            criteria.append(('name', 'eq', name))
        if rate is not None:
            criteria.append(('rate', 'eq', rate))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Tax(**r) for r in found]

    def read_one(self, tax_id: int = None) -> models.Tax:
        """Reads one Tax by its key. [crud:read_one: READ_ONE_BY_ID]"""
        found = self._store.select(self.ENTITY, [(self.PK, 'eq', tax_id)])
        if not found:
            return None
        record = found[0]
        return models.Tax(**record)

    def update(self, tax_id: int = None, name: str = None, rate: int = None) -> models.Tax:
        """Updates an existing Tax. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if tax_id is not None:
            criteria.append(('tax_id', 'eq', tax_id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise LookupError(f"Tax update matched {len(found)} records")
        patch = {}
        if tax_id is not None and 'tax_id' in ['tax_id', 'name', 'rate']:
            patch['tax_id'] = tax_id
        if name is not None and 'name' in ['tax_id', 'name', 'rate']:
            patch['name'] = name
        if rate is not None and 'rate' in ['tax_id', 'name', 'rate']:
            patch['rate'] = rate
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=LookupError)
        return models.Tax(**record)
