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
    name: str = None
    email: str = None


@dataclass
class Order:
    order_id: int = None
    customer_id: int = None
    items: str = None
    status: str = None
    created_at: datetime.datetime = None
