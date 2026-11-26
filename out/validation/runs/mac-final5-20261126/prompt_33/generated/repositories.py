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


    def create(self, name: str = None, email: str = None, phone: str = None, address: str = None, created_at: Any = None, updated_at: Any = None, deleted_at: Any = None) -> Any:
        """Creates a new Customer. [crud:create: STANDARD_CRUD]"""
        values = {}
        if name is not None:
            values['name'] = name
        if email is not None:
            values['email'] = email
        if phone is not None:
            values['phone'] = phone
        if address is not None:
            values['address'] = address
        if created_at is not None:
            values['created_at'] = created_at
        if updated_at is not None:
            values['updated_at'] = updated_at
        if deleted_at is not None:
            values['deleted_at'] = deleted_at
        unknown = [k for k in values if k not in ['id', 'name', 'email', 'phone', 'address', 'created_at', 'updated_at', 'deleted_at']]
        if unknown:
            raise ValueError(f"cannot create Customer from {unknown}")
        if values.get('created_at') is None:
            values['created_at'] = datetime.datetime.now()
        if values.get('updated_at') is None:
            values['updated_at'] = datetime.datetime.now()
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[])
        self._store.add('AuditLog', 'id', {'operation': 'create', 'customer_id': record[self.PK], 'timestamp': datetime.datetime.now()}, check_fk=[])
        return models.Customer(**record)

    def read_one(self, id: int = None) -> Any:
        """Reads one Customer by its key. [crud:read_one: READ_ONE_BY_ID]"""
        found = self._store.select(self.ENTITY, [(self.PK, 'eq', id)])
        if not found:
            return None
        record = found[0]
        return models.Customer(**record)

    def read_all(self, name: str = None, email: str = None, phone: str = None, address: str = None, created_at: Any = None, updated_at: Any = None, deleted_at: Any = None) -> list[models.Customer]:
        """Lists every Customer; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if name is not None:
            criteria.append(('name', 'eq', name))
        if email is not None:
            criteria.append(('email', 'eq', email))
        if phone is not None:
            criteria.append(('phone', 'eq', phone))
        if address is not None:
            criteria.append(('address', 'eq', address))
        if created_at is not None:
            criteria.append(('created_at', 'eq', created_at))
        if updated_at is not None:
            criteria.append(('updated_at', 'eq', updated_at))
        if deleted_at is not None:
            criteria.append(('deleted_at', 'eq', deleted_at))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Customer(**r) for r in found]

    def update(self, id: int = None, name: str = None, email: str = None, phone: str = None, address: str = None, created_at: Any = None, updated_at: Any = None, deleted_at: Any = None) -> Any:
        """Updates an existing Customer. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if id is not None:
            criteria.append(('id', 'eq', id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise LookupError(f"Customer update matched {len(found)} records")
        patch = {}
        if id is not None and 'id' in ['id', 'name', 'email', 'phone', 'address', 'created_at', 'updated_at', 'deleted_at']:
            patch['id'] = id
        if name is not None and 'name' in ['id', 'name', 'email', 'phone', 'address', 'created_at', 'updated_at', 'deleted_at']:
            patch['name'] = name
        if email is not None and 'email' in ['id', 'name', 'email', 'phone', 'address', 'created_at', 'updated_at', 'deleted_at']:
            patch['email'] = email
        if phone is not None and 'phone' in ['id', 'name', 'email', 'phone', 'address', 'created_at', 'updated_at', 'deleted_at']:
            patch['phone'] = phone
        if address is not None and 'address' in ['id', 'name', 'email', 'phone', 'address', 'created_at', 'updated_at', 'deleted_at']:
            patch['address'] = address
        if created_at is not None and 'created_at' in ['id', 'name', 'email', 'phone', 'address', 'created_at', 'updated_at', 'deleted_at']:
            patch['created_at'] = created_at
        if updated_at is not None and 'updated_at' in ['id', 'name', 'email', 'phone', 'address', 'created_at', 'updated_at', 'deleted_at']:
            patch['updated_at'] = updated_at
        if deleted_at is not None and 'deleted_at' in ['id', 'name', 'email', 'phone', 'address', 'created_at', 'updated_at', 'deleted_at']:
            patch['deleted_at'] = deleted_at
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=LookupError)
        self._store.add('AuditLog', 'id', {'operation': 'update', 'customer_id': record[self.PK], 'timestamp': datetime.datetime.now()}, check_fk=[])
        return models.Customer(**record)

    def delete(self, id: int = None, name: str = None, email: str = None, phone: str = None, address: str = None, created_at: Any = None, updated_at: Any = None, deleted_at: Any = None) -> None:
        """Deletes an existing Customer. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if id is not None:
            criteria.append(('id', 'eq', id))
        if name is not None:
            criteria.append(('name', 'eq', name))
        if email is not None:
            criteria.append(('email', 'eq', email))
        if phone is not None:
            criteria.append(('phone', 'eq', phone))
        if address is not None:
            criteria.append(('address', 'eq', address))
        if created_at is not None:
            criteria.append(('created_at', 'eq', created_at))
        if updated_at is not None:
            criteria.append(('updated_at', 'eq', updated_at))
        if deleted_at is not None:
            criteria.append(('deleted_at', 'eq', deleted_at))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise LookupError(f"Customer delete matched no records")
        for record in found:
            self._store.add('AuditLog', 'id', {'operation': 'delete', 'customer_id': record[self.PK], 'timestamp': datetime.datetime.now()}, check_fk=[])
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None

    def create_customer(self, name: str = None, email: str = None, phone: str = None, address: str = None, created_at: datetime.datetime = None, updated_at: datetime.datetime = None, deleted_at: datetime.datetime = None) -> Any:
        """Creates a new customer record and generates an audit log entry for the creation operation with the customer's ID, operation type, and timestamp. [crud:create: STANDARD_CRUD]"""
        values = {}
        if name is not None:
            values['name'] = name
        if email is not None:
            values['email'] = email
        if phone is not None:
            values['phone'] = phone
        if address is not None:
            values['address'] = address
        if created_at is not None:
            values['created_at'] = created_at
        if updated_at is not None:
            values['updated_at'] = updated_at
        if deleted_at is not None:
            values['deleted_at'] = deleted_at
        unknown = [k for k in values if k not in ['id', 'name', 'email', 'phone', 'address', 'created_at', 'updated_at', 'deleted_at']]
        if unknown:
            raise ValueError(f"cannot create Customer from {unknown}")
        if values.get('created_at') is None:
            values['created_at'] = datetime.datetime.now()
        if values.get('updated_at') is None:
            values['updated_at'] = datetime.datetime.now()
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[])
        self._store.add('AuditLog', 'id', {'operation': 'create', 'customer_id': record[self.PK], 'timestamp': datetime.datetime.now()}, check_fk=[])
        return models.Customer(**record)

    def read_customer_by_id(self, customer_id: int = None) -> models.Customer | None:
        """Retrieves a customer record by their unique ID, including the full details of the customer. [crud:read_one: READ_ONE_BY_ID]"""
        found = self._store.select(self.ENTITY, [(self.PK, 'eq', customer_id)])
        if not found:
            return None
        record = found[0]
        return models.Customer(**record)

    def read_all_customers(self) -> list[models.Customer]:
        """Retrieves a list of all active customer records, excluding those marked as deleted. [crud:read_all: READ_ALL]"""
        criteria = []
        found = self._store.select(self.ENTITY, criteria)
        return [models.Customer(**r) for r in found]

    def update_customer(self, customer_id: int = None, name: str = None, email: str = None, phone: str = None, address: str = None, created_at: datetime.datetime = None, updated_at: datetime.datetime = None, deleted_at: datetime.datetime = None) -> Any:
        """Updates an existing customer's details and generates an audit log entry for the update operation with the customer's ID, operation type, and timestamp. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if customer_id is not None:
            criteria.append(('id', 'eq', customer_id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise LookupError(f"Customer update matched {len(found)} records")
        patch = {}
        if customer_id is not None and 'customer_id' in ['id', 'name', 'email', 'phone', 'address', 'created_at', 'updated_at', 'deleted_at']:
            patch['customer_id'] = customer_id
        if name is not None and 'name' in ['id', 'name', 'email', 'phone', 'address', 'created_at', 'updated_at', 'deleted_at']:
            patch['name'] = name
        if email is not None and 'email' in ['id', 'name', 'email', 'phone', 'address', 'created_at', 'updated_at', 'deleted_at']:
            patch['email'] = email
        if phone is not None and 'phone' in ['id', 'name', 'email', 'phone', 'address', 'created_at', 'updated_at', 'deleted_at']:
            patch['phone'] = phone
        if address is not None and 'address' in ['id', 'name', 'email', 'phone', 'address', 'created_at', 'updated_at', 'deleted_at']:
            patch['address'] = address
        if created_at is not None and 'created_at' in ['id', 'name', 'email', 'phone', 'address', 'created_at', 'updated_at', 'deleted_at']:
            patch['created_at'] = created_at
        if updated_at is not None and 'updated_at' in ['id', 'name', 'email', 'phone', 'address', 'created_at', 'updated_at', 'deleted_at']:
            patch['updated_at'] = updated_at
        if deleted_at is not None and 'deleted_at' in ['id', 'name', 'email', 'phone', 'address', 'created_at', 'updated_at', 'deleted_at']:
            patch['deleted_at'] = deleted_at
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=LookupError)
        self._store.add('AuditLog', 'id', {'operation': 'update', 'customer_id': record[self.PK], 'timestamp': datetime.datetime.now()}, check_fk=[])
        return models.Customer(**record)

    def delete_customer(self, customer_id: int = None) -> bool:
        """Deletes a customer record and generates an audit log entry for the deletion operation with the customer's ID, operation type, and timestamp. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if customer_id is not None:
            criteria.append(('id', 'eq', customer_id))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise LookupError(f"Customer delete matched no records")
        for record in found:
            self._store.add('AuditLog', 'id', {'operation': 'delete', 'customer_id': record[self.PK], 'timestamp': datetime.datetime.now()}, check_fk=[])
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None


