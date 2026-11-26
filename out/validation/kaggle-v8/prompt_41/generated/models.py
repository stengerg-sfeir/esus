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
    availability_status: bool = None


@dataclass
class Member:
    member_id: int = None
    name: str = None
    contact_details: str = None
    membership_status: bool = None


@dataclass
class Loan:
    loan_id: int = None
    member_id: int = None
    book_id: int = None
    loan_date: datetime.datetime = None
    return_date: Optional[datetime.date] = None
