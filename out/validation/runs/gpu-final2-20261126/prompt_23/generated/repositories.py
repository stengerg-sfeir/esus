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



class AuthorRepository:
    ENTITY = "Author"
    PK = "author_id"

    def __init__(self, store):
        self._store = store


    def create(self, name: str = None, email: str = None) -> Any:
        """Creates a new Author. [crud:create: STANDARD_CRUD]"""
        values = {}
        if name is not None:
            values['name'] = name
        if email is not None:
            values['email'] = email
        unknown = [k for k in values if k not in ['author_id', 'name', 'email']]
        if unknown:
            raise ValueError(f"cannot create Author from {unknown}")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[])
        return models.Author(**record)

    def read_one(self, author_id: int = None) -> Any:
        """Reads one Author by its key. [crud:read_one: READ_ONE_BY_ID]"""
        found = self._store.select(self.ENTITY, [(self.PK, 'eq', author_id)])
        if not found:
            return None
        record = found[0]
        return models.Author(**record)

    def read_all(self, name: str = None, email: str = None) -> list[models.Author]:
        """Lists every Author; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if name is not None:
            criteria.append(('name', 'eq', name))
        if email is not None:
            criteria.append(('email', 'eq', email))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Author(**r) for r in found]

    def update(self, author_id: int = None, name: str = None, email: str = None) -> Any:
        """Updates an existing Author. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if author_id is not None:
            criteria.append(('author_id', 'eq', author_id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise LookupError(f"Author update matched {len(found)} records")
        patch = {}
        if author_id is not None and 'author_id' in ['author_id', 'name', 'email']:
            patch['author_id'] = author_id
        if name is not None and 'name' in ['author_id', 'name', 'email']:
            patch['name'] = name
        if email is not None and 'email' in ['author_id', 'name', 'email']:
            patch['email'] = email
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=LookupError)
        return models.Author(**record)

    def delete(self, author_id: int = None, name: str = None, email: str = None) -> None:
        """Deletes an existing Author. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if author_id is not None:
            criteria.append(('author_id', 'eq', author_id))
        if name is not None:
            criteria.append(('name', 'eq', name))
        if email is not None:
            criteria.append(('email', 'eq', email))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise LookupError(f"Author delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None


class PostRepository:
    ENTITY = "Post"
    PK = "post_id"

    def __init__(self, store):
        self._store = store


    def create(self, title: str = None, content: str = None, author_id: int = None) -> Any:
        """Creates a new Post. [crud:create: STANDARD_CRUD]"""
        values = {}
        if title is not None:
            values['title'] = title
        if content is not None:
            values['content'] = content
        if author_id is not None:
            values['author_id'] = author_id
        unknown = [k for k in values if k not in ['post_id', 'title', 'content', 'author_id']]
        if unknown:
            raise ValueError(f"cannot create Post from {unknown}")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[("author_id", "Author", "author_id", None)])
        return models.Post(**record)

    def read_one(self, post_id: int = None) -> Any:
        """Reads one Post by its key. [crud:read_one: READ_ONE_BY_ID]"""
        found = self._store.select(self.ENTITY, [(self.PK, 'eq', post_id)])
        if not found:
            return None
        record = found[0]
        return models.Post(**record)

    def read_all(self, title: str = None, content: str = None, author_id: int = None) -> list[models.Post]:
        """Lists every Post; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if title is not None:
            criteria.append(('title', 'eq', title))
        if content is not None:
            criteria.append(('content', 'eq', content))
        if author_id is not None:
            criteria.append(('author_id', 'eq', author_id))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Post(**r) for r in found]

    def update(self, post_id: int = None, title: str = None, content: str = None, author_id: int = None) -> Any:
        """Updates an existing Post. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if post_id is not None:
            criteria.append(('post_id', 'eq', post_id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise LookupError(f"Post update matched {len(found)} records")
        patch = {}
        if post_id is not None and 'post_id' in ['post_id', 'title', 'content', 'author_id']:
            patch['post_id'] = post_id
        if title is not None and 'title' in ['post_id', 'title', 'content', 'author_id']:
            patch['title'] = title
        if content is not None and 'content' in ['post_id', 'title', 'content', 'author_id']:
            patch['content'] = content
        if author_id is not None and 'author_id' in ['post_id', 'title', 'content', 'author_id']:
            patch['author_id'] = author_id
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=LookupError)
        return models.Post(**record)

    def delete(self, post_id: int = None, title: str = None, content: str = None, author_id: int = None) -> None:
        """Deletes an existing Post. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if post_id is not None:
            criteria.append(('post_id', 'eq', post_id))
        if title is not None:
            criteria.append(('title', 'eq', title))
        if content is not None:
            criteria.append(('content', 'eq', content))
        if author_id is not None:
            criteria.append(('author_id', 'eq', author_id))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise LookupError(f"Post delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None

    def get_posts_by_author_id(self, author_id: int = None) -> list[models.Post]:
        """Lists the Post records belonging to one Author. [crud:filter: FILTER_BY_FIELD: by parameter shape]"""
        criteria = []
        if author_id is not None:
            criteria.append(('author_id', 'eq', author_id))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Post(**r) for r in found]


