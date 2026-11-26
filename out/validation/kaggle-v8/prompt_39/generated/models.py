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
    user_id: int = None
    email: str = None
    password_hash: str = None
    role: str = None


@dataclass
class Product:
    product_id: int = None
    name: str = None
    price: Decimal = None
    description: Optional[str] = None


@dataclass
class Order:
    order_id: int = None
    user_id: int = None
    order_date: datetime.datetime = None
    status: str = None
