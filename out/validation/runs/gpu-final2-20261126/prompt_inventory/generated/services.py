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



class InventoryService:

    def __init__(self, repos):
        self._repos = repos


    def add_product(self, sku: str = None, name: str = None, category_id: int = None, price_cents: int = None, stock_qty: int = None) -> None:
        """Adds a new product with validation that the category exists and the SKU is unique. [mechanical CRUD wrapper]"""
        if sku is None or name is None or category_id is None or price_cents is None or stock_qty is None:
            raise ValueError('missing required field')
        self._repos['ProductRepository'].create(sku=sku, name=name, category_id=category_id, price_cents=price_cents, stock_qty=stock_qty)

    def update_product(self, id: int = None, data: Dict[str, Any] = None) -> None:
        """Updates a product's fields, with validation that the product exists and category exists if provided. [delegates the mapping to the repository update]"""
        if data is None:
            return
        self._repos['ProductRepository'].update(id=id, sku=data.get('sku'), name=data.get('name'), category_id=data.get('category_id'), price_cents=data.get('price_cents'), stock_qty=data.get('stock_qty'), low_active=data.get('low_active'))

    def delete_product(self, id: int = None) -> None:
        """Deletes a product by its ID, raising an error if the product does not exist. [mechanical CRUD wrapper]"""
        self._repos['ProductRepository'].delete(id=id)

    def get_product_by_id(self, id: int = None) -> Dict[str, Any]:
        """Returns a product by its ID, raising an error if the product does not exist. [llm-written by server — review]"""
        product = self._repos['ProductRepository'].read_one(id=id)
        if product is None:
            raise errors.ProductNotFoundError(f'product with id {id} not found')
        return {key: value for key, value in product.__dict__.items() if value is not None}

    def list_products(self, category_id: int = None, low_only: bool = None) -> list[dict]:
        """Lists products filtered by optional category ID and whether to include only low-stock items. [llm-written by server — review]"""
        products = self._repos['ProductRepository'].read_all(category_id=category_id)
        result = []
        for product in products:
            if low_only and product.stock_qty is not None and (product.stock_qty < (self._repos['CategoryRepository'].read_one(id=product.category_id).reorder_threshold or 0)):
                result.append({'id': product.id, 'sku': product.sku, 'name': product.name, 'stock_qty': product.stock_qty, 'reorder_threshold': self._repos['CategoryRepository'].read_one(id=product.category_id).reorder_threshold if product.category_id else None})
            elif not low_only:
                result.append({'id': product.id, 'sku': product.sku, 'name': product.name, 'stock_qty': product.stock_qty, 'reorder_threshold': self._repos['CategoryRepository'].read_one(id=product.category_id).reorder_threshold if product.category_id else None})
        return result

    def restock(self, id: int = None, qty: int = None) -> None:
        """Increases a product's stock_qty by the specified quantity. [llm-written by server — review]"""
        if qty is None or qty < 0:
            raise ValueError('restock quantity must be non-negative')
        product = self._repos['ProductRepository'].read_one(id=id)
        if product is None:
            raise errors.ProductNotFoundError(f'product with id {id} not found')
        new_stock_qty = product.stock_qty + qty
        self._repos['ProductRepository'].update(id=id, stock_qty=new_stock_qty)

    def low_stock_report(self) -> list[dict]:
        """Returns a list of products whose stock_qty is below their category's reorder_threshold. [llm-written by server — review]"""
        result = []
        products = self._repos['ProductRepository'].read_all()
        for product in products:
            if product.category_id is None:
                continue
            category = self._repos['CategoryRepository'].read_one(id=product.category_id)
            if category is None:
                continue
            if product.stock_qty is not None and product.stock_qty < (category.reorder_threshold or 0):
                result.append({'id': product.id, 'sku': product.sku, 'name': product.name, 'stock_qty': product.stock_qty, 'reorder_threshold': category.reorder_threshold})
        return result

    def stock_value_by_category(self) -> dict[int, int]:
        """Returns a dictionary mapping each category ID to the total value (price_cents * stock_qty) of all products in that category. [delegates to the stock-value aggregate]"""
        return self._repos['ProductRepository'].aggregate_stock_value_by_category()
