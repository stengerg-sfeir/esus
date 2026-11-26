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
    room_id: int = None
    room_number: str = None
    room_type: str = None
    price_per_night: Decimal = None


@dataclass
class Guest:
    guest_id: int = None
    first_name: str = None
    last_name: str = None
    email: str = None
    phone_number: Optional[str] = None


@dataclass
class Booking:
    booking_id: int = None
    guest_id: int = None
    room_id: int = None
    check_in_date: datetime.date = None
    check_out_date: datetime.date = None
    status: str = None
