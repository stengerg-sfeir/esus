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
    available: bool = None


@dataclass
class Member:
    id: int = None
    name: str = None
    email: str = None


@dataclass
class Loan:
    id: int = None
    book_id: int = None
    member_id: int = None
    loan_date: datetime.datetime = None
    due_date: datetime.datetime = None
    closed: bool = None
