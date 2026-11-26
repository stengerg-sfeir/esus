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



class RoomRepository:
    ENTITY = "Room"
    PK = "id"

    def __init__(self, store):
        self._store = store


    def create(self, room_number: str = None, availability_status: bool = None) -> Any:
        """Creates a new Room. [crud:create: STANDARD_CRUD]"""
        values = {}
        if room_number is not None:
            values['room_number'] = room_number
        if availability_status is not None:
            values['availability_status'] = availability_status
        unknown = [k for k in values if k not in ['id', 'room_number', 'availability_status']]
        if unknown:
            raise ValueError(f"cannot create Room from {unknown}")
        if values.get('availability_status') is None:
            values['availability_status'] = False
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[])
        return models.Room(**record)

    def read_all(self, room_number: str = None, availability_status: bool = None) -> list[models.Room]:
        """Lists every Room; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if room_number is not None:
            criteria.append(('room_number', 'eq', room_number))
        if availability_status is not None:
            criteria.append(('availability_status', 'eq', availability_status))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Room(**r) for r in found]

    def read_one(self, id: int = None) -> Any:
        """Reads one Room by its key. [crud:read_one: READ_ONE_BY_ID]"""
        record = self._store.get(self.ENTITY, self.PK, id, error=errors.RoomNotFoundError)
        return models.Room(**record)

    def update(self, id: int = None, room_number: str = None, availability_status: bool = None) -> Any:
        """Updates an existing Room. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if id is not None:
            criteria.append(('id', 'eq', id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise errors.RoomNotFoundError(f"Room update matched {len(found)} records")
        patch = {}
        if id is not None and 'id' in ['id', 'room_number', 'availability_status']:
            patch['id'] = id
        if room_number is not None and 'room_number' in ['id', 'room_number', 'availability_status']:
            patch['room_number'] = room_number
        if availability_status is not None and 'availability_status' in ['id', 'room_number', 'availability_status']:
            patch['availability_status'] = availability_status
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=errors.RoomNotFoundError)
        return models.Room(**record)

    def delete(self, id: int = None, room_number: str = None, availability_status: bool = None) -> None:
        """Deletes an existing Room. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if id is not None:
            criteria.append(('id', 'eq', id))
        if room_number is not None:
            criteria.append(('room_number', 'eq', room_number))
        if availability_status is not None:
            criteria.append(('availability_status', 'eq', availability_status))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise errors.RoomNotFoundError(f"Room delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None


class GuestRepository:
    ENTITY = "Guest"
    PK = "id"

    def __init__(self, store):
        self._store = store


    def create(self, first_name: str = None, last_name: str = None, email: str = None, phone_number: str = None) -> Any:
        """Creates a new Guest. [crud:create: STANDARD_CRUD]"""
        values = {}
        if first_name is not None:
            values['first_name'] = first_name
        if last_name is not None:
            values['last_name'] = last_name
        if email is not None:
            values['email'] = email
        if phone_number is not None:
            values['phone_number'] = phone_number
        unknown = [k for k in values if k not in ['id', 'first_name', 'last_name', 'email', 'phone_number']]
        if unknown:
            raise ValueError(f"cannot create Guest from {unknown}")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[])
        return models.Guest(**record)

    def read_all(self, first_name: str = None, last_name: str = None, email: str = None, phone_number: str = None) -> list[models.Guest]:
        """Lists every Guest; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if first_name is not None:
            criteria.append(('first_name', 'eq', first_name))
        if last_name is not None:
            criteria.append(('last_name', 'eq', last_name))
        if email is not None:
            criteria.append(('email', 'eq', email))
        if phone_number is not None:
            criteria.append(('phone_number', 'eq', phone_number))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Guest(**r) for r in found]

    def read_one(self, id: int = None) -> Any:
        """Reads one Guest by its key. [crud:read_one: READ_ONE_BY_ID]"""
        record = self._store.get(self.ENTITY, self.PK, id, error=errors.GuestNotFoundError)
        return models.Guest(**record)

    def update(self, id: int = None, first_name: str = None, last_name: str = None, email: str = None, phone_number: str = None) -> Any:
        """Updates an existing Guest. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if id is not None:
            criteria.append(('id', 'eq', id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise errors.GuestNotFoundError(f"Guest update matched {len(found)} records")
        patch = {}
        if id is not None and 'id' in ['id', 'first_name', 'last_name', 'email', 'phone_number']:
            patch['id'] = id
        if first_name is not None and 'first_name' in ['id', 'first_name', 'last_name', 'email', 'phone_number']:
            patch['first_name'] = first_name
        if last_name is not None and 'last_name' in ['id', 'first_name', 'last_name', 'email', 'phone_number']:
            patch['last_name'] = last_name
        if email is not None and 'email' in ['id', 'first_name', 'last_name', 'email', 'phone_number']:
            patch['email'] = email
        if phone_number is not None and 'phone_number' in ['id', 'first_name', 'last_name', 'email', 'phone_number']:
            patch['phone_number'] = phone_number
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=errors.GuestNotFoundError)
        return models.Guest(**record)

    def delete(self, id: int = None, first_name: str = None, last_name: str = None, email: str = None, phone_number: str = None) -> None:
        """Deletes an existing Guest. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if id is not None:
            criteria.append(('id', 'eq', id))
        if first_name is not None:
            criteria.append(('first_name', 'eq', first_name))
        if last_name is not None:
            criteria.append(('last_name', 'eq', last_name))
        if email is not None:
            criteria.append(('email', 'eq', email))
        if phone_number is not None:
            criteria.append(('phone_number', 'eq', phone_number))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise errors.GuestNotFoundError(f"Guest delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None


class BookingRepository:
    ENTITY = "Booking"
    PK = "id"

    def __init__(self, store):
        self._store = store


    def create(self, room_id: int = None, guest_id: int = None, check_in_date: Any = None, check_out_date: Any = None, booking_status: str = None) -> Any:
        """Creates a new Booking. [crud:create: STANDARD_CRUD]"""
        values = {}
        if room_id is not None:
            values['room_id'] = room_id
        if guest_id is not None:
            values['guest_id'] = guest_id
        if check_in_date is not None:
            values['check_in_date'] = check_in_date
        if check_out_date is not None:
            values['check_out_date'] = check_out_date
        if booking_status is not None:
            values['booking_status'] = booking_status
        unknown = [k for k in values if k not in ['id', 'room_id', 'guest_id', 'check_in_date', 'check_out_date', 'booking_status']]
        if unknown:
            raise ValueError(f"cannot create Booking from {unknown}")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[("room_id", "Room", "id", errors.RoomNotFoundError), ("guest_id", "Guest", "id", errors.GuestNotFoundError)])
        return models.Booking(**record)

    def read_all(self, room_id: int = None, guest_id: int = None, check_in_date: Any = None, check_out_date: Any = None, booking_status: str = None) -> list[models.Booking]:
        """Lists every Booking; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if room_id is not None:
            criteria.append(('room_id', 'eq', room_id))
        if guest_id is not None:
            criteria.append(('guest_id', 'eq', guest_id))
        if check_in_date is not None:
            criteria.append(('check_in_date', 'eq', check_in_date))
        if check_out_date is not None:
            criteria.append(('check_out_date', 'eq', check_out_date))
        if booking_status is not None:
            criteria.append(('booking_status', 'eq', booking_status))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Booking(**r) for r in found]

    def read_one(self, id: int = None) -> Any:
        """Reads one Booking by its key. [crud:read_one: READ_ONE_BY_ID]"""
        record = self._store.get(self.ENTITY, self.PK, id, error=errors.BookingNotFoundError)
        return models.Booking(**record)

    def update(self, id: int = None, room_id: int = None, guest_id: int = None, check_in_date: Any = None, check_out_date: Any = None, booking_status: str = None) -> Any:
        """Updates an existing Booking. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if id is not None:
            criteria.append(('id', 'eq', id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise errors.BookingNotFoundError(f"Booking update matched {len(found)} records")
        patch = {}
        if id is not None and 'id' in ['id', 'room_id', 'guest_id', 'check_in_date', 'check_out_date', 'booking_status']:
            patch['id'] = id
        if room_id is not None and 'room_id' in ['id', 'room_id', 'guest_id', 'check_in_date', 'check_out_date', 'booking_status']:
            patch['room_id'] = room_id
        if guest_id is not None and 'guest_id' in ['id', 'room_id', 'guest_id', 'check_in_date', 'check_out_date', 'booking_status']:
            patch['guest_id'] = guest_id
        if check_in_date is not None and 'check_in_date' in ['id', 'room_id', 'guest_id', 'check_in_date', 'check_out_date', 'booking_status']:
            patch['check_in_date'] = check_in_date
        if check_out_date is not None and 'check_out_date' in ['id', 'room_id', 'guest_id', 'check_in_date', 'check_out_date', 'booking_status']:
            patch['check_out_date'] = check_out_date
        if booking_status is not None and 'booking_status' in ['id', 'room_id', 'guest_id', 'check_in_date', 'check_out_date', 'booking_status']:
            patch['booking_status'] = booking_status
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=errors.BookingNotFoundError)
        return models.Booking(**record)

    def delete(self, id: int = None, room_id: int = None, guest_id: int = None, check_in_date: Any = None, check_out_date: Any = None, booking_status: str = None) -> None:
        """Deletes an existing Booking. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if id is not None:
            criteria.append(('id', 'eq', id))
        if room_id is not None:
            criteria.append(('room_id', 'eq', room_id))
        if guest_id is not None:
            criteria.append(('guest_id', 'eq', guest_id))
        if check_in_date is not None:
            criteria.append(('check_in_date', 'eq', check_in_date))
        if check_out_date is not None:
            criteria.append(('check_out_date', 'eq', check_out_date))
        if booking_status is not None:
            criteria.append(('booking_status', 'eq', booking_status))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise errors.BookingNotFoundError(f"Booking delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None

    def findBookingsByRoomAndDateRange(self, roomId: int = None, checkInDate: datetime.datetime = None, checkOutDate: datetime.datetime = None) -> list[models.Booking]:
        """Checks for existing bookings in a room during a specified date range to prevent double booking. [crud:filter: FILTER_BY_FIELD]"""
        criteria = []
        if roomId is not None:
            criteria.append(('room_id', 'eq', roomId))
        if checkInDate is not None:
            criteria.append(('check_in_date', 'eq', checkInDate))
        if checkOutDate is not None:
            criteria.append(('check_out_date', 'eq', checkOutDate))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Booking(**r) for r in found]

    def findOverlappingBookings(self, roomId: int = None, checkInDate: datetime.datetime = None, checkOutDate: datetime.datetime = None) -> list[models.Booking]:
        """Identifies all bookings that overlap with a proposed new booking in terms of date and room, helping to validate booking conflicts. [crud:filter: FILTER_BY_FIELD]"""
        criteria = []
        if roomId is not None:
            criteria.append(('room_id', 'eq', roomId))
        if checkInDate is not None:
            criteria.append(('check_in_date', 'eq', checkInDate))
        if checkOutDate is not None:
            criteria.append(('check_out_date', 'eq', checkOutDate))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Booking(**r) for r in found]
