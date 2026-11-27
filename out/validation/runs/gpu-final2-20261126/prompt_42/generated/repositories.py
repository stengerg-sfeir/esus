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


    def read_all(self, email: str = None, name: str = None) -> list[models.Customer]:
        """Lists every Customer; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if email is not None:
            criteria.append(('email', 'eq', email))
        if name is not None:
            criteria.append(('name', 'eq', name))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Customer(**r) for r in found]

    def read_one(self, customer_id: int = None) -> models.Customer:
        """Reads one Customer by its key. [crud:read_one: READ_ONE_BY_ID]"""
        found = self._store.select(self.ENTITY, [(self.PK, 'eq', customer_id)])
        if not found:
            return None
        record = found[0]
        return models.Customer(**record)


class PurchaseRepository:
    ENTITY = "Purchase"
    PK = "purchase_id"

    def __init__(self, store):
        self._store = store


    def find_customer_purchases(self, customer_id: int = None) -> list[models.Purchase]:
        """Find customer purchases. [mechanical contained-name filter]"""
        criteria = []
        if customer_id is not None:
            criteria.append(('customer_id', 'eq', customer_id))
        found = self._store.select(self.ENTITY, criteria)
        return _model_list([models.Purchase(**row) for row in found], models.Purchase)

    def get_purchases_by_customer_id(self, customer_id: int = None) -> list[models.Purchase]:
        """Lists the Purchase records belonging to one Customer. [mechanical contained-name filter]"""
        criteria = []
        if customer_id is not None:
            criteria.append(('customer_id', 'eq', customer_id))
        found = self._store.select(self.ENTITY, criteria)
        return _model_list([models.Purchase(**row) for row in found], models.Purchase)

    def get_total_spent_by_customer(self, customer_id: int = None) -> float:
        """Calculate and return the total amount spent by a customer across all their purchases. [AGGREGATE_BY_FK_AND_DATE via answered slots: fk_field=customer_id, date_field=purchase_date, target_field=amount, aggregate_func=SUM]"""
        total = 0
        for record in self._store.select(self.ENTITY, []):
            if customer_id is not None and record.get('customer_id') != customer_id:
                continue
            total += record.get('amount') or 0
        return total

    def read_all(self, customer_id: int = None, purchase_date: Any = None, amount: int = None) -> list[models.Purchase]:
        """Lists every Purchase; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if customer_id is not None:
            criteria.append(('customer_id', 'eq', customer_id))
        if purchase_date is not None:
            criteria.append(('purchase_date', 'eq', purchase_date))
        if amount is not None:
            criteria.append(('amount', 'eq', amount))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Purchase(**r) for r in found]

    def read_one(self, purchase_id: int = None) -> models.Purchase:
        """Reads one Purchase by its key. [crud:read_one: READ_ONE_BY_ID]"""
        found = self._store.select(self.ENTITY, [(self.PK, 'eq', purchase_id)])
        if not found:
            return None
        record = found[0]
        return models.Purchase(**record)
