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


    def create(self, name: str = None, email: str = None) -> models.Customer:
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

    def read_all(self, name: str = None, email: str = None) -> list[models.Customer]:
        """Lists every Customer; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if name is not None:
            criteria.append(('name', 'eq', name))
        if email is not None:
            criteria.append(('email', 'eq', email))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Customer(**r) for r in found]

    def read_one(self, customer_id: int = None) -> models.Customer:
        """Reads one Customer by its key. [crud:read_one: READ_ONE_BY_ID]"""
        record = self._store.get(self.ENTITY, self.PK, customer_id, error=errors.CustomerNotFoundError)
        return models.Customer(**record)


class ReservationRepository:
    ENTITY = "Reservation"
    PK = "reservation_id"

    def __init__(self, store):
        self._store = store


    def create(self, customer_id: int = None, room_id: int = None, start_time: Any = None, end_time: Any = None) -> models.Reservation:
        """Creates a new Reservation. [crud:create: STANDARD_CRUD]"""
        values = {}
        if customer_id is not None:
            values['customer_id'] = customer_id
        if room_id is not None:
            values['room_id'] = room_id
        if start_time is not None:
            values['start_time'] = start_time
        if end_time is not None:
            values['end_time'] = end_time
        unknown = [k for k in values if k not in ['reservation_id', 'customer_id', 'room_id', 'start_time', 'end_time']]
        if unknown:
            raise ValueError(f"cannot create Reservation from {unknown}")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[("customer_id", "Customer", "customer_id", errors.CustomerNotFoundError), ("room_id", "Room", "room_id", errors.RoomNotFoundError)])
        return models.Reservation(**record)

    def delete(self, reservation_id: int = None, customer_id: int = None, room_id: int = None, start_time: Any = None, end_time: Any = None) -> None:
        """Deletes an existing Reservation. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if reservation_id is not None:
            criteria.append(('reservation_id', 'eq', reservation_id))
        if customer_id is not None:
            criteria.append(('customer_id', 'eq', customer_id))
        if room_id is not None:
            criteria.append(('room_id', 'eq', room_id))
        if start_time is not None:
            criteria.append(('start_time', 'eq', start_time))
        if end_time is not None:
            criteria.append(('end_time', 'eq', end_time))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise LookupError(f"Reservation delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None

    def get_reservations_by_customer_id(self, customer_id: int = None) -> list[models.Reservation]:
        """Lists the Reservation records belonging to one Customer. [mechanical contained-name filter]"""
        criteria = []
        if customer_id is not None:
            criteria.append(('customer_id', 'eq', customer_id))
        found = self._store.select(self.ENTITY, criteria)
        return _model_list([models.Reservation(**row) for row in found], models.Reservation)

    def read_all(self, customer_id: int = None, room_id: int = None, start_time: Any = None, end_time: Any = None) -> list[models.Reservation]:
        """Lists every Reservation; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if customer_id is not None:
            criteria.append(('customer_id', 'eq', customer_id))
        if room_id is not None:
            criteria.append(('room_id', 'eq', room_id))
        if start_time is not None:
            criteria.append(('start_time', 'eq', start_time))
        if end_time is not None:
            criteria.append(('end_time', 'eq', end_time))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Reservation(**r) for r in found]

    def read_one(self, reservation_id: int = None) -> models.Reservation:
        """Reads one Reservation by its key. [crud:read_one: READ_ONE_BY_ID]"""
        found = self._store.select(self.ENTITY, [(self.PK, 'eq', reservation_id)])
        if not found:
            return None
        record = found[0]
        return models.Reservation(**record)

    def update(self, reservation_id: int = None, customer_id: int = None, room_id: int = None, start_time: Any = None, end_time: Any = None) -> models.Reservation:
        """Updates an existing Reservation. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if reservation_id is not None:
            criteria.append(('reservation_id', 'eq', reservation_id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise LookupError(f"Reservation update matched {len(found)} records")
        patch = {}
        if reservation_id is not None and 'reservation_id' in ['reservation_id', 'customer_id', 'room_id', 'start_time', 'end_time']:
            patch['reservation_id'] = reservation_id
        if customer_id is not None and 'customer_id' in ['reservation_id', 'customer_id', 'room_id', 'start_time', 'end_time']:
            patch['customer_id'] = customer_id
        if room_id is not None and 'room_id' in ['reservation_id', 'customer_id', 'room_id', 'start_time', 'end_time']:
            patch['room_id'] = room_id
        if start_time is not None and 'start_time' in ['reservation_id', 'customer_id', 'room_id', 'start_time', 'end_time']:
            patch['start_time'] = start_time
        if end_time is not None and 'end_time' in ['reservation_id', 'customer_id', 'room_id', 'start_time', 'end_time']:
            patch['end_time'] = end_time
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=LookupError)
        return models.Reservation(**record)


class RoomRepository:
    ENTITY = "Room"
    PK = "room_id"

    def __init__(self, store):
        self._store = store


    def create(self, room_number: str = None, capacity: int = None) -> models.Room:
        """Creates a new Room. [crud:create: STANDARD_CRUD]"""
        values = {}
        if room_number is not None:
            values['room_number'] = room_number
        if capacity is not None:
            values['capacity'] = capacity
        unknown = [k for k in values if k not in ['room_id', 'room_number', 'capacity']]
        if unknown:
            raise ValueError(f"cannot create Room from {unknown}")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[])
        return models.Room(**record)

    def read_all(self, room_number: str = None, capacity: int = None) -> list[models.Room]:
        """Lists every Room; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if room_number is not None:
            criteria.append(('room_number', 'eq', room_number))
        if capacity is not None:
            criteria.append(('capacity', 'eq', capacity))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Room(**r) for r in found]

    def read_one(self, room_id: int = None) -> models.Room:
        """Reads one Room by its key. [crud:read_one: READ_ONE_BY_ID]"""
        record = self._store.get(self.ENTITY, self.PK, room_id, error=errors.RoomNotFoundError)
        return models.Room(**record)
