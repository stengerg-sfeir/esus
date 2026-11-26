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


def _filter_value(value):
    """Dates compare as ISO text, the form the store keeps."""
    return value.isoformat() if hasattr(value, "isoformat") else value



class PurchaseHistoryService:

    def __init__(self, repos):
        self._repos = repos


    def get_customer_purchase_history(self, customer_id: int = None) -> list[models.Purchase]:
        """Retrieves the purchase history for a specific customer, including total spending amount. [llm-written by server — review]"""
        purchases = self._repos['PurchaseRepository'].get_purchases_by_customer_id(customer_id)
        return purchases


class SpendingAnalysisService:

    def __init__(self, repos):
        self._repos = repos


    def calculate_total_spent_by_customer(self, customer_id: int = None) -> float:
        """Calculates the total amount spent by a customer across all their purchases. [llm-written by server — review]"""
        purchases = self._repos['PurchaseRepository'].get_purchases_by_customer_id(customer_id)
        total_spent = sum((purchase.amount for purchase in purchases))
        return total_spent


class PurchaseValidationService:

    def __init__(self, repos):
        self._repos = repos


    def validate_purchase_amount(self, purchase_id: int = None) -> bool:
        """Validates that a purchase amount is present and non-negative. [llm-written by server — review]"""
        purchase = self._repos['PurchaseRepository'].read_one(purchase_id=purchase_id)
        if not purchase or purchase.amount is None:
            return False
        return purchase.amount >= 0


class CustomerDataService:

    def __init__(self, repos):
        self._repos = repos


    def customerreport(self, customer_id: int = None) -> None:
        """Customerreport. [llm-written by server — review]"""
        purchases = self._repos['PurchaseRepository'].get_purchases_by_customer_id(customer_id)
        total_spent = sum((purchase.amount for purchase in purchases))
        total_purchases = len(purchases)
        average_spent = total_spent / total_purchases if total_purchases > 0 else 0
        print(f'Customer ID: {customer_id}')
        print(f'Total spent: {total_spent}')
        print(f'Total purchases: {total_purchases}')
        print(f'Average spent: {average_spent}')


class PurchaseHistorySearchService:

    def __init__(self, repos):
        self._repos = repos


    def search_purchases_by_customer_and_date_range(self, customer_id: int = None, start_date: datetime.datetime = None, end_date: datetime.datetime = None) -> list[models.Purchase]:
        """Searches for purchases made by a customer within a specified date range. [composes PurchaseRepository.read_all over signature-pagination]"""
        records = self._repos['PurchaseRepository'].read_all()
        criteria = []
        if customer_id is not None:
            criteria.append(('customer_id', 'eq', customer_id))
        if start_date is not None:
            criteria.append(('purchase_date', 'ge', start_date))
        if end_date is not None:
            criteria.append(('purchase_date', 'le', end_date))
        out = []
        for record in records:
            row = record if isinstance(record, dict) else vars(record)
            if all(_holds(_filter_value(row.get(field)), operator,
                          _filter_value(value))
                   for field, operator, value in criteria):
                out.append(record)
        return out

    def purchasesearch(self, customer_id: int = None, start_date: str = None, end_date: str = None) -> list[models.Purchase]:
        """Purchasesearch. [composes PurchaseRepository.read_all over name-only: step F never saw this method; by parameter shape]"""
        records = self._repos['PurchaseRepository'].read_all()
        criteria = []
        if customer_id is not None:
            criteria.append(('customer_id', 'eq', customer_id))
        if start_date is not None:
            criteria.append(('purchase_date', 'ge', start_date))
        if end_date is not None:
            criteria.append(('purchase_date', 'le', end_date))
        out = []
        for record in records:
            row = record if isinstance(record, dict) else vars(record)
            if all(_holds(_filter_value(row.get(field)), operator,
                          _filter_value(value))
                   for field, operator, value in criteria):
                out.append(record)
        return out
