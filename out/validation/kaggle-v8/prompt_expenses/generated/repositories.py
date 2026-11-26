"""Repositories over an in-memory Store, one class per persistence port.

CRUD, reads and filters run for real. Anything else raises
NotImplementedError with its work order — an aggregate or guard body
is specified by its pattern, not invented here.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple, Union

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


def _model_list(records, model_cls):
    """Model objects from records, deduplicated by stable id."""
    out = []
    seen = set()
    if records is None:
        records = []
    elif isinstance(records, dict) or isinstance(records, (str, bytes)) \
            or not hasattr(records, '__iter__'):
        records = [records]
    for record in records:
        if isinstance(record, dict):
            key = record.get('id')
            item = model_cls(**record)
        else:
            key = getattr(record, 'id', None)
            item = record
        if key is not None:
            if key in seen:
                continue
            seen.add(key)
        out.append(item)
    return out



class CategoryRepository:
    ENTITY = "Category"
    PK = "id"

    def __init__(self, store):
        self._store = store


    def create(self, name: str = None, description: str = None, monthly_budget: int = None, icon: str = None) -> Any:
        """Creates a new Category. [crud:create: STANDARD_CRUD]"""
        values = {}
        if name is not None:
            values['name'] = name
        if description is not None:
            values['description'] = description
        if monthly_budget is not None:
            values['monthly_budget'] = monthly_budget
        if icon is not None:
            values['icon'] = icon
        unknown = [k for k in values if k not in ['id', 'name', 'description', 'monthly_budget', 'icon']]
        if unknown:
            raise ValueError(f"cannot create Category from {unknown}")
        for unique_field in ['name']:
            value = values.get(unique_field)
            if value is not None and self._store.select(self.ENTITY, [(unique_field, 'eq', value)]):
                raise ValueError(f"Category with {unique_field}={value!r} already exists")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[])
        return models.Category(**record)

    def read_one(self, id: int = None) -> Any:
        """Reads one Category by its key. [crud:read_one: READ_ONE_BY_ID]"""
        record = self._store.get(self.ENTITY, self.PK, id, error=errors.CategoryNotFoundError)
        return models.Category(**record)

    def read_all(self, name: str = None, description: str = None, monthly_budget: int = None, icon: str = None) -> list[models.Category]:
        """Lists every Category; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if name is not None:
            criteria.append(('name', 'eq', name))
        if description is not None:
            criteria.append(('description', 'eq', description))
        if monthly_budget is not None:
            criteria.append(('monthly_budget', 'eq', monthly_budget))
        if icon is not None:
            criteria.append(('icon', 'eq', icon))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Category(**r) for r in found]

    def update(self, id: int = None, name: str = None, description: str = None, monthly_budget: int = None, icon: str = None) -> Any:
        """Updates an existing Category. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if id is not None:
            criteria.append(('id', 'eq', id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise errors.CategoryNotFoundError(f"Category update matched {len(found)} records")
        patch = {}
        if id is not None and 'id' in ['id', 'name', 'description', 'monthly_budget', 'icon']:
            patch['id'] = id
        if name is not None and 'name' in ['id', 'name', 'description', 'monthly_budget', 'icon']:
            patch['name'] = name
        if description is not None and 'description' in ['id', 'name', 'description', 'monthly_budget', 'icon']:
            patch['description'] = description
        if monthly_budget is not None and 'monthly_budget' in ['id', 'name', 'description', 'monthly_budget', 'icon']:
            patch['monthly_budget'] = monthly_budget
        if icon is not None and 'icon' in ['id', 'name', 'description', 'monthly_budget', 'icon']:
            patch['icon'] = icon
        for unique_field in ['name']:
            value = patch.get(unique_field)
            if value is not None and any(row.get(self.PK) != found[0][self.PK] for row in self._store.select(self.ENTITY, [(unique_field, 'eq', value)])):
                raise ValueError(f"Category with {unique_field}={value!r} already exists")
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=errors.CategoryNotFoundError)
        return models.Category(**record)

    def delete(self, id: int = None, name: str = None, description: str = None, monthly_budget: int = None, icon: str = None) -> None:
        """Deletes an existing Category. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if id is not None:
            criteria.append(('id', 'eq', id))
        if name is not None:
            criteria.append(('name', 'eq', name))
        if description is not None:
            criteria.append(('description', 'eq', description))
        if monthly_budget is not None:
            criteria.append(('monthly_budget', 'eq', monthly_budget))
        if icon is not None:
            criteria.append(('icon', 'eq', icon))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise errors.CategoryNotFoundError(f"Category delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None


class ExpenseRepository:
    ENTITY = "Expense"
    PK = "id"

    def __init__(self, store):
        self._store = store


    def create(self, amount_cents: int = None, description: str = None, expense_date: Any = None, category_id: int = None, payment_method: str = None, is_recurring: bool = None) -> Any:
        """Creates a new Expense. [crud:create: STANDARD_CRUD]"""
        values = {}
        if amount_cents is not None:
            values['amount_cents'] = amount_cents
        if description is not None:
            values['description'] = description
        if expense_date is not None:
            values['expense_date'] = expense_date
        if category_id is not None:
            values['category_id'] = category_id
        if payment_method is not None:
            values['payment_method'] = payment_method
        if is_recurring is not None:
            values['is_recurring'] = is_recurring
        unknown = [k for k in values if k not in ['id', 'amount_cents', 'description', 'expense_date', 'category_id', 'payment_method', 'is_recurring']]
        if unknown:
            raise ValueError(f"cannot create Expense from {unknown}")
        if values.get('payment_method') is None:
            values['payment_method'] = 'cash'
        if values.get('payment_method') not in ['cash', 'card', 'transfer']:
            raise ValueError(f"Expense.payment_method must be one of ['cash', 'card', 'transfer']")
        if values.get('is_recurring') is None:
            values['is_recurring'] = False
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[("category_id", "Category", "id", errors.CategoryNotFoundError)])
        return models.Expense(**record)

    def read_one(self, id: int = None) -> Any:
        """Reads one Expense by its key. [crud:read_one: READ_ONE_BY_ID]"""
        record = self._store.get(self.ENTITY, self.PK, id, error=errors.ExpenseNotFoundError)
        return models.Expense(**record)

    def read_all(self, amount_cents: int = None, description: str = None, expense_date: Any = None, category_id: int = None, payment_method: str = None, is_recurring: bool = None) -> list[models.Expense]:
        """Lists every Expense; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if amount_cents is not None:
            criteria.append(('amount_cents', 'eq', amount_cents))
        if description is not None:
            criteria.append(('description', 'eq', description))
        if expense_date is not None:
            criteria.append(('expense_date', 'eq', expense_date))
        if category_id is not None:
            criteria.append(('category_id', 'eq', category_id))
        if payment_method is not None:
            criteria.append(('payment_method', 'eq', payment_method))
        if is_recurring is not None:
            criteria.append(('is_recurring', 'eq', is_recurring))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Expense(**r) for r in found]

    def update(self, id: int = None, amount_cents: int = None, description: str = None, expense_date: Any = None, category_id: int = None, payment_method: str = None, is_recurring: bool = None) -> Any:
        """Updates an existing Expense. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if id is not None:
            criteria.append(('id', 'eq', id))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise errors.ExpenseNotFoundError(f"Expense update matched {len(found)} records")
        patch = {}
        if id is not None and 'id' in ['id', 'amount_cents', 'description', 'expense_date', 'category_id', 'payment_method', 'is_recurring']:
            patch['id'] = id
        if amount_cents is not None and 'amount_cents' in ['id', 'amount_cents', 'description', 'expense_date', 'category_id', 'payment_method', 'is_recurring']:
            patch['amount_cents'] = amount_cents
        if description is not None and 'description' in ['id', 'amount_cents', 'description', 'expense_date', 'category_id', 'payment_method', 'is_recurring']:
            patch['description'] = description
        if expense_date is not None and 'expense_date' in ['id', 'amount_cents', 'description', 'expense_date', 'category_id', 'payment_method', 'is_recurring']:
            patch['expense_date'] = expense_date
        if category_id is not None and 'category_id' in ['id', 'amount_cents', 'description', 'expense_date', 'category_id', 'payment_method', 'is_recurring']:
            patch['category_id'] = category_id
        if payment_method is not None and 'payment_method' in ['id', 'amount_cents', 'description', 'expense_date', 'category_id', 'payment_method', 'is_recurring']:
            patch['payment_method'] = payment_method
        if is_recurring is not None and 'is_recurring' in ['id', 'amount_cents', 'description', 'expense_date', 'category_id', 'payment_method', 'is_recurring']:
            patch['is_recurring'] = is_recurring
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=errors.ExpenseNotFoundError)
        return models.Expense(**record)

    def delete(self, id: int = None, amount_cents: int = None, description: str = None, expense_date: Any = None, category_id: int = None, payment_method: str = None, is_recurring: bool = None) -> None:
        """Deletes an existing Expense. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if id is not None:
            criteria.append(('id', 'eq', id))
        if amount_cents is not None:
            criteria.append(('amount_cents', 'eq', amount_cents))
        if description is not None:
            criteria.append(('description', 'eq', description))
        if expense_date is not None:
            criteria.append(('expense_date', 'eq', expense_date))
        if category_id is not None:
            criteria.append(('category_id', 'eq', category_id))
        if payment_method is not None:
            criteria.append(('payment_method', 'eq', payment_method))
        if is_recurring is not None:
            criteria.append(('is_recurring', 'eq', is_recurring))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise errors.ExpenseNotFoundError(f"Expense delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None

    def find_expenses_by_date_range(self, start_date: Any = None, end_date: Any = None, category_id: int = None, payment_method: str = None) -> List[models.Expense]:
        """Returns a list of expenses filtered by start and end date (inclusive), optionally filtered by category and payment method. [crud:filter: FILTER_BY_FIELD]"""
        criteria = []
        if start_date is not None:
            criteria.append(('expense_date', 'ge', start_date))
        if end_date is not None:
            criteria.append(('expense_date', 'le', end_date))
        if category_id is not None:
            criteria.append(('category_id', 'eq', category_id))
        if payment_method is not None:
            criteria.append(('payment_method', 'eq', payment_method))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Expense(**r) for r in found]

    def get_monthly_spending_by_category(self, month: str = None) -> Dict[str, int]:
        """Returns a dictionary mapping category names to total spending in cents for a given month. [AGGREGATE_BY_FK_AND_DATE via answered slots: date_field=expense_date, target_field=amount_cents, aggregate_func=SUM]"""
        total = 0
        for record in self._store.select(self.ENTITY, []):
            if month is not None and not str(record.get('expense_date') or '').startswith(str(month)):
                continue
            total += record.get('amount_cents') or 0
        return total

    def get_yearly_spending_summary(self, year: int = None) -> Dict[str, Dict[str, int]]:
        """Returns a dictionary with monthly totals and top spending categories by total amount. [AGGREGATE_BY_FK_AND_DATE via answered slots: date_field=expense_date, target_field=amount_cents, aggregate_func=SUM]"""
        total = 0
        for record in self._store.select(self.ENTITY, []):
            if year is not None and not str(record.get('expense_date') or '').startswith(str(year)):
                continue
            total += record.get('amount_cents') or 0
        return total

    def get_category_expense_count(self, category_id: int = None) -> int:
        """Returns the number of expenses associated with a given category. [AGGREGATE_BY_FK via answered slots: fk_field=category_id, target_field=amount_cents, aggregate_func=COUNT]"""
        count = 0
        for record in self._store.select(self.ENTITY, []):
            if category_id is not None and record.get('category_id') != category_id:
                continue
            count += 1
        return count

    def get_budget_status_for_category(self, category_id: int = None, month: str = None) -> str:
        """Returns whether a category's budget is on_track, warning, or exceeded for a given month. [llm-written by server — review]"""
        if not month:
            raise ValueError("budget check needs a month scope: an empty month matches every record")
        if category_id is None:
            raise ValueError("category_id is required to check budget status")

        # Find the budget for the given category and month
        budget_record = self._store.select(self.ENTITY, [
            ('category_id', 'eq', category_id),
            ('month', 'eq', month)
        ])

        if not budget_record:
            return "on_track"  # No budget set, so no violation

        budget = budget_record[0]
        limit_cents = budget.get('amount_limit_cents')

        if limit_cents is None:
            return "on_track"  # No limit set, so no violation

        # Calculate total spending for the category in the given month
        total_spent = 0
        for expense_record in self._store.select('Expense', []):
            expense_date_str = str(expense_record.get('expense_date') or '')
            if not expense_date_str:
                continue
            # Normalize date to YYYY-MM-DD format for comparison
            date_str = expense_date_str[:10]
            month_str = date_str[:7]
            if month_str != month:
                continue
            if expense_record.get('category_id') != category_id:
                continue
            total_spent += expense_record.get('amount_cents') or 0

        # Determine status based on spending vs limit
        if total_spent > limit_cents:
            return "exceeded"
        elif total_spent >= limit_cents * 0.9:
            return "warning"
        else:
            return "on_track"


