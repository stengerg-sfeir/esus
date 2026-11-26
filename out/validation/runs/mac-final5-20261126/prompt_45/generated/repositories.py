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
    PK = "room_id"

    def __init__(self, store):
        self._store = store


    def create(self, room_number: str = None, room_type: str = None, price_per_night: int = None) -> Any:
        """Creates a new Room. [crud:create: STANDARD_CRUD]"""
        values = {}
        if room_number is not None:
            values['room_number'] = room_number
        if room_type is not None:
            values['room_type'] = room_type
        if price_per_night is not None:
            values['price_per_night'] = price_per_night
        unknown = [k for k in values if k not in ['room_id', 'room_number', 'room_type', 'price_per_night']]
        if unknown:
            raise ValueError(f"cannot create Room from {unknown}")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[])
        return models.Room(**record)

    def read_all(self, room_number: str = None, room_type: str = None, price_per_night: int = None) -> list[models.Room]:
        """Lists every Room; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if room_number is not None:
            criteria.append(('room_number', 'eq', room_number))
        if room_type is not None:
            criteria.append(('room_type', 'eq', room_type))
        if price_per_night is not None:
            criteria.append(('price_per_night', 'eq', price_per_night))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Room(**r) for r in found]

    def update(self, room_id: int = None, room_number: str = None, room_type: str = None, price_per_night: int = None) -> Any:
        """Updates an existing Room. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if room_id is not None:
            criteria.append(('room_id', 'eq', room_id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise errors.RoomNotFoundError(f"Room update matched {len(found)} records")
        patch = {}
        if room_id is not None and 'room_id' in ['room_id', 'room_number', 'room_type', 'price_per_night']:
            patch['room_id'] = room_id
        if room_number is not None and 'room_number' in ['room_id', 'room_number', 'room_type', 'price_per_night']:
            patch['room_number'] = room_number
        if room_type is not None and 'room_type' in ['room_id', 'room_number', 'room_type', 'price_per_night']:
            patch['room_type'] = room_type
        if price_per_night is not None and 'price_per_night' in ['room_id', 'room_number', 'room_type', 'price_per_night']:
            patch['price_per_night'] = price_per_night
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=errors.RoomNotFoundError)
        return models.Room(**record)

    def delete(self, room_id: int = None, room_number: str = None, room_type: str = None, price_per_night: int = None) -> None:
        """Deletes an existing Room. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if room_id is not None:
            criteria.append(('room_id', 'eq', room_id))
        if room_number is not None:
            criteria.append(('room_number', 'eq', room_number))
        if room_type is not None:
            criteria.append(('room_type', 'eq', room_type))
        if price_per_night is not None:
            criteria.append(('price_per_night', 'eq', price_per_night))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise errors.RoomNotFoundError(f"Room delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None

    def read_one(self, room_id: int = None) -> Any:
        """Reads one Room by its key. [crud:read_one: READ_ONE_BY_ID]"""
        record = self._store.get(self.ENTITY, self.PK, room_id, error=errors.RoomNotFoundError)
        return models.Room(**record)

    def read_one_by_room_number(self, room_number: str = None) -> Any:
        """Fetches a room by its room number, ensuring unique identification and avoiding duplicate bookings. [crud:read_one: READ_ONE_BY_ID]"""
        criteria = []
        if room_number is not None:
            criteria.append(('room_number', 'eq', room_number))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise errors.RoomNotFoundError(f"Room lookup matched {len(found)} records")
        record = found[0]
        return models.Room(**record)

    def read_all_available_rooms(self, check_in_date: datetime.date = None, check_out_date: datetime.date = None) -> list[models.Room]:
        """Returns all rooms that are not currently booked during the specified check-in and check-out dates, preventing double bookings. [llm-written by server — review]"""
        available_rooms = self._store.select(self.ENTITY, [])
        bookings = self._store.select(self.ENTITY, [])
        if check_in_date is not None and check_out_date is not None:
            bookings = self._store.select(self.ENTITY, [('check_in_date', 'ge', check_in_date), ('check_out_date', 'le', check_out_date)])
            if not bookings:
                return _model_list([models.Room(**r) for r in available_rooms], models.Room)
            for booking in bookings:
                check_in = booking.get('check_in_date')
                check_out = booking.get('check_out_date')
                if check_in is None or check_out is None:
                    continue
                check_in_str = str(check_in)[:10]
                check_out_str = str(check_out)[:10]
                for room in available_rooms:
                    if room.room_id == booking.get('room_id'):
                        if check_in_str <= str(check_out)[:10] and check_out_str >= str(check_in)[:10]:
                            available_rooms.remove(room)
                            break
        return _model_list(available_rooms, models.Room)


class GuestRepository:
    ENTITY = "Guest"
    PK = "guest_id"

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
        unknown = [k for k in values if k not in ['guest_id', 'first_name', 'last_name', 'email', 'phone_number']]
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

    def update(self, guest_id: int = None, first_name: str = None, last_name: str = None, email: str = None, phone_number: str = None) -> Any:
        """Updates an existing Guest. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if guest_id is not None:
            criteria.append(('guest_id', 'eq', guest_id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise errors.GuestNotFoundError(f"Guest update matched {len(found)} records")
        patch = {}
        if guest_id is not None and 'guest_id' in ['guest_id', 'first_name', 'last_name', 'email', 'phone_number']:
            patch['guest_id'] = guest_id
        if first_name is not None and 'first_name' in ['guest_id', 'first_name', 'last_name', 'email', 'phone_number']:
            patch['first_name'] = first_name
        if last_name is not None and 'last_name' in ['guest_id', 'first_name', 'last_name', 'email', 'phone_number']:
            patch['last_name'] = last_name
        if email is not None and 'email' in ['guest_id', 'first_name', 'last_name', 'email', 'phone_number']:
            patch['email'] = email
        if phone_number is not None and 'phone_number' in ['guest_id', 'first_name', 'last_name', 'email', 'phone_number']:
            patch['phone_number'] = phone_number
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=errors.GuestNotFoundError)
        return models.Guest(**record)

    def delete(self, guest_id: int = None, first_name: str = None, last_name: str = None, email: str = None, phone_number: str = None) -> None:
        """Deletes an existing Guest. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if guest_id is not None:
            criteria.append(('guest_id', 'eq', guest_id))
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

    def read_one(self, guest_id: int = None) -> Any:
        """Reads one Guest by its key. [crud:read_one: READ_ONE_BY_ID]"""
        record = self._store.get(self.ENTITY, self.PK, guest_id, error=errors.GuestNotFoundError)
        return models.Guest(**record)

    def read_one_by_email(self, email: str = None) -> Any:
        """Fetches a guest by their email address, enabling staff to verify or retrieve guest details without relying on full name or phone number. [crud:read_one: READ_ONE_BY_ID]"""
        criteria = []
        if email is not None:
            criteria.append(('email', 'eq', email))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise errors.GuestNotFoundError(f"Guest lookup matched {len(found)} records")
        record = found[0]
        return models.Guest(**record)


class BookingRepository:
    ENTITY = "Booking"
    PK = "booking_id"

    def __init__(self, store):
        self._store = store


    def create(self, guest_id: int = None, room_id: int = None, check_in_date: Any = None, check_out_date: Any = None, status: str = None) -> Any:
        """Creates a new Booking. [crud:create: STANDARD_CRUD]"""
        values = {}
        if guest_id is not None:
            values['guest_id'] = guest_id
        if room_id is not None:
            values['room_id'] = room_id
        if check_in_date is not None:
            values['check_in_date'] = check_in_date
        if check_out_date is not None:
            values['check_out_date'] = check_out_date
        if status is not None:
            values['status'] = status
        unknown = [k for k in values if k not in ['booking_id', 'guest_id', 'room_id', 'check_in_date', 'check_out_date', 'status']]
        if unknown:
            raise ValueError(f"cannot create Booking from {unknown}")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[("guest_id", "Guest", "guest_id", errors.GuestNotFoundError), ("room_id", "Room", "room_id", errors.RoomNotFoundError)])
        return models.Booking(**record)

    def read_all(self, guest_id: int = None, room_id: int = None, check_in_date: Any = None, check_out_date: Any = None, status: str = None) -> list[models.Booking]:
        """Lists every Booking; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if guest_id is not None:
            criteria.append(('guest_id', 'eq', guest_id))
        if room_id is not None:
            criteria.append(('room_id', 'eq', room_id))
        if check_in_date is not None:
            criteria.append(('check_in_date', 'eq', check_in_date))
        if check_out_date is not None:
            criteria.append(('check_out_date', 'eq', check_out_date))
        if status is not None:
            criteria.append(('status', 'eq', status))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Booking(**r) for r in found]

    def read_one(self, booking_id: int = None) -> Any:
        """Reads one Booking by its key. [crud:read_one: READ_ONE_BY_ID]"""
        record = self._store.get(self.ENTITY, self.PK, booking_id, error=errors.BookingNotFoundError)
        return models.Booking(**record)

    def update(self, booking_id: int = None, guest_id: int = None, room_id: int = None, check_in_date: Any = None, check_out_date: Any = None, status: str = None) -> Any:
        """Updates an existing Booking. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if booking_id is not None:
            criteria.append(('booking_id', 'eq', booking_id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise errors.BookingNotFoundError(f"Booking update matched {len(found)} records")
        patch = {}
        if booking_id is not None and 'booking_id' in ['booking_id', 'guest_id', 'room_id', 'check_in_date', 'check_out_date', 'status']:
            patch['booking_id'] = booking_id
        if guest_id is not None and 'guest_id' in ['booking_id', 'guest_id', 'room_id', 'check_in_date', 'check_out_date', 'status']:
            patch['guest_id'] = guest_id
        if room_id is not None and 'room_id' in ['booking_id', 'guest_id', 'room_id', 'check_in_date', 'check_out_date', 'status']:
            patch['room_id'] = room_id
        if check_in_date is not None and 'check_in_date' in ['booking_id', 'guest_id', 'room_id', 'check_in_date', 'check_out_date', 'status']:
            patch['check_in_date'] = check_in_date
        if check_out_date is not None and 'check_out_date' in ['booking_id', 'guest_id', 'room_id', 'check_in_date', 'check_out_date', 'status']:
            patch['check_out_date'] = check_out_date
        if status is not None and 'status' in ['booking_id', 'guest_id', 'room_id', 'check_in_date', 'check_out_date', 'status']:
            patch['status'] = status
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=errors.BookingNotFoundError)
        return models.Booking(**record)

    def delete(self, booking_id: int = None, guest_id: int = None, room_id: int = None, check_in_date: Any = None, check_out_date: Any = None, status: str = None) -> None:
        """Deletes an existing Booking. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if booking_id is not None:
            criteria.append(('booking_id', 'eq', booking_id))
        if guest_id is not None:
            criteria.append(('guest_id', 'eq', guest_id))
        if room_id is not None:
            criteria.append(('room_id', 'eq', room_id))
        if check_in_date is not None:
            criteria.append(('check_in_date', 'eq', check_in_date))
        if check_out_date is not None:
            criteria.append(('check_out_date', 'eq', check_out_date))
        if status is not None:
            criteria.append(('status', 'eq', status))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise errors.BookingNotFoundError(f"Booking delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None

    def get_bookings_by_guest_id(self, guest_id: int = None) -> list[models.Booking]:
        """Lists the Booking records belonging to one Guest. [crud:filter: FILTER_BY_FIELD: by parameter shape]"""
        criteria = []
        if guest_id is not None:
            criteria.append(('guest_id', 'eq', guest_id))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Booking(**r) for r in found]

    def read_one_by_booking_id(self, booking_id: int = None) -> Any:
        """Fetches a booking by its unique booking ID, allowing staff to view or modify existing bookings. [crud:read_one: READ_ONE_BY_ID]"""
        record = self._store.get(self.ENTITY, self.PK, booking_id, error=errors.BookingNotFoundError)
        return models.Booking(**record)

    def read_all_bookings_for_room_and_date_range(self, room_id: int = None, check_in_date: datetime.date = None, check_out_date: datetime.date = None) -> list[models.Booking]:
        """Returns all bookings for a specific room within a given date range, used to validate room availability before creating new bookings. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if room_id is not None:
            criteria.append(('room_id', 'eq', room_id))
        if check_in_date is not None:
            criteria.append(('check_in_date', 'eq', check_in_date))
        if check_out_date is not None:
            criteria.append(('check_out_date', 'eq', check_out_date))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Booking(**r) for r in found]

    def validate_booking_conflict(self, room_id: int = None, check_in_date: datetime.date = None, check_out_date: datetime.date = None) -> bool:
        """Checks whether a new booking overlaps with any existing booking for the same room during the specified dates, preventing double bookings. [llm-written by server — review]"""
        criteria = []
        if room_id is not None:
            criteria.append(('room_id', 'eq', room_id))
        if check_in_date is not None:
            criteria.append(('check_in_date', 'eq', check_in_date))
        if check_out_date is not None:
            criteria.append(('check_out_date', 'eq', check_out_date))
        existing_bookings = self._store.select(self.ENTITY, criteria)
        if not existing_bookings:
            return False
        for booking in existing_bookings:
            existing_check_in = booking.get('check_in_date')
            existing_check_out = booking.get('check_out_date')
            if existing_check_in is not None and existing_check_out is not None:
                existing_check_in_str = str(existing_check_in)[:10]
                existing_check_out_str = str(existing_check_out)[:10]
                current_check_in_str = str(check_in_date)[:10]
                current_check_out_str = str(check_out_date)[:10]
                # Check for overlap: if current check-in is before existing check-out and current check-out is after existing check-in
                if (current_check_in_str < existing_check_out_str and current_check_out_str > existing_check_in_str):
                    return True
        return False
