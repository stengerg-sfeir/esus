"""Data models. Every field defaults to None: the store assigns integer
primary keys on insert, and updates merge only non-None values."""

from dataclasses import dataclass
from decimal import Decimal
import datetime
from typing import Any, Dict, List, Optional



@dataclass
class Wine:
    wine_id: int = None
    name: str = None
    vintage_year: int = None
    wine_type: str = None
    country_of_origin: str = None
    cost_price: Decimal = None
    selling_price: Decimal = None
    stock_quantity: int = None
    primary_location_id: int = None


@dataclass
class StorageLocation:
    location_id: int = None
    zone_name: str = None
    row_number: int = None
    shelf_number: int = None
    max_bottle_capacity: int = None
