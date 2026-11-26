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



class AppointmentRepository:
    ENTITY = "Appointment"
    PK = "id"

    def __init__(self, store):
        self._store = store


    def create(self, start_time: Any = None, end_time: Any = None) -> Any:
        """Creates a new Appointment. [crud:create: STANDARD_CRUD]"""
        values = {}
        if start_time is not None:
            values['start_time'] = start_time
        if end_time is not None:
            values['end_time'] = end_time
        unknown = [k for k in values if k not in ['id', 'start_time', 'end_time']]
        if unknown:
            raise ValueError(f"cannot create Appointment from {unknown}")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[])
        return models.Appointment(**record)

    def read_one(self, id: int = None) -> Any:
        """Reads one Appointment by its key. [crud:read_one: READ_ONE_BY_ID]"""
        found = self._store.select(self.ENTITY, [(self.PK, 'eq', id)])
        if not found:
            return None
        record = found[0]
        return models.Appointment(**record)

    def read_all(self, start_time: Any = None, end_time: Any = None) -> list[models.Appointment]:
        """Lists every Appointment; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if start_time is not None:
            criteria.append(('start_time', 'eq', start_time))
        if end_time is not None:
            criteria.append(('end_time', 'eq', end_time))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Appointment(**r) for r in found]

    def update(self, id: int = None, start_time: Any = None, end_time: Any = None) -> Any:
        """Updates an existing Appointment. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if id is not None:
            criteria.append(('id', 'eq', id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise LookupError(f"Appointment update matched {len(found)} records")
        patch = {}
        if id is not None and 'id' in ['id', 'start_time', 'end_time']:
            patch['id'] = id
        if start_time is not None and 'start_time' in ['id', 'start_time', 'end_time']:
            patch['start_time'] = start_time
        if end_time is not None and 'end_time' in ['id', 'start_time', 'end_time']:
            patch['end_time'] = end_time
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=LookupError)
        return models.Appointment(**record)

    def delete(self, id: int = None, start_time: Any = None, end_time: Any = None) -> None:
        """Deletes an existing Appointment. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if id is not None:
            criteria.append(('id', 'eq', id))
        if start_time is not None:
            criteria.append(('start_time', 'eq', start_time))
        if end_time is not None:
            criteria.append(('end_time', 'eq', end_time))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise LookupError(f"Appointment delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None
