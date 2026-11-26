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



class SalesReportService:

    def __init__(self, repos):
        self._repos = repos


    def generate_product_sales_report(self) -> Dict[str, Any]:
        """Generates a report showing the total sales amount and number of sales per product. [llm-written by server — review]"""
        product_sales = self._repos['SaleRepository'].get_sales_by_product_id()
        report = {}
        for sale in product_sales:
            product_id = sale.product_id
            if product_id not in report:
                report[product_id] = {'total_sales_amount': 0, 'number_of_sales': 0}
            sale_amount = sale.quantity * self._repos['ProductRepository'].read_product_by_id(product_id).price
            report[product_id]['total_sales_amount'] += sale_amount
            report[product_id]['number_of_sales'] += 1
        return report
