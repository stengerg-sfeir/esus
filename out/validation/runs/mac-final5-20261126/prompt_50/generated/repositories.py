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



class EventRepository:
    ENTITY = "Event"
    PK = "event_id"

    def __init__(self, store):
        self._store = store


    def create(self, title: str = None, date: Any = None, capacity: int = None, current_attendees_count: int = None) -> Any:
        """Creates a new Event. [crud:create: STANDARD_CRUD]"""
        values = {}
        if title is not None:
            values['title'] = title
        if date is not None:
            values['date'] = date
        if capacity is not None:
            values['capacity'] = capacity
        if current_attendees_count is not None:
            values['current_attendees_count'] = current_attendees_count
        unknown = [k for k in values if k not in ['event_id', 'title', 'date', 'capacity', 'current_attendees_count']]
        if unknown:
            raise ValueError(f"cannot create Event from {unknown}")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[])
        return models.Event(**record)

    def read_all(self, title: str = None, date: Any = None, capacity: int = None, current_attendees_count: int = None) -> list[models.Event]:
        """Lists every Event; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if title is not None:
            criteria.append(('title', 'eq', title))
        if date is not None:
            criteria.append(('date', 'eq', date))
        if capacity is not None:
            criteria.append(('capacity', 'eq', capacity))
        if current_attendees_count is not None:
            criteria.append(('current_attendees_count', 'eq', current_attendees_count))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Event(**r) for r in found]

    def read_one(self, event_id: int = None) -> Any:
        """Reads one Event by its key. [crud:read_one: READ_ONE_BY_ID]"""
        record = self._store.get(self.ENTITY, self.PK, event_id, error=errors.EventNotFoundError)
        return models.Event(**record)

    def update(self, event_id: int = None, title: str = None, date: Any = None, capacity: int = None, current_attendees_count: int = None) -> Any:
        """Updates an existing Event. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if event_id is not None:
            criteria.append(('event_id', 'eq', event_id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise errors.EventNotFoundError(f"Event update matched {len(found)} records")
        patch = {}
        if event_id is not None and 'event_id' in ['event_id', 'title', 'date', 'capacity', 'current_attendees_count']:
            patch['event_id'] = event_id
        if title is not None and 'title' in ['event_id', 'title', 'date', 'capacity', 'current_attendees_count']:
            patch['title'] = title
        if date is not None and 'date' in ['event_id', 'title', 'date', 'capacity', 'current_attendees_count']:
            patch['date'] = date
        if capacity is not None and 'capacity' in ['event_id', 'title', 'date', 'capacity', 'current_attendees_count']:
            patch['capacity'] = capacity
        if current_attendees_count is not None and 'current_attendees_count' in ['event_id', 'title', 'date', 'capacity', 'current_attendees_count']:
            patch['current_attendees_count'] = current_attendees_count
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=errors.EventNotFoundError)
        return models.Event(**record)

    def delete(self, event_id: int = None, title: str = None, date: Any = None, capacity: int = None, current_attendees_count: int = None) -> None:
        """Deletes an existing Event. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if event_id is not None:
            criteria.append(('event_id', 'eq', event_id))
        if title is not None:
            criteria.append(('title', 'eq', title))
        if date is not None:
            criteria.append(('date', 'eq', date))
        if capacity is not None:
            criteria.append(('capacity', 'eq', capacity))
        if current_attendees_count is not None:
            criteria.append(('current_attendees_count', 'eq', current_attendees_count))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise errors.EventNotFoundError(f"Event delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None

    def get_event_by_title(self, title: str = None) -> Any:
        """Fetches an event by its title, allowing users to search for events by name. [crud:read_one: READ_ONE_BY_ID]"""
        criteria = []
        if title is not None:
            criteria.append(('title', 'eq', title))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise errors.EventNotFoundError(f"Event lookup matched {len(found)} records")
        record = found[0]
        return models.Event(**record)

    def get_event_with_registration_count(self, event_id: int = None) -> Any:
        """Returns an event with the current number of registrations, useful for checking if an event is full. [crud:read_one: READ_ONE_BY_ID]"""
        record = self._store.get(self.ENTITY, self.PK, event_id, error=errors.EventNotFoundError)
        return models.Event(**record)


class RegistrationRepository:
    ENTITY = "Registration"
    PK = "registration_id"

    def __init__(self, store):
        self._store = store


    def create(self, event_id: int = None, user_id: int = None) -> Any:
        """Creates a new Registration. [crud:create: STANDARD_CRUD]"""
        values = {}
        if event_id is not None:
            values['event_id'] = event_id
        if user_id is not None:
            values['user_id'] = user_id
        unknown = [k for k in values if k not in ['registration_id', 'event_id', 'user_id']]
        if unknown:
            raise ValueError(f"cannot create Registration from {unknown}")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[("event_id", "Event", "event_id", errors.EventNotFoundError), ("user_id", "User", "user_id", errors.UserNotFoundError)])
        return models.Registration(**record)

    def read_all(self, event_id: int = None, user_id: int = None) -> list[models.Registration]:
        """Lists every Registration; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if event_id is not None:
            criteria.append(('event_id', 'eq', event_id))
        if user_id is not None:
            criteria.append(('user_id', 'eq', user_id))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Registration(**r) for r in found]

    def read_one(self, registration_id: int = None) -> Any:
        """Reads one Registration by its key. [crud:read_one: READ_ONE_BY_ID]"""
        record = self._store.get(self.ENTITY, self.PK, registration_id, error=errors.RegistrationNotFoundError)
        return models.Registration(**record)

    def get_registrations_by_event_id(self, event_id: int = None) -> list[models.Registration]:
        """Lists the Registration records belonging to one Event. [crud:filter: FILTER_BY_FIELD: by parameter shape]"""
        criteria = []
        if event_id is not None:
            criteria.append(('event_id', 'eq', event_id))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Registration(**r) for r in found]

    def register_user_for_event(self, event_id: int = None, user_id: int = None) -> Any:
        """Registers a user for an event, only if the event has available capacity. [crud:create: STANDARD_CRUD]"""
        values = {}
        if event_id is not None:
            values['event_id'] = event_id
        if user_id is not None:
            values['user_id'] = user_id
        unknown = [k for k in values if k not in ['registration_id', 'event_id', 'user_id']]
        if unknown:
            raise ValueError(f"cannot create Registration from {unknown}")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[("event_id", "Event", "event_id", errors.EventNotFoundError), ("user_id", "User", "user_id", errors.UserNotFoundError)])
        return models.Registration(**record)

    def check_registration_capacity(self, event_id: int = None) -> bool:
        """Checks whether a given event has remaining capacity for new registrations. [mechanical capacity check]"""
        event = self._store.get('Event', 'event_id', event_id)
        if event is None:
            return False
        used = len(self._store.select(self.ENTITY, [('event_id', 'eq', event_id)]))
        return used < (event.get('capacity') or 0)


class UserRepository:
    ENTITY = "User"
    PK = "user_id"

    def __init__(self, store):
        self._store = store


    def read_one(self, user_id: int = None) -> Any:
        """Reads one User by its key. [crud:read_one: READ_ONE_BY_ID]"""
        record = self._store.get(self.ENTITY, self.PK, user_id, error=errors.UserNotFoundError)
        return models.User(**record)

    def get_user_by_name(self, name: str = None) -> Any:
        """Fetches a user by their name, enabling user lookup during registration. [crud:read_one: READ_ONE_BY_ID]"""
        criteria = []
        if name is not None:
            criteria.append(('name', 'eq', name))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise errors.UserNotFoundError(f"User lookup matched {len(found)} records")
        record = found[0]
        return models.User(**record)
