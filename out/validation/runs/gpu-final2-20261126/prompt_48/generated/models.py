"""Data models. The store assigns integer primary keys on insert,
and updates merge only non-None values. Explicit application defaults
from the requirements are preserved on the dataclasses."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import datetime
from typing import Any, Dict, List, Literal, Optional



@dataclass
class Book:
    id: int = None
    title: str = None
    author: str = None
    genre: Optional[str] = None
    isbn: Optional[str] = None
    publication_year: Optional[int] = None
    category: Optional[str] = None


@dataclass
class User:
    id: int = None
    email: str = None
    username: str = None
    created_at: datetime.datetime = None
