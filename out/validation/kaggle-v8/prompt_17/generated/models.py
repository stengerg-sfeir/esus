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
    id: int = None
    name: str = None
    category: str = None
    price: Decimal = None
    quantity: int = None


@dataclass
class User:
    id: int = None
    username: str = None
    email: str = None
