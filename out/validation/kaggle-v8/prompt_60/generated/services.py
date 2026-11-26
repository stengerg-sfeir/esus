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
        """Confirms an order, reserving the stock for the products in the order. An invoice is generated upon confirmation. [llm-written by server — review]"""
        order = self._repos['OrderRepository'].read_one(order_id)
        if not order:
            raise errors.OrderNotFoundError
        order_items = self._repos['OrderItemRepository'].get_order_items_by_order_id(order.order_id)
        for item in order_items:
            product = self._repos['ProductRepository'].read_one(product_id=item.product_id)
            if not product:
                continue
            if product.stock_quantity is None:
                continue
            if product.stock_quantity < item.quantity:
                raise errors.InsufficientStockError
            product.stock_quantity -= item.quantity
            self._repos['ProductRepository'].update(product_id=product.product_id, stock_quantity=product.stock_quantity)
        self._repos['InvoiceRepository'].create(order_id=order.order_id, total_amount=0)
        self._repos['OrderRepository'].update(order_id=order.order_id, status='confirmed', confirmed_at=datetime.datetime.now())

    def cancel_order(self, order_id: int = None) -> None:
        """Cancels a confirmed order, releasing the reserved stock. The order status is updated to cancelled. [llm-written by server — review]"""
        order = self._repos['OrderRepository'].read_one(order_id)
        if not order:
            raise errors.OrderNotFoundError
        order_items = self._repos['OrderItemRepository'].get_order_items_by_order_id(order.order_id)
        for item in order_items:
            product = self._repos['ProductRepository'].read_one(product_id=item.product_id)
            if not product:
                continue
            if product.stock_quantity is None:
                continue
            product.stock_quantity += item.quantity
            self._repos['ProductRepository'].update(product_id=product.product_id, stock_quantity=product.stock_quantity)
        self._repos['OrderRepository'].update(order_id=order.order_id, status='cancelled')

    def ship_order(self, order_id: int = None) -> None:
        """Marks an order as shipped. Only valid for confirmed orders. [closed contract: closed scalar contract]"""
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
        order.status = 'confirmed'
        order.confirmed_at = datetime.datetime.now()
        order_items = self._repos['OrderItemRepository'].get_order_items_by_order_id(order.order_id)
        for item in order_items:
            product = self._repos['ProductRepository'].read_one(product_id=item.product_id)
            if not product:
                continue
            if product.stock_quantity is None:
                continue
            if product.stock_quantity < item.quantity:
                raise errors.InsufficientStockError
            product.stock_quantity -= item.quantity
            self._repos['ProductRepository'].update(product_id=product.product_id, stock_quantity=product.stock_quantity)
        self._repos['OrderRepository'].update(order_id=order.order_id, status='confirmed', confirmed_at=order.confirmed_at)

    def ordersearch(self, customer_id: int = None) -> list[models.Order]:
        """Ordersearch. [delegates the list filter to read_all]"""
        return self._repos['OrderRepository'].read_all(customer_id=customer_id)

    def orderexport(self, file_path: str = None) -> None:
        """Orderexport. [llm-written by server — review]"""
        if file_path is None:
            raise ValueError('file_path is required')
        try:
            orders = self._repos['OrderRepository'].read_all()
            with open(file_path, 'w', newline='', encoding='utf-8') as csvfile:
                fieldnames = ['order_id', 'customer_name', 'status', 'created_at', 'confirmed_at', 'shipped_at', 'cancelled_at']
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
                for order in orders:
                    order_data = vars(order)
                    customer = self._repos['CustomerRepository'].read_one(customer_id=order_data.get('customer_id'))
                    if customer is None:
                        customer_name = ''
                    else:
                        customer_name = customer.name
                    row = {'order_id': order.order_id, 'customer_name': customer_name, 'status': order.status, 'created_at': order.created_at.isoformat() if order.created_at else '', 'confirmed_at': order.confirmed_at.isoformat() if order.confirmed_at else '', 'shipped_at': order.shipped_at.isoformat() if order.shipped_at else '', 'cancelled_at': order.cancelled_at.isoformat() if order.cancelled_at else ''}
                    writer.writerow(row)
        except OSError as e:
            raise ValueError(f'Failed to write file: {file_path}')


class ProductService:

    def __init__(self, repos):
        self._repos = repos


    def add_product(self, product_name: str = None, category_id: int = None, price: float = None, stock_quantity: int = None) -> None:
        """Adds a new product to the system with a specified name, category ID, price, and stock quantity. [mechanical CRUD wrapper]"""
        if product_name is None or category_id is None or price is None or stock_quantity is None:
            raise ValueError('missing required field')
        self._repos['ProductRepository'].create(name=product_name, category_id=category_id, price=price, stock_quantity=stock_quantity)

    def update_product_stock(self, product_id: int = None, new_stock_quantity: int = None) -> None:
        """Updates the stock quantity of an existing product. [mechanical CRUD wrapper]"""
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
            with open(file_path, 'w', newline='', encoding='utf-8') as csvfile:
                fieldnames = ['product_name', 'category_name', 'price', 'stock_quantity']
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
                for product in products:
                    if product.name is None or product.stock_quantity is None:
                        continue
                    category = self._repos['CategoryRepository'].read_one(category_id=product.category_id)
                    if category is None:
                        continue
                    writer.writerow({'product_name': product.name, 'category_name': category.name, 'price': product.price, 'stock_quantity': product.stock_quantity})
        except OSError as e:
            raise ValueError(f'Failed to write file: {file_path}')


