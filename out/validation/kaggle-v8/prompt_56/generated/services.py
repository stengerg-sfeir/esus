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
        """Cancels an order, which releases the reserved stock quantities of the products in the order. The order status is updated to 'cancelled'. [delegates to OrderRepository.cancel_order — cancel/restore]"""
        self._repos['OrderRepository'].cancel_order(order_id)

    def get_order_with_products(self, order_id: int = None) -> Dict[str, Any]:
        """Retrieves an order with its associated products and their quantities, including the order status and customer details. [llm-written by server — review]"""
        order = self._repos['OrderRepository'].find_order_by_id(order_id)
        if order is None:
            raise errors.OrderNotFoundError
        order_products = self._repos['OrderProductRepository'].get_order_products_by_product_id(order_id)
        customer = self._repos['CustomerRepository'].read_one(customer_id=order.customer_id)
        if customer is None:
            raise errors.CustomerNotFoundError
        result = {'order_id': order.order_id, 'customer_id': customer.customer_id, 'name': customer.name, 'email': customer.email, 'order_date': order.order_date, 'status': order.status, 'products': [{'product_id': product.product_id, 'name': product.name, 'quantity': product.quantity} for product in order_products]}
        return result

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

    def update_order(self, order_id: int = None, customer_id: int = None, order_date: Any = None, status: str = None) -> None:
        """Updates an existing Order. [mechanical CRUD wrapper]"""
        self._repos['OrderRepository'].update(order_id=order_id, customer_id=customer_id, order_date=order_date, status=status)

    def delete_order(self, order_id: int = None) -> None:
        """Deletes an existing Order. [mechanical CRUD wrapper]"""
        self._repos['OrderRepository'].delete(order_id=order_id)

    def orderconfirm(self, order_id: int = None) -> None:
        """Orderconfirm. [llm-written by server — review]"""
        order = self._repos['OrderRepository'].find_order_by_id(order_id)
        if order is None:
            raise errors.OrderNotFoundError
        order_products = self._repos['OrderProductRepository'].get_order_products_by_product_id(order_id)
        for order_product in order_products:
            product = self._repos['ProductRepository'].read_one(product_id=order_product.product_id)
            if product is None:
                raise errors.ProductNotFoundError
            if product.stock_quantity < order_product.quantity:
                raise errors.InsufficientStockError
            product.stock_quantity -= order_product.quantity
            self._repos['ProductRepository'].update(product_id=product.product_id, stock_quantity=product.stock_quantity)
        order.status = 'confirmed'
        self._repos['OrderRepository'].update(order_id=order_id, status=order.status)


class ProductService:

    def __init__(self, repos):
        self._repos = repos


    def search_products(self, query: str = None, category: str = None) -> list[dict]:
        """Searches products by name or category, returning a list of matching products with their stock quantities and prices. [llm-written by server — review]"""
        records = self._repos['ProductRepository'].search_products_by_name_or_category(search_term=query) if query else []
        if category:
            records = [product for product in records if product.category == category]
        result = []
        for product in records:
            result.append({
                'product_id': product.product_id,
                'name': product.name,
                'price': product.price,
                'stock_quantity': product.stock_quantity,
                'category': product.category
            })
        return result

    def update_product_stock(self, product_id: int = None, new_stock_quantity: int = None) -> None:
        """Updates the stock quantity of a product. The new quantity must be non-negative. [mechanical CRUD wrapper]"""
        self._repos['ProductRepository'].update(product_id=product_id, stock_quantity=new_stock_quantity)

    def create_product(self, name: str = None, price: int = None, stock_quantity: int = None, category: str = None) -> None:
        """Creates a new Product. [mechanical CRUD wrapper]"""
        if name is None or price is None or stock_quantity is None:
            raise ValueError('missing required field')
        self._repos['ProductRepository'].create(name=name, price=price, stock_quantity=stock_quantity, category=category)

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

    def delete_product(self, product_id: int = None) -> None:
        """Deletes an existing Product. [mechanical CRUD wrapper]"""
        self._repos['ProductRepository'].delete(product_id=product_id)

    def productsearch(self, query: str = None, category: str = None) -> list[models.Product]:
        """Productsearch. [llm-written by server — review]"""
        records = self._repos['ProductRepository'].search_products_by_name_or_category(search_term=query) if query else []
        if category:
            records = [product for product in records if product.category == category]
        return records


class CustomerService:

    def __init__(self, repos):
        self._repos = repos


    def list_customers(self) -> list[dict]:
        """Returns a list of all customers with their IDs, names, and emails. [llm-written by server — review]"""
        records = self._repos['CustomerRepository'].read_all()
        out = []
        for record in records:
            row = record if isinstance(record, dict) else vars(record)
            out.append({'customer_id': row.get('customer_id'), 'name': row.get('name'), 'email': row.get('email')})
        return out

    def create_customer(self, name: str = None, email: str = None) -> None:
        """Creates a new Customer. [mechanical CRUD wrapper]"""
        if name is None or email is None:
            raise ValueError('missing required field')
        self._repos['CustomerRepository'].create(name=name, email=email)

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
