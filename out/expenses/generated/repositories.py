"""Repositories over an in-memory Store, one class per persistence port.

CRUD, reads and filters run for real. Anything else raises
NotImplementedError with its work order — an aggregate or guard body
is specified by its pattern, not invented here.
"""

from typing import Any, Dict, List, Optional, Union

import datetime

import models
import errors
from store import Store, match_criterion


def _record_values(data, field_names):
    """A dataclass or dict entity argument as a `{field: value}` dict."""
    if data is None:
        return {}
    if isinstance(data, dict):
        return {name: data.get(name) for name in field_names}
    return {name: getattr(data, name, None) for name in field_names}



class CategoryRepository:
    ENTITY = "Category"
    PK = "id"

    def __init__(self, store):
        self._store = store


    def create_category(self, category: models.Category = None) -> None:
        """Creates a new category record in the database. [crud:create: STANDARD_CRUD]"""
        values = _record_values(category, ['id', 'name', 'description', 'monthly_budget', 'icon'])
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[])
        return models.Category(**record)

    def read_category_by_id(self, id: int = None) -> models.Category:
        """Reads a category by its ID from the database. [crud:read_one: STANDARD_CRUD]"""
        record = self._store.get(self.ENTITY, self.PK, id, error=errors.CategoryNotFoundError)
        return models.Category(**record)

    def read_all_categories(self) -> List[models.Category]:
        """Reads all categories from the database. [crud:read_all: READ_ALL]"""
        criteria = []
        found = self._store.select(self.ENTITY, criteria)
        return [models.Category(**r) for r in found]

    def update_category(self, id: int = None, category: models.Category = None) -> None:
        """Updates an existing category record. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if id is not None:
            criteria.append(('id', 'eq', id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise errors.CategoryNotFoundError(f"Category update matched {len(found)} records")
        patch = {}
        for key, value in _record_values(category, ['id', 'name', 'description', 'monthly_budget', 'icon']).items():
            if value is not None:
                patch[key] = value
        if id is not None and 'id' in ['id', 'name', 'description', 'monthly_budget', 'icon']:
            patch['id'] = id
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=errors.CategoryNotFoundError)
        return models.Category(**record)

    def delete_category(self, id: int = None) -> None:
        """Deletes a category record from the database. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if id is not None:
            criteria.append(('id', 'eq', id))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise errors.CategoryNotFoundError(f"Category delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None

    def find_expenses_by_category(self, category_id: int = None) -> List[models.Expense]:
        """Finds all expenses associated with a category. [crud:filter: FILTER_BY_FIELD]"""
        criteria = []
        if category_id is not None:
            criteria.append(('category_id', 'eq', category_id))
        found = self._store.select('Expense', criteria)
        return [models.Expense(**r) for r in found]


class ExpenseRepository:
    ENTITY = "Expense"
    PK = "id"

    def __init__(self, store):
        self._store = store


    def create_expense(self, expense: models.Expense = None) -> None:
        """Creates a new expense record in the database. [crud:create: STANDARD_CRUD]"""
        values = _record_values(expense, ['id', 'amount_cents', 'description', 'expense_date', 'category_id', 'payment_method', 'is_recurring'])
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[("category_id", "Category", "id", errors.CategoryNotFoundError)])
        return models.Expense(**record)

    def read_expense_by_id(self, id: int = None) -> models.Expense:
        """Reads an expense by its ID from the database. [crud:read_one: STANDARD_CRUD]"""
        record = self._store.get(self.ENTITY, self.PK, id, error=errors.ExpenseNotFoundError)
        return models.Expense(**record)

    def read_expenses_by_category(self, category_id: int = None) -> List[models.Expense]:
        """Reads all expenses associated with a category. [crud:filter: FILTER_BY_FIELD: by parameter shape]"""
        criteria = []
        if category_id is not None:
            criteria.append(('category_id', 'eq', category_id))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Expense(**r) for r in found]

    def read_all_expenses(self) -> List[models.Expense]:
        """Reads all expenses from the database. [crud:read_all: READ_ALL]"""
        criteria = []
        found = self._store.select(self.ENTITY, criteria)
        return [models.Expense(**r) for r in found]

    def read_expenses_by_date_range(self, start_date: str = None, end_date: str = None) -> List[models.Expense]:
        """Reads expenses within a specified date range. [crud:filter: FILTER_WITH_PAGINATION: by parameter shape]"""
        criteria = []
        if start_date is not None:
            criteria.append(('expense_date', 'ge', start_date))
        if end_date is not None:
            criteria.append(('expense_date', 'le', end_date))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Expense(**r) for r in found]

    def read_expenses_by_payment_method(self, payment_method: str = None) -> List[models.Expense]:
        """Reads expenses by payment method. [crud:filter: FILTER_BY_FIELD: by parameter shape]"""
        criteria = []
        if payment_method is not None:
            criteria.append(('payment_method', 'eq', payment_method))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Expense(**r) for r in found]

    def read_expenses_by_category_and_payment_method(self, category_id: int = None, payment_method: str = None) -> List[models.Expense]:
        """Reads expenses by category and payment method. [crud:filter: FILTER_BY_FIELD: by parameter shape]"""
        criteria = []
        if category_id is not None:
            criteria.append(('category_id', 'eq', category_id))
        if payment_method is not None:
            criteria.append(('payment_method', 'eq', payment_method))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Expense(**r) for r in found]

    def update_expense(self, id: int = None, expense: models.Expense = None) -> None:
        """Updates an existing expense record. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if id is not None:
            criteria.append(('id', 'eq', id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise errors.ExpenseNotFoundError(f"Expense update matched {len(found)} records")
        patch = {}
        for key, value in _record_values(expense, ['id', 'amount_cents', 'description', 'expense_date', 'category_id', 'payment_method', 'is_recurring']).items():
            if value is not None:
                patch[key] = value
        if id is not None and 'id' in ['id', 'amount_cents', 'description', 'expense_date', 'category_id', 'payment_method', 'is_recurring']:
            patch['id'] = id
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=errors.ExpenseNotFoundError)
        return models.Expense(**record)

    def delete_expense(self, id: int = None) -> None:
        """Deletes an expense record from the database. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if id is not None:
            criteria.append(('id', 'eq', id))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise errors.ExpenseNotFoundError(f"Expense delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None

    def get_monthly_expense_total(self, month: str = None) -> int:
        """Calculates total expenses for a given month. [AGGREGATE_BY_FK_AND_DATE via answered slots: date_field=expense_date, target_field=amount_cents, aggregate_func=SUM]"""
        total = 0
        for record in self._store.select(self.ENTITY, []):
            if month is not None and not str(record.get('expense_date') or '').startswith(str(month)):
                continue
            total += record.get('amount_cents') or 0
        return total

    def get_yearly_expense_total(self, year: str = None) -> int:
        """Calculates total expenses for a given year. [AGGREGATE_BY_FK_AND_DATE via answered slots: date_field=expense_date, target_field=amount_cents, aggregate_func=SUM]"""
        total = 0
        for record in self._store.select(self.ENTITY, []):
            if year is not None and not str(record.get('expense_date') or '').startswith(str(year)):
                continue
            total += record.get('amount_cents') or 0
        return total

    def get_category_spending(self, category_id: int = None, start_date: str = None, end_date: str = None) -> int:
        """Calculates total spending for a category over a period. [AGGREGATE_BY_FK_AND_DATE via answered slots: fk_field=category_id, date_field=expense_date, target_field=amount_cents, aggregate_func=SUM]"""
        total = 0
        for record in self._store.select(self.ENTITY, []):
            if category_id is not None and record.get('category_id') != category_id:
                continue
            if start_date is not None and str(record.get('expense_date') or '') < str(start_date):
                continue
            if end_date is not None and str(record.get('expense_date') or '') > str(end_date):
                continue
            total += record.get('amount_cents') or 0
        return total

    def export_expenses_to_csv(self, file_path: str = None, start_date: str = None, end_date: str = None) -> None:
        """Exports expenses to a CSV file. [stub: gap NO_PATTERN_IN_DOMAIN: AGGREGATE_BY_FK_AND_DATE refused (AGGREGATE_BY_FK_AND_DATE returns mapping/scalar, but this method returns none (None))]"""
        raise NotImplementedError(
            "Expense.export_expenses_to_csv: stub: gap NO_PATTERN_IN_DOMAIN: AGGREGATE_BY_FK_AND_DATE refused (AGGREGATE_BY_FK_AND_DATE returns mapping/scalar, but this method returns none (None))")


class BudgetRepository:
    ENTITY = "Budget"
    PK = "id"

    def __init__(self, store):
        self._store = store


    def create_budget(self, budget: models.Budget = None) -> None:
        """Creates a new budget record in the database. [crud:create: STANDARD_CRUD]"""
        values = _record_values(budget, ['id', 'category_id', 'month', 'amount_limit_cents'])
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[("category_id", "Category", "id", errors.CategoryNotFoundError)])
        return models.Budget(**record)

    def read_budget_by_id(self, id: int = None) -> models.Budget:
        """Reads a budget by its ID from the database. [crud:read_one: STANDARD_CRUD]"""
        record = self._store.get(self.ENTITY, self.PK, id, error=errors.BudgetExceededException)
        return models.Budget(**record)

    def read_budget_by_category_and_month(self, category_id: int = None, month: str = None) -> models.Budget:
        """Reads a budget for a category and month. [crud:read_one: gap NO_PATTERN_IN_DOMAIN: AGGREGATE_BY_FK_AND_DATE refused (AGGREGATE_BY_FK_AND_DATE returns mapping/scalar, but this method returns entity (Budget)); read-one by parameter shape]"""
        criteria = []
        if category_id is not None:
            criteria.append(('category_id', 'eq', category_id))
        if month is not None:
            criteria.append(('month', 'eq', month))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise errors.BudgetExceededException(f"Budget lookup matched {len(found)} records")
        record = found[0]
        return models.Budget(**record)

    def read_all_budgets(self) -> List[models.Budget]:
        """Reads all budgets from the database. [crud:read_all: READ_ALL]"""
        criteria = []
        found = self._store.select(self.ENTITY, criteria)
        return [models.Budget(**r) for r in found]

    def update_budget(self, id: int = None, budget: models.Budget = None) -> None:
        """Updates an existing budget record. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if id is not None:
            criteria.append(('id', 'eq', id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise errors.BudgetExceededException(f"Budget update matched {len(found)} records")
        patch = {}
        for key, value in _record_values(budget, ['id', 'category_id', 'month', 'amount_limit_cents']).items():
            if value is not None:
                patch[key] = value
        if id is not None and 'id' in ['id', 'category_id', 'month', 'amount_limit_cents']:
            patch['id'] = id
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=errors.BudgetExceededException)
        return models.Budget(**record)

    def delete_budget(self, category_id: int = None, month: str = None) -> None:
        """Deletes a budget record from the fixed month and category. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if category_id is not None:
            criteria.append(('category_id', 'eq', category_id))
        if month is not None:
            criteria.append(('month', 'eq', month))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise errors.BudgetExceededException(f"Budget delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None

    def check_budget_status(self, category_id: int = None, month: str = None) -> bool:
        """Checks if a category has exceeded its budget for a given month. [BUDGET_OVERFLOW_GUARD via answered slots: limit_field=amount_limit_cents, target_field=amount_cents, date_field=expense_date, spend_entity=Expense]"""
        if not (month):
            raise ValueError("budget check needs a month scope: an empty month matches every record")
        budgets = self._store.select(self.ENTITY, [])
        match = [record for record in budgets
                    if record.get('category_id') == category_id
                    if record.get('month') == month
        ]
        if not match:
            return True  # no budget record: no limit to exceed
        limit = match[0].get('amount_limit_cents')
        spent = 0
        for record in self._store.select('Expense', []):
            if record.get('category_id') != category_id:
                continue
            if not str(record.get('expense_date') or '').startswith(month):
                continue
            spent += record.get('amount_cents') or 0
        return spent <= limit if limit is not None else True
