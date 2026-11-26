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


    def create(self, name: str = None, price: int = None, stock_quantity: int = None) -> Any:
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

    def read_one(self, product_id: int = None) -> Any:
        """Reads one Product by its key. [crud:read_one: READ_ONE_BY_ID]"""
        found = self._store.select(self.ENTITY, [(self.PK, 'eq', product_id)])
        if not found:
            return None
        record = found[0]
        return models.Product(**record)

    def update(self, product_id: int = None, name: str = None, price: int = None, stock_quantity: int = None) -> Any:
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

    def get_product_by_name(self, name: str = None) -> Any:
        """Retrieves a product by its name, returning the product details if found. [crud:read_one: READ_ONE_BY_ID]"""
        criteria = []
        if name is not None:
            criteria.append(('name', 'eq', name))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            return None
        record = found[0]
        return models.Product(**record)


class CustomerRepository:
    ENTITY = "Customer"
    PK = "customer_id"

    def __init__(self, store):
        self._store = store


    def create(self, name: str = None, email: str = None, phone: str = None) -> Any:
        """Creates a new Customer. [crud:create: STANDARD_CRUD]"""
        values = {}
        if name is not None:
            values['name'] = name
        if email is not None:
            values['email'] = email
        if phone is not None:
            values['phone'] = phone
        unknown = [k for k in values if k not in ['customer_id', 'name', 'email', 'phone']]
        if unknown:
            raise ValueError(f"cannot create Customer from {unknown}")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[])
        return models.Customer(**record)

    def read_all(self, name: str = None, email: str = None, phone: str = None) -> list[models.Customer]:
        """Lists every Customer; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if name is not None:
            criteria.append(('name', 'eq', name))
        if email is not None:
            criteria.append(('email', 'eq', email))
        if phone is not None:
            criteria.append(('phone', 'eq', phone))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Customer(**r) for r in found]

    def read_one(self, customer_id: int = None) -> Any:
        """Reads one Customer by its key. [crud:read_one: READ_ONE_BY_ID]"""
        found = self._store.select(self.ENTITY, [(self.PK, 'eq', customer_id)])
        if not found:
            return None
        record = found[0]
        return models.Customer(**record)

    def update(self, customer_id: int = None, name: str = None, email: str = None, phone: str = None) -> Any:
        """Updates an existing Customer. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if customer_id is not None:
            criteria.append(('customer_id', 'eq', customer_id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise LookupError(f"Customer update matched {len(found)} records")
        patch = {}
        if customer_id is not None and 'customer_id' in ['customer_id', 'name', 'email', 'phone']:
            patch['customer_id'] = customer_id
        if name is not None and 'name' in ['customer_id', 'name', 'email', 'phone']:
            patch['name'] = name
        if email is not None and 'email' in ['customer_id', 'name', 'email', 'phone']:
            patch['email'] = email
        if phone is not None and 'phone' in ['customer_id', 'name', 'email', 'phone']:
            patch['phone'] = phone
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=LookupError)
        return models.Customer(**record)

    def delete(self, customer_id: int = None, name: str = None, email: str = None, phone: str = None) -> None:
        """Deletes an existing Customer. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if customer_id is not None:
            criteria.append(('customer_id', 'eq', customer_id))
        if name is not None:
            criteria.append(('name', 'eq', name))
        if email is not None:
            criteria.append(('email', 'eq', email))
        if phone is not None:
            criteria.append(('phone', 'eq', phone))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise LookupError(f"Customer delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None

    def get_customer_by_email(self, email: str = None) -> Any:
        """Retrieves a customer by their email address, returning the customer details if found. [crud:read_one: READ_ONE_BY_ID]"""
        criteria = []
        if email is not None:
            criteria.append(('email', 'eq', email))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            return None
        record = found[0]
        return models.Customer(**record)


class SaleRepository:
    ENTITY = "Sale"
    PK = "sale_id"

    def __init__(self, store):
        self._store = store


    def create(self, customer_id: int = None, product_id: int = None, quantity: int = None, sale_date: Any = None) -> Any:
        """Creates a new Sale. [crud:create: STANDARD_CRUD]"""
        values = {}
        if customer_id is not None:
            values['customer_id'] = customer_id
        if product_id is not None:
            values['product_id'] = product_id
        if quantity is not None:
            values['quantity'] = quantity
        if sale_date is not None:
            values['sale_date'] = sale_date
        unknown = [k for k in values if k not in ['sale_id', 'customer_id', 'product_id', 'quantity', 'sale_date']]
        if unknown:
            raise ValueError(f"cannot create Sale from {unknown}")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[("customer_id", "Customer", "customer_id", None), ("product_id", "Product", "product_id", None)])
        return models.Sale(**record)

    def read_all(self, customer_id: int = None, product_id: int = None, quantity: int = None, sale_date: Any = None) -> list[models.Sale]:
        """Lists every Sale; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if customer_id is not None:
            criteria.append(('customer_id', 'eq', customer_id))
        if product_id is not None:
            criteria.append(('product_id', 'eq', product_id))
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

    def get_sales_by_customer_id(self, customer_id: int = None) -> list[models.Sale]:
        """Lists the Sale records belonging to one Customer. [crud:filter: FILTER_BY_FIELD: by parameter shape]"""
        criteria = []
        if customer_id is not None:
            criteria.append(('customer_id', 'eq', customer_id))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Sale(**r) for r in found]
