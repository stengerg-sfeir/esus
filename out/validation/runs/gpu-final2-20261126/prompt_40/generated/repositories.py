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



class OrderRepository:
    ENTITY = "Order"
    PK = "id"

    def __init__(self, store):
        self._store = store


    def confirm_order(self, id: int = None) -> None:
        """Confirms a Order. [mechanical named state update]"""
        record = self._store.get('Order', 'id', id)
        if record is None:
            return None
        self._store.update('Order', 'id', record.get('id'), {'status': 'confirmed'})
        return None

    def create(self, status: str = None) -> models.Order:
        """Creates a new Order. [crud:create: STANDARD_CRUD]"""
        values = {}
        if status is not None:
            values['status'] = status
        unknown = [k for k in values if k not in ['id', 'status']]
        if unknown:
            raise ValueError(f"cannot create Order from {unknown}")
        if values.get('status') is None:
            values['status'] = 'pending'
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[])
        return models.Order(**record)

    def read_all(self, status: str = None) -> list[models.Order]:
        """Lists every Order; optional fields narrow the result. [mechanical contained-name filter]"""
        criteria = []
        if status is not None:
            criteria.append(('status', 'eq', status))
        found = self._store.select(self.ENTITY, criteria)
        return _model_list([models.Order(**row) for row in found], models.Order)

    def read_one(self, id: int = None) -> models.Order:
        """Reads one Order by its key. [crud:read_one: READ_ONE_BY_ID]"""
        found = self._store.select(self.ENTITY, [(self.PK, 'eq', id)])
        if not found:
            return None
        record = found[0]
        return models.Order(**record)

    def update(self, id: int = None, status: str = None) -> models.Order:
        """Updates an existing Order. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if id is not None:
            criteria.append(('id', 'eq', id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise LookupError(f"Order update matched {len(found)} records")
        patch = {}
        if id is not None and 'id' in ['id', 'status']:
            patch['id'] = id
        if status is not None and 'status' in ['id', 'status']:
            patch['status'] = status
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=LookupError)
        return models.Order(**record)
