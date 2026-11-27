"""Data models. The store assigns integer primary keys on insert,
and updates merge only non-None values. Explicit application defaults
from the requirements are preserved on the dataclasses."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import datetime
from typing import Any, Dict, List, Literal, Optional



@dataclass
class Author:
    author_id: int = None
    name: str = None
    email: str = None


@dataclass
class Post:
    post_id: int = None
    title: str = None
    content: str = None
    author_id: int = None


@dataclass
class Tag:
    tag_id: int = None
    name: str = None


@dataclass
class PostTag:
    post_tag_id: int = None
    post_id: int = None
    tag_id: int = None
