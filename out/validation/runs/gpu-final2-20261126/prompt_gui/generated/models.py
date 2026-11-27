"""Data models. The store assigns integer primary keys on insert,
and updates merge only non-None values. Explicit application defaults
from the requirements are preserved on the dataclasses."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import datetime
from typing import Any, Dict, List, Literal, Optional



@dataclass
class StorageLocation:
    id: int = None
    zone_name: str = None
    row_number: int = None
    shelf_number: int = None
    max_capacity: int = None


@dataclass
class Wine:
    id: int = None
    name: str = None
    vintage_year: int = None
    wine_type: str = None
    country_of_origin: str = None
    cost_price: Decimal = None
    selling_price: Decimal = None
    stock_quantity: int = None
    storage_location_id: int = None
