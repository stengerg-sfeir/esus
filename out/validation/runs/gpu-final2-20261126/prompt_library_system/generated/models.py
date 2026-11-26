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
    isbn: str = None
    published_year: int = None
    available_copies: int = 1
    author_id: int = None


@dataclass
class Author:
    id: int = None
    name: str = None
    birth_year: int = None
    biography: Optional[str] = None


@dataclass
class Member:
    id: int = None
    name: str = None
    email: str = None
    membership_date: datetime.date = None
    is_active: bool = True


@dataclass
class Loan:
    id: int = None
    book_id: int = None
    member_id: int = None
    loan_date: datetime.date = None
    due_date: datetime.date = None
    return_date: Optional[datetime.date] = None
    status: str = None
