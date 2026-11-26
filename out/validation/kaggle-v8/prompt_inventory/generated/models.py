"""Data models. The store assigns integer primary keys on insert,
and updates merge only non-None values. Explicit application defaults
from the requirements are preserved on the dataclasses."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import datetime
from typing import Any, Dict, List, Literal, Optional



@dataclass
class Category:
    id: int = None
    name: str = None
    description: Optional[str] = None
    reorder_threshold: Optional[int] = None


@dataclass
class Product:
    id: int = None
    sku: str = None
    name: str = None
    category_id: int = None
    price_cents: int = None
    stock_qty: int = None
    low_active: Optional[bool] = None
