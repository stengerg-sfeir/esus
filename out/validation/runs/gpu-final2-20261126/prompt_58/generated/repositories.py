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


    def read_one(self, id: int = None) -> models.Customer:
        """Reads one Customer by its key. [crud:read_one: READ_ONE_BY_ID]"""
        found = self._store.select(self.ENTITY, [(self.PK, 'eq', id)])
        if not found:
            return None
        record = found[0]
        return models.Customer(**record)


class ExternalServiceResponseRepository:
    ENTITY = "ExternalServiceResponse"
    PK = "id"

    def __init__(self, store):
        self._store = store


    def create(self, customer_id: int = None, additional_info: str = None, status: str = None, error_message: str = None, timestamp: Any = None) -> models.ExternalServiceResponse:
        """Creates a new ExternalServiceResponse. [crud:create: STANDARD_CRUD]"""
        values = {}
        if customer_id is not None:
            values['customer_id'] = customer_id
        if additional_info is not None:
            values['additional_info'] = additional_info
        if status is not None:
            values['status'] = status
        if error_message is not None:
            values['error_message'] = error_message
        if timestamp is not None:
            values['timestamp'] = timestamp
        unknown = [k for k in values if k not in ['id', 'customer_id', 'additional_info', 'status', 'error_message', 'timestamp']]
        if unknown:
            raise ValueError(f"cannot create ExternalServiceResponse from {unknown}")
        if values.get('status') is None:
            values['status'] = 'pending'
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[("customer_id", "Customer", "id", None)])
        return models.ExternalServiceResponse(**record)

    def read_all(self, customer_id: int = None, additional_info: str = None, status: str = None, error_message: str = None, timestamp: Any = None) -> list[models.ExternalServiceResponse]:
        """Lists every ExternalServiceResponse; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if customer_id is not None:
            criteria.append(('customer_id', 'eq', customer_id))
        if additional_info is not None:
            criteria.append(('additional_info', 'eq', additional_info))
        if status is not None:
            criteria.append(('status', 'eq', status))
        if error_message is not None:
            criteria.append(('error_message', 'eq', error_message))
        if timestamp is not None:
            criteria.append(('timestamp', 'eq', timestamp))
        found = self._store.select(self.ENTITY, criteria)
        return [models.ExternalServiceResponse(**r) for r in found]

    def read_one(self, id: int = None) -> models.ExternalServiceResponse:
        """Reads one ExternalServiceResponse by its key. [crud:read_one: READ_ONE_BY_ID]"""
        found = self._store.select(self.ENTITY, [(self.PK, 'eq', id)])
        if not found:
            return None
        record = found[0]
        return models.ExternalServiceResponse(**record)
