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


    def create(self, name: str = None, price: int = None) -> Any:
        """Creates a new Product. [crud:create: STANDARD_CRUD]"""
        values = {}
        if name is not None:
            values['name'] = name
        if price is not None:
            values['price'] = price
        unknown = [k for k in values if k not in ['product_id', 'name', 'price']]
        if unknown:
            raise ValueError(f"cannot create Product from {unknown}")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[])
        return models.Product(**record)

    def read_one(self, product_id: int = None) -> Any:
        """Reads one Product by its key. [crud:read_one: READ_ONE_BY_ID]"""
        found = self._store.select(self.ENTITY, [(self.PK, 'eq', product_id)])
        if not found:
            return None
        record = found[0]
        return models.Product(**record)

    def read_all(self, name: str = None, price: int = None) -> list[models.Product]:
        """Lists every Product; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if name is not None:
            criteria.append(('name', 'eq', name))
        if price is not None:
            criteria.append(('price', 'eq', price))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Product(**r) for r in found]

    def update(self, product_id: int = None, name: str = None, price: int = None) -> Any:
        """Updates an existing Product. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if product_id is not None:
            criteria.append(('product_id', 'eq', product_id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise LookupError(f"Product update matched {len(found)} records")
        patch = {}
        if product_id is not None and 'product_id' in ['product_id', 'name', 'price']:
            patch['product_id'] = product_id
        if name is not None and 'name' in ['product_id', 'name', 'price']:
            patch['name'] = name
        if price is not None and 'price' in ['product_id', 'name', 'price']:
            patch['price'] = price
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=LookupError)
        return models.Product(**record)

    def delete(self, product_id: int = None, name: str = None, price: int = None) -> None:
        """Deletes an existing Product. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if product_id is not None:
            criteria.append(('product_id', 'eq', product_id))
        if name is not None:
            criteria.append(('name', 'eq', name))
        if price is not None:
            criteria.append(('price', 'eq', price))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise LookupError(f"Product delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None

    def create_product(self, name: str = None, price: float = None) -> bool:
        """Creates a new product with the given name and price. [crud:create: STANDARD_CRUD]"""
        values = {}
        if name is not None:
            values['name'] = name
        if price is not None:
            values['price'] = price
        unknown = [k for k in values if k not in ['product_id', 'name', 'price']]
        if unknown:
            raise ValueError(f"cannot create Product from {unknown}")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[])
        return record[self.PK]

    def read_product_by_id(self, product_id: int = None) -> models.Product | None:
        """Retrieves a product by its product_id. [crud:read_one: READ_ONE_BY_ID]"""
        found = self._store.select(self.ENTITY, [(self.PK, 'eq', product_id)])
        if not found:
            return None
        record = found[0]
        return models.Product(**record)

    def read_all_products(self) -> list[models.Product]:
        """Retrieves all products from the database. [crud:read_all: READ_ALL]"""
        criteria = []
        found = self._store.select(self.ENTITY, criteria)
        return [models.Product(**r) for r in found]

    def update_product(self, product_id: int = None, name: str = None, price: float = None) -> bool:
        """Updates the name and price of a product by its product_id. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if product_id is not None:
            criteria.append(('product_id', 'eq', product_id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise LookupError(f"Product update matched {len(found)} records")
        patch = {}
        if product_id is not None and 'product_id' in ['product_id', 'name', 'price']:
            patch['product_id'] = product_id
        if name is not None and 'name' in ['product_id', 'name', 'price']:
            patch['name'] = name
        if price is not None and 'price' in ['product_id', 'name', 'price']:
            patch['price'] = price
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=LookupError)
        return models.Product(**record)

    def delete_product(self, product_id: int = None) -> bool:
        """Deletes a product by its product_id. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if product_id is not None:
            criteria.append(('product_id', 'eq', product_id))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise LookupError(f"Product delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None


class SaleRepository:
    ENTITY = "Sale"
    PK = "sale_id"

    def __init__(self, store):
        self._store = store


    def create(self, product_id: int = None, quantity: int = None, sale_date: Any = None) -> Any:
        """Creates a new Sale. [crud:create: STANDARD_CRUD]"""
        values = {}
        if product_id is not None:
            values['product_id'] = product_id
        if quantity is not None:
            values['quantity'] = quantity
        if sale_date is not None:
            values['sale_date'] = sale_date
        unknown = [k for k in values if k not in ['sale_id', 'product_id', 'quantity', 'sale_date']]
        if unknown:
            raise ValueError(f"cannot create Sale from {unknown}")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[("product_id", "Product", "product_id", None)])
        return models.Sale(**record)

    def read_one(self, sale_id: int = None) -> Any:
        """Reads one Sale by its key. [crud:read_one: READ_ONE_BY_ID]"""
        found = self._store.select(self.ENTITY, [(self.PK, 'eq', sale_id)])
        if not found:
            return None
        record = found[0]
        return models.Sale(**record)

    def read_all(self, product_id: int = None, quantity: int = None, sale_date: Any = None) -> list[models.Sale]:
        """Lists every Sale; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if product_id is not None:
            criteria.append(('product_id', 'eq', product_id))
        if quantity is not None:
            criteria.append(('quantity', 'eq', quantity))
        if sale_date is not None:
            criteria.append(('sale_date', 'eq', sale_date))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Sale(**r) for r in found]

    def update(self, sale_id: int = None, product_id: int = None, quantity: int = None, sale_date: Any = None) -> Any:
        """Updates an existing Sale. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if sale_id is not None:
            criteria.append(('sale_id', 'eq', sale_id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise LookupError(f"Sale update matched {len(found)} records")
        patch = {}
        if sale_id is not None and 'sale_id' in ['sale_id', 'product_id', 'quantity', 'sale_date']:
            patch['sale_id'] = sale_id
        if product_id is not None and 'product_id' in ['sale_id', 'product_id', 'quantity', 'sale_date']:
            patch['product_id'] = product_id
        if quantity is not None and 'quantity' in ['sale_id', 'product_id', 'quantity', 'sale_date']:
            patch['quantity'] = quantity
        if sale_date is not None and 'sale_date' in ['sale_id', 'product_id', 'quantity', 'sale_date']:
            patch['sale_date'] = sale_date
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=LookupError)
        return models.Sale(**record)

    def delete(self, sale_id: int = None, product_id: int = None, quantity: int = None, sale_date: Any = None) -> None:
        """Deletes an existing Sale. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if sale_id is not None:
            criteria.append(('sale_id', 'eq', sale_id))
        if product_id is not None:
            criteria.append(('product_id', 'eq', product_id))
        if quantity is not None:
            criteria.append(('quantity', 'eq', quantity))
        if sale_date is not None:
            criteria.append(('sale_date', 'eq', sale_date))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise LookupError(f"Sale delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None

    def get_sales_by_product_id(self, product_id: int = None) -> list[models.Sale]:
        """Lists the Sale records belonging to one Product. [crud:filter: FILTER_BY_FIELD: by parameter shape]"""
        criteria = []
        if product_id is not None:
            criteria.append(('product_id', 'eq', product_id))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Sale(**r) for r in found]

    def create_sale(self, product_id: int = None, quantity: int = None, sale_date: datetime.datetime = None) -> bool:
        """Creates a new sale with the given product_id, quantity, and sale_date. [crud:create: STANDARD_CRUD]"""
        values = {}
        if product_id is not None:
            values['product_id'] = product_id
        if quantity is not None:
            values['quantity'] = quantity
        if sale_date is not None:
            values['sale_date'] = sale_date
        unknown = [k for k in values if k not in ['sale_id', 'product_id', 'quantity', 'sale_date']]
        if unknown:
            raise ValueError(f"cannot create Sale from {unknown}")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[("product_id", "Product", "product_id", None)])
        return record[self.PK]

    def read_sale_by_id(self, sale_id: int = None) -> models.Sale | None:
        """Retrieves a sale by its sale_id. [crud:read_one: READ_ONE_BY_ID]"""
        found = self._store.select(self.ENTITY, [(self.PK, 'eq', sale_id)])
        if not found:
            return None
        record = found[0]
        return models.Sale(**record)

    def read_all_sales(self) -> list[models.Sale]:
        """Retrieves all sales from the database. [crud:read_all: READ_ALL]"""
        criteria = []
        found = self._store.select(self.ENTITY, criteria)
        return [models.Sale(**r) for r in found]

    def update_sale(self, sale_id: int = None, quantity: int = None, sale_date: datetime.datetime = None) -> bool:
        """Updates the quantity and sale_date of a sale by its sale_id. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if sale_id is not None:
            criteria.append(('sale_id', 'eq', sale_id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise LookupError(f"Sale update matched {len(found)} records")
        patch = {}
        if sale_id is not None and 'sale_id' in ['sale_id', 'product_id', 'quantity', 'sale_date']:
            patch['sale_id'] = sale_id
        if quantity is not None and 'quantity' in ['sale_id', 'product_id', 'quantity', 'sale_date']:
            patch['quantity'] = quantity
        if sale_date is not None and 'sale_date' in ['sale_id', 'product_id', 'quantity', 'sale_date']:
            patch['sale_date'] = sale_date
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=LookupError)
        return models.Sale(**record)

    def delete_sale(self, sale_id: int = None) -> bool:
        """Deletes a sale by its sale_id. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if sale_id is not None:
            criteria.append(('sale_id', 'eq', sale_id))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise LookupError(f"Sale delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None
