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



class OrderManagementService:

    def __init__(self, repos):
        self._repos = repos


    def place_order(self, customer_id: int = None, order_items: Any = None) -> Any:
        """Places an order for a customer with specified products and quantities. Validates that all products have sufficient stock. If valid, reserves stock and creates the order. [mechanical order placement]"""
        Customer = self._repos['CustomerRepository'].read_one(id=customer_id)
        if Customer is None:
            raise errors.CustomerNotFoundError
        items = order_items or []
        for item in items:
            product_id = item.get('product_id')
            quantity = item.get('quantity')
            if product_id is None or quantity is None:
                continue
            product = self._repos['ProductRepository'].read_one(id=product_id)
            if product is None:
                raise errors.ProductNotFoundError
            if product.stock_quantity is None or product.stock_quantity < quantity:
                raise errors.InsufficientStockError
        order = self._repos['OrderRepository'].create(customer_id=customer_id, order_date=datetime.datetime.now())
        for item in items:
            product_id = item.get('product_id')
            quantity = item.get('quantity')
            if product_id is None or quantity is None:
                continue
            self._repos['OrderItemRepository'].create(order_id=order.id, quantity=quantity, product_id=product_id)
            product = self._repos['ProductRepository'].read_one(id=product_id)
            self._repos['ProductRepository'].update(id=product_id, stock_quantity=product.stock_quantity - quantity)
        return order


def _atomic(method):
    """Run a multi-write service method in one store transaction."""
    def wrapper(self, *args, **kwargs):
        store = None
        for repo in self._repos.values():
            store = getattr(repo, '_store', None)
            if store is not None:
                break
        if store is None or not hasattr(store, 'transaction'):
            return method(self, *args, **kwargs)
        with store.transaction():
            return method(self, *args, **kwargs)
    wrapper.__name__ = method.__name__
    wrapper.__doc__ = method.__doc__
    wrapper.__wrapped__ = method
    return wrapper


for _name in ['place_order', 'place_order']:
    if hasattr(OrderManagementService, _name):
        setattr(OrderManagementService, _name, _atomic(getattr(OrderManagementService, _name)))
