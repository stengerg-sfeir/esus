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
        """Reserves stock for products in the order and creates an invoice. The order status is updated to 'confirmed'. [llm-written by server — review]"""
        order = self._repos['OrderRepository'].read_one(order_id)
        if not order:
            raise errors.OrderNotFoundError
        if order.status != 'pending':
            raise errors.InvalidOrderStatusError
        order_items = self._repos['OrderItemRepository'].read_all(order_id=order_id)
        for item in order_items:
            product = self._repos['ProductRepository'].read_one(product_id=item.product_id)
            if not product:
                raise errors.ProductNotFoundError
            if product.stock_quantity < item.quantity:
                raise errors.InsufficientStockError
            product.stock_quantity -= item.quantity
            self._repos['ProductRepository'].update(product_id=product.product_id, stock_quantity=product.stock_quantity)
        self._repos['OrderRepository'].update(order_id=order_id, status='confirmed', confirmed_at=datetime.datetime.now())
        self._repos['InvoiceRepository'].create(order_id=order_id, total_amount=sum((item.quantity * self._repos['ProductRepository'].read_one(item.product_id).price for item in order_items)))

    def cancel_order(self, order_id: int = None) -> None:
        """Releases reserved stock and updates the order status to 'cancelled'. Only allowed for confirmed orders. [llm-written by server — review]"""
        order = self._repos['OrderRepository'].read_one(order_id)
        if not order:
            raise errors.OrderNotFoundError
        if order.status != 'confirmed':
            raise errors.InvalidOrderStatusError
        order_items = self._repos['OrderItemRepository'].read_all(order_id=order_id)
        for item in order_items:
            product = self._repos['ProductRepository'].read_one(product_id=item.product_id)
            if not product:
                raise errors.ProductNotFoundError
            product.stock_quantity += item.quantity
            self._repos['ProductRepository'].update(product_id=product.product_id, stock_quantity=product.stock_quantity)
        self._repos['OrderRepository'].update(order_id=order_id, status='cancelled')

    def ship_order(self, order_id: int = None) -> None:
        """Updates the order status to 'shipped'. Only allowed for confirmed orders. [closed contract: closed scalar contract]"""
        order = self._repos['OrderRepository'].read_one(order_id)
        if not (order.status == 'confirmed'):
            raise ValueError("order.status == 'confirmed'")
        self._repos['OrderRepository'].update(order.order_id, status='shipped')

    def create_order(self, customer_id: int = None, status: str = None, created_at: Any = None, confirmed_at: Any = None, shipped_at: Any = None, cancelled_at: Any = None) -> None:
        """Creates a new Order. [mechanical CRUD wrapper]"""
        if customer_id is None or status is None or created_at is None:
            raise ValueError('missing required field')
        self._repos['OrderRepository'].create(customer_id=customer_id, status=status, created_at=created_at, confirmed_at=confirmed_at, shipped_at=shipped_at, cancelled_at=cancelled_at)

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

    def update_order(self, order_id: int = None, customer_id: int = None, status: str = None, created_at: Any = None, confirmed_at: Any = None, shipped_at: Any = None, cancelled_at: Any = None) -> None:
        """Updates an existing Order. [mechanical CRUD wrapper]"""
        self._repos['OrderRepository'].update(order_id=order_id, customer_id=customer_id, status=status, created_at=created_at, confirmed_at=confirmed_at, shipped_at=shipped_at, cancelled_at=cancelled_at)

    def delete_order(self, order_id: int = None) -> None:
        """Deletes an existing Order. [mechanical CRUD wrapper]"""
        self._repos['OrderRepository'].delete(order_id=order_id)

    def orderconfirm(self, order_id: int = None) -> None:
        """Orderconfirm. [llm-written by server — review]"""
        order = self._repos['OrderRepository'].read_one(order_id)
        if not order:
            raise errors.OrderNotFoundError
        if order.status != 'pending':
            raise errors.InvalidOrderStatusError
        order_items = self._repos['OrderItemRepository'].read_all(order_id=order_id)
        for item in order_items:
            product = self._repos['ProductRepository'].read_one(product_id=item.product_id)
            if not product:
                raise errors.ProductNotFoundError
            if product.stock_quantity < item.quantity:
                raise errors.InsufficientStockError
            product.stock_quantity -= item.quantity
            self._repos['ProductRepository'].update(product_id=product.product_id, stock_quantity=product.stock_quantity)
        self._repos['OrderRepository'].update(order_id=order_id, status='confirmed', confirmed_at=datetime.datetime.now())
        invoice = self._repos['InvoiceRepository'].create(order_id=order_id, total_amount=sum((item.quantity * self._repos['ProductRepository'].read_one(item.product_id).price for item in order_items)))

    def ordersearch(self, customer_id: int = None) -> list[models.Order]:
        """Ordersearch. [delegates the list filter to read_all]"""
        return self._repos['OrderRepository'].read_all(customer_id=customer_id)

    def orderexport(self, file_path: str = None) -> None:
        """Orderexport. [llm-written by server — review]"""
        if file_path is None:
            raise ValueError('file_path is required')
        try:
            orders = self._repos['OrderRepository'].read_all()
            with open(file_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=['order_id', 'customer_id', 'status', 'created_at', 'confirmed_at', 'shipped_at', 'cancelled_at'])
                writer.writeheader()
                for order in orders:
                    writer.writerow({'order_id': order.order_id, 'customer_id': order.customer_id, 'status': order.status, 'created_at': order.created_at.isoformat() if order.created_at else None, 'confirmed_at': order.confirmed_at.isoformat() if order.confirmed_at else None, 'shipped_at': order.shipped_at.isoformat() if order.shipped_at else None, 'cancelled_at': order.cancelled_at.isoformat() if order.cancelled_at else None})
        except OSError as e:
            raise ValueError(f'failed to write file: {file_path}') from e


