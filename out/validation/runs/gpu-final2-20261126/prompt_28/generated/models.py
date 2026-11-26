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
    id: int = None
    name: str = None
    email: str = None


@dataclass
class Product:
    id: int = None
    name: str = None
    price: Decimal = None


@dataclass
class Invoice:
    id: int = None
    customer_id: int = None
    issue_date: datetime.date = None
    total_amount: Decimal = None


@dataclass
class InvoiceLine:
    line_id: int = None
    invoice_id: int = None
    product_id: int = None
    quantity: int = None