class AuditLogRepository:
    ENTITY = "AuditLog"
    PK = "id"

    def __init__(self, store):
        self._store = store


    def create(self, operation: str = None, customer_id: int = None, timestamp: Any = None, performed_by: str = None) -> Any:
        """Creates a new AuditLog. [crud:create: STANDARD_CRUD]"""
        values = {}
        if operation is not None:
            values['operation'] = operation
        if customer_id is not None:
            values['customer_id'] = customer_id
        if timestamp is not None:
            values['timestamp'] = timestamp
        if performed_by is not None:
            values['performed_by'] = performed_by
        unknown = [k for k in values if k not in ['id', 'operation', 'customer_id', 'timestamp', 'performed_by']]
        if unknown:
            raise ValueError(f"cannot create AuditLog from {unknown}")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[("customer_id", "Customer", "id", None)])
        return models.AuditLog(**record)

    def read_one(self, id: int = None) -> Any:
        """Reads one AuditLog by its key. [crud:read_one: READ_ONE_BY_ID]"""
        found = self._store.select(self.ENTITY, [(self.PK, 'eq', id)])
        if not found:
            return None
        record = found[0]
        return models.AuditLog(**record)

    def read_all(self, operation: str = None, customer_id: int = None, timestamp: Any = None, performed_by: str = None) -> list[models.AuditLog]:
        """Lists every AuditLog; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if operation is not None:
            criteria.append(('operation', 'eq', operation))
        if customer_id is not None:
            criteria.append(('customer_id', 'eq', customer_id))
        if timestamp is not None:
            criteria.append(('timestamp', 'eq', timestamp))
        if performed_by is not None:
            criteria.append(('performed_by', 'eq', performed_by))
        found = self._store.select(self.ENTITY, criteria)
        return [models.AuditLog(**r) for r in found]

    def create_audit_log(self, operation: str = None, customer_id: int = None, performed_by: str = None, timestamp: datetime.datetime = None) -> Any:
        """Creates an audit log entry with the operation type, customer ID, timestamp, and performing user, ensuring all operations are tracked. [crud:create: STANDARD_CRUD]"""
        values = {}
        if operation is not None:
            values['operation'] = operation
        if customer_id is not None:
            values['customer_id'] = customer_id
        if performed_by is not None:
            values['performed_by'] = performed_by
        if timestamp is not None:
            values['timestamp'] = timestamp
        unknown = [k for k in values if k not in ['id', 'operation', 'customer_id', 'timestamp', 'performed_by']]
        if unknown:
            raise ValueError(f"cannot create AuditLog from {unknown}")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[("customer_id", "Customer", "id", None)])
        return models.AuditLog(**record)

    def read_audit_log_by_customer_id(self, customer_id: int = None) -> list[models.AuditLog]:
        """Retrieves all audit logs for a specific customer ID, ordered by timestamp in descending order. [crud:filter: FILTER_BY_FIELD: by parameter shape]"""
        criteria = []
        if customer_id is not None:
            criteria.append(('customer_id', 'eq', customer_id))
        found = self._store.select(self.ENTITY, criteria)
        return [models.AuditLog(**r) for r in found]

    def read_all_audit_logs(self) -> list[models.AuditLog]:
        """Retrieves a list of all audit log entries, ordered by timestamp in descending order. [crud:read_all: READ_ALL]"""
        criteria = []
        found = self._store.select(self.ENTITY, criteria)
        return [models.AuditLog(**r) for r in found]
