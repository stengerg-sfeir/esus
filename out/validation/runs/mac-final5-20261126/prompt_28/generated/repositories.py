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



class InvoiceRepository:
    ENTITY = "Invoice"
    PK = "id"

    def __init__(self, store):
        self._store = store


    def read_one(self, id: int = None) -> Any:
        """Reads one Invoice by its key. [crud:read_one: READ_ONE_BY_ID]"""
        record = self._store.get(self.ENTITY, self.PK, id, error=errors.InvoiceNotFoundError)
        return models.Invoice(**record)

    def read_all(self, customer_id: int = None, total_amount: int = None, created_at: Any = None) -> list[models.Invoice]:
        """Lists every Invoice; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if customer_id is not None:
            criteria.append(('customer_id', 'eq', customer_id))
        if total_amount is not None:
            criteria.append(('total_amount', 'eq', total_amount))
        if created_at is not None:
            criteria.append(('created_at', 'eq', created_at))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Invoice(**r) for r in found]

    def read_one_by_customer_id(self, customer_id: int = None) -> models.Invoice | None:
        """Fetches an invoice by its customer ID, returning the full invoice object including all associated invoice lines and product details. [lookup through a named relation]"""
        criteria = []
        if customer_id is not None:
            parent_rows = self._store.select('Customer', [('id', 'eq', customer_id)])
            if not parent_rows:
                return None
            criteria.append(('customer_id', 'eq', parent_rows[0]['id']))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            return None
        return models.Invoice(**found[0])

    def read_all_by_date_range(self, start_date: datetime.datetime = None, end_date: datetime.datetime = None) -> list[models.Invoice]:
        """Retrieves all invoices created within a specified date range, inclusive of both start and end dates, with full line item and product details. [llm-written by server — review]"""
        criteria = []
        if start_date is not None:
            criteria.append(('created_at', 'ge', start_date))
        if end_date is not None:
            criteria.append(('created_at', 'le', end_date))
        found = self._store.select(self.ENTITY, criteria)
        return _model_list([models.Invoice(**r) for r in found], models.Invoice)


class ProductRepository:
    ENTITY = "Product"
    PK = "id"

    def __init__(self, store):
        self._store = store


    def read_one(self, id: int = None) -> Any:
        """Reads one Product by its key. [crud:read_one: READ_ONE_BY_ID]"""
        record = self._store.get(self.ENTITY, self.PK, id, error=errors.ProductNotFoundError)
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

    def read_one_by_name(self, name: str = None) -> models.Product | None:
        """Fetches a product by its name, returning the full product object with its price. [crud:read_one: READ_ONE_BY_ID]"""
        criteria = []
        if name is not None:
            criteria.append(('name', 'eq', name))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise errors.ProductNotFoundError(f"Product lookup matched {len(found)} records")
        record = found[0]
        return models.Product(**record)

    def read_all_by_price_range(self, min_price: float = None, max_price: float = None) -> list[models.Product]:
        """Returns all products whose price falls within a specified range, inclusive of both bounds. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if min_price is not None:
            criteria.append(('price', 'ge', min_price))
        if max_price is not None:
            criteria.append(('price', 'le', max_price))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Product(**r) for r in found]


class CustomerRepository:
    ENTITY = "Customer"
    PK = "id"

    def __init__(self, store):
        self._store = store


    def read_one(self, id: int = None) -> Any:
        """Reads one Customer by its key. [crud:read_one: READ_ONE_BY_ID]"""
        record = self._store.get(self.ENTITY, self.PK, id, error=errors.CustomerNotFoundError)
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

    def read_one_by_email(self, email: str = None) -> models.Customer | None:
        """Fetches a customer by their email address, returning the full customer object. [crud:read_one: READ_ONE_BY_ID]"""
        criteria = []
        if email is not None:
            criteria.append(('email', 'eq', email))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise errors.CustomerNotFoundError(f"Customer lookup matched {len(found)} records")
        record = found[0]
        return models.Customer(**record)

    def read_all_active(self) -> list[models.Customer]:
        """Returns all customers who have active status (e.g., not deleted or suspended), with their name and email. [crud:read_all: READ_ALL]"""
        criteria = []
        found = self._store.select(self.ENTITY, criteria)
        return [models.Customer(**r) for r in found]


