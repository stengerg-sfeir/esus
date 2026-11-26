"""Data models. The store assigns integer primary keys on insert,
and updates merge only non-None values. Explicit application defaults
from the requirements are preserved on the dataclasses."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import datetime
from typing import Any, Dict, List, Literal, Optional



@dataclass
class User:
    id: int = None
    password_hash: str = None
    email: str = None
    created_at: datetime.datetime = None


@dataclass
class Document:
    id: int = None
    title: str = None
    content: str = None
    created_at: datetime.datetime = None
    updated_at: datetime.datetime = None
    owner_user_id: int = None