class BudgetRepository:
    ENTITY = "Budget"
    PK = "id"

    def __init__(self, store):
        self._store = store


    def create(self, category_id: int = None, month: str = None, amount_limit_cents: int = None) -> Any:
        """Creates a new Budget. [crud:create: STANDARD_CRUD]"""
        values = {}
        if category_id is not None:
            values['category_id'] = category_id
        if month is not None:
            values['month'] = month
        if amount_limit_cents is not None:
            values['amount_limit_cents'] = amount_limit_cents
        unknown = [k for k in values if k not in ['id', 'category_id', 'month', 'amount_limit_cents']]
        if unknown:
            raise ValueError(f"cannot create Budget from {unknown}")
        record = self._store.add(self.ENTITY, self.PK, values, check_fk=[("category_id", "Category", "id", errors.CategoryNotFoundError)])
        return models.Budget(**record)

    def read_all(self, category_id: int = None, month: str = None, amount_limit_cents: int = None) -> list[models.Budget]:
        """Lists every Budget; optional fields narrow the result. [crud:read_all: FILTER_BY_FIELD]"""
        criteria = []
        if category_id is not None:
            criteria.append(('category_id', 'eq', category_id))
        if month is not None:
            criteria.append(('month', 'eq', month))
        if amount_limit_cents is not None:
            criteria.append(('amount_limit_cents', 'eq', amount_limit_cents))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Budget(**r) for r in found]

    def read_one(self, id: int = None) -> Any:
        """Reads one Budget by its key. [crud:read_one: READ_ONE_BY_ID]"""
        found = self._store.select(self.ENTITY, [(self.PK, 'eq', id)])
        if not found:
            return None
        record = found[0]
        return models.Budget(**record)

    def update(self, id: int = None, category_id: int = None, month: str = None, amount_limit_cents: int = None) -> Any:
        """Updates an existing Budget. [crud:update: STANDARD_CRUD]"""
        criteria = []
        if id is not None:
            criteria.append(('id', 'eq', id))
        if category_id is not None:
            criteria.append(('category_id', 'eq', category_id))
        if month is not None:
            criteria.append(('month', 'eq', month))
        found = self._store.select(self.ENTITY, criteria)
        if len(found) != 1:
            raise LookupError(f"Budget update matched {len(found)} records")
        patch = {}
        if id is not None and 'id' in ['id', 'category_id', 'month', 'amount_limit_cents']:
            patch['id'] = id
        if category_id is not None and 'category_id' in ['id', 'category_id', 'month', 'amount_limit_cents']:
            patch['category_id'] = category_id
        if month is not None and 'month' in ['id', 'category_id', 'month', 'amount_limit_cents']:
            patch['month'] = month
        if amount_limit_cents is not None and 'amount_limit_cents' in ['id', 'category_id', 'month', 'amount_limit_cents']:
            patch['amount_limit_cents'] = amount_limit_cents
        record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error=LookupError)
        return models.Budget(**record)

    def delete(self, id: int = None, category_id: int = None, month: str = None, amount_limit_cents: int = None) -> None:
        """Deletes an existing Budget. [crud:delete: STANDARD_CRUD]"""
        criteria = []
        if id is not None:
            criteria.append(('id', 'eq', id))
        if category_id is not None:
            criteria.append(('category_id', 'eq', category_id))
        if month is not None:
            criteria.append(('month', 'eq', month))
        if amount_limit_cents is not None:
            criteria.append(('amount_limit_cents', 'eq', amount_limit_cents))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            raise LookupError(f"Budget delete matched no records")
        for record in found:
            self._store.delete(self.ENTITY, self.PK, record[self.PK])
        return None

    def find_budgets_by_month(self, month: str = None, category_id: int = None) -> List[models.Budget]:
        """Returns a list of budgets for a specific month, optionally filtered by category. [crud:filter: FILTER_BY_FIELD]"""
        criteria = []
        if month is not None:
            criteria.append(('month', 'eq', month))
        if category_id is not None:
            criteria.append(('category_id', 'eq', category_id))
        found = self._store.select(self.ENTITY, criteria)
        return [models.Budget(**r) for r in found]

    def check_budget_exceeded(self, category_id: int = None, month: str = None) -> bool:
        """Checks if a category has exceeded its monthly budget for a given month. [BUDGET_OVERFLOW_GUARD via answered slots: limit_field=amount_limit_cents, target_field=amount_cents, date_field=expense_date, spend_entity=Expense]"""
        if not (month):
            raise ValueError("budget check needs a month scope: an empty month matches every record")
        budgets = self._store.select(self.ENTITY, [])
        match = [record for record in budgets
                    if record.get('category_id') == category_id
                    if record.get('month') == month
        ]
        if not match:
            return False  # no budget record: no limit to exceed
        limit = match[0].get('amount_limit_cents')
        spent = 0
        for record in self._store.select('Expense', []):
            if record.get('category_id') != category_id:
                continue
            if not str(record.get('expense_date') or '').startswith(month):
                continue
            spent += record.get('amount_cents') or 0
        return spent > limit if limit is not None else False

    def get_budget_by_category_and_month(self, category_id: int = None, month: str = None) -> Any:
        """Returns a single budget entry for a given category and month. [lookup through a named relation]"""
        criteria = []
        if category_id is not None:
            parent_rows = self._store.select('Category', [('id', 'eq', category_id)])
            if not parent_rows:
                return None
            criteria.append(('category_id', 'eq', parent_rows[0]['id']))
        if month is not None:
            criteria.append(('month', 'eq', month))
        found = self._store.select(self.ENTITY, criteria)
        if not found:
            return None
        return models.Budget(**found[0])
