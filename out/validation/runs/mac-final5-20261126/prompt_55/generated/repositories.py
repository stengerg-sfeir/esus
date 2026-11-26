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
    PK = "id"

    def __init__(self, store):
        self._store = store


    def create(self, name: str = None, stock_quantity: int = None) -> Any:
        """Creates a new Product. [crud:create: STANDARD_CRUD]"""
        values = {}
        if name is not None:
            values['name'] = name
        if stock_quantity is not None:
            values['stock_quantity'] = stock_quantity
        unknown = [k for k in values if k not in ['id', 'name', 'stock_quantity']]
        if unknown:
            raise ValueError(f"cannot create Product from {unknown}")
        value = values.get('stock_quantity')
        if value is not None and value < 0:
            raise ValueError(f"Product.stock_quantity must be >= 0, got {value!r}")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[])
        return models.Product(**record)

    def read_one(self, id: int = None) -> Any:
        """Reads one Product by its key. [crud:read_one: READ_ONE_BY_ID]"""
        record = self._store.get(self.ENTITY, self.PK, id, error=errors.ProductNotFoundError)
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

    def update(self, id: int = None, name: str = None, stock_quantity: int = None) -> Any:
        """Updates an existing Product. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if id is not None:
            criteria.append(('id', 'eq', id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise errors.ProductNotFoundError(f"Product update matched {len(found)} records")
        patch = {}
        if id is not None and 'id' in ['id', 'name', 'stock_quantity']:
            patch['id'] = id
        if name is not None and 'name' in ['id', 'name', 'stock_quantity']:
            patch['name'] = name
        if stock_quantity is not None and 'stock_quantity' in ['id', 'name', 'stock_quantity']:
            patch['stock_quantity'] = stock_quantity
        value = patch.get('stock_quantity')
        if value is not None and value < 0:
            raise ValueError(f"Product.stock_quantity must be >= 0, got {value!r}")
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=errors.ProductNotFoundError)
        return models.Product(**record)

    def delete(self, id: int = None, name: str = None, stock_quantity: int = None) -> None:
        """Deletes an existing Product. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if id is not None:
            criteria.append(('id', 'eq', id))
        if name is not None:
            criteria.append(('name', 'eq', name))
        if stock_quantity is not None:
            criteria.append(('stock_quantity', 'eq', stock_quantity))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise errors.ProductNotFoundError(f"Product delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None

    def get_product_by_name(self, name: str = None) -> Any:
        """Retrieves a product by its name, ensuring the product exists in the inventory. [crud:read_one: READ_ONE_BY_ID]"""
        criteria = []
        if name is not None:
            criteria.append(('name', 'eq', name))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise errors.ProductNotFoundError(f"Product lookup matched {len(found)} records")
        record = found[0]
        return models.Product(**record)

    def get_product_by_id(self, id: int = None) -> Any:
        """Retrieves a product by its unique identifier, ensuring the product exists in the inventory. [crud:read_one: READ_ONE_BY_ID]"""
        record = self._store.get(self.ENTITY, self.PK, id, error=errors.ProductNotFoundError)
        return models.Product(**record)

    def get_all_products_with_stock(self) -> list[models.Product]:
        """Retrieves all products with their current stock quantities, used for inventory audits and reporting. [crud:read_all: READ_ALL]"""
        criteria = []
        found = self._store.select(self.ENTITY, criteria)
        return [models.Product(**r) for r in found]

    def update_product_stock(self, id: int = None, new_stock_quantity: int = None) -> bool:
        """Updates the stock quantity of a product, ensuring that stock never goes below zero and maintaining inventory integrity. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if id is not None:
            criteria.append(('id', 'eq', id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise errors.ProductNotFoundError(f"Product update matched {len(found)} records")
        patch = {}
        if id is not None and 'id' in ['id', 'name', 'stock_quantity']:
            patch['id'] = id
        if new_stock_quantity is not None and 'new_stock_quantity' in ['id', 'name', 'stock_quantity']:
            patch['new_stock_quantity'] = new_stock_quantity
        value = patch.get('stock_quantity')
        if value is not None and value < 0:
            raise ValueError(f"Product.stock_quantity must be >= 0, got {value!r}")
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=errors.ProductNotFoundError)
        return models.Product(**record)


class SaleRepository:
    ENTITY = "Sale"
    PK = "id"

    def __init__(self, store):
        self._store = store


    def create(self, product_id: int = None, quantity: int = None, sale_timestamp: Any = None) -> Any:
        """Creates a new Sale. [crud:create: STANDARD_CRUD]"""
        values = {}
        if product_id is not None:
            values['product_id'] = product_id
        if quantity is not None:
            values['quantity'] = quantity
        if sale_timestamp is not None:
            values['sale_timestamp'] = sale_timestamp
        unknown = [k for k in values if k not in ['id', 'product_id', 'quantity', 'sale_timestamp']]
        if unknown:
            raise ValueError(f"cannot create Sale from {unknown}")
        value = values.get('quantity')
        if value is not None and value < 0:
            raise ValueError(f"Sale.quantity must be >= 0, got {value!r}")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[("product_id", "Product", "id", errors.ProductNotFoundError)])
        return models.Sale(**record)

    def read_all(self, product_id: int = None, quantity: int = None, sale_timestamp: Any = None) -> list[models.Sale]:
        """Lists every Sale; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if product_id is not None:
            criteria.append(('product_id', 'eq', product_id))
        if quantity is not None:
            criteria.append(('quantity', 'eq', quantity))
        if sale_timestamp is not None:
            criteria.append(('sale_timestamp', 'eq', sale_timestamp))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Sale(**r) for r in found]

    def read_one(self, id: int = None) -> Any:
        """Reads one Sale by its key. [crud:read_one: READ_ONE_BY_ID]"""
        record = self._store.get(self.ENTITY, self.PK, id, error=errors.SaleProductNotFoundError)
        return models.Sale(**record)

    def create_sale(self, product_id: int = None, quantity: int = None, sale_timestamp: datetime.datetime = None) -> Any:
        """Creates a new sale record, deducts the sold quantity from the product's stock, and ensures inventory remains accurate after the transaction. [crud:create: STANDARD_CRUD]"""
        values = {}
        if product_id is not None:
            values['product_id'] = product_id
        if quantity is not None:
            values['quantity'] = quantity
        if sale_timestamp is not None:
            values['sale_timestamp'] = sale_timestamp
        unknown = [k for k in values if k not in ['id', 'product_id', 'quantity', 'sale_timestamp']]
        if unknown:
            raise ValueError(f"cannot create Sale from {unknown}")
        value = values.get('quantity')
        if value is not None and value < 0:
            raise ValueError(f"Sale.quantity must be >= 0, got {value!r}")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[("product_id", "Product", "id", errors.ProductNotFoundError)])
        if product_id is not None and quantity is not None:
            _target = self._store.get('Product', 'id', product_id)
            if _target is not None:
                self._store.update('Product', 'id', product_id, {'stock_quantity': _target.get('stock_quantity', 0) - quantity})
        return models.Sale(**record)

    def get_sale_by_product_and_timestamp(self, product_id: int = None, sale_timestamp: datetime.datetime = None) -> Any:
        """Retrieves a sale record by product ID and sale timestamp, used for transaction verification and audit trails. [crud:read_one: READ_ONE_BY_ID]"""
        criteria = []
        if product_id is not None:
            criteria.append(('product_id', 'eq', product_id))
        if sale_timestamp is not None:
            criteria.append(('sale_timestamp', 'eq', sale_timestamp))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise errors.SaleProductNotFoundError(f"Sale lookup matched {len(found)} records")
        record = found[0]
        return models.Sale(**record)

    def get_all_sales_for_product(self, product_id: int = None) -> list[models.Sale]:
        """Retrieves all sale records for a specific product, used for sales history and inventory tracking. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if product_id is not None:
            criteria.append(('product_id', 'eq', product_id))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Sale(**r) for r in found]
