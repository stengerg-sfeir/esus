"""Services. A method with the same name as a repository method delegates
to it; anything else raises NotImplementedError with its work order.
"""

from typing import Any, Dict, List, Optional, Union

import calendar

import models
import errors
from store import match_criterion
import csv


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
        """Generates a monthly expense report with total spent, category breakdown, and budget status. [llm-written by Ministral-3-3B-Instruct-2512-Q4_K_M.gguf — review]"""
        category_expenses = self._repos['ExpenseRepository'].read_expenses_by_category(category_id)
        monthly_expenses = {}
        for expense in category_expenses:
            month = expense.expense_date[:7]
            if month not in monthly_expenses:
                monthly_expenses[month] = []
            monthly_expenses[month].append(expense)

        total_spent = sum(expense.amount_cents for expense in monthly_expenses[month])

        category_spending = {}
        for expense in monthly_expenses[month]:
            category_id = expense.category_id
            if category_id not in category_spending:
                category_spending[category_id] = 0
            category_spending[category_id] += expense.amount_cents

        budget_status = self._repos['BudgetRepository'].check_budget_status(category_id, month)

        return {
            'total_spent': total_spent,
            'category_spending': category_spending,
            'budget_status': budget_status
        }

    def get_yearly_summary(self, year: str = None) -> Dict[str, Any]:
        """Generates a yearly expense summary with monthly totals and top spending categories. [llm-written by Ministral-3-3B-Instruct-2512-Q4_K_M.gguf — review]"""
        expenses = self._repos['ExpenseRepository'].read_all_expenses()
        monthly_totals = {}
        for expense in expenses:
            month = expense.expense_date[:7]
            if month not in monthly_totals:
                monthly_totals[month] = 0
            monthly_totals[month] += expense.amount_cents

        top_categories = {}
        for expense in expenses:
            category_id = expense.category_id
            if category_id not in top_categories:
                top_categories[category_id] = 0
            top_categories[category_id] += expense.amount_cents

        # Sort top categories by total spending
        sorted_categories = sorted(top_categories.items(), key=lambda x: x[1], reverse=True)

        # Calculate average monthly spend
        total_spend = sum(monthly_totals.values())
        num_months = len(monthly_totals)
        average_monthly_spend = total_spend / num_months if num_months > 0 else 0

        return {
            'monthly_totals': monthly_totals,
            'top_categories': sorted_categories,
            'average_monthly_spend': average_monthly_spend
        }

    def get_category_spending(self, category_id: int = None, start_date: str = None, end_date: str = None) -> int:
        """Calculates total spending for a category over a period. [delegates to ExpenseRepository.get_category_spending — pattern realized by target]"""
        return self._repos['ExpenseRepository'].get_category_spending(category_id, start_date, end_date)

    def export_to_csv(self, file_path: str = None, start_date: Optional[str] = None, end_date: Optional[str] = None) -> None:
        """Exports filtered expenses to a CSV file. [llm-written by Ministral-3-3B-Instruct-2512-Q4_K_M.gguf — review]"""
        expenses = self.list_expenses(start_date=start_date, end_date=end_date)
        with open(file_path, 'w', newline='') as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(['ID', 'Amount (cents)', 'Description', 'Expense Date', 'Category ID', 'Payment Method', 'Is Recurring'])

            for expense in expenses:
                writer.writerow([
                    expense.id,
                    expense.amount_cents,
                    expense.description,
                    expense.expense_date,
                    expense.category_id,
                    expense.payment_method,
                    expense.is_recurring
                ])

    def detect_recurring(self) -> List[models.Expense]:
        """Detects recurring expenses by checking for consistent monthly expenses. [llm-written by Ministral-3-3B-Instruct-2512-Q4_K_M.gguf — review]"""
        expenses = self._repos['ExpenseRepository'].read_all_expenses()
        recurring_expenses = []

        for expense in expenses:
            if expense.is_recurring:
                continue

            category_id = expense.category_id
            category_expenses = self._repos['ExpenseRepository'].read_expenses_by_category(category_id)

            # Group expenses by month
            monthly_expenses = {}
            for exp in category_expenses:
                month = exp.expense_date[:7]  # Format as YYYY-MM
                if month not in monthly_expenses:
                    monthly_expenses[month] = []
                monthly_expenses[month].append(exp)

            # Check for recurring pattern
            for month, expenses_in_month in monthly_expenses.items():
                if len(expenses_in_month) > 1:
                    # Check if all expenses in the month have the same amount
                    amounts = [exp.amount_cents for exp in expenses_in_month]
                    if len(set(amounts)) == 1:
                        # Check if the same amount appears in consecutive months
                        for i in range(len(monthly_expenses) - 1):
                            current_month = monthly_expenses.keys()[i]
                            next_month = monthly_expenses.keys()[i + 1]
                            current_amounts = [exp.amount_cents for exp in monthly_expenses[current_month]]
                            next_amounts = [exp.amount_cents for exp in monthly_expenses[next_month]]
                            if current_amounts == next_amounts:
                                recurring_expenses.append(expense)

        return recurring_expenses
