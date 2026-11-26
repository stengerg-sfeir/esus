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

    def find_orders_by_customer_id(self, customer_id: int = None) -> list[models.Order]:
        """Retrieves all orders placed by a specific customer, including order status and associated products. [crud:filter: FILTER_BY_FIELD]"""
        criteria = []
        if customer_id is not None:
            criteria.append(('customer_id', 'eq', customer_id))
        found = self._store.select('Order', criteria)
        return [models.Order(**r) for r in found]

    def find_invoices_by_customer_id(self, customer_id: int = None) -> list[models.Invoice]:
        """Retrieves all invoices generated for a specific customer, including invoice total and generation date. [filters through one intermediate relation]"""
        middle_rows = self._store.select('Order', [('customer_id', 'eq', customer_id)])
        middle_ids = {row['order_id'] for row in middle_rows}
        found = [row for row in self._store.select('Invoice', []) if row.get('order_id') in middle_ids]
        return _model_list([models.Invoice(**row) for row in found], models.Invoice)


class ProductRepository:
    ENTITY = "Product"
    PK = "product_id"

    def __init__(self, store):
        self._store = store


    def create(self, name: str = None, category_id: int = None, price: int = None, stock_quantity: int = None) -> Any:
        """Creates a new Product. [crud:create: STANDARD_CRUD]"""
        values = {}
        if name is not None:
            values['name'] = name
        if category_id is not None:
            values['category_id'] = category_id
        if price is not None:
            values['price'] = price
        if stock_quantity is not None:
            values['stock_quantity'] = stock_quantity
        unknown = [k for k in values if k not in ['product_id', 'name', 'category_id', 'price', 'stock_quantity']]
        if unknown:
            raise ValueError(f"cannot create Product from {unknown}")
        value = values.get('stock_quantity')
        if value is not None and value < 0:
            raise ValueError(f"Product.stock_quantity must be >= 0, got {value!r}")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[("category_id", "Category", "category_id", errors.CategoryNotFoundError)])
        return models.Product(**record)

    def read_all(self, name: str = None, category_id: int = None, price: int = None, stock_quantity: int = None) -> list[models.Product]:
        """Lists every Product; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if name is not None:
            criteria.append(('name', 'eq', name))
        if category_id is not None:
            criteria.append(('category_id', 'eq', category_id))
        if price is not None:
            criteria.append(('price', 'eq', price))
        if stock_quantity is not None:
            criteria.append(('stock_quantity', 'eq', stock_quantity))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Product(**r) for r in found]

    def read_one(self, product_id: int = None) -> Any:
        """Reads one Product by its key. [crud:read_one: READ_ONE_BY_ID]"""
        record = self._store.get(self.ENTITY, self.PK, product_id, error=errors.ProductNotFoundError)
        return models.Product(**record)

    def update(self, product_id: int = None, name: str = None, category_id: int = None, price: int = None, stock_quantity: int = None) -> Any:
        """Updates an existing Product. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if product_id is not None:
            criteria.append(('product_id', 'eq', product_id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise errors.ProductNotFoundError(f"Product update matched {len(found)} records")
        patch = {}
        if product_id is not None and 'product_id' in ['product_id', 'name', 'category_id', 'price', 'stock_quantity']:
            patch['product_id'] = product_id
        if name is not None and 'name' in ['product_id', 'name', 'category_id', 'price', 'stock_quantity']:
            patch['name'] = name
        if category_id is not None and 'category_id' in ['product_id', 'name', 'category_id', 'price', 'stock_quantity']:
            patch['category_id'] = category_id
        if price is not None and 'price' in ['product_id', 'name', 'category_id', 'price', 'stock_quantity']:
            patch['price'] = price
        if stock_quantity is not None and 'stock_quantity' in ['product_id', 'name', 'category_id', 'price', 'stock_quantity']:
            patch['stock_quantity'] = stock_quantity
        value = patch.get('stock_quantity')
        if value is not None and value < 0:
            raise ValueError(f"Product.stock_quantity must be >= 0, got {value!r}")
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=errors.ProductNotFoundError)
        return models.Product(**record)

    def delete(self, product_id: int = None, name: str = None, category_id: int = None, price: int = None, stock_quantity: int = None) -> None:
        """Deletes an existing Product. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if product_id is not None:
            criteria.append(('product_id', 'eq', product_id))
        if name is not None:
            criteria.append(('name', 'eq', name))
        if category_id is not None:
            criteria.append(('category_id', 'eq', category_id))
        if price is not None:
            criteria.append(('price', 'eq', price))
        if stock_quantity is not None:
            criteria.append(('stock_quantity', 'eq', stock_quantity))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise errors.ProductNotFoundError(f"Product delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None

    def get_products_by_category_id(self, category_id: int = None) -> list[models.Product]:
        """Lists the Product records belonging to one Category. [crud:filter: FILTER_BY_FIELD: by parameter shape]"""
        criteria = []
        if category_id is not None:
            criteria.append(('category_id', 'eq', category_id))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Product(**r) for r in found]


class CategoryRepository:
    ENTITY = "Category"
    PK = "category_id"

    def __init__(self, store):
        self._store = store


    def create(self, name: str = None) -> Any:
        """Creates a new Category. [crud:create: STANDARD_CRUD]"""
        values = {}
        if name is not None:
            values['name'] = name
        unknown = [k for k in values if k not in ['category_id', 'name']]
        if unknown:
            raise ValueError(f"cannot create Category from {unknown}")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[])
        return models.Category(**record)

    def read_all(self, name: str = None) -> list[models.Category]:
        """Lists every Category; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if name is not None:
            criteria.append(('name', 'eq', name))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Category(**r) for r in found]

    def read_one(self, category_id: int = None) -> Any:
        """Reads one Category by its key. [crud:read_one: READ_ONE_BY_ID]"""
        record = self._store.get(self.ENTITY, self.PK, category_id, error=errors.CategoryNotFoundError)
        return models.Category(**record)

    def update(self, category_id: int = None, name: str = None) -> Any:
        """Updates an existing Category. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if category_id is not None:
            criteria.append(('category_id', 'eq', category_id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise errors.CategoryNotFoundError(f"Category update matched {len(found)} records")
        patch = {}
        if category_id is not None and 'category_id' in ['category_id', 'name']:
            patch['category_id'] = category_id
        if name is not None and 'name' in ['category_id', 'name']:
            patch['name'] = name
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=errors.CategoryNotFoundError)
        return models.Category(**record)

    def get_category_by_name(self, name: str = None) -> models.Category | None:
        """Finds a category by its name, used for product categorization and admin lookup. [crud:read_one: READ_ONE_BY_ID]"""
        criteria = []
        if name is not None:
            criteria.append(('name', 'eq', name))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise errors.CategoryNotFoundError(f"Category lookup matched {len(found)} records")
        record = found[0]
        return models.Category(**record)


class OrderRepository:
    ENTITY = "Order"
    PK = "order_id"

    def __init__(self, store):
        self._store = store


    def create(self, customer_id: int = None, status: str = None, created_at: Any = None, confirmed_at: Any = None, shipped_at: Any = None, cancelled_at: Any = None) -> Any:
        """Creates a new Order. [crud:create: STANDARD_CRUD]"""
        values = {}
        if customer_id is not None:
            values['customer_id'] = customer_id
        if status is not None:
            values['status'] = status
        if created_at is not None:
            values['created_at'] = created_at
        if confirmed_at is not None:
            values['confirmed_at'] = confirmed_at
        if shipped_at is not None:
            values['shipped_at'] = shipped_at
        if cancelled_at is not None:
            values['cancelled_at'] = cancelled_at
        unknown = [k for k in values if k not in ['order_id', 'customer_id', 'status', 'created_at', 'confirmed_at', 'shipped_at', 'cancelled_at']]
        if unknown:
            raise ValueError(f"cannot create Order from {unknown}")
        if values.get('created_at') is None:
            values['created_at'] = datetime.datetime.now()
        if values.get('status') is None:
            values['status'] = 'pending'
        if values.get('status') not in ['pending', 'confirmed', 'shipped', 'cancelled']:
            raise ValueError(f"Order.status must be one of ['pending', 'confirmed', 'shipped', 'cancelled']")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[("customer_id", "Customer", "customer_id", errors.CustomerNotFoundError)])
        return models.Order(**record)

    def read_all(self, customer_id: int = None, status: str = None, created_at: Any = None, confirmed_at: Any = None, shipped_at: Any = None, cancelled_at: Any = None) -> list[models.Order]:
        """Lists every Order; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if customer_id is not None:
            criteria.append(('customer_id', 'eq', customer_id))
        if status is not None:
            criteria.append(('status', 'eq', status))
        if created_at is not None:
            criteria.append(('created_at', 'eq', created_at))
        if confirmed_at is not None:
            criteria.append(('confirmed_at', 'eq', confirmed_at))
        if shipped_at is not None:
            criteria.append(('shipped_at', 'eq', shipped_at))
        if cancelled_at is not None:
            criteria.append(('cancelled_at', 'eq', cancelled_at))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Order(**r) for r in found]

    def read_one(self, order_id: int = None) -> Any:
        """Reads one Order by its key. [crud:read_one: READ_ONE_BY_ID]"""
        record = self._store.get(self.ENTITY, self.PK, order_id, error=errors.OrderNotFoundError)
        return models.Order(**record)

    def update(self, order_id: int = None, customer_id: int = None, status: str = None, created_at: Any = None, confirmed_at: Any = None, shipped_at: Any = None, cancelled_at: Any = None) -> Any:
        """Updates an existing Order. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if order_id is not None:
            criteria.append(('order_id', 'eq', order_id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise errors.OrderNotFoundError(f"Order update matched {len(found)} records")
        patch = {}
        if order_id is not None and 'order_id' in ['order_id', 'customer_id', 'status', 'created_at', 'confirmed_at', 'shipped_at', 'cancelled_at']:
            patch['order_id'] = order_id
        if customer_id is not None and 'customer_id' in ['order_id', 'customer_id', 'status', 'created_at', 'confirmed_at', 'shipped_at', 'cancelled_at']:
            patch['customer_id'] = customer_id
        if status is not None and 'status' in ['order_id', 'customer_id', 'status', 'created_at', 'confirmed_at', 'shipped_at', 'cancelled_at']:
            patch['status'] = status
        if created_at is not None and 'created_at' in ['order_id', 'customer_id', 'status', 'created_at', 'confirmed_at', 'shipped_at', 'cancelled_at']:
            patch['created_at'] = created_at
        if confirmed_at is not None and 'confirmed_at' in ['order_id', 'customer_id', 'status', 'created_at', 'confirmed_at', 'shipped_at', 'cancelled_at']:
            patch['confirmed_at'] = confirmed_at
        if shipped_at is not None and 'shipped_at' in ['order_id', 'customer_id', 'status', 'created_at', 'confirmed_at', 'shipped_at', 'cancelled_at']:
            patch['shipped_at'] = shipped_at
        if cancelled_at is not None and 'cancelled_at' in ['order_id', 'customer_id', 'status', 'created_at', 'confirmed_at', 'shipped_at', 'cancelled_at']:
            patch['cancelled_at'] = cancelled_at
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=errors.OrderNotFoundError)
        return models.Order(**record)

    def delete(self, order_id: int = None, customer_id: int = None, status: str = None, created_at: Any = None, confirmed_at: Any = None, shipped_at: Any = None, cancelled_at: Any = None) -> None:
        """Deletes an existing Order. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if order_id is not None:
            criteria.append(('order_id', 'eq', order_id))
        if customer_id is not None:
            criteria.append(('customer_id', 'eq', customer_id))
        if status is not None:
            criteria.append(('status', 'eq', status))
        if created_at is not None:
            criteria.append(('created_at', 'eq', created_at))
        if confirmed_at is not None:
            criteria.append(('confirmed_at', 'eq', confirmed_at))
        if shipped_at is not None:
            criteria.append(('shipped_at', 'eq', shipped_at))
        if cancelled_at is not None:
            criteria.append(('cancelled_at', 'eq', cancelled_at))
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

    def get_order_by_id_and_status(self, order_id: int = None, status: str = None) -> models.Order | None:
        """Retrieves an order by its ID and status (pending, confirmed, shipped, cancelled), used for filtering and status-based queries. [crud:read_one: READ_ONE_BY_ID]"""
        criteria = []
        if order_id is not None:
            criteria.append(('order_id', 'eq', order_id))
        if status is not None:
            criteria.append(('status', 'eq', status))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise errors.OrderNotFoundError(f"Order lookup matched {len(found)} records")
        record = found[0]
        return models.Order(**record)

    def get_orders_by_customer_id_and_status(self, customer_id: int = None, status: str = None) -> list[models.Order]:
        """Retrieves all orders for a customer with a specific status, used for customer order history filtering. [crud:filter: FILTER_BY_FIELD: by parameter shape]"""
        criteria = []
        if customer_id is not None:
            criteria.append(('customer_id', 'eq', customer_id))
        if status is not None:
            criteria.append(('status', 'eq', status))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Order(**r) for r in found]


