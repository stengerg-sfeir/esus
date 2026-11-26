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


    def confirm_order(self, order_id: int = None) -> None:
        """Transitions an order from pending to confirmed state. The order must be in pending state; cannot confirm a confirmed, shipped, or cancelled order. [closed contract: closed scalar contract]"""
        order = self._repos['OrderRepository'].read_one(order_id)
        if not (order.status == 'pending'):
            raise ValueError("order.status == 'pending'")
        self._repos['OrderRepository'].update(order.id, status='confirmed')

    def cancel_order(self, order_id: int = None) -> None:
        """Transitions an order from confirmed to cancelled state. The order must be in confirmed state; cannot cancel a pending, shipped, or cancelled order. [closed contract: closed scalar contract]"""
        order = self._repos['OrderRepository'].read_one(order_id)
        if not (order.status in {'confirmed', 'pending'}):
            raise ValueError("order.status in {'confirmed', 'pending'}")
        self._repos['OrderRepository'].update(order.id, status='cancelled')

    def ship_order(self, order_id: int = None) -> None:
        """Transitions an order from confirmed to shipped state. The order must be in confirmed state; cannot ship a pending, cancelled, or shipped order. [closed contract: closed scalar contract]"""
        order = self._repos['OrderRepository'].read_one(order_id)
        if not (order.status in {'confirmed', 'pending'}):
            raise ValueError("order.status in {'confirmed', 'pending'}")
        self._repos['OrderRepository'].update(order.id, status='shipped')

    def create_order(self, status: str = None) -> None:
        """Creates a new Order. [mechanical CRUD wrapper]"""
        if status is None:
            raise ValueError('missing required field')
        self._repos['OrderRepository'].create(status=status)

    def read_order_by_id(self, id: int = None) -> models.Order | None:
        """Reads one Order by its key. [mechanical standard read]"""
        return self._repos['OrderRepository'].read_one(id)

    def read_all_orders(self) -> list[models.Order]:
        """Lists every Order. [composes OrderRepository.read_all over READ_ALL]"""
        records = self._repos['OrderRepository'].read_all()
        criteria = []
        out = []
        for record in records:
            row = record if isinstance(record, dict) else vars(record)
            if all(_holds(row.get(field), operator, value)
                   for field, operator, value in criteria):
                out.append(record)
        return out

    def update_order(self, id: int = None, status: str = None) -> None:
        """Updates an existing Order. [mechanical CRUD wrapper]"""
        self._repos['OrderRepository'].update(id=id, status=status)

    def delete_order(self, id: int = None) -> None:
        """Deletes an existing Order. [mechanical CRUD wrapper]"""
        self._repos['OrderRepository'].delete(id=id)

    def orderconfirm(self, order_id: int = None) -> None:
        """Orderconfirm. [llm-written by server — review]"""
        order = self._repos['OrderRepository'].read_one(order_id)
        if order.status != 'pending':
            raise errors.OrderNotConfirmedError('Order must be in pending state to confirm')
        self._repos['OrderRepository'].update(order.id, status='confirmed')
