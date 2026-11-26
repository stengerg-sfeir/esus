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


    def create(self, name: str = None, stock_quantity: int = None, price: int = None) -> Any:
        """Creates a new Product. [crud:create: STANDARD_CRUD]"""
        values = {}
        if name is not None:
            values['name'] = name
        if stock_quantity is not None:
            values['stock_quantity'] = stock_quantity
        if price is not None:
            values['price'] = price
        unknown = [k for k in values if k not in ['id', 'name', 'stock_quantity', 'price']]
        if unknown:
            raise ValueError(f"cannot create Product from {unknown}")
        value = values.get('stock_quantity')
        if value is not None and value < 0:
            raise ValueError(f"Product.stock_quantity must be >= 0, got {value!r}")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[])
        return models.Product(**record)

    def read_all(self, name: str = None, stock_quantity: int = None, price: int = None) -> list[models.Product]:
        """Lists every Product; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if name is not None:
            criteria.append(('name', 'eq', name))
        if stock_quantity is not None:
            criteria.append(('stock_quantity', 'eq', stock_quantity))
        if price is not None:
            criteria.append(('price', 'eq', price))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Product(**r) for r in found]

    def read_one(self, id: int = None) -> Any:
        """Reads one Product by its key. [crud:read_one: READ_ONE_BY_ID]"""
        found = self._store.select(self.ENTITY, [(self.PK, 'eq', id)])
        if not found:
            return None
        record = found[0]
        return models.Product(**record)

    def update(self, id: int = None, name: str = None, stock_quantity: int = None, price: int = None) -> Any:
        """Updates an existing Product. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if id is not None:
            criteria.append(('id', 'eq', id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise LookupError(f"Product update matched {len(found)} records")
        patch = {}
        if id is not None and 'id' in ['id', 'name', 'stock_quantity', 'price']:
            patch['id'] = id
        if name is not None and 'name' in ['id', 'name', 'stock_quantity', 'price']:
            patch['name'] = name
        if stock_quantity is not None and 'stock_quantity' in ['id', 'name', 'stock_quantity', 'price']:
            patch['stock_quantity'] = stock_quantity
        if price is not None and 'price' in ['id', 'name', 'stock_quantity', 'price']:
            patch['price'] = price
        value = patch.get('stock_quantity')
        if value is not None and value < 0:
            raise ValueError(f"Product.stock_quantity must be >= 0, got {value!r}")
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=LookupError)
        return models.Product(**record)

    def createProduct(self, name: str = None, stock_quantity: int = None, price: float = None) -> Any:
        """Creates a new product with the specified name, stock quantity, and price. Ensures that the product is added to the inventory with valid initial values. [crud:create: STANDARD_CRUD]"""
        values = {}
        if name is not None:
            values['name'] = name
        if stock_quantity is not None:
            values['stock_quantity'] = stock_quantity
        if price is not None:
            values['price'] = price
        unknown = [k for k in values if k not in ['id', 'name', 'stock_quantity', 'price']]
        if unknown:
            raise ValueError(f"cannot create Product from {unknown}")
        value = values.get('stock_quantity')
        if value is not None and value < 0:
            raise ValueError(f"Product.stock_quantity must be >= 0, got {value!r}")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[])
        return models.Product(**record)

    def readAllProducts(self) -> List[models.Product]:
        """Retrieves all products from the inventory, including their name, stock quantity, and price. Used for displaying the full product catalog. [crud:read_all: READ_ALL]"""
        criteria = []
        found = self._store.select(self.ENTITY, criteria)
        return [models.Product(**r) for r in found]

    def readProductById(self, id: int = None) -> Any:
        """Retrieves a product by its unique ID. Ensures the product exists in the inventory and returns its details. [crud:read_one: READ_ONE_BY_ID]"""
        found = self._store.select(self.ENTITY, [(self.PK, 'eq', id)])
        if not found:
            return None
        record = found[0]
        return models.Product(**record)

    def updateProductStock(self, id: int = None, new_stock_quantity: int = None) -> Any:
        """Updates the stock quantity of a product by ID. Validates that the new stock quantity is non-negative and updates the inventory accordingly. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if id is not None:
            criteria.append(('id', 'eq', id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise LookupError(f"Product update matched {len(found)} records")
        patch = {}
        if id is not None and 'id' in ['id', 'name', 'stock_quantity', 'price']:
            patch['id'] = id
        if new_stock_quantity is not None and 'new_stock_quantity' in ['id', 'name', 'stock_quantity', 'price']:
            patch['new_stock_quantity'] = new_stock_quantity
        value = patch.get('stock_quantity')
        if value is not None and value < 0:
            raise ValueError(f"Product.stock_quantity must be >= 0, got {value!r}")
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=LookupError)
        return models.Product(**record)


class SaleRepository:
    ENTITY = "Sale"
    PK = "id"

    def __init__(self, store):
        self._store = store


    def create(self, product_id: int = None, quantity: int = None, sale_date: Any = None, user_id: str = None) -> Any:
        """Creates a new Sale. [crud:create: STANDARD_CRUD]"""
        values = {}
        if product_id is not None:
            values['product_id'] = product_id
        if quantity is not None:
            values['quantity'] = quantity
        if sale_date is not None:
            values['sale_date'] = sale_date
        if user_id is not None:
            values['user_id'] = user_id
        unknown = [k for k in values if k not in ['id', 'product_id', 'quantity', 'sale_date', 'user_id']]
        if unknown:
            raise ValueError(f"cannot create Sale from {unknown}")
        value = values.get('quantity')
        if value is not None and value < 0:
            raise ValueError(f"Sale.quantity must be >= 0, got {value!r}")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[("product_id", "Product", "id", None)])
        return models.Sale(**record)

    def read_one(self, id: int = None) -> Any:
        """Reads one Sale by its key. [crud:read_one: READ_ONE_BY_ID]"""
        found = self._store.select(self.ENTITY, [(self.PK, 'eq', id)])
        if not found:
            return None
        record = found[0]
        return models.Sale(**record)

    def createSale(self, product_id: int = None, quantity: int = None, sale_date: datetime.datetime = None, user_id: int = None) -> Any:
        """Records a sale of a product by updating the product's stock quantity to reflect the sold amount. Ensures that the product has sufficient stock before allowing the sale to proceed. [crud:create: STANDARD_CRUD]"""
        values = {}
        if product_id is not None:
            values['product_id'] = product_id
        if quantity is not None:
            values['quantity'] = quantity
        if sale_date is not None:
            values['sale_date'] = sale_date
        if user_id is not None:
            values['user_id'] = user_id
        unknown = [k for k in values if k not in ['id', 'product_id', 'quantity', 'sale_date', 'user_id']]
        if unknown:
            raise ValueError(f"cannot create Sale from {unknown}")
        value = values.get('quantity')
        if value is not None and value < 0:
            raise ValueError(f"Sale.quantity must be >= 0, got {value!r}")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[("product_id", "Product", "id", None)])
        return models.Sale(**record)

    def readSaleById(self, id: int = None) -> Any:
        """Retrieves a sale record by its unique ID. Used to view transaction details such as product, quantity, date, and user. [crud:read_one: READ_ONE_BY_ID]"""
        found = self._store.select(self.ENTITY, [(self.PK, 'eq', id)])
        if not found:
            return None
        record = found[0]
        return models.Sale(**record)