class InvoiceRepository:
    ENTITY = "Invoice"
    PK = "invoice_id"

    def __init__(self, store):
        self._store = store


    def create(self, order_id: int = None, total_amount: int = None, generated_at: Any = None) -> Any:
        """Creates a new Invoice. [crud:create: STANDARD_CRUD]"""
        values = {}
        if order_id is not None:
            values['order_id'] = order_id
        if total_amount is not None:
            values['total_amount'] = total_amount
        if generated_at is not None:
            values['generated_at'] = generated_at
        unknown = [k for k in values if k not in ['invoice_id', 'order_id', 'total_amount', 'generated_at']]
        if unknown:
            raise ValueError(f"cannot create Invoice from {unknown}")
        if values.get('generated_at') is None:
            values['generated_at'] = datetime.datetime.now()
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[("order_id", "Order", "order_id", errors.OrderNotFoundError)])
        return models.Invoice(**record)

    def read_all(self, order_id: int = None, total_amount: int = None, generated_at: Any = None) -> list[models.Invoice]:
        """Lists every Invoice; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if order_id is not None:
            criteria.append(('order_id', 'eq', order_id))
        if total_amount is not None:
            criteria.append(('total_amount', 'eq', total_amount))
        if generated_at is not None:
            criteria.append(('generated_at', 'eq', generated_at))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Invoice(**r) for r in found]

    def read_one(self, invoice_id: int = None) -> Any:
        """Reads one Invoice by its key. [crud:read_one: READ_ONE_BY_ID]"""
        record = self._store.get(self.ENTITY, self.PK, invoice_id, error=errors.InvoiceNotFoundError)
        return models.Invoice(**record)

    def get_invoices_by_order_id(self, order_id: int = None) -> list[models.Invoice]:
        """Lists the Invoice records belonging to one Order. [crud:filter: FILTER_BY_FIELD: by parameter shape]"""
        criteria = []
        if order_id is not None:
            criteria.append(('order_id', 'eq', order_id))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Invoice(**r) for r in found]

    def get_invoice_by_order_id(self, order_id: int = None) -> models.Invoice | None:
        """Retrieves an invoice by its associated order ID, used to link invoices to confirmed orders. [crud:read_one: READ_ONE_BY_ID]"""
        criteria = []
        if order_id is not None:
            criteria.append(('order_id', 'eq', order_id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise errors.InvoiceNotFoundError(f"Invoice lookup matched {len(found)} records")
        record = found[0]
        return models.Invoice(**record)


class OrderItemRepository:
    ENTITY = "OrderItem"
    PK = "order_item_id"

    def __init__(self, store):
        self._store = store


    def create(self, order_id: int = None, product_id: int = None, quantity: int = None) -> Any:
        """Creates a new OrderItem. [crud:create: STANDARD_CRUD]"""
        values = {}
        if order_id is not None:
            values['order_id'] = order_id
        if product_id is not None:
            values['product_id'] = product_id
        if quantity is not None:
            values['quantity'] = quantity
        unknown = [k for k in values if k not in ['order_item_id', 'order_id', 'product_id', 'quantity']]
        if unknown:
            raise ValueError(f"cannot create OrderItem from {unknown}")
        value = values.get('quantity')
        if value is not None and value < 0:
            raise ValueError(f"OrderItem.quantity must be >= 0, got {value!r}")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[("order_id", "Order", "order_id", errors.OrderNotFoundError), ("product_id", "Product", "product_id", errors.ProductNotFoundError)])
        return models.OrderItem(**record)

    def read_one(self, order_item_id: int = None) -> Any:
        """Reads one OrderItem by its key. [crud:read_one: READ_ONE_BY_ID]"""
        record = self._store.get(self.ENTITY, self.PK, order_item_id, error=errors.OrderItemNotFoundError)
        return models.OrderItem(**record)

    def read_all(self, order_id: int = None, product_id: int = None, quantity: int = None) -> list[models.OrderItem]:
        """Lists every OrderItem; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if order_id is not None:
            criteria.append(('order_id', 'eq', order_id))
        if product_id is not None:
            criteria.append(('product_id', 'eq', product_id))
        if quantity is not None:
            criteria.append(('quantity', 'eq', quantity))
        found = self._store.select(self.ENTITY, criteria)
        return [models.OrderItem(**r) for r in found]

    def get_order_items_by_order_id(self, order_id: int = None) -> list[models.OrderItem]:
        """Lists the OrderItem records belonging to one Order. [crud:filter: FILTER_BY_FIELD: by parameter shape]"""
        criteria = []
        if order_id is not None:
            criteria.append(('order_id', 'eq', order_id))
        found = self._store.select(self.ENTITY, criteria)
        return [models.OrderItem(**r) for r in found]
