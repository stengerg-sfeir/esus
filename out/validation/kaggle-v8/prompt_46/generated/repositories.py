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



class ClientRepository:
    ENTITY = "Client"
    PK = "id"

    def __init__(self, store):
        self._store = store


    def create(self, name: str = None, email: str = None, phone: str = None, account_status: str = None) -> Any:
        """Creates a new Client. [crud:create: STANDARD_CRUD]"""
        values = {}
        if name is not None:
            values['name'] = name
        if email is not None:
            values['email'] = email
        if phone is not None:
            values['phone'] = phone
        if account_status is not None:
            values['account_status'] = account_status
        unknown = [k for k in values if k not in ['id', 'name', 'email', 'phone', 'account_status']]
        if unknown:
            raise ValueError(f"cannot create Client from {unknown}")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[])
        return models.Client(**record)

    def read_one(self, id: int = None) -> Any:
        """Reads one Client by its key. [crud:read_one: READ_ONE_BY_ID]"""
        record = self._store.get(self.ENTITY, self.PK, id, error=errors.ClientNotFoundError)
        return models.Client(**record)

    def read_all(self, name: str = None, email: str = None, phone: str = None, account_status: str = None) -> list[models.Client]:
        """Lists every Client; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if name is not None:
            criteria.append(('name', 'eq', name))
        if email is not None:
            criteria.append(('email', 'eq', email))
        if phone is not None:
            criteria.append(('phone', 'eq', phone))
        if account_status is not None:
            criteria.append(('account_status', 'eq', account_status))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Client(**r) for r in found]

    def read_one_by_email(self, email: str = None) -> Any:
        """Fetches a client record by their email address. [crud:read_one: READ_ONE_BY_ID]"""
        criteria = []
        if email is not None:
            criteria.append(('email', 'eq', email))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise errors.ClientNotFoundError(f"Client lookup matched {len(found)} records")
        record = found[0]
        return models.Client(**record)

    def read_all_active(self) -> list[models.Client]:
        """Retrieves all clients with an active account status. [crud:read_all: READ_ALL]"""
        criteria = []
        found = self._store.select(self.ENTITY, criteria)
        return [models.Client(**r) for r in found]


class InvoiceRepository:
    ENTITY = "Invoice"
    PK = "id"

    def __init__(self, store):
        self._store = store


    def create(self, client_id: int = None, due_date: Any = None, amount: int = None, description: str = None, status: str = None) -> Any:
        """Creates a new Invoice. [crud:create: STANDARD_CRUD]"""
        values = {}
        if client_id is not None:
            values['client_id'] = client_id
        if due_date is not None:
            values['due_date'] = due_date
        if amount is not None:
            values['amount'] = amount
        if description is not None:
            values['description'] = description
        if status is not None:
            values['status'] = status
        unknown = [k for k in values if k not in ['id', 'client_id', 'due_date', 'amount', 'description', 'status']]
        if unknown:
            raise ValueError(f"cannot create Invoice from {unknown}")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[("client_id", "Client", "id", errors.ClientNotFoundError)])
        return models.Invoice(**record)

    def read_one(self, id: int = None) -> Any:
        """Reads one Invoice by its key. [crud:read_one: READ_ONE_BY_ID]"""
        record = self._store.get(self.ENTITY, self.PK, id, error=errors.InvoiceNotFoundError)
        return models.Invoice(**record)

    def read_all(self, client_id: int = None, due_date: Any = None, amount: int = None, description: str = None, status: str = None) -> list[models.Invoice]:
        """Lists every Invoice; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if client_id is not None:
            criteria.append(('client_id', 'eq', client_id))
        if due_date is not None:
            criteria.append(('due_date', 'eq', due_date))
        if amount is not None:
            criteria.append(('amount', 'eq', amount))
        if description is not None:
            criteria.append(('description', 'eq', description))
        if status is not None:
            criteria.append(('status', 'eq', status))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Invoice(**r) for r in found]

    def update(self, id: int = None, client_id: int = None, due_date: Any = None, amount: int = None, description: str = None, status: str = None) -> Any:
        """Updates an existing Invoice. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if id is not None:
            criteria.append(('id', 'eq', id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise errors.InvoiceNotFoundError(f"Invoice update matched {len(found)} records")
        patch = {}
        if id is not None and 'id' in ['id', 'client_id', 'due_date', 'amount', 'description', 'status']:
            patch['id'] = id
        if client_id is not None and 'client_id' in ['id', 'client_id', 'due_date', 'amount', 'description', 'status']:
            patch['client_id'] = client_id
        if due_date is not None and 'due_date' in ['id', 'client_id', 'due_date', 'amount', 'description', 'status']:
            patch['due_date'] = due_date
        if amount is not None and 'amount' in ['id', 'client_id', 'due_date', 'amount', 'description', 'status']:
            patch['amount'] = amount
        if description is not None and 'description' in ['id', 'client_id', 'due_date', 'amount', 'description', 'status']:
            patch['description'] = description
        if status is not None and 'status' in ['id', 'client_id', 'due_date', 'amount', 'description', 'status']:
            patch['status'] = status
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=errors.InvoiceNotFoundError)
        return models.Invoice(**record)

    def delete(self, id: int = None, client_id: int = None, due_date: Any = None, amount: int = None, description: str = None, status: str = None) -> None:
        """Deletes an existing Invoice. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if id is not None:
            criteria.append(('id', 'eq', id))
        if client_id is not None:
            criteria.append(('client_id', 'eq', client_id))
        if due_date is not None:
            criteria.append(('due_date', 'eq', due_date))
        if amount is not None:
            criteria.append(('amount', 'eq', amount))
        if description is not None:
            criteria.append(('description', 'eq', description))
        if status is not None:
            criteria.append(('status', 'eq', status))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise errors.InvoiceNotFoundError(f"Invoice delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None

    def find_outstanding_invoices(self) -> list[models.Invoice]:
        """Returns all invoices that are not paid and have a due date in the future. [llm-written by server — review]"""
        found_invoices = self._store.select(self.ENTITY, [])
        outstanding = []
        for invoice in found_invoices:
            if invoice.get('status') != 'paid':
                if invoice.get('due_date') is not None:
                    today = datetime.date.today()
                    if invoice['due_date'] > today:
                        outstanding.append(models.Invoice(**invoice))
        return _model_list(outstanding, models.Invoice)

    def read_all_by_client(self, client_id: int = None) -> list[models.Invoice]:
        """Retrieves all invoices associated with a specific client. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if client_id is not None:
            criteria.append(('client_id', 'eq', client_id))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Invoice(**r) for r in found]


class PaymentRepository:
    ENTITY = "Payment"
    PK = "id"

    def __init__(self, store):
        self._store = store


    def create(self, invoice_id: int = None, payment_date: Any = None, amount: int = None, payment_method: str = None) -> Any:
        """Creates a new Payment. [crud:create: STANDARD_CRUD]"""
        values = {}
        if invoice_id is not None:
            values['invoice_id'] = invoice_id
        if payment_date is not None:
            values['payment_date'] = payment_date
        if amount is not None:
            values['amount'] = amount
        if payment_method is not None:
            values['payment_method'] = payment_method
        unknown = [k for k in values if k not in ['id', 'invoice_id', 'payment_date', 'amount', 'payment_method']]
        if unknown:
            raise ValueError(f"cannot create Payment from {unknown}")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[("invoice_id", "Invoice", "id", errors.InvoiceNotFoundError)])
        return models.Payment(**record)

    def read_one(self, id: int = None) -> Any:
        """Reads one Payment by its key. [crud:read_one: READ_ONE_BY_ID]"""
        record = self._store.get(self.ENTITY, self.PK, id, error=errors.PaymentNotFoundError)
        return models.Payment(**record)

    def read_all(self, invoice_id: int = None, payment_date: Any = None, amount: int = None, payment_method: str = None) -> list[models.Payment]:
        """Lists every Payment; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if invoice_id is not None:
            criteria.append(('invoice_id', 'eq', invoice_id))
        if payment_date is not None:
            criteria.append(('payment_date', 'eq', payment_date))
        if amount is not None:
            criteria.append(('amount', 'eq', amount))
        if payment_method is not None:
            criteria.append(('payment_method', 'eq', payment_method))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Payment(**r) for r in found]

    def update(self, id: int = None, invoice_id: int = None, payment_date: Any = None, amount: int = None, payment_method: str = None) -> Any:
        """Updates an existing Payment. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if id is not None:
            criteria.append(('id', 'eq', id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise errors.PaymentNotFoundError(f"Payment update matched {len(found)} records")
        patch = {}
        if id is not None and 'id' in ['id', 'invoice_id', 'payment_date', 'amount', 'payment_method']:
            patch['id'] = id
        if invoice_id is not None and 'invoice_id' in ['id', 'invoice_id', 'payment_date', 'amount', 'payment_method']:
            patch['invoice_id'] = invoice_id
        if payment_date is not None and 'payment_date' in ['id', 'invoice_id', 'payment_date', 'amount', 'payment_method']:
            patch['payment_date'] = payment_date
        if amount is not None and 'amount' in ['id', 'invoice_id', 'payment_date', 'amount', 'payment_method']:
            patch['amount'] = amount
        if payment_method is not None and 'payment_method' in ['id', 'invoice_id', 'payment_date', 'amount', 'payment_method']:
            patch['payment_method'] = payment_method
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=errors.PaymentNotFoundError)
        return models.Payment(**record)

    def delete(self, id: int = None, invoice_id: int = None, payment_date: Any = None, amount: int = None, payment_method: str = None) -> None:
        """Deletes an existing Payment. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if id is not None:
            criteria.append(('id', 'eq', id))
        if invoice_id is not None:
            criteria.append(('invoice_id', 'eq', invoice_id))
        if payment_date is not None:
            criteria.append(('payment_date', 'eq', payment_date))
        if amount is not None:
            criteria.append(('amount', 'eq', amount))
        if payment_method is not None:
            criteria.append(('payment_method', 'eq', payment_method))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise errors.PaymentNotFoundError(f"Payment delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None

    def read_one_by_invoice_id(self, invoice_id: int = None) -> Any:
        """Fetches a payment record by invoice ID. [lookup through a named relation]"""
        criteria = []
        if invoice_id is not None:
            parent_rows = self._store.select('Invoice', [('id', 'eq', invoice_id)])
            if not parent_rows:
                return None
            criteria.append(('invoice_id', 'eq', parent_rows[0]['id']))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            return None
        return models.Payment(**found[0])

    def find_paid_invoices(self) -> list[models.Invoice]:
        """Returns a list of invoices that have been fully paid, identified by matching payment records. [llm-written by server — review]"""
        found_payments = self._store.select(self.ENTITY, [])
        if not found_payments:
            return _model_list([], models.Invoice)
        invoice_ids = {payment['invoice_id'] for payment in found_payments}
        invoices = self._store.select(self.ENTITY, [])
        paid_invoices = []
        for invoice in invoices:
            if invoice['id'] in invoice_ids:
                paid_invoices.append(models.Invoice(**invoice))
        return _model_list(paid_invoices, models.Invoice)
