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



class CategoryService:

    def __init__(self, repos):
        self._repos = repos


    def add_category(self, name: str = None) -> None:
        """Adds a new category to the system with a specified name. Throws a CategoryNotFoundError if category already exists (assumed unique). [mechanical CRUD wrapper]"""
        if name is None:
            raise ValueError('missing required field')
        self._repos['CategoryRepository'].create(name=name)

    def delete_category(self, category_id: int = None) -> None:
        """Deletes an existing Category. [mechanical CRUD wrapper]"""
        self._repos['CategoryRepository'].delete(category_id=category_id)

    def read_all_categories(self) -> list[models.Category]:
        """Lists every Category. [composes CategoryRepository.read_all over READ_ALL]"""
        records = self._repos['CategoryRepository'].read_all()
        criteria = []
        out = []
        for record in records:
            row = record if isinstance(record, dict) else vars(record)
            if all(_holds(row.get(field), operator, value)
                   for field, operator, value in criteria):
                out.append(record)
        return out

    def read_category_by_id(self, category_id: int = None) -> models.Category | None:
        """Reads one Category by its key. [mechanical standard read]"""
        try:
            return self._repos['CategoryRepository'].read_one(category_id)
        except errors.CategoryNotFoundError:
            return None

    def update_category(self, category_id: int = None, name: str = None) -> None:
        """Updates an existing Category. [mechanical CRUD wrapper]"""
        self._repos['CategoryRepository'].update(category_id=category_id, name=name)


class CustomerService:

    def __init__(self, repos):
        self._repos = repos


    def create_customer(self, name: str = None, email: str = None) -> None:
        """Creates a new Customer. [mechanical CRUD wrapper]"""
        if name is None or email is None:
            raise ValueError('missing required field')
        self._repos['CustomerRepository'].create(name=name, email=email)

    def delete_customer(self, customer_id: int = None) -> None:
        """Deletes an existing Customer. [mechanical CRUD wrapper]"""
        self._repos['CustomerRepository'].delete(customer_id=customer_id)

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

    def search_invoices_by_customer(self, customer_id: int = None) -> list[models.Invoice]:
        """Returns all invoices generated for a given customer. Throws CustomerNotFoundError if customer not found. [composes InvoiceRepository.read_all over signature-pagination]"""
        records = self._repos['InvoiceRepository'].read_all()
        criteria = []
        if customer_id is not None:
            criteria.append(('customer_id', 'eq', customer_id))
        out = []
        for record in records:
            row = record if isinstance(record, dict) else vars(record)
            if all(_holds(row.get(field), operator, value)
                   for field, operator, value in criteria):
                out.append(record)
        return out

    def search_orders_by_customer(self, customer_id: int = None) -> list[models.Order]:
        """Returns all orders placed by a given customer. Throws CustomerNotFoundError if customer not found. [composes OrderRepository.read_all over signature-pagination]"""
        records = self._repos['OrderRepository'].read_all()
        criteria = []
        if customer_id is not None:
            criteria.append(('customer_id', 'eq', customer_id))
        out = []
        for record in records:
            row = record if isinstance(record, dict) else vars(record)
            if all(_holds(row.get(field), operator, value)
                   for field, operator, value in criteria):
                out.append(record)
        return out

    def update_customer(self, customer_id: int = None, name: str = None, email: str = None) -> None:
        """Updates an existing Customer. [mechanical CRUD wrapper]"""
        self._repos['CustomerRepository'].update(customer_id=customer_id, name=name, email=email)


