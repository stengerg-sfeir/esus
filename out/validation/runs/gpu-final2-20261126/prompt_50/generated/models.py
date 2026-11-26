"""Data models. The store assigns integer primary keys on insert,
and updates merge only non-None values. Explicit application defaults
from the requirements are preserved on the dataclasses."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import datetime
from typing import Any, Dict, List, Literal, Optional



@dataclass
class Event:
    event_id: int = None
    title: str = None
    date: datetime.datetime = None
    capacity: int = None
    current_registration_count: int = None


@dataclass
class Registration:
    registration_id: int = None
    event_id: int = None
    user_id: int = None