class ProductService:

    def __init__(self, repos):
        self._repos = repos


    def update_product_stock(self, product_id: int = None, new_stock_quantity: int = None) -> None:
        """Updates the stock quantity of a product. Does not modify other fields. [mechanical CRUD wrapper]"""
        self._repos['ProductRepository'].update(product_id=product_id, stock_quantity=new_stock_quantity)

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

    def delete_product(self, product_id: int = None) -> None:
        """Deletes an existing Product. [mechanical CRUD wrapper]"""
        self._repos['ProductRepository'].delete(product_id=product_id)

    def productsearch(self, category_id: int = None) -> list[models.Product]:
        """Productsearch. [delegates the list filter to read_all]"""
        return self._repos['ProductRepository'].read_all(category_id=category_id)

    def productexport(self, file_path: str = None) -> None:
        """Productexport. [llm-written by server — review]"""
        if file_path is None:
            raise ValueError('file_path is required')
        try:
            products = self._repos['ProductRepository'].read_all()
            with open(file_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=['product_id', 'name', 'category_id', 'price', 'stock_quantity', 'category_name'])
                writer.writeheader()
                categories = self._repos['CategoryRepository'].read_all()
                category_map = {cat.category_id: cat.name for cat in categories}
                for product in products:
                    category_name = category_map.get(product.category_id)
                    writer.writerow({'product_id': product.product_id, 'name': product.name, 'category_id': product.category_id, 'price': product.price, 'stock_quantity': product.stock_quantity, 'category_name': category_name})
        except OSError as e:
            raise ValueError(f'failed to write file: {file_path}') from e


class CategoryService:

    def __init__(self, repos):
        self._repos = repos


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


    def search_orders_by_customer(self, customer_id: int = None) -> list[models.Order]:
        """Returns all orders placed by a customer, filtered by customer ID. [composes OrderRepository.read_all over signature-pagination]"""
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

    def search_invoices_by_customer(self, customer_id: int = None) -> list[models.Invoice]:
        """Returns all invoices associated with orders from a customer, filtered by customer ID. [filters through one relation]"""
        middle = [row for row in self._repos['OrderRepository'].read_all() if row.customer_id == customer_id]
        middle_ids = {row.order_id for row in middle}
        return [row for row in self._repos['InvoiceRepository'].read_all() if row.order_id in middle_ids]

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

    def create_customer(self, name: str = None, email: str = None) -> None:
        """Creates a new Customer. [mechanical CRUD wrapper]"""
        if name is None or email is None:
            raise ValueError('missing required field')
        self._repos['CustomerRepository'].create(name=name, email=email)

    def update_customer(self, customer_id: int = None, name: str = None, email: str = None) -> None:
        """Updates an existing Customer. [mechanical CRUD wrapper]"""
        self._repos['CustomerRepository'].update(customer_id=customer_id, name=name, email=email)


class ReportService:

    def __init__(self, repos):
        self._repos = repos


    def get_order_status_report(self) -> Dict[str, Any]:
        """Returns a summary of order statuses: pending, confirmed, shipped, cancelled. [mechanical count report]"""
        counts = {'pending': 0, 'confirmed': 0, 'shipped': 0, 'cancelled': 0}
        for order in self._repos['OrderRepository'].read_all():
            key = order.status
            if key in counts:
                counts[key] += 1
        return counts

    def get_product_stock_report(self) -> list[dict]:
        """Returns a list of products with their current stock quantities and category names. [mechanical stock report]"""
        rows = self._repos['ProductRepository'].read_all()
        parents = self._repos['CategoryRepository'].read_all()
        names = {row.category_id: row.name for row in parents}
        result = []
        for product in rows:
            result.append({'product_id': product.product_id, 'name': product.name, 'category_id': product.category_id, 'price': product.price, 'stock_quantity': product.stock_quantity, 'category_name': names.get(product.category_id)})
        return result


class SearchService:

    def __init__(self, repos):
        self._repos = repos


    def search_orders_by_status(self, status: str = None) -> list[models.Order]:
        """Returns all orders with a specific status (pending, confirmed, shipped, cancelled). [delegates the list filter to read_all]"""
        return self._repos['OrderRepository'].read_all(status=status)

    def search_products_by_category(self, category_id: int = None) -> list[models.Product]:
        """Returns all products belonging to a specific category. [delegates the list filter to read_all]"""
        return self._repos['ProductRepository'].read_all(category_id=category_id)


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
