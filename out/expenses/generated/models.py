"""Data models. Every field defaults to None: the store assigns integer
primary keys on insert, and updates merge only non-None values."""

from dataclasses import dataclass
from decimal import Decimal
import datetime
from typing import Any, Dict, List, Optional



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
    expense_date: Optional[datetime.date] = None
    category_id: Optional[int] = None
    payment_method: Optional[str] = None
    is_recurring: bool = None


@dataclass
class Budget:
    id: int = None
    category_id: int = None
    month: datetime.date = None
    amount_limit_cents: int = None
