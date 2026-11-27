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
    PK = "id"

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

    def read_one(self, id: int = None) -> models.Customer:
        """Reads one Customer by its key. [crud:read_one: READ_ONE_BY_ID]"""
        record = self._store.get(self.ENTITY, self.PK, id, error=errors.CustomerNotFoundError)
        return models.Customer(**record)


class InvoiceLineRepository:
    ENTITY = "InvoiceLine"
    PK = "line_id"

    def __init__(self, store):
        self._store = store


    def create(self, invoice_id: int = None, product_id: int = None, quantity: int = None) -> models.InvoiceLine:
        """Creates a new InvoiceLine. [crud:create: STANDARD_CRUD]"""
        values = {}
        if invoice_id is not None:
            values['invoice_id'] = invoice_id
        if product_id is not None:
            values['product_id'] = product_id
        if quantity is not None:
            values['quantity'] = quantity
        unknown = [k for k in values if k not in ['line_id', 'invoice_id', 'product_id', 'quantity']]
        if unknown:
            raise ValueError(f"cannot create InvoiceLine from {unknown}")
        value = values.get('quantity')
        if value is not None and value <= 0:
            raise ValueError(f"InvoiceLine.quantity must be > 0, got {value!r}")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[("invoice_id", "Invoice", "id", errors.InvoiceLineNotFoundError), ("product_id", "Product", "id", errors.ProductNotFoundError)])
        return models.InvoiceLine(**record)

    def read_one(self, line_id: int = None) -> models.InvoiceLine:
        """Reads one InvoiceLine by its key. [crud:read_one: READ_ONE_BY_ID]"""
        record = self._store.get(self.ENTITY, self.PK, line_id, error=errors.InvoiceLineNotFoundError)
        return models.InvoiceLine(**record)


class InvoiceRepository:
    ENTITY = "Invoice"
    PK = "id"

    def __init__(self, store):
        self._store = store


    def create(self, customer_id: int = None, issue_date: Any = None, total_amount: int = None) -> models.Invoice:
        """Creates a new Invoice. [crud:create: STANDARD_CRUD]"""
        values = {}
        if customer_id is not None:
            values['customer_id'] = customer_id
        if issue_date is not None:
            values['issue_date'] = issue_date
        if total_amount is not None:
            values['total_amount'] = total_amount
        unknown = [k for k in values if k not in ['id', 'customer_id', 'issue_date', 'total_amount']]
        if unknown:
            raise ValueError(f"cannot create Invoice from {unknown}")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[("customer_id", "Customer", "id", errors.CustomerNotFoundError)])
        return models.Invoice(**record)

    def read_all(self, customer_id: int = None, issue_date: Any = None, total_amount: int = None) -> list[models.Invoice]:
        """Lists every Invoice; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if customer_id is not None:
            criteria.append(('customer_id', 'eq', customer_id))
        if issue_date is not None:
            criteria.append(('issue_date', 'eq', issue_date))
        if total_amount is not None:
            criteria.append(('total_amount', 'eq', total_amount))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Invoice(**r) for r in found]

    def read_one(self, id: int = None) -> models.Invoice:
        """Reads one Invoice by its key. [crud:read_one: READ_ONE_BY_ID]"""
        record = self._store.get(self.ENTITY, self.PK, id, error=errors.InvoiceLineNotFoundError)
        return models.Invoice(**record)


class ProductRepository:
    ENTITY = "Product"
    PK = "id"

    def __init__(self, store):
        self._store = store


    def read_all(self, name: str = None, price: int = None) -> list[models.Product]:
        """Lists every Product; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if name is not None:
            criteria.append(('name', 'eq', name))
        if price is not None:
            criteria.append(('price', 'eq', price))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Product(**r) for r in found]

    def read_one(self, id: int = None) -> models.Product:
        """Reads one Product by its key. [crud:read_one: READ_ONE_BY_ID]"""
        record = self._store.get(self.ENTITY, self.PK, id, error=errors.ProductNotFoundError)
        return models.Product(**record)
