"""Data models. The store assigns integer primary keys on insert,
and updates merge only non-None values. Explicit application defaults
from the requirements are preserved on the dataclasses."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import datetime
from typing import Any, Dict, List, Literal, Optional



@dataclass
class Room:
    id: int = None
    room_number: str = None
    availability_status: bool = None


@dataclass
class Guest:
    id: int = None
    first_name: str = None
    last_name: str = None
    email: str = None
    phone_number: Optional[str] = None


@dataclass
class Booking:
    id: int = None
    room_id: int = None
    guest_id: int = None
    check_in_date: datetime.date = None
    check_out_date: datetime.date = None
    booking_status: str = None
