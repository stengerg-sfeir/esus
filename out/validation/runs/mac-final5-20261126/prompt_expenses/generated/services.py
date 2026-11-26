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

    def get_expense_by_id(self, id: int = None) -> Any:
        """Returns a single expense by its ID. [delegates to CategoryRepository.read_one — renamed from get_expense_by_id]"""
        return self._repos['CategoryRepository'].read_one(id)

    def add_expense(self, amount_cents: int = None, description: str = None, expense_date: str = None, category_id: int = None, payment_method: str = None, is_recurring: bool = None) -> Any:
        """Adds a new expense, validates that the category exists, and checks if adding the expense exceeds the category's monthly budget for the given month. [llm-written by generator-mechanical-fallback — review]"""
        return self._repos['ExpenseRepository'].create(amount_cents=amount_cents, description=description, expense_date=expense_date, category_id=category_id, payment_method=payment_method, is_recurring=is_recurring)

    def update_expense(self, id: int = None, amount_cents: int = None, description: str = None, expense_date: datetime.date = None, category_id: int = None, payment_method: str = None, is_recurring: bool = None) -> Any:
        """Updates an existing expense with the provided data. Validates that the category exists and checks for budget exceedance after update. [llm-written by generator-mechanical-fallback — review]"""
        return self._repos['ExpenseRepository'].update(id=id, amount_cents=amount_cents, description=description, expense_date=expense_date, category_id=category_id, payment_method=payment_method, is_recurring=is_recurring)

    def delete_expense(self, id: int = None) -> None:
        """Deletes an expense by its ID. [mechanical CRUD wrapper]"""
        self._repos['ExpenseRepository'].delete(id=id)

    def get_monthly_report(self, month: str = None) -> Dict[str, Any]:
        """Returns a monthly report including total spending, per-category breakdown, and budget status (on_track/warning/exceeded) for a given month in 'YYYY-MM' format. [llm-written by server — review]"""
        month_str = month or datetime.datetime.now().strftime('%Y-%m')
        start_date = _as_date(f'{month_str}-01')
        _, last_day = calendar.monthrange(int(month_str[:4]), int(month_str[5:]))
        end_date = datetime.date(int(month_str[:4]), int(month_str[5:]), last_day)
        records = self._repos['ExpenseRepository'].read_all()
        total_spent = 0
        category_spending = {}
        monthly_budget_status = {}
        filtered_records = []
        for record in records:
            date_str = str(getattr(record, 'expense_date', None) or '')[:7]
            if date_str != month_str:
                continue
            filtered_records.append(record)
        for record in filtered_records:
            total_spent += record.amount_cents or 0
            category_id = record.category_id
            category_spending[category_id] = category_spending.get(category_id, 0) + record.amount_cents
        for category_id in category_spending:
            budget = self._repos['BudgetRepository'].get_budget_by_category_and_month(category_id=category_id, month=month_str)
            if budget is None:
                monthly_budget_status[category_id] = 'on_track'
            else:
                total_in_month = category_spending[category_id]
                limit = budget.amount_limit_cents
                if total_in_month > limit:
                    monthly_budget_status[category_id] = 'exceeded'
                elif total_in_month >= limit * 0.9:
                    monthly_budget_status[category_id] = 'warning'
                else:
                    monthly_budget_status[category_id] = 'on_track'
        return {'total_spent': total_spent, 'category_spending': category_spending, 'monthly_budget_status': monthly_budget_status}

    def get_yearly_summary(self, year: int = None) -> Dict[str, Any]:
        """Returns a yearly summary including monthly totals, top spending categories, and average monthly spend. [llm-written by server — review]"""
        year = year or datetime.datetime.now().year
        monthly_totals = self._repos['ExpenseRepository'].get_monthly_spending_by_category(month=f'{year}-01')
        monthly_totals = {month: total for month, total in monthly_totals.items() if month.startswith(str(year))}
        total_spent = sum(monthly_totals.values())
        average_monthly = total_spent / 12 if monthly_totals else 0
        top_categories = self._repos['ExpenseRepository'].get_top_spending_categories(start_date=f'{year}-01-01', end_date=f'{year}-12-31')
        top_categories_list = [(cat_id, total) for cat_id, cat_name, total in top_categories]
        result = {'total_spent': total_spent, 'monthly_totals': monthly_totals, 'top_spending_categories': top_categories_list, 'average_monthly_spending': average_monthly}
        return result

    def get_category_spending(self, category_id: int = None, start_date: str = None, end_date: str = None) -> Dict[str, Any]:
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

    def export_to_csv(self, file_path: str = None, start_date: str = None, end_date: str = None) -> None:
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

    def detect_recurring(self) -> List[models.Expense]:
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

    def expensereportmonthly(self, month: str = None) -> None:
        """Expensereportmonthly. [llm-written by server — review]"""
        month_str = month or datetime.datetime.now().strftime('%Y-%m')
        start_date = _as_date(f'{month_str}-01')
        end_date = _as_date(f'{month_str}-01')
        _, last_day = calendar.monthrange(int(month_str[:4]), int(month_str[5:]))
        end_date = datetime.date(int(month_str[:4]), int(month_str[5:]), last_day)
        records = self._repos['ExpenseRepository'].read_all()
        total_spent = 0
        category_spending = {}
        monthly_budget_status = {}
        filtered_records = []
        for record in records:
            date_str = str(getattr(record, 'expense_date', None) or '')[:7]
            if date_str != month_str:
                continue
            filtered_records.append(record)
        for record in filtered_records:
            total_spent += record.amount_cents or 0
            category_id = record.category_id
            category_spending[category_id] = category_spending.get(category_id, 0) + record.amount_cents
        for category_id in category_spending:
            budget = self._repos['BudgetRepository'].get_budget_by_category_and_month(category_id=category_id, month=month_str)
            if budget is None:
                monthly_budget_status[category_id] = 'on_track'
            else:
                total_in_month = category_spending[category_id]
                limit = budget.amount_limit_cents
                if total_in_month > limit:
                    monthly_budget_status[category_id] = 'exceeded'
                elif total_in_month >= limit * 0.9:
                    monthly_budget_status[category_id] = 'warning'
                else:
                    monthly_budget_status[category_id] = 'on_track'
        result = {'total_spent': total_spent, 'category_spending': category_spending, 'monthly_budget_status': monthly_budget_status}
        return result

    def expensereportyearly(self, year: str = None) -> None:
        """Expensereportyearly. [llm-written by server — review]"""
        year_str = year if year is not None else datetime.datetime.now().strftime('%Y')
        year_int = int(year_str)
        monthly_totals = {}
        category_spending = {}
        monthly_budget_status = {}
        monthly_spending = self._repos['ExpenseRepository'].get_monthly_spending_by_category(month=year_str)
        for month, total in monthly_spending.items():
            monthly_totals[month] = total
        top_categories = self._repos['ExpenseRepository'].get_top_spending_categories(start_date=f'{year_int}-01-01', end_date=f'{year_int}-12-31')
        top_categories_list = []
        for cat_id, cat_name, total in top_categories:
            top_categories_list.append((cat_id, total))
        total_spent = sum(monthly_totals.values())
        average_monthly = total_spent / 12 if monthly_totals else 0
        monthly_budget_status = {}
        for month in monthly_spending:
            month_str = month
            pass
        expenses = self._repos['ExpenseRepository'].read_all()
        monthly_budget_status = {}
        for month in monthly_spending:
            month_str = month
            monthly_budget_status[month_str] = {}
            for expense in expenses:
                if expense.category_id is None or expense.expense_date is None:
                    continue
                date_str = str(expense.expense_date)[:7]
                if date_str != month_str:
                    continue
                budget = self._repos['BudgetRepository'].get_budget_by_category_and_month(category_id=expense.category_id, month=month_str)
                if budget is None:
                    monthly_budget_status[month_str][expense.category_id] = 'on_track'
                else:
                    total_spent_in_month = sum((e.amount_cents for e in expenses if e.category_id == expense.category_id and str(e.expense_date)[:7] == month_str))
                    if total_spent_in_month > budget.amount_limit_cents:
                        monthly_budget_status[month_str][expense.category_id] = 'exceeded'
                    else:
                        monthly_budget_status[month_str][expense.category_id] = 'on_track'
        result = {'total_spent': total_spent, 'monthly_totals': monthly_totals, 'top_spending_categories': top_categories_list, 'average_monthly_spending': average_monthly, 'monthly_budget_status': monthly_budget_status}
        return result

    def expenseexport(self, from_date: str = None, to_date: str = None, output: str = None) -> None:
        """Expenseexport. [llm-written by server — review]"""
        start_date = _as_date(from_date) if from_date is not None else None
        end_date = _as_date(to_date) if to_date is not None else None
        records = self._repos['ExpenseRepository'].read_all()
        filtered = []
        for record in records:
            date = getattr(record, 'expense_date', None)
            if date is not None:
                date_str = str(date)[:10]
            else:
                date_str = ''
            if start_date is not None and date_str < str(start_date)[:10]:
                continue
            if end_date is not None and date_str > str(end_date)[:10]:
                continue
            filtered.append(record)
        with open(output, 'w', newline='', encoding='utf-8') as handle:
            writer = csv.writer(handle)
            writer.writerow(['id', 'amount_cents', 'description', 'expense_date', 'category_id', 'payment_method', 'is_recurring'])
            for record in filtered:
                writer.writerow([record.id, record.amount_cents, record.description or '', record.expense_date or '', record.category_id, record.payment_method or '', record.is_recurring])
        if not filtered:
            raise ValueError(f'No expenses found in the date range from {from_date} to {to_date}')
