"""Data models. The store assigns integer primary keys on insert,
and updates merge only non-None values. Explicit application defaults
from the requirements are preserved on the dataclasses."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import datetime
from typing import Any, Dict, List, Literal, Optional



@dataclass
class Budget:
    id: int = None
    category_id: int = None
    month: str = None
    amount_limit_cents: int = None


@dataclass
class Category:
    id: int = None
    name: str = None
    description: Optional[str] = None
    monthly_budget: Optional[int] = None
    icon: Optional[str] = None


@dataclass
class Expense:
    id: int = None
    amount_cents: int = None
    description: Optional[str] = None
    expense_date: datetime.date = None
    category_id: int = None
    payment_method: str = None
    is_recurring: bool = None
