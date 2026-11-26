"""Data models. The store assigns integer primary keys on insert,
and updates merge only non-None values. Explicit application defaults
from the requirements are preserved on the dataclasses."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import datetime
from typing import Any, Dict, List, Literal, Optional



@dataclass
class Client:
    id: int = None
    name: str = None
    email: str = None
    phone: Optional[str] = None
    account_status: str = None


@dataclass
class Invoice:
    id: int = None
    client_id: int = None
    due_date: datetime.date = None
    amount: Decimal = None
    description: Optional[str] = None
    status: str = None


@dataclass
class Payment:
    id: int = None
    invoice_id: int = None
    payment_date: datetime.date = None
    amount: Decimal = None
    payment_method: str = None
