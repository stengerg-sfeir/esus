"""Data models. The store assigns integer primary keys on insert,
and updates merge only non-None values. Explicit application defaults
from the requirements are preserved on the dataclasses."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import datetime
from typing import Any, Dict, List, Literal, Optional



@dataclass
class Product:
    product_id: int = None
    name: str = None
    price: Decimal = None
    stock_quantity: int = None


@dataclass
class Customer:
    customer_id: int = None
    name: str = None
    email: str = None
    phone: Optional[str] = None


@dataclass
class Sale:
    sale_id: int = None
    customer_id: int = None
    product_id: int = None
    quantity: int = None
    sale_date: datetime.datetime = None
