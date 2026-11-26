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
    book_id: int = None
    title: str = None
    author: str = None
    genre: Optional[str] = None
    publication_date: Optional[datetime.date] = None
    isbn: Optional[str] = None


@dataclass
class User:
    user_id: int = None
    email: str = None
    name: str = None