class OrderService:

    def __init__(self, repos):
        self._repos = repos


    def cancel_order(self, order_id: int = None) -> None:
        """Releases reserved stock for products in the order. Only allowed for confirmed orders. Throws OrderCannotBeCancelledError if order is not confirmed. [llm-written by server — review]"""
        order = self._repos['OrderRepository'].read_one(order_id)
        if order.status != 'confirmed':
            raise errors.OrderCannotBeCancelledError('order must be confirmed to cancel')
        order_items = self._repos['OrderItemRepository'].get_order_items_by_order_id(order_id=order_id)
        for item in order_items:
            product = self._repos['ProductRepository'].read_one(product_id=item.product_id)
            if product is None:
                raise errors.ProductNotFoundError('product not found')
            product.stock_quantity += item.quantity
            self._repos['ProductRepository'].update(product_id=product.product_id, stock_quantity=product.stock_quantity)
        self._repos['OrderRepository'].update(order_id=order_id, status='cancelled')

    def confirm_order(self, order_id: int = None) -> None:
        """Reserves stock for products in the order and creates an invoice. Only allowed for pending orders. Throws InsufficientStockError if stock is insufficient. [llm-written by server — review]"""
        order = self._repos['OrderRepository'].read_one(order_id)
        if order.status != 'pending':
            raise errors.InvalidOrderStatusError('order must be pending to confirm')
        order_items = self._repos['OrderItemRepository'].get_order_items_by_order_id(order_id=order_id)
        for item in order_items:
            product = self._repos['ProductRepository'].read_one(product_id=item.product_id)
            if product is None:
                raise errors.ProductNotFoundError('product not found')
            if product.stock_quantity < item.quantity:
                raise errors.InsufficientStockError(f'insufficient stock for product {item.product_id}')
            product.stock_quantity -= item.quantity
            self._repos['ProductRepository'].update(product.product_id, stock_quantity=product.stock_quantity)
        self._repos['OrderRepository'].update(order_id=order_id, status='confirmed')
        self._repos['InvoiceRepository'].create(order_id=order_id, total_amount=0, generated_at=datetime.datetime.now(), customer_id=order.customer_id)

    def create_order(self, customer_id: int = None, status: str = None, created_at: Any = None, confirmed_at: Any = None, shipped_at: Any = None, cancelled_at: Any = None) -> None:
        """Creates a new Order. [mechanical CRUD wrapper]"""
        if customer_id is None or status is None or created_at is None:
            raise ValueError('missing required field')
        self._repos['OrderRepository'].create(customer_id=customer_id, status=status, created_at=created_at, confirmed_at=confirmed_at, shipped_at=shipped_at, cancelled_at=cancelled_at)

    def delete_order(self, order_id: int = None) -> None:
        """Deletes an existing Order. [mechanical CRUD wrapper]"""
        self._repos['OrderRepository'].delete(order_id=order_id)

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
        """Reads one Order by its key. [mechanical standard read]"""
        try:
            return self._repos['OrderRepository'].read_one(order_id)
        except errors.OrderNotFoundError:
            return None

    def ship_order(self, order_id: int = None) -> None:
        """Marks an order as shipped. Only allowed for confirmed orders. Throws OrderCannotBeShippedError if order is not confirmed. [closed contract: closed scalar contract]"""
        order = self._repos['OrderRepository'].read_one(order_id)
        if not (order.status == 'confirmed'):
            raise ValueError("order.status == 'confirmed'")
        self._repos['OrderRepository'].update(order.order_id, status='shipped')

    def update_order(self, order_id: int = None, customer_id: int = None, status: str = None, created_at: Any = None, confirmed_at: Any = None, shipped_at: Any = None, cancelled_at: Any = None) -> None:
        """Updates an existing Order. [mechanical CRUD wrapper]"""
        self._repos['OrderRepository'].update(order_id=order_id, customer_id=customer_id, status=status, created_at=created_at, confirmed_at=confirmed_at, shipped_at=shipped_at, cancelled_at=cancelled_at)


class ProductService:

    def __init__(self, repos):
        self._repos = repos


    def add_product(self, product_id: int = None, name: str = None, category_id: int = None, price: float = None, stock_quantity: int = None) -> None:
        """Adds a new product to the catalog with specified name, category ID, price, and stock quantity. Throws InvalidPriceError if price is invalid, InvalidProductIdError if product ID is invalid. [llm-written by server — review]"""
        if name is None:
            raise ValueError('missing required field')
        if category_id is None:
            raise ValueError('missing required field')
        if price is not None and price < 0:
            raise errors.InvalidPriceError('price is negative')
        if product_id is not None and product_id <= 0:
            raise errors.InvalidProductIdError('product_id is invalid')
        category = self._repos['CategoryRepository'].read_one(category_id=category_id)
        if category is None:
            raise errors.CategoryNotFoundError('category does not exist')
        self._repos['ProductRepository'].create(name=name, category_id=category_id, price=price, stock_quantity=stock_quantity)

    def delete_product(self, product_id: int = None) -> None:
        """Deletes an existing Product. [mechanical CRUD wrapper]"""
        self._repos['ProductRepository'].delete(product_id=product_id)

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

    def update_product_stock(self, product_id: int = None, stock_quantity: int = None) -> None:
        """Updates the stock quantity of a product. Throws ProductNotFoundError if product not found. [mechanical CRUD wrapper]"""
        self._repos['ProductRepository'].update(product_id=product_id, stock_quantity=stock_quantity)


class ReportService:

    def __init__(self, repos):
        self._repos = repos


    def generate_order_summary_report(self) -> Dict[str, Any]:
        """Generates a summary report of all orders by status (pending, confirmed, shipped, cancelled). [llm-written by server — review]"""
        records = self._repos['OrderRepository'].read_all()
        status_count = {}
        for record in records:
            row = record if isinstance(record, dict) else vars(record)
            status = row.get('status')
            if status is None:
                continue
            status_count[status] = status_count.get(status, 0) + 1
        return status_count

    def generate_product_stock_report(self) -> Dict[str, Any]:
        """Generates a report showing product names, categories, and current stock levels. [llm-written by server — review]"""
        records = self._repos['ProductRepository'].read_all()
        category_map = {}
        for product in records:
            row = product if isinstance(product, dict) else vars(product)
            category_id = row.get('category_id')
            if category_id is None:
                continue
            category_name = self._repos['CategoryRepository'].read_one(category_id=category_id)
            if category_name is None:
                continue
            category_name = category_name.name
            if category_name not in category_map:
                category_map[category_name] = 0
            category_map[category_name] += row.get('stock_quantity', 0)
        return category_map


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


for _name in ['confirm_order', 'cancel_order']:
    if hasattr(OrderService, _name):
        setattr(OrderService, _name, _atomic(getattr(OrderService, _name)))
