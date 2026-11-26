"""Data models. The store assigns integer primary keys on insert,
and updates merge only non-None values. Explicit application defaults
from the requirements are preserved on the dataclasses."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import datetime
from typing import Any, Dict, List, Literal, Optional



@dataclass
class Customer:
    customer_id: int = None
    email: str = None
    name: str = None


@dataclass
class Purchase:
    purchase_id: int = None
    customer_id: int = None
    amount: Decimal = None
    purchase_date: datetime.datetime = None
