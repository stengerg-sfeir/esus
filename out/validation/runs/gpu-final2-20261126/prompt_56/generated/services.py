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
        """Cancels an order by updating its status to 'cancelled' and releasing the reserved stock quantities of the products in the order. [delegates to OrderRepository.cancel_order — cancel/restore]"""
        self._repos['OrderRepository'].cancel_order(order_id)

    def create_order(self, customer_id: int = None, order_date: Any = None, status: str = None) -> None:
        """Creates a new Order. [mechanical CRUD wrapper]"""
        if customer_id is None or order_date is None or status is None:
            raise ValueError('missing required field')
        self._repos['OrderRepository'].create(customer_id=customer_id, order_date=order_date, status=status)

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

    def read_order_by_id(self, order_id: int = None) -> models.Order | None:
        """Reads one Order by its key. [delegates to OrderRepository.get_order_with_products — renamed from read_order_by_id]"""
        return self._repos['OrderRepository'].get_order_with_products(order_id)

    def update_order(self, order_id: int = None, customer_id: int = None, order_date: Any = None, status: str = None) -> None:
        """Updates an existing Order. [mechanical CRUD wrapper]"""
        self._repos['OrderRepository'].update(order_id=order_id, customer_id=customer_id, order_date=order_date, status=status)

    def delete_order(self, order_id: int = None) -> None:
        """Deletes an existing Order. [mechanical CRUD wrapper]"""
        self._repos['OrderRepository'].delete(order_id=order_id)


class ProductService:

    def __init__(self, repos):
        self._repos = repos


    def create_product(self, name: str = None, description: str = None, stock_quantity: int = None) -> None:
        """Creates a new Product. [mechanical CRUD wrapper]"""
        if name is None or stock_quantity is None:
            raise ValueError('missing required field')
        self._repos['ProductRepository'].create(name=name, description=description, stock_quantity=stock_quantity)

    def read_all_products(self) -> list[models.Product]:
        """Lists every Product. [composes ProductRepository.read_all over READ_ALL]"""
        records = self._repos['ProductRepository'].read_all()
        criteria = []
        out = []
        for record in records:
            row = record if isinstance(record, dict) else vars(record)
            if all(_holds(row.get(field), operator, value)
                   for field, operator, value in criteria):
                out.append(record)
        return out

    def read_product_by_id(self, product_id: int = None) -> models.Product | None:
        """Reads one Product by its key. [mechanical standard read]"""
        try:
            return self._repos['ProductRepository'].read_one(product_id)
        except errors.ProductNotFoundError:
            return None

    def update_product(self, product_id: int = None, name: str = None, description: str = None, stock_quantity: int = None) -> None:
        """Updates an existing Product. [mechanical CRUD wrapper]"""
        self._repos['ProductRepository'].update(product_id=product_id, name=name, description=description, stock_quantity=stock_quantity)

    def delete_product(self, product_id: int = None) -> None:
        """Deletes an existing Product. [mechanical CRUD wrapper]"""
        self._repos['ProductRepository'].delete(product_id=product_id)


class CustomerService:

    def __init__(self, repos):
        self._repos = repos


    def validate_customer_exists(self, customer_id: int = None) -> bool:
        """Validates that a customer exists in the system by customer ID. [llm-written by server — review]"""
        try:
            self._repos['CustomerRepository'].read_one(customer_id)
            return True
        except errors.CustomerNotFoundError:
            return False

    def create_customer(self, name: str = None, email: str = None) -> None:
        """Creates a new Customer. [mechanical CRUD wrapper]"""
        if name is None or email is None:
            raise ValueError('missing required field')
        self._repos['CustomerRepository'].create(name=name, email=email)

    def read_all_customers(self) -> list[models.Customer]:
        """Lists every Customer. [composes CustomerRepository.read_all over READ_ALL]"""
        records = self._repos['CustomerRepository'].read_all()
        criteria = []
        out = []
        for record in records:
            row = record if isinstance(record, dict) else vars(record)
            if all(_holds(row.get(field), operator, value)
                   for field, operator, value in criteria):
                out.append(record)
        return out

    def read_customer_by_id(self, customer_id: int = None) -> models.Customer | None:
        """Reads one Customer by its key. [mechanical standard read]"""
        try:
            return self._repos['CustomerRepository'].read_one(customer_id)
        except errors.CustomerNotFoundError:
            return None

    def update_customer(self, customer_id: int = None, name: str = None, email: str = None) -> None:
        """Updates an existing Customer. [mechanical CRUD wrapper]"""
        self._repos['CustomerRepository'].update(customer_id=customer_id, name=name, email=email)

    def delete_customer(self, customer_id: int = None) -> None:
        """Deletes an existing Customer. [mechanical CRUD wrapper]"""
        self._repos['CustomerRepository'].delete(customer_id=customer_id)


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


for _name in ['cancel_order']:
    if hasattr(OrderService, _name):
        setattr(OrderService, _name, _atomic(getattr(OrderService, _name)))