class CategoryService:

    def __init__(self, repos):
        self._repos = repos


    def add_category(self, category_name: str = None) -> None:
        """Adds a new category to the system with a specified name. [mechanical CRUD wrapper]"""
        if category_name is None:
            raise ValueError('missing required field')
        self._repos['CategoryRepository'].create(name=category_name)

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


    def search_orders_by_customer(self, customer_id: int = None) -> Any:
        """Searches for all orders placed by a specific customer. [llm-written by server — review]"""
        orders = self._repos['OrderRepository'].get_orders_by_customer_id(customer_id)
        return orders

    def search_invoices_by_customer(self, customer_id: int = None) -> Any:
        """Searches for all invoices generated for a specific customer. [llm-written by server — review]"""
        orders = self._repos['OrderRepository'].get_orders_by_customer_id(customer_id)
        invoices = []
        for order in orders:
            order_invoices = self._repos['InvoiceRepository'].get_invoices_by_order_id(order.order_id)
            invoices.extend(order_invoices)
        return invoices

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
        """Generates a report showing the count of orders by status (pending, confirmed, shipped, cancelled). [mechanical count report]"""
        counts = {'pending': 0, 'confirmed': 0, 'shipped': 0, 'cancelled': 0}
        for order in self._repos['OrderRepository'].read_all():
            key = order.status
            if key in counts:
                counts[key] += 1
        return counts

    def get_product_stock_report(self) -> Any:
        """Generates a report showing product names, category names, and current stock quantities. [llm-written by server — review]"""
        report = {}
        products = self._repos['ProductRepository'].read_all()
        for product in products:
            if product.name is None or product.stock_quantity is None:
                continue
            category = self._repos['CategoryRepository'].read_one(category_id=product.category_id)
            if category is None:
                continue
            product_name = product.name
            category_name = category.name
            stock_quantity = product.stock_quantity
            if product_name not in report:
                report[product_name] = {}
            if category_name not in report[product_name]:
                report[product_name][category_name] = 0
            report[product_name][category_name] += stock_quantity
        return report


class SearchService:

    def __init__(self, repos):
        self._repos = repos


    def search_orders_by_status(self, status: str = None) -> Any:
        """Searches for orders by their status (pending, confirmed, shipped, cancelled). [delegates the list filter to read_all]"""
        return self._repos['OrderRepository'].read_all(status=status)

    def search_products_by_category(self, category_id: int = None) -> Any:
        """Searches for products belonging to a specific category. [delegates the list filter to read_all]"""
        return self._repos['ProductRepository'].read_all(category_id=category_id)


class ExportService:

    def __init__(self, repos):
        self._repos = repos


    def export_orders_to_csv(self, file_path: str = None) -> None:
        """Exports all orders to a CSV file with customer, product, quantity, and status details. [llm-written by server — review]"""
        if file_path is None:
            raise ValueError('file_path is required')
        try:
            orders = self._repos['OrderRepository'].read_all()
            with open(file_path, 'w', newline='', encoding='utf-8') as csvfile:
                fieldnames = ['order_id', 'customer_name', 'status', 'created_at', 'confirmed_at', 'shipped_at', 'cancelled_at']
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
                for order in orders:
                    order_data = vars(order)
                    customer = self._repos['CustomerRepository'].read_one(customer_id=order_data.get('customer_id'))
                    if customer is None:
                        customer_name = ''
                    else:
                        customer_name = customer.name
                    row = {'order_id': order.order_id, 'customer_name': customer_name, 'status': order.status, 'created_at': order.created_at.isoformat() if order.created_at else '', 'confirmed_at': order.confirmed_at.isoformat() if order.confirmed_at else '', 'shipped_at': order.shipped_at.isoformat() if order.shipped_at else '', 'cancelled_at': order.cancelled_at.isoformat() if order.cancelled_at else ''}
                    writer.writerow(row)
        except OSError as e:
            raise ValueError(f'Failed to write file: {file_path}')

    def export_product_stock_to_csv(self, file_path: str = None) -> None:
        """Exports product stock information to a CSV file with product name, category, and stock quantity. [llm-written by server — review]"""
        products = self._repos['ProductRepository'].read_all()
        with open(file_path, 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = ['product_name', 'category_name', 'stock_quantity']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            for product in products:
                if product.name is None or product.stock_quantity is None:
                    continue
                category = self._repos['CategoryRepository'].read_one(category_id=product.category_id)
                if category is None:
                    continue
                writer.writerow({'product_name': product.name, 'category_name': category.name, 'stock_quantity': product.stock_quantity})
        return None


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
