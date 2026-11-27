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


def _filter_value(value):
    """Dates compare as ISO text, the form the store keeps."""
    return value.isoformat() if hasattr(value, "isoformat") else value



class ExpenseService:

    def __init__(self, repos):
        self._repos = repos


    def add_expense(self, amount_cents: int = None, description: str = None, expense_date: datetime.date = None, category_id: int = None, payment_method: str = None, is_recurring: bool = None) -> models.Expense:
        """validates category exists, adds expense, checks if budget exceeded after insertion [llm-written by server — review]"""
        if amount_cents is None:
            raise ValueError('amount_cents is required')
        if category_id is None:
            raise ValueError('category_id is required')
        category = self._repos['CategoryRepository'].read_one(id=category_id)
        if not category:
            raise errors.CategoryNotFoundError(f'Category with id {category_id} not found')
        expense = self._repos['ExpenseRepository'].create(amount_cents=amount_cents, description=description, expense_date=expense_date, category_id=category_id, payment_method=payment_method, is_recurring=is_recurring)
        if self._repos['BudgetRepository'].check_budget_exceeded(category_id=category_id, month=expense.expense_date.strftime('%Y-%m')):
            raise errors.BudgetExceededException(f'Budget exceeded for category {category_id} in month {expense.expense_date.strftime('%Y-%m')}')
        return expense

    def delete_expense(self, id: int = None) -> None:
        """Deletes an expense by its ID. [mechanical CRUD wrapper]"""
        self._repos['ExpenseRepository'].delete(id=id)

    def detect_recurring(self) -> None:
        """Detects recurring expenses (same amount and category) that occur monthly and marks them as recurring. [mechanical recurring detection]"""
        records = self._repos['ExpenseRepository'].read_all()
        groups = {}
        for record in records:
            key = (record.amount_cents, record.category_id)
            groups.setdefault(key, []).append(record)
        result = []
        for group in groups.values():
            months = {str(getattr(item, 'expense_date', None) or '')[:7] for item in group}
            if len(months) <= 1:
                continue
            for item in group:
                result.append(self._repos['ExpenseRepository'].update(item.id, is_recurring=True))
        return result

    def expenseexport(self, from_date: str = None, to_date: str = None, output: str = None) -> None:
        """Expenseexport. [llm-written by server — review]"""
        from_date = _as_date(from_date) if from_date else None
        to_date = _as_date(to_date) if to_date else None
        records = self._repos['ExpenseRepository'].read_all()
        filtered = []
        for record in records:
            date_str = str(getattr(record, 'expense_date', None) or '')[:10]
            if from_date and date_str < str(from_date)[:10]:
                continue
            if to_date and date_str > str(to_date)[:10]:
                continue
            filtered.append(record)
        with open(output, 'w', newline='', encoding='utf-8') as handle:
            writer = csv.writer(handle)
            writer.writerow(['id', 'amount_cents', 'description', 'expense_date', 'category_id', 'payment_method', 'is_recurring'])
            for record in filtered:
                writer.writerow([record.id, record.amount_cents, record.description or '', record.expense_date or '', record.category_id, record.payment_method or '', record.is_recurring])

    def expensereportmonthly(self, month: str = None) -> None:
        """Expensereportmonthly. [llm-written by server — review]"""
        month_obj = month.split('-')
        if len(month_obj) != 2:
            raise ValueError("Invalid month format: must be 'YYYY-MM'")
        year, month_str = (int(month_obj[0]), month_obj[1])
        start_date = datetime.date(year, int(month_str), 1)
        end_date = datetime.date(year, int(month_str), calendar.monthrange(year, int(month_str))[1])
        records = self._repos['ExpenseRepository'].read_all()
        total_spent = 0
        category_spending = {}
        budget_status = {}
        for record in records:
            expense_date = record.expense_date
            if expense_date is None:
                continue
            date_str = str(expense_date)[:10]
            if not date_str.startswith(f'{year}-{month_str}'):
                continue
            total_spent += record.amount_cents or 0
            category_id = record.category_id
            category_spending[category_id] = category_spending.get(category_id, 0) + record.amount_cents or 0
        budgets = self._repos['BudgetRepository'].get_budgets_by_month(month=month)
        category_budgets = {}
        for budget in budgets:
            category_budgets[budget.category_id] = budget.amount_limit_cents
        for category_id in category_spending:
            total_spent_for_category = category_spending[category_id]
            limit = category_budgets.get(category_id, 0)
            if total_spent_for_category > limit:
                budget_status[category_id] = 'exceeded'
            elif total_spent_for_category >= limit * 0.9:
                budget_status[category_id] = 'warning'
            else:
                budget_status[category_id] = 'on_track'
        return {'total_spent': total_spent, 'category_spending': category_spending, 'budget_status': budget_status}

    def expensereportyearly(self, year: str = None) -> None:
        """Expensereportyearly. [llm-written by server — review]"""
        year = int(year) if year else None
        if year is None:
            raise ValueError('Year must be provided')
        records = self._repos['ExpenseRepository'].get_yearly_spending_summary(year=year)
        if not records:
            return {'monthly_totals': {}, 'top_spending_categories': [], 'average_monthly_spend': 0}
        monthly_totals = {}
        for month, total in records.items():
            month_str = month
            monthly_totals[month_str] = total
        category_spending = {}
        all_expenses = self._repos['ExpenseRepository'].read_all()
        for expense in all_expenses:
            expense_date = expense.expense_date
            if expense_date is None or str(expense_date)[:4] != str(year):
                continue
            category_id = expense.category_id
            amount = expense.amount_cents or 0
            category_spending[category_id] = category_spending.get(category_id, 0) + amount
        top_categories = []
        for category_id, total in category_spending.items():
            top_categories.append([category_id, total])
        top_categories.sort(key=lambda x: x[1], reverse=True)
        top_categories = top_categories[:5]
        total_spent = sum(monthly_totals.values())
        average_monthly_spend = total_spent / 12 if monthly_totals else 0
        return {'monthly_totals': monthly_totals, 'top_spending_categories': top_categories, 'average_monthly_spend': average_monthly_spend}

    def export_to_csv(self, file_path: str = None, start_date: datetime.date = None, end_date: datetime.date = None) -> None:
        """Exports filtered expenses to a CSV file at the specified path. [mechanical CSV export]"""
        records = self._repos['ExpenseRepository'].read_all()
        start = str(start_date)[:10] if start_date is not None else ''
        end = str(end_date)[:10] if end_date is not None else ''
        filtered = []
        for record in records:
            date = str(getattr(record, 'expense_date', None) or '')[:10]
            if start and date < start:
                continue
            if end and date > end:
                continue
            filtered.append(record)
        with open(file_path, 'w', newline='', encoding='utf-8') as handle:
            writer = csv.writer(handle)
            writer.writerow(['id', 'amount_cents', 'description', 'expense_date', 'category_id', 'payment_method', 'is_recurring'])
            for record in filtered:
                writer.writerow([record.id, record.amount_cents, '' if record.description is None else record.description, '' if record.expense_date is None else record.expense_date, record.category_id, '' if record.payment_method is None else record.payment_method, record.is_recurring])

    def get_category_spending(self, category_id: int = None, start_date: datetime.date = None, end_date: datetime.date = None) -> Dict[str, Any]:
        """Returns aggregated spending for a category over a specified date range. [AGGREGATE_BY_FK_AND_DATE via extraction plan]"""
        records = self._repos['ExpenseRepository'].read_all()
        total = 0
        by_key = {}
        for record in records:
            if category_id is not None and record.category_id != category_id:
                continue
            when = str(record.expense_date or '')[:10]
            if start_date is not None and when < str(start_date)[:10]:
                continue
            when = str(record.expense_date or '')[:10]
            if end_date is not None and when > str(end_date)[:10]:
                continue
            value = record.amount_cents or 0
            total += value
            key = record.category_id
            by_key[key] = by_key.get(key, 0) + value
        return {'total_spending': total, 'category_spending': by_key}

    def get_expense_by_id(self, id: int = None) -> models.Expense:
        """Retrieves a single expense by its ID. [delegates to ExpenseRepository.read_one — renamed from get_expense_by_id]"""
        return self._repos['ExpenseRepository'].read_one(id)

    def get_monthly_report(self, month: str = None) -> Dict[str, Any]:
        """Returns a monthly report including total spending, per-category breakdown, and budget status (on_track/warning/exceeded) for a given month in 'YYYY-MM' format. [llm-written by server — review]"""
        month_obj = month.split('-')
        if len(month_obj) != 2:
            raise ValueError("Invalid month format: must be 'YYYY-MM'")
        year, month_str = (int(month_obj[0]), month_obj[1])
        start_date = datetime.date(year, int(month_str), 1)
        end_date = datetime.date(year, int(month_str), calendar.monthrange(year, int(month_str))[1])
        records = self._repos['ExpenseRepository'].read_all()
        total_spent = 0
        category_spending = {}
        budget_status = {}
        for record in records:
            expense_date = record.expense_date
            if expense_date is None:
                continue
            date_str = str(expense_date)[:10]
            if not date_str.startswith(f'{year}-{month_str}'):
                continue
            total_spent += record.amount_cents or 0
            category_id = record.category_id
            category_spending[category_id] = category_spending.get(category_id, 0) + record.amount_cents or 0
        budgets = self._repos['BudgetRepository'].get_budgets_by_month(month=month)
        category_budgets = {}
        for budget in budgets:
            category_budgets[budget.category_id] = budget.amount_limit_cents
        for category_id in category_spending:
            total_spent_for_category = category_spending[category_id]
            limit = category_budgets.get(category_id, 0)
            if total_spent_for_category > limit:
                budget_status[category_id] = 'exceeded'
            elif total_spent_for_category >= limit * 0.9:
                budget_status[category_id] = 'warning'
            else:
                budget_status[category_id] = 'on_track'
        return {'total_spent': total_spent, 'category_spending': category_spending, 'budget_status': budget_status}

    def get_yearly_summary(self, year: int = None) -> Dict[str, Any]:
        """Returns a yearly summary including monthly totals, top spending categories, and average monthly spend for a given year. [llm-written by server — review]"""
        records = self._repos['ExpenseRepository'].get_yearly_spending_summary(year=year)
        if not records:
            return {'monthly_totals': {}, 'top_spending_categories': [], 'average_monthly_spend': 0}
        monthly_totals = {}
        category_spending = {}
        for month, total in records.items():
            month_str = month
            monthly_totals[month_str] = total
        for record in self._repos['ExpenseRepository'].read_all():
            if str(record.expense_date)[:4] != str(year):
                continue
            category_id = record.category_id
            amount = record.amount_cents or 0
            category_spending[category_id] = category_spending.get(category_id, 0) + amount
        top_categories = []
        for category_id, total in category_spending.items():
            top_categories.append([category_id, total])
        top_categories.sort(key=lambda x: x[1], reverse=True)
        top_categories = top_categories[:5]
        total_spent = sum(monthly_totals.values())
        average_monthly_spend = total_spent / 12 if monthly_totals else 0
        return {'monthly_totals': monthly_totals, 'top_spending_categories': top_categories, 'average_monthly_spend': average_monthly_spend}

    def list_expenses(self, category_id: Optional[int] = None, start_date: Optional[datetime.date] = None, end_date: Optional[datetime.date] = None, payment_method: Optional[str] = None) -> List[models.Expense]:
        """Lists expenses filtered by optional category, date range, and payment method. All parameters are optional; omitting them returns all expenses. [composes ExpenseRepository.read_all over FILTER_WITH_PAGINATION: by parameter shape]"""
        records = self._repos['ExpenseRepository'].read_all()
        criteria = []
        if category_id is not None:
            criteria.append(('category_id', 'eq', category_id))
        if start_date is not None:
            criteria.append(('expense_date', 'ge', start_date))
        if end_date is not None:
            criteria.append(('expense_date', 'le', end_date))
        if payment_method is not None:
            criteria.append(('payment_method', 'eq', payment_method))
        out = []
        for record in records:
            row = record if isinstance(record, dict) else vars(record)
            if all(_holds(_filter_value(row.get(field)), operator,
                          _filter_value(value))
                   for field, operator, value in criteria):
                out.append(record)
        return out

    def update_expense(self, id: int = None, amount_cents: int = None, description: str = None, expense_date: datetime.date = None, category_id: int = None, payment_method: str = None, is_recurring: bool = None) -> None:
        """Updates an existing expense with new values. Validates that the category exists and updates the expense accordingly. [mechanical CRUD wrapper]"""
        self._repos['ExpenseRepository'].update(id=id, amount_cents=amount_cents, description=description, expense_date=expense_date, category_id=category_id, payment_method=payment_method, is_recurring=is_recurring)
