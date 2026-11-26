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
class Room:
    room_id: int = None
    room_number: str = None
    capacity: int = None


@dataclass
class Reservation:
    reservation_id: int = None
    customer_id: int = None
    room_id: int = None
    start_time: datetime.datetime = None
    end_time: datetime.datetime = None
