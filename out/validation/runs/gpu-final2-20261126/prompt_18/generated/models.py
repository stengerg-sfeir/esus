"""Data models. The store assigns integer primary keys on insert,
and updates merge only non-None values. Explicit application defaults
from the requirements are preserved on the dataclasses."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import datetime
from typing import Any, Dict, List, Literal, Optional



@dataclass
class Contact:
    id: int = None
    first_name: str = None
    last_name: str = None
    email: str = None
    phone: Optional[str] = None
    address: Optional[str] = None
    created_at: datetime.datetime = None
    updated_at: datetime.datetime = None
