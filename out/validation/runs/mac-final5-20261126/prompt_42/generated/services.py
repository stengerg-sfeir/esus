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



class CustomerPurchaseService:

    def __init__(self, repos):
        self._repos = repos


    def get_customer_purchase_history(self, customer_id: int = None) -> list[models.Purchase]:
        """Retrieves the purchase history for a specific customer, including total spending amount. [llm-written by server — review]"""
        purchases = self._repos['PurchaseRepository'].read_all_by_customer_id(customer_id)
        return purchases

    def calculate_total_spent_by_customer(self, customer_id: int = None) -> float:
        """Calculates the total amount spent by a customer across all their purchases. [delegates to PurchaseRepository.calculate_total_spent_by_customer — pattern realized by target]"""
        return self._repos['PurchaseRepository'].calculate_total_spent_by_customer(customer_id)
