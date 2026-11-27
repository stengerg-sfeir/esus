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



class OrderService:

    def __init__(self, repos):
        self._repos = repos


    def cancel_order(self, order_id: int = None) -> None:
        """Transitions an order from pending or confirmed to cancelled state. A cancelled order cannot be shipped. The order must be in pending or confirmed state; cannot cancel a shipped order. [closed contract: closed scalar contract]"""
        order = self._repos['OrderRepository'].read_one(order_id)
        if not (order.state in ('pending', 'confirmed')):
            raise errors.OrderStateException("order.state in ('pending', 'confirmed')")
        self._repos['OrderRepository'].update(order.id, state='cancelled')

    def confirm_order(self, order_id: int = None) -> None:
        """Transitions an order from pending to confirmed state. The order must be in pending state; cannot confirm a confirmed, shipped, or cancelled order. [closed contract: closed scalar contract]"""
        order = self._repos['OrderRepository'].read_one(order_id)
        if not (order.state == 'pending'):
            raise errors.OrderStateException("order.state == 'pending'")
        self._repos['OrderRepository'].update(order.id, state='confirmed')

    def read_order_by_id(self, id: int = None) -> models.Order | None:
        """Reads one Order by its key. [mechanical standard read]"""
        return self._repos['OrderRepository'].read_one(id)

    def ship_order(self, order_id: int = None) -> None:
        """Transitions an order from confirmed to shipped state. The order must be in confirmed state; cannot ship a pending, cancelled, or shipped order. [closed contract: closed scalar contract]"""
        order = self._repos['OrderRepository'].read_one(order_id)
        if not (order.state == 'confirmed'):
            raise errors.OrderStateException("order.state == 'confirmed'")
        self._repos['OrderRepository'].update(order.id, state='shipped')

    def update_order(self, id: int = None, state: str = None, created_at: Any = None, updated_at: Any = None) -> None:
        """Updates an existing Order. [mechanical CRUD wrapper]"""
        self._repos['OrderRepository'].update(id=id, state=state, created_at=created_at, updated_at=updated_at)
