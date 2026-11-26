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



class UserRepository:
    ENTITY = "User"
    PK = "id"

    def __init__(self, store):
        self._store = store


    def create(self, password_hash: str = None, email: str = None, created_at: Any = None) -> Any:
        """Creates a new User. [crud:create: STANDARD_CRUD]"""
        values = {}
        if password_hash is not None:
            values['password_hash'] = password_hash
        if email is not None:
            values['email'] = email
        if created_at is not None:
            values['created_at'] = created_at
        unknown = [k for k in values if k not in ['id', 'password_hash', 'email', 'created_at']]
        if unknown:
            raise ValueError(f"cannot create User from {unknown}")
        if values.get('created_at') is None:
            values['created_at'] = datetime.datetime.now()
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[])
        return models.User(**record)

    def read_one(self, id: int = None) -> Any:
        """Reads one User by its key. [crud:read_one: READ_ONE_BY_ID]"""
        record = self._store.get(self.ENTITY, self.PK, id, error=errors.UserNotFoundError)
        return models.User(**record)

    def read_all(self, password_hash: str = None, email: str = None, created_at: Any = None) -> list[models.User]:
        """Lists every User; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if password_hash is not None:
            criteria.append(('password_hash', 'eq', password_hash))
        if email is not None:
            criteria.append(('email', 'eq', email))
        if created_at is not None:
            criteria.append(('created_at', 'eq', created_at))
        found = self._store.select(self.ENTITY, criteria)
        return [models.User(**r) for r in found]

    def find_user_by_email(self, email: str = None) -> models.User | None:
        """Retrieve a user by their email address, used during authentication. [crud:read_one: READ_ONE_BY_ID]"""
        criteria = []
        if email is not None:
            criteria.append(('email', 'eq', email))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise errors.UserNotFoundError(f"User lookup matched {len(found)} records")
        record = found[0]
        return models.User(**record)

    def find_user_by_id(self, user_id: int = None) -> models.User | None:
        """Retrieve a user by their unique identifier (ID), used for user-specific operations. [crud:read_one: READ_ONE_BY_ID]"""
        record = self._store.get(self.ENTITY, self.PK, user_id, error=errors.UserNotFoundError)
        return models.User(**record)


class DocumentRepository:
    ENTITY = "Document"
    PK = "id"

    def __init__(self, store):
        self._store = store


    def create(self, title: str = None, content: str = None, created_at: Any = None, updated_at: Any = None, owner_user_id: int = None) -> Any:
        """Creates a new Document. [crud:create: STANDARD_CRUD]"""
        values = {}
        if title is not None:
            values['title'] = title
        if content is not None:
            values['content'] = content
        if created_at is not None:
            values['created_at'] = created_at
        if updated_at is not None:
            values['updated_at'] = updated_at
        if owner_user_id is not None:
            values['owner_user_id'] = owner_user_id
        unknown = [k for k in values if k not in ['id', 'title', 'content', 'created_at', 'updated_at', 'owner_user_id']]
        if unknown:
            raise ValueError(f"cannot create Document from {unknown}")
        if values.get('created_at') is None:
            values['created_at'] = datetime.datetime.now()
        if values.get('updated_at') is None:
            values['updated_at'] = datetime.datetime.now()
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[("owner_user_id", "User", "id", errors.UserNotFoundError)])
        return models.Document(**record)

    def read_one(self, id: int = None) -> Any:
        """Reads one Document by its key. [crud:read_one: READ_ONE_BY_ID]"""
        record = self._store.get(self.ENTITY, self.PK, id, error=errors.DocumentNotFoundError)
        return models.Document(**record)

    def read_all(self, title: str = None, content: str = None, created_at: Any = None, updated_at: Any = None, owner_user_id: int = None) -> list[models.Document]:
        """Lists every Document; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if title is not None:
            criteria.append(('title', 'eq', title))
        if content is not None:
            criteria.append(('content', 'eq', content))
        if created_at is not None:
            criteria.append(('created_at', 'eq', created_at))
        if updated_at is not None:
            criteria.append(('updated_at', 'eq', updated_at))
        if owner_user_id is not None:
            criteria.append(('owner_user_id', 'eq', owner_user_id))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Document(**r) for r in found]

    def update(self, id: int = None, title: str = None, content: str = None, created_at: Any = None, updated_at: Any = None, owner_user_id: int = None) -> Any:
        """Updates an existing Document. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if id is not None:
            criteria.append(('id', 'eq', id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise errors.DocumentNotFoundError(f"Document update matched {len(found)} records")
        patch = {}
        if id is not None and 'id' in ['id', 'title', 'content', 'created_at', 'updated_at', 'owner_user_id']:
            patch['id'] = id
        if title is not None and 'title' in ['id', 'title', 'content', 'created_at', 'updated_at', 'owner_user_id']:
            patch['title'] = title
        if content is not None and 'content' in ['id', 'title', 'content', 'created_at', 'updated_at', 'owner_user_id']:
            patch['content'] = content
        if created_at is not None and 'created_at' in ['id', 'title', 'content', 'created_at', 'updated_at', 'owner_user_id']:
            patch['created_at'] = created_at
        if updated_at is not None and 'updated_at' in ['id', 'title', 'content', 'created_at', 'updated_at', 'owner_user_id']:
            patch['updated_at'] = updated_at
        if owner_user_id is not None and 'owner_user_id' in ['id', 'title', 'content', 'created_at', 'updated_at', 'owner_user_id']:
            patch['owner_user_id'] = owner_user_id
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=errors.DocumentNotFoundError)
        return models.Document(**record)

    def delete(self, id: int = None, title: str = None, content: str = None, created_at: Any = None, updated_at: Any = None, owner_user_id: int = None) -> None:
        """Deletes an existing Document. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if id is not None:
            criteria.append(('id', 'eq', id))
        if title is not None:
            criteria.append(('title', 'eq', title))
        if content is not None:
            criteria.append(('content', 'eq', content))
        if created_at is not None:
            criteria.append(('created_at', 'eq', created_at))
        if updated_at is not None:
            criteria.append(('updated_at', 'eq', updated_at))
        if owner_user_id is not None:
            criteria.append(('owner_user_id', 'eq', owner_user_id))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise errors.DocumentNotFoundError(f"Document delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None

    def find_document_by_owner_and_id(self, owner_user_id: int = None, document_id: int = None) -> models.Document | None:
        """Retrieve a document by its owner user ID and document ID, enforcing ownership checks. [crud:read_one: READ_ONE_BY_ID]"""
        criteria = []
        if owner_user_id is not None:
            criteria.append(('owner_user_id', 'eq', owner_user_id))
        if document_id is not None:
            criteria.append(('id', 'eq', document_id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise errors.DocumentNotFoundError(f"Document lookup matched {len(found)} records")
        record = found[0]
        return models.Document(**record)

    def find_document_by_id(self, document_id: int = None) -> models.Document | None:
        """Retrieve a document by its unique identifier, used for read operations with ownership validation. [crud:read_one: READ_ONE_BY_ID]"""
        record = self._store.get(self.ENTITY, self.PK, document_id, error=errors.DocumentNotFoundError)
        return models.Document(**record)

    def find_all_documents_by_owner(self, owner_user_id: int = None) -> list[models.Document]:
        """Retrieve all documents owned by a specific user, used to list user-accessible documents. [crud:filter: FILTER_BY_FIELD]"""
        criteria = []
        if owner_user_id is not None:
            criteria.append(('owner_user_id', 'eq', owner_user_id))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Document(**r) for r in found]

    def count_documents_by_owner(self, owner_user_id: int = None) -> int:
        """Count the total number of documents owned by a specific user, used for UI statistics. [llm-written by server — review]"""
        criteria = []
        if owner_user_id is not None:
            criteria.append(('owner_user_id', 'eq', owner_user_id))
        found = self._store.select(self.ENTITY, criteria)
        return len(found)
