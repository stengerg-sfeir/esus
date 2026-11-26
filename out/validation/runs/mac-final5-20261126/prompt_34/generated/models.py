"""Data models. The store assigns integer primary keys on insert,
and updates merge only non-None values. Explicit application defaults
from the requirements are preserved on the dataclasses."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import datetime
from typing import Any, Dict, List, Literal, Optional



@dataclass
class Order:
    order_id: int = None
    created_at: datetime.datetime = None
    updated_at: datetime.datetime = None
    status: str = None


@dataclass
class OrderLine:
    order_line_id: int = None
    order_id: int = None
    product_id: str = None
    quantity: int = None
    unit_price: Decimal = None
    total_price: Decimal = None
    is_valid: bool = None
