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
class Product:
    product_id: int = None
    name: str = None
    category_id: int = None
    price: Decimal = None
    stock_quantity: int = None


@dataclass
class Category:
    category_id: int = None
    name: str = None


@dataclass
class Order:
    order_id: int = None
    customer_id: int = None
    status: str = None
    created_at: datetime.datetime = None
    confirmed_at: Optional[datetime.datetime] = None
    shipped_at: Optional[datetime.datetime] = None
    cancelled_at: Optional[datetime.datetime] = None


@dataclass
class OrderItem:
    order_item_id: int = None
    order_id: int = None
    product_id: int = None
    quantity: int = None


@dataclass
class Invoice:
    invoice_id: int = None
    order_id: int = None
    total_amount: Decimal = None
    generated_at: datetime.datetime = None
