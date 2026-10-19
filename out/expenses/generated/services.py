"""Services. A method with the same name as a repository method delegates
to it; anything else raises NotImplementedError with its work order.
"""

from typing import Any, Dict, List, Optional, Union

import calendar

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
    raise ValueError(f"unknown operator {operator!r}")



class ExpenseService:

    def __init__(self, repos):
        self._repos = repos


    def list_expenses(self, category_id: Optional[int] = None, start_date: Optional[str] = None, end_date: Optional[str] = None, payment_method: Optional[str] = None) -> List[models.Expense]:
        """Lists expenses filtered by optional category, date range, and payment method. [composes ExpenseRepository.read_all_expenses over FILTER_BY_FIELD]"""
        records = self._repos['ExpenseRepository'].read_all_expenses()
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
            if all(_holds(row.get(field), operator, value)
                   for field, operator, value in criteria):
                out.append(record)
        return out

    def get_expense_by_id(self, id: int = None) -> models.Expense:
        """Retrieves a single expense by its ID. [delegates to ExpenseRepository.read_expense_by_id — renamed from get_expense_by_id]"""
        return self._repos['ExpenseRepository'].read_expense_by_id(id)

    def add_expense(self, expense: models.Expense = None) -> None:
        """Adds a new expense, validates category, and checks budget. [budget guard over ExpenseRepository.get_monthly_expense_total]"""
        record = expense if isinstance(expense, dict) else vars(expense)
        month = str(record.get('expense_date') or '')[:7]
        if not month:
            raise ValueError(f"budget guard needs expense_date: without it the expense cannot be scoped to a month")
        current = self._repos['ExpenseRepository'].get_monthly_expense_total(month)
        try:
            budget = self._repos['BudgetRepository'].read_budget_by_category_and_month(record.get('category_id'), month)
        except (errors.BudgetExceededException, LookupError):
            budget = None  # no budget record: no limit to exceed
        if budget is not None:
            limit = budget.get('amount_limit_cents') if isinstance(budget, dict) else getattr(budget, 'amount_limit_cents', None)
            new_amount = record.get('amount_cents') or 0
            if limit is not None and current + new_amount > limit:
                raise errors.BudgetExceededException(f"exceeds budget limit of {limit}")
        return self._repos['ExpenseRepository'].create_expense(expense)

    def update_expense(self, id: int = None, expense_data: models.Expense = None) -> None:
        """Updates an existing expense. [delegates to ExpenseRepository.update_expense]"""
        return self._repos['ExpenseRepository'].update_expense(id, expense_data)

    def delete_expense(self, id: int = None) -> None:
        """Deletes an expense by its ID. [delegates to ExpenseRepository.delete_expense]"""
        return self._repos['ExpenseRepository'].delete_expense(id)

    def get_monthly_report(self, month: str = None) -> Dict[str, Any]:
        """Generates a monthly expense report with total spent, category breakdown, and budget status. [pattern AGGREGATE_BY_FK_AND_DATE: no mechanical reading]"""
        raise NotImplementedError(
            "ExpenseService.get_monthly_report: pattern AGGREGATE_BY_FK_AND_DATE: no mechanical reading")

    def get_yearly_summary(self, year: str = None) -> Dict[str, Any]:
        """Generates a yearly expense summary with monthly totals and top spending categories. [pattern AGGREGATE_BY_FK_AND_DATE: no mechanical reading]"""
        raise NotImplementedError(
            "ExpenseService.get_yearly_summary: pattern AGGREGATE_BY_FK_AND_DATE: no mechanical reading")

    def get_category_spending(self, category_id: int = None, start_date: str = None, end_date: str = None) -> int:
        """Calculates total spending for a category over a period. [delegates to ExpenseRepository.get_category_spending — pattern realized by target]"""
        return self._repos['ExpenseRepository'].get_category_spending(category_id, start_date, end_date)

    def export_to_csv(self, file_path: str = None, start_date: Optional[str] = None, end_date: Optional[str] = None) -> None:
        """Exports filtered expenses to a CSV file. [gap NO_PATTERN_IN_DOMAIN: FILTER_BY_FIELD refused (FILTER_BY_FIELD returns collection, but this method returns none (None))]"""
        raise NotImplementedError(
            "ExpenseService.export_to_csv: gap NO_PATTERN_IN_DOMAIN: FILTER_BY_FIELD refused (FILTER_BY_FIELD returns collection, but this method returns none (None))")

    def detect_recurring(self) -> List[models.Expense]:
        """Detects recurring expenses by checking for consistent monthly expenses. [rule signature-pagination: method needs custom logic]"""
        raise NotImplementedError(
            "ExpenseService.detect_recurring: rule signature-pagination: method needs custom logic")
