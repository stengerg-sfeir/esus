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

    def read_one(self, customer_id: int = None) -> Any:
        """Reads one Customer by its key. [crud:read_one: READ_ONE_BY_ID]"""
        record = self._store.get(self.ENTITY, self.PK, customer_id, error=errors.CustomerNotFoundError)
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

    def delete(self, customer_id: int = None, name: str = None, email: str = None) -> None:
        """Deletes an existing Customer. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if customer_id is not None:
            criteria.append(('customer_id', 'eq', customer_id))
        if name is not None:
            criteria.append(('name', 'eq', name))
        if email is not None:
            criteria.append(('email', 'eq', email))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise errors.CustomerNotFoundError(f"Customer delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None


class RoomRepository:
    ENTITY = "Room"
    PK = "room_id"

    def __init__(self, store):
        self._store = store


    def create(self, room_number: str = None, capacity: int = None) -> Any:
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

    def read_one(self, room_id: int = None) -> Any:
        """Reads one Room by its key. [crud:read_one: READ_ONE_BY_ID]"""
        record = self._store.get(self.ENTITY, self.PK, room_id, error=errors.RoomNotFoundError)
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

    def update(self, room_id: int = None, room_number: str = None, capacity: int = None) -> Any:
        """Updates an existing Room. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if room_id is not None:
            criteria.append(('room_id', 'eq', room_id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise errors.RoomNotFoundError(f"Room update matched {len(found)} records")
        patch = {}
        if room_id is not None and 'room_id' in ['room_id', 'room_number', 'capacity']:
            patch['room_id'] = room_id
        if room_number is not None and 'room_number' in ['room_id', 'room_number', 'capacity']:
            patch['room_number'] = room_number
        if capacity is not None and 'capacity' in ['room_id', 'room_number', 'capacity']:
            patch['capacity'] = capacity
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=errors.RoomNotFoundError)
        return models.Room(**record)

    def delete(self, room_id: int = None, room_number: str = None, capacity: int = None) -> None:
        """Deletes an existing Room. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if room_id is not None:
            criteria.append(('room_id', 'eq', room_id))
        if room_number is not None:
            criteria.append(('room_number', 'eq', room_number))
        if capacity is not None:
            criteria.append(('capacity', 'eq', capacity))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise errors.RoomNotFoundError(f"Room delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None


class ReservationRepository:
    ENTITY = "Reservation"
    PK = "reservation_id"

    def __init__(self, store):
        self._store = store


    def create(self, customer_id: int = None, room_id: int = None, start_date: Any = None, end_date: Any = None) -> Any:
        """Creates a new Reservation. [crud:create: STANDARD_CRUD]"""
        values = {}
        if customer_id is not None:
            values['customer_id'] = customer_id
        if room_id is not None:
            values['room_id'] = room_id
        if start_date is not None:
            values['start_date'] = start_date
        if end_date is not None:
            values['end_date'] = end_date
        unknown = [k for k in values if k not in ['reservation_id', 'customer_id', 'room_id', 'start_date', 'end_date']]
        if unknown:
            raise ValueError(f"cannot create Reservation from {unknown}")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[("customer_id", "Customer", "customer_id", errors.CustomerNotFoundError), ("room_id", "Room", "room_id", errors.RoomNotFoundError)])
        return models.Reservation(**record)

    def read_one(self, reservation_id: int = None) -> Any:
        """Reads one Reservation by its key. [crud:read_one: READ_ONE_BY_ID]"""
        record = self._store.get(self.ENTITY, self.PK, reservation_id, error=errors.ReservationNotFoundError)
        return models.Reservation(**record)

    def read_all(self, customer_id: int = None, room_id: int = None, start_date: Any = None, end_date: Any = None) -> list[models.Reservation]:
        """Lists every Reservation; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if customer_id is not None:
            criteria.append(('customer_id', 'eq', customer_id))
        if room_id is not None:
            criteria.append(('room_id', 'eq', room_id))
        if start_date is not None:
            criteria.append(('start_date', 'eq', start_date))
        if end_date is not None:
            criteria.append(('end_date', 'eq', end_date))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Reservation(**r) for r in found]

    def update(self, reservation_id: int = None, customer_id: int = None, room_id: int = None, start_date: Any = None, end_date: Any = None) -> Any:
        """Updates an existing Reservation. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if reservation_id is not None:
            criteria.append(('reservation_id', 'eq', reservation_id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise errors.ReservationNotFoundError(f"Reservation update matched {len(found)} records")
        patch = {}
        if reservation_id is not None and 'reservation_id' in ['reservation_id', 'customer_id', 'room_id', 'start_date', 'end_date']:
            patch['reservation_id'] = reservation_id
        if customer_id is not None and 'customer_id' in ['reservation_id', 'customer_id', 'room_id', 'start_date', 'end_date']:
            patch['customer_id'] = customer_id
        if room_id is not None and 'room_id' in ['reservation_id', 'customer_id', 'room_id', 'start_date', 'end_date']:
            patch['room_id'] = room_id
        if start_date is not None and 'start_date' in ['reservation_id', 'customer_id', 'room_id', 'start_date', 'end_date']:
            patch['start_date'] = start_date
        if end_date is not None and 'end_date' in ['reservation_id', 'customer_id', 'room_id', 'start_date', 'end_date']:
            patch['end_date'] = end_date
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=errors.ReservationNotFoundError)
        return models.Reservation(**record)

    def delete(self, reservation_id: int = None, customer_id: int = None, room_id: int = None, start_date: Any = None, end_date: Any = None) -> None:
        """Deletes an existing Reservation. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if reservation_id is not None:
            criteria.append(('reservation_id', 'eq', reservation_id))
        if customer_id is not None:
            criteria.append(('customer_id', 'eq', customer_id))
        if room_id is not None:
            criteria.append(('room_id', 'eq', room_id))
        if start_date is not None:
            criteria.append(('start_date', 'eq', start_date))
        if end_date is not None:
            criteria.append(('end_date', 'eq', end_date))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise errors.ReservationNotFoundError(f"Reservation delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None

    def get_reservations_by_customer_id(self, customer_id: int = None) -> list[models.Reservation]:
        """Lists the Reservation records belonging to one Customer. [crud:filter: FILTER_BY_FIELD: by parameter shape]"""
        criteria = []
        if customer_id is not None:
            criteria.append(('customer_id', 'eq', customer_id))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Reservation(**r) for r in found]
