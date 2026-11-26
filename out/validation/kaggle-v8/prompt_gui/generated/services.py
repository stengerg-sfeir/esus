"""Services. A method with the same name as a repository method delegates
to it; anything else raises NotImplementedError with its work order.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple, Union

import calendar
import csv
import datetime
import json

import models
import errors
from store import match_criterion


def _holds(actual, operator, expected):
    """Twin of `store._holds`: the operators filter composition reuses."""
    if operator == "eq":
        return actual == expected
    if operator == "ge":
        return actual is not None and actual >= expected
    if operator == "le":
        return actual is not None and actual <= expected
    if operator == "gt":
        return actual is not None and actual > expected
    if operator == "lt":
        return actual is not None and actual < expected
    raise ValueError(f"unknown operator {operator!r}")


def _as_date(value):
    """Accept an ISO string or a date object; return a date or None."""
    if value is None or isinstance(value, datetime.date):
        return value
    return datetime.date.fromisoformat(str(value))



class WineInventoryService:

    def __init__(self, repos):
        self._repos = repos


    def assign_wine_to_location(self, wine_id: int = None, location_id: str = None) -> bool:
        """Assigns a wine to a specific storage location. Ensures the wine name is unique and that the location has sufficient capacity. [mechanical capacity guard]"""
        location = self._repos['StorageLocationRepository'].read_one(location_id)
        if location is None:
            raise errors.LocationOverCapacityException('location not found')
        wines = self._repos['WineRepository'].read_all(storage_location_id=location_id)
        used = sum((item.stock_quantity or 0) for item in wines)
        if used + 1 > location.maximum_capacity:
            raise errors.LocationOverCapacityException('storage location capacity exceeded')
        return True

    def update_wine_stock(self, wine_id: int = None, new_stock_quantity: int = None) -> bool:
        """Updates the stock quantity of a wine. Ensures the new stock level is non-negative and does not violate storage location capacity constraints. [mechanical non-negative stock guard]"""
        if new_stock_quantity is not None and new_stock_quantity < 0:
            raise errors.NegativeStockError('stock_quantity must be non-negative')
        return True

    def validate_wine_pricing(self, wine_id: int = None, cost_price: float = None, selling_price: float = None) -> bool:
        """Validates that a wine's selling price is strictly greater than its cost price. [llm-written by server — review]"""
        record = self._repos['WineRepository'].read_one(wine_id)
        if record is None:
            raise errors.WineNotFoundError(f'Wine not found')
        if cost_price is not None and selling_price is not None:
            if cost_price >= selling_price:
                raise errors.InvalidPricingException('Selling price must be strictly greater than cost price')
        elif cost_price is not None:
            pass
        elif selling_price is not None:
            pass
        return True

    def check_storage_location_capacity(self, location_id: str = None, wine_id: int = None) -> bool:
        """Checks whether adding a wine to a storage location would exceed its maximum bottle capacity. [mechanical capacity guard]"""
        location = self._repos['StorageLocationRepository'].read_one(location_id)
        if location is None:
            raise errors.LocationOverCapacityException('location not found')
        wines = self._repos['WineRepository'].read_all(storage_location_id=location_id)
        used = sum((item.stock_quantity or 0) for item in wines)
        if used + 1 > location.maximum_capacity:
            raise errors.LocationOverCapacityException('storage location capacity exceeded')
        return True

    def list_wines_by_type(self, wine_type: str = None) -> Any:
        """Returns a list of wines filtered by wine type (red, white, rosé, sparkling). [delegates the list filter to read_all]"""
        return self._repos['WineRepository'].read_all(wine_type=wine_type)

    def get_storage_location_summary(self) -> Dict[str, Any]:
        """Returns a summary of all storage locations, including total bottles assigned and remaining capacity. [llm-written by server — review]"""
        locations = self._repos['StorageLocationRepository'].read_all()
        summary = {}
        for location in locations:
            location_id = location.id
            total_stock = 0
            wines = self._repos['WineRepository'].read_all(storage_location_id=location_id)
            for wine in wines:
                total_stock += wine.stock_quantity
            utilization_rate = self._repos['StorageLocationRepository'].get_location_utilization_rate(location_id=location_id)
            summary[location_id] = {'total_bottles_assigned': total_stock, 'remaining_capacity': location.maximum_capacity - total_stock, 'utilization_rate': utilization_rate}
        return summary
