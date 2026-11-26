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
        """Adds a new expense, validates that the category exists, and checks if adding the expense exceeds the category's monthly budget for the given month. [llm-written by server — review]"""
        if amount_cents is None:
            raise ValueError('amount_cents is required')
        if category_id is None:
            raise ValueError('category_id is required')
        category = self._repos['CategoryRepository'].read_one(id=category_id)
        if category is None:
            raise errors.CategoryNotFoundError(f'Category with id {category_id} not found')
        expense_data = {'amount_cents': amount_cents, 'description': description or '', 'expense_date': expense_date or datetime.date.today().isoformat(), 'category_id': category_id, 'payment_method': payment_method or 'cash', 'is_recurring': is_recurring or False}
        created_expense = self._repos['ExpenseRepository'].create(amount_cents=expense_data['amount_cents'], description=expense_data['description'], expense_date=expense_data['expense_date'], category_id=expense_data['category_id'], payment_method=expense_data['payment_method'], is_recurring=expense_data['is_recurring'])
        month = created_expense.expense_date.strftime('%Y-%m')
        budget = self._repos['BudgetRepository'].get_budget_by_category_and_month(category_id=category_id, month=month)
        if budget is None:
            pass
        else:
            category_total = self._repos['ExpenseRepository'].get_category_expense_count(category_id=category_id)
            if category_total > budget.amount_limit_cents:
                raise errors.BudgetExceededException(f'Budget exceeded for category {category_id} in month {month}')
        return created_expense

    def update_expense(self, id: int = None, amount_cents: int = None, description: str = None, expense_date: datetime.date = None, category_id: int = None, payment_method: str = None, is_recurring: bool = None) -> Any:
        """Updates an existing expense with the provided data. Validates that the category exists and checks for budget exceedance after update. [llm-written by server — review]"""
        expense = self._repos['ExpenseRepository'].read_one(id=id)
        if expense is None:
            raise errors.ExpenseNotFoundError(f'Expense with id {id} not found')
        category_id = None
        if 'category_id' in locals() and category_id is not None:
            category_id = category_id
        if category_id is not None:
            category = self._repos['CategoryRepository'].read_one(id=category_id)
            if category is None:
                raise errors.CategoryNotFoundError(f'Category with id {category_id} not found')
        updated_expense = self._repos['ExpenseRepository'].update(id=id, amount_cents=amount_cents, description=description, expense_date=expense_date, category_id=category_id, payment_method=payment_method, is_recurring=is_recurring)
        if category_id is not None:
            budget_status = self._repos['BudgetRepository'].get_budget_by_category_and_month(category_id=category_id, month=expense.expense_date.strftime('%Y-%m'))
            if budget_status is not None:
                category_total = self._repos['ExpenseRepository'].get_category_expense_count(category_id=category_id)
                budget_limit = budget_status.amount_limit_cents
                if category_total > budget_limit:
                    raise errors.BudgetExceededException(f"Budget exceeded for category {category_id} in month {expense.expense_date.strftime('%Y-%m')}")
                elif category_total >= 0.9 * budget_limit:
                    pass
        return updated_expense

    def delete_expense(self, id: int = None) -> None:
        """Deletes an expense by its ID. [mechanical CRUD wrapper]"""
        self._repos['ExpenseRepository'].delete(id=id)

    def get_monthly_report(self, month: str = None) -> Dict[str, Any]:
        """Returns a monthly report including total spending, per-category breakdown, and budget status (on_track/warning/exceeded) for a given month in 'YYYY-MM' format. [llm-written by server — review]"""
        month_str = month or datetime.datetime.now().strftime('%Y-%m')
        year, month_part = month_str.split('-')
        start_date = datetime.date(int(year), int(month_part), 1)
        end_date = start_date + datetime.timedelta(days=calendar.monthrange(int(year), int(month_part))[1] - 1)
        records = self._repos['ExpenseRepository'].read_all()
        total_spent = 0
        category_spending = {}
        budget_status = {}
        for record in records:
            expense_date = getattr(record, 'expense_date', None)
            if expense_date is None:
                continue
            date_str = str(expense_date)[:10]
            if not date_str.startswith(f'{year}-{month_part}'):
                continue
            amount_cents = record.amount_cents or 0
            total_spent += amount_cents
            category_id = record.category_id
            if category_id is not None:
                category_spending[category_id] = category_spending.get(category_id, 0) + amount_cents
        for category_id in category_spending.keys():
            budget = self._repos['BudgetRepository'].get_budget_by_category_and_month(category_id=category_id, month=month_str)
            if budget is None:
                budget_status[category_id] = 'on_track'
            else:
                category_total = category_spending.get(category_id, 0)
                budget_limit = budget.amount_limit_cents
                if category_total > budget_limit:
                    budget_status[category_id] = 'exceeded'
                elif category_total >= 0.9 * budget_limit:
                    budget_status[category_id] = 'warning'
                else:
                    budget_status[category_id] = 'on_track'
        return {'total_spent': total_spent, 'category_spending': category_spending, 'budget_status': budget_status}

    def get_yearly_summary(self, year: int = None) -> Dict[str, Any]:
        """Returns a yearly summary including monthly totals, top spending categories, and average monthly spend. [llm-written by server — review]"""
        year = year or datetime.datetime.now().year
        year_str = str(year)
        monthly_totals = {}
        category_totals = {}
        category_spending = {}
        records = self._repos['ExpenseRepository'].read_all()
        for record in records:
            expense_date = getattr(record, 'expense_date', None)
            if expense_date is None:
                continue
            date_str = str(expense_date)[:10]
            if date_str[:4] != year_str:
                continue
            month = date_str[5:7]
            month_key = f'{year}-{month}'
            amount_cents = record.amount_cents or 0
            monthly_totals[month_key] = monthly_totals.get(month_key, 0) + amount_cents
            category_id = record.category_id
            if category_id is not None:
                category_key = str(category_id)
                category_totals[category_key] = category_totals.get(category_key, 0) + amount_cents
                category_spending[category_key] = category_spending.get(category_key, {})
                category_spending[category_key][month_key] = category_spending[category_key].get(month_key, 0) + amount_cents
        total_spent = sum(monthly_totals.values())
        average_monthly = total_spent / 12 if monthly_totals else 0
        top_categories = []
        for category_id, total in sorted(category_totals.items(), key=lambda x: x[1], reverse=True):
            top_categories.append([category_id, total])
        budget_status = {}
        for category_id in category_totals.keys():
            budget = self._repos['BudgetRepository'].get_budget_by_category_and_month(category_id=category_id, month=year_str)
            if budget is None:
                budget_status[category_id] = 'on_track'
            else:
                total_spent_this_year = category_totals.get(category_id, 0)
                budget_limit = budget.amount_limit_cents
                if total_spent_this_year > budget_limit:
                    budget_status[category_id] = 'exceeded'
                elif total_spent_this_year >= 0.9 * budget_limit:
                    budget_status[category_id] = 'warning'
                else:
                    budget_status[category_id] = 'on_track'
        return {'total_spent': total_spent, 'monthly_totals': monthly_totals, 'top_spending_categories': top_categories, 'budget_status': budget_status}

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
        month_str = month if month is not None else datetime.datetime.now().strftime('%Y-%m')
        year, month_part = month_str.split('-')
        start_date = datetime.date(int(year), int(month_part), 1)
        end_date = datetime.date(int(year), int(month_part), 1) + datetime.timedelta(days=calendar.monthrange(int(year), int(month_part))[1] - 1)
        records = self._repos['ExpenseRepository'].read_all()
        total_spent = 0
        category_spending = {}
        budget_status = {}
        for record in records:
            expense_date = getattr(record, 'expense_date', None)
            if expense_date is None:
                continue
            date_str = str(expense_date)[:10]
            if not date_str.startswith(f'{year}-{month_part}'):
                continue
            amount_cents = record.amount_cents or 0
            total_spent += amount_cents
            category_id = record.category_id
            if category_id is not None:
                category_spending[category_id] = category_spending.get(category_id, 0) + amount_cents
        for category_id in category_spending.keys():
            budget = self._repos['BudgetRepository'].get_budget_by_category_and_month(category_id=category_id, month=month_str)
            if budget is None:
                budget_status[category_id] = 'on_track'
            else:
                category_total = category_spending.get(category_id, 0)
                budget_limit = budget.amount_limit_cents
                if category_total > budget_limit:
                    budget_status[category_id] = 'exceeded'
                elif category_total >= 0.9 * budget_limit:
                    budget_status[category_id] = 'warning'
                else:
                    budget_status[category_id] = 'on_track'
        result = {'total_spent': total_spent, 'category_spending': category_spending, 'budget_status': budget_status}
        return result

    def expensereportyearly(self, year: str = None) -> None:
        """Expensereportyearly. [llm-written by server — review]"""
        year_str = year if year is not None else datetime.datetime.now().strftime('%Y')
        year_int = int(year_str)
        monthly_totals = {}
        category_totals = {}
        category_spending = {}
        records = self._repos['ExpenseRepository'].read_all()
        for record in records:
            expense_date = getattr(record, 'expense_date', None)
            if expense_date is None:
                continue
            date_str = str(expense_date)[:10]
            year_part = date_str[:4]
            if year_part != str(year_int):
                continue
            month = date_str[5:7]
            month_key = f'{year_int}-{month}'
            amount_cents = record.amount_cents or 0
            monthly_totals[month_key] = monthly_totals.get(month_key, 0) + amount_cents
            category_id = record.category_id
            if category_id is not None:
                category_key = str(category_id)
                category_totals[category_key] = category_totals.get(category_key, 0) + amount_cents
                category_spending[category_key] = category_spending.get(category_key, {})
                category_spending[category_key][month_key] = category_spending[category_key].get(month_key, 0) + amount_cents
        budget_status = {}
        for category_id in category_totals.keys():
            budget = self._repos['BudgetRepository'].get_budget_by_category_and_month(category_id=category_id, month=year_str)
            if budget is None:
                budget_status[category_id] = 'on_track'
            else:
                total_spent = monthly_totals.get(f'{year_int}-01', 0)
                category_monthly_spending = {}
                for month_key in monthly_totals.keys():
                    if month_key.startswith(f'{year_int}-'):
                        month_part = month_key[5:7]
                        category_monthly_spending[month_part] = monthly_totals[month_key]
                total_spent = sum(category_monthly_spending.values())
                budget_limit = budget.amount_limit_cents
                if total_spent > budget_limit:
                    budget_status[category_id] = 'exceeded'
                elif total_spent >= 0.9 * budget_limit:
                    budget_status[category_id] = 'warning'
                else:
                    budget_status[category_id] = 'on_track'
        total_spent = sum(monthly_totals.values())
        top_categories = []
        for category_id, total in sorted(category_totals.items(), key=lambda x: x[1], reverse=True):
            top_categories.append([str(category_id), total])
        result = {'total_spent': total_spent, 'monthly_totals': monthly_totals, 'top_spending_categories': top_categories, 'budget_status': budget_status}
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