class TagRepository:
    ENTITY = "Tag"
    PK = "tag_id"

    def __init__(self, store):
        self._store = store


    def create(self, name: str = None) -> Any:
        """Creates a new Tag. [crud:create: STANDARD_CRUD]"""
        values = {}
        if name is not None:
            values['name'] = name
        unknown = [k for k in values if k not in ['tag_id', 'name']]
        if unknown:
            raise ValueError(f"cannot create Tag from {unknown}")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[])
        return models.Tag(**record)

    def read_one(self, tag_id: int = None) -> Any:
        """Reads one Tag by its key. [crud:read_one: READ_ONE_BY_ID]"""
        found = self._store.select(self.ENTITY, [(self.PK, 'eq', tag_id)])
        if not found:
            return None
        record = found[0]
        return models.Tag(**record)

    def read_all(self, name: str = None) -> list[models.Tag]:
        """Lists every Tag; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if name is not None:
            criteria.append(('name', 'eq', name))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Tag(**r) for r in found]

    def update(self, tag_id: int = None, name: str = None) -> Any:
        """Updates an existing Tag. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if tag_id is not None:
            criteria.append(('tag_id', 'eq', tag_id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise LookupError(f"Tag update matched {len(found)} records")
        patch = {}
        if tag_id is not None and 'tag_id' in ['tag_id', 'name']:
            patch['tag_id'] = tag_id
        if name is not None and 'name' in ['tag_id', 'name']:
            patch['name'] = name
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=LookupError)
        return models.Tag(**record)

    def delete(self, tag_id: int = None, name: str = None) -> None:
        """Deletes an existing Tag. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if tag_id is not None:
            criteria.append(('tag_id', 'eq', tag_id))
        if name is not None:
            criteria.append(('name', 'eq', name))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise LookupError(f"Tag delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None


class PostTagRepository:
    ENTITY = "PostTag"
    PK = "post_id"

    def __init__(self, store):
        self._store = store


    def create(self, tag_id: int = None) -> Any:
        """Creates a new PostTag. [crud:create: STANDARD_CRUD]"""
        values = {}
        if tag_id is not None:
            values['tag_id'] = tag_id
        unknown = [k for k in values if k not in ['post_id', 'tag_id']]
        if unknown:
            raise ValueError(f"cannot create PostTag from {unknown}")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[("tag_id", "Tag", "tag_id", None)])
        return models.PostTag(**record)

    def read_one(self, post_id: int = None) -> Any:
        """Reads one PostTag by its key. [crud:read_one: READ_ONE_BY_ID]"""
        found = self._store.select(self.ENTITY, [(self.PK, 'eq', post_id)])
        if not found:
            return None
        record = found[0]
        return models.PostTag(**record)

    def read_all(self, tag_id: int = None) -> list[models.PostTag]:
        """Lists every PostTag; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if tag_id is not None:
            criteria.append(('tag_id', 'eq', tag_id))
        found = self._store.select(self.ENTITY, criteria)
        return [models.PostTag(**r) for r in found]

    def get_post_tags_by_tag_id(self, tag_id: int = None) -> list[models.PostTag]:
        """Lists the PostTag records belonging to one Tag. [crud:filter: FILTER_BY_FIELD: by parameter shape]"""
        criteria = []
        if tag_id is not None:
            criteria.append(('tag_id', 'eq', tag_id))
        found = self._store.select(self.ENTITY, criteria)
        return [models.PostTag(**r) for r in found]