class InvoiceLineRepository:
    ENTITY = "InvoiceLine"
    PK = "id"

    def __init__(self, store):
        self._store = store


    def create(self, invoice_id: int = None, product_id: int = None, quantity: int = None, unit_price: int = None, line_total: int = None) -> Any:
        """Creates a new InvoiceLine. [crud:create: STANDARD_CRUD]"""
        values = {}
        if invoice_id is not None:
            values['invoice_id'] = invoice_id
        if product_id is not None:
            values['product_id'] = product_id
        if quantity is not None:
            values['quantity'] = quantity
        if unit_price is not None:
            values['unit_price'] = unit_price
        if line_total is not None:
            values['line_total'] = line_total
        unknown = [k for k in values if k not in ['id', 'invoice_id', 'product_id', 'quantity', 'unit_price', 'line_total']]
        if unknown:
            raise ValueError(f"cannot create InvoiceLine from {unknown}")
        if values.get('line_total') is None:
            values['line_total'] = values.get('quantity', 0) * values.get('unit_price', 0)
        value = values.get('quantity')
        if value is not None and value <= 0:
            raise ValueError(f"InvoiceLine.quantity must be > 0, got {value!r}")
        value = values.get('unit_price')
        if value is not None and value <= 0:
            raise ValueError(f"InvoiceLine.unit_price must be > 0, got {value!r}")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[("invoice_id", "Invoice", "id", errors.InvoiceNotFoundError), ("product_id", "Product", "id", errors.ProductNotFoundError)])
        return models.InvoiceLine(**record)

    def read_one(self, id: int = None) -> Any:
        """Reads one InvoiceLine by its key. [crud:read_one: READ_ONE_BY_ID]"""
        record = self._store.get(self.ENTITY, self.PK, id, error=errors.InvoiceLineNotFoundError)
        return models.InvoiceLine(**record)

    def read_all(self, invoice_id: int = None, product_id: int = None, quantity: int = None, unit_price: int = None, line_total: int = None) -> list[models.InvoiceLine]:
        """Lists every InvoiceLine; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if invoice_id is not None:
            criteria.append(('invoice_id', 'eq', invoice_id))
        if product_id is not None:
            criteria.append(('product_id', 'eq', product_id))
        if quantity is not None:
            criteria.append(('quantity', 'eq', quantity))
        if unit_price is not None:
            criteria.append(('unit_price', 'eq', unit_price))
        if line_total is not None:
            criteria.append(('line_total', 'eq', line_total))
        found = self._store.select(self.ENTITY, criteria)
        return [models.InvoiceLine(**r) for r in found]

    def create_with_product_and_quantity(self, invoice_id: int = None, product_id: int = None, quantity: int = None, unit_price: float = None) -> Any:
        """Creates a new invoice line with a specified product ID, quantity, and unit price, and associates it with an invoice. Returns the created line object. [crud:create: STANDARD_CRUD]"""
        values = {}
        if invoice_id is not None:
            values['invoice_id'] = invoice_id
        if product_id is not None:
            values['product_id'] = product_id
        if quantity is not None:
            values['quantity'] = quantity
        if unit_price is not None:
            values['unit_price'] = unit_price
        unknown = [k for k in values if k not in ['id', 'invoice_id', 'product_id', 'quantity', 'unit_price', 'line_total']]
        if unknown:
            raise ValueError(f"cannot create InvoiceLine from {unknown}")
        if values.get('line_total') is None:
            values['line_total'] = values.get('quantity', 0) * values.get('unit_price', 0)
        value = values.get('quantity')
        if value is not None and value <= 0:
            raise ValueError(f"InvoiceLine.quantity must be > 0, got {value!r}")
        value = values.get('unit_price')
        if value is not None and value <= 0:
            raise ValueError(f"InvoiceLine.unit_price must be > 0, got {value!r}")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[("invoice_id", "Invoice", "id", errors.InvoiceNotFoundError), ("product_id", "Product", "id", errors.ProductNotFoundError)])
        return models.InvoiceLine(**record)

    def read_one_by_invoice_and_product(self, invoice_id: int = None, product_id: int = None) -> models.InvoiceLine | None:
        """Fetches an invoice line by invoice ID and product ID, returning the line with its total calculated as quantity times unit price. [lookup through a named relation]"""
        criteria = []
        if invoice_id is not None:
            parent_rows = self._store.select('Invoice', [('id', 'eq', invoice_id)])
            if not parent_rows:
                return None
            criteria.append(('invoice_id', 'eq', parent_rows[0]['id']))
        if product_id is not None:
            parent_rows = self._store.select('Product', [('id', 'eq', product_id)])
            if not parent_rows:
                return None
            criteria.append(('product_id', 'eq', parent_rows[0]['id']))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            return None
        return models.InvoiceLine(**found[0])
