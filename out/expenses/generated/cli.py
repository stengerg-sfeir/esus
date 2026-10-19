"""Command line. Every declared verb parses; bound verbs dispatch to
their adapter's service method, unbound ones fail with the reason.

Transforms follow the adapter document: DIRECT passes through, ISO_DATE
validates ISO format, DECIMAL_TO_CENTS converts money to integer cents,
CSV_LIST splits on commas, LOOKUP_ID coerces to int (existence is
enforced by the repository's foreign-key check on write, or by the
record lookup itself on read).
"""

import argparse
import dataclasses
import datetime
import json
import sys

import models
import errors
from store import Store
import repositories
import services


MODELS = ['Category', 'Expense', 'Budget']
REPOSITORIES = ['CategoryRepository', 'ExpenseRepository', 'BudgetRepository']
SERVICES = ['ExpenseService']


def _transform(kind, value, field):
    if kind == "DIRECT" or value is None:
        return value
    if kind == "ISO_DATE":
        datetime.date.fromisoformat(str(value))
        return value
    if kind == "DECIMAL_TO_CENTS":
        return int(round(float(value) * 100))
    if kind == "CSV_LIST":
        items = value if isinstance(value, list) else [value]
        split = []
        for part in items:
            split.extend(p.strip() for p in str(part).split(",") if p.strip())
        return split
    if kind == "LOOKUP_ID":
        return int(value)
    if kind == "ENUM_LOOKUP":
        return str(value)
    raise ValueError(f"unknown transform {kind!r} for {field!r}")


def _show(result):
    if result is None:
        return
    if isinstance(result, list):
        for item in result:
            _show(item)
        return
    if dataclasses.is_dataclass(result):
        print(json.dumps(dataclasses.asdict(result), default=str))
        return
    print(result)


ADAPTERS = {
    'add_expense': {
        'service': 'ExpenseService',
        'method': 'add_expense',
        'fields': [
            ('amount_cents', ('expense', 'DECIMAL_TO_CENTS', True)),
            ('description', ('expense', 'DIRECT', True)),
            ('expense_date', ('expense', 'ISO_DATE', False)),
            ('category_id', ('expense', 'DIRECT', True)),
            ('payment_method', ('expense', 'DIRECT', False)),
            ('is_recurring', ('expense', 'DIRECT', False)),
        ],
        'argv': {'amount_cents': 'amount', 'description': 'description', 'expense_date': 'expense_date', 'category_id': 'category', 'payment_method': 'method', 'is_recurring': 'recurring'},
        'targets': {'expense': 'Expense'},
        'assembled': [],
    },
    'check_budget_status': {
        'service': 'BudgetRepository',
        'method': 'check_budget_status',
        'fields': [
            ('category_id', ('category_id', 'DIRECT', True)),
            ('month', ('month', 'ISO_DATE', True)),
        ],
        'argv': {'category_id': None, 'month': None},
        'targets': {'category_id': None, 'month': None},
        'assembled': [],
    },
    'create_budget': {
        'service': 'BudgetRepository',
        'method': 'create_budget',
        'fields': [
            ('category_id', ('budget', 'DIRECT', True)),
            ('month', ('budget', 'DIRECT', True)),
            ('amount_limit_cents', ('budget', 'DECIMAL_TO_CENTS', True)),
        ],
        'argv': {'category_id': 'category_id', 'month': 'month', 'amount_limit_cents': 'amount'},
        'targets': {'budget': 'Budget'},
        'assembled': [],
    },
    'create_category': {
        'service': 'CategoryRepository',
        'method': 'create_category',
        'fields': [
            ('name', ('category', 'DIRECT', True)),
            ('description', ('category', 'DIRECT', False)),
            ('monthly_budget', ('category', 'DECIMAL_TO_CENTS', False)),
            ('icon', ('category', 'DIRECT', False)),
        ],
        'argv': {'name': 'name', 'description': 'description', 'monthly_budget': None, 'icon': 'icon'},
        'targets': {'category': 'Category'},
        'assembled': [],
    },
    'create_expense': {
        'service': 'ExpenseRepository',
        'method': 'create_expense',
        'fields': [
            ('amount_cents', ('expense', 'DECIMAL_TO_CENTS', True)),
            ('description', ('expense', 'DIRECT', True)),
            ('expense_date', ('expense', 'ISO_DATE', False)),
            ('category_id', ('expense', 'DIRECT', True)),
            ('payment_method', ('expense', 'DIRECT', False)),
            ('is_recurring', ('expense', 'DIRECT', False)),
        ],
        'argv': {'amount_cents': None, 'description': None, 'expense_date': None, 'category_id': None, 'payment_method': None, 'is_recurring': None},
        'targets': {'expense': 'Expense'},
        'assembled': [],
    },
    'delete_budget': {
        'service': 'BudgetRepository',
        'method': 'delete_budget',
        'fields': [
            ('category_id', ('category_id', 'DIRECT', True)),
            ('month', ('month', 'ISO_DATE', True)),
        ],
        'argv': {'category_id': 'category_id', 'month': 'month'},
        'targets': {'category_id': None, 'month': None},
        'assembled': [],
    },
    'delete_category': {
        'service': 'CategoryRepository',
        'method': 'delete_category',
        'fields': [
            ('id', ('id', 'DIRECT', True)),
        ],
        'argv': {'id': 'id'},
        'targets': {'id': None},
        'assembled': [],
    },
    'delete_expense': {
        'service': 'ExpenseRepository',
        'method': 'delete_expense',
        'fields': [
            ('id', ('id', 'DIRECT', True)),
        ],
        'argv': {'id': None},
        'targets': {'id': None},
        'assembled': [],
    },
    'detect_recurring': {
        'service': 'ExpenseService',
        'method': 'detect_recurring',
        'fields': [
        ],
        'argv': {},
        'targets': {},
        'assembled': [],
    },
    'export_expenses_to_csv': {
        'service': 'ExpenseRepository',
        'method': 'export_expenses_to_csv',
        'fields': [
            ('output', ('file_path', 'DIRECT', True)),
            ('start_date', ('start_date', 'ISO_DATE', False)),
            ('end_date', ('end_date', 'ISO_DATE', False)),
        ],
        'argv': {'output': 'output', 'start_date': 'from_date', 'end_date': 'to_date'},
        'targets': {'file_path': None, 'start_date': None, 'end_date': None},
        'assembled': [],
    },
    'export_to_csv': {
        'service': 'ExpenseService',
        'method': 'export_to_csv',
        'fields': [
            ('file_path', ('file_path', 'DIRECT', True)),
            ('start_date', ('start_date', 'ISO_DATE', False)),
            ('end_date', ('end_date', 'ISO_DATE', False)),
        ],
        'argv': {'file_path': None, 'start_date': None, 'end_date': None},
        'targets': {'file_path': None, 'start_date': None, 'end_date': None},
        'assembled': [],
    },
    'find_expenses_by_category': {
        'service': 'ExpenseRepository',
        'method': 'read_expenses_by_category',
        'fields': [
            ('category_id', ('category_id', 'DIRECT', True)),
        ],
        'argv': {'category_id': None},
        'targets': {'category_id': None},
        'assembled': [],
    },
    'get_category_spending': {
        'service': 'ExpenseRepository',
        'method': 'get_category_spending',
        'fields': [
            ('category_id', ('category_id', 'DIRECT', True)),
            ('start_date', ('start_date', 'ISO_DATE', False)),
            ('end_date', ('end_date', 'ISO_DATE', False)),
        ],
        'argv': {'category_id': None, 'start_date': None, 'end_date': None},
        'targets': {'category_id': None, 'start_date': None, 'end_date': None},
        'assembled': [],
    },
    'get_expense_by_id': {
        'service': 'ExpenseService',
        'method': 'get_expense_by_id',
        'fields': [
            ('id', ('id', 'DIRECT', True)),
        ],
        'argv': {'id': None},
        'targets': {'id': None},
        'assembled': [],
    },
    'get_monthly_expense_total': {
        'service': 'ExpenseRepository',
        'method': 'get_monthly_expense_total',
        'fields': [
            ('month', ('month', 'ISO_DATE', True)),
        ],
        'argv': {'month': None},
        'targets': {'month': None},
        'assembled': [],
    },
    'get_monthly_report': {
        'service': 'ExpenseService',
        'method': 'get_monthly_report',
        'fields': [
            ('month', ('month', 'ISO_DATE', True)),
        ],
        'argv': {'month': 'monthly'},
        'targets': {'month': None},
        'assembled': [],
    },
    'get_yearly_expense_total': {
        'service': 'ExpenseRepository',
        'method': 'get_yearly_expense_total',
        'fields': [
            ('year', ('year', 'ISO_DATE', True)),
        ],
        'argv': {'year': None},
        'targets': {'year': None},
        'assembled': [],
    },
    'get_yearly_summary': {
        'service': 'ExpenseService',
        'method': 'get_yearly_summary',
        'fields': [
            ('year', ('year', 'ISO_DATE', True)),
        ],
        'argv': {'year': None},
        'targets': {'year': None},
        'assembled': [],
    },
    'list_expenses': {
        'service': 'ExpenseService',
        'method': 'list_expenses',
        'fields': [
            ('category_id', ('category_id', 'DIRECT', False)),
            ('start_date', ('start_date', 'ISO_DATE', False)),
            ('end_date', ('end_date', 'ISO_DATE', False)),
            ('payment_method', ('payment_method', 'DIRECT', False)),
        ],
        'argv': {'category_id': 'category', 'start_date': 'from_date', 'end_date': 'to_date', 'payment_method': 'method'},
        'targets': {'category_id': None, 'start_date': None, 'end_date': None, 'payment_method': None},
        'assembled': [],
    },
    'read_all_budgets': {
        'service': 'BudgetRepository',
        'method': 'read_all_budgets',
        'fields': [
        ],
        'argv': {},
        'targets': {},
        'assembled': [],
    },
    'read_all_categories': {
        'service': 'CategoryRepository',
        'method': 'read_all_categories',
        'fields': [
        ],
        'argv': {},
        'targets': {},
        'assembled': [],
    },
    'read_budget_by_category_and_month': {
        'service': 'BudgetRepository',
        'method': 'read_budget_by_category_and_month',
        'fields': [
            ('category_id', ('category_id', 'DIRECT', True)),
            ('month', ('month', 'ISO_DATE', True)),
        ],
        'argv': {'category_id': None, 'month': None},
        'targets': {'category_id': None, 'month': None},
        'assembled': [],
    },
    'read_budget_by_id': {
        'service': 'BudgetRepository',
        'method': 'read_budget_by_id',
        'fields': [
            ('id', ('id', 'DIRECT', True)),
        ],
        'argv': {'id': None},
        'targets': {'id': None},
        'assembled': [],
    },
    'read_category_by_id': {
        'service': 'CategoryRepository',
        'method': 'read_category_by_id',
        'fields': [
            ('id', ('id', 'DIRECT', True)),
        ],
        'argv': {'id': None},
        'targets': {'id': None},
        'assembled': [],
    },
    'read_expense_by_id': {
        'service': 'ExpenseRepository',
        'method': 'read_expense_by_id',
        'fields': [
            ('id', ('id', 'DIRECT', True)),
        ],
        'argv': {'id': None},
        'targets': {'id': None},
        'assembled': [],
    },
    'read_expenses_by_category_and_payment_method': {
        'service': 'ExpenseRepository',
        'method': 'read_expenses_by_category_and_payment_method',
        'fields': [
            ('category_id', ('category_id', 'DIRECT', True)),
            ('payment_method', ('payment_method', 'DIRECT', False)),
        ],
        'argv': {'category_id': None, 'payment_method': None},
        'targets': {'category_id': None, 'payment_method': None},
        'assembled': [],
    },
    'read_expenses_by_date_range': {
        'service': 'ExpenseRepository',
        'method': 'read_expenses_by_date_range',
        'fields': [
            ('start_date', ('start_date', 'ISO_DATE', True)),
            ('end_date', ('end_date', 'ISO_DATE', True)),
        ],
        'argv': {'start_date': None, 'end_date': None},
        'targets': {'start_date': None, 'end_date': None},
        'assembled': [],
    },
    'read_expenses_by_payment_method': {
        'service': 'ExpenseRepository',
        'method': 'read_expenses_by_payment_method',
        'fields': [
            ('payment_method', ('payment_method', 'DIRECT', True)),
        ],
        'argv': {'payment_method': None},
        'targets': {'payment_method': None},
        'assembled': [],
    },
    'update_budget': {
        'service': 'BudgetRepository',
        'method': 'update_budget',
        'fields': [
            ('id', ('id', 'DIRECT', True)),
            ('category_id', ('budget', 'DIRECT', False)),
            ('month', ('budget', 'ISO_DATE', False)),
            ('amount_limit_cents', ('budget', 'DECIMAL_TO_CENTS', False)),
        ],
        'argv': {'id': 'category_id', 'category_id': 'category_id', 'month': 'month', 'amount_limit_cents': 'amount'},
        'targets': {'id': None, 'budget': 'Budget'},
        'assembled': [],
    },
    'update_category': {
        'service': 'CategoryRepository',
        'method': 'update_category',
        'fields': [
            ('id', ('id', 'DIRECT', True)),
            ('name', ('category', 'DIRECT', False)),
            ('description', ('category', 'DIRECT', False)),
            ('monthly_budget', ('category', 'DECIMAL_TO_CENTS', False)),
            ('icon', ('category', 'DIRECT', False)),
        ],
        'argv': {'id': 'id', 'name': 'name', 'description': 'description', 'monthly_budget': None, 'icon': 'icon'},
        'targets': {'id': None, 'category': 'Category'},
        'assembled': [],
    },
    'update_expense': {
        'service': 'ExpenseRepository',
        'method': 'update_expense',
        'fields': [
            ('id', ('id', 'DIRECT', True)),
            ('amount_cents', ('expense', 'DECIMAL_TO_CENTS', False)),
            ('description', ('expense', 'DIRECT', False)),
            ('expense_date', ('expense', 'ISO_DATE', False)),
            ('category_id', ('expense', 'DIRECT', False)),
            ('payment_method', ('expense', 'DIRECT', False)),
            ('is_recurring', ('expense', 'DIRECT', False)),
        ],
        'argv': {'id': None, 'amount_cents': None, 'description': None, 'expense_date': None, 'category_id': None, 'payment_method': None, 'is_recurring': None},
        'targets': {'id': None, 'expense': 'Expense'},
        'assembled': [],
    },
    'update_expense_data': {
        'service': 'ExpenseService',
        'method': 'update_expense',
        'fields': [
            ('id', ('id', 'DIRECT', True)),
            ('amount_cents', ('expense_data', 'DECIMAL_TO_CENTS', False)),
            ('description', ('expense_data', 'DIRECT', False)),
            ('expense_date', ('expense_data', 'ISO_DATE', False)),
            ('category_id', ('expense_data', 'DIRECT', False)),
            ('payment_method', ('expense_data', 'DIRECT', False)),
            ('is_recurring', ('expense_data', 'DIRECT', False)),
        ],
        'argv': {'id': None, 'amount_cents': None, 'description': None, 'expense_date': None, 'category_id': None, 'payment_method': None, 'is_recurring': None},
        'targets': {'id': None, 'expense_data': 'Expense'},
        'assembled': [],
    },
}


BINDINGS = {  # (command, subcommand) -> (action, score)
    ('budget', 'add'): ('create_budget', 4),
    ('budget', 'delete'): ('delete_budget', 7),
    ('budget', 'list'): ('read_all_budgets', 4),
    ('budget', 'update'): ('update_budget', 7),
    ('category', 'add'): ('create_category', 4),
    ('category', 'delete'): ('delete_category', 7),
    ('category', 'list'): ('read_all_categories', 4),
    ('category', 'update'): ('update_category', 7),
    ('expense', 'add'): ('add_expense', 7),
    ('expense', 'export'): ('export_expenses_to_csv', 7),
    ('expense', 'list'): ('list_expenses', 7),
    ('expense', 'recurring'): ('detect_recurring', 7),
    ('expense', 'report'): ('get_monthly_report', 7),
}


def _normalize(text):
    return "".join(c for c in str(text).lower() if c.isalnum())


DEFAULT_DB = 'expenses.db'


def build_parser():
    parser = argparse.ArgumentParser(prog='expenses')
    parser.add_argument('--db', default=None,
                        help=('SQLite file for record storage (default: ' + DEFAULT_DB + ' in the working directory; use :memory: to stay in memory)'))
    sub = parser.add_subparsers(dest='command')
    p_category = sub.add_parser('category')
    sub_category = p_category.add_subparsers(dest='subcommand')
    p_category_add = sub_category.add_parser('add')
    p_category_add.add_argument('-name', '-n', type=str, required=True, dest='name')
    p_category_add.add_argument('-description', '-d', type=str, required=False, dest='description')
    p_category_add.add_argument('-icon', '-i', type=str, required=False, dest='icon')
    p_category_add.set_defaults(_binding=('category', 'add'))
    p_category_list = sub_category.add_parser('list')
    p_category_list.set_defaults(_binding=('category', 'list'))
    p_category_update = sub_category.add_parser('update')
    p_category_update.add_argument('-id', '-i', type=int, required=True, dest='id')
    p_category_update.add_argument('-name', '-n', type=str, required=False, dest='name')
    p_category_update.add_argument('-description', '-d', type=str, required=False, dest='description')
    p_category_update.add_argument('-icon', type=str, required=False, dest='icon')
    p_category_update.set_defaults(_binding=('category', 'update'))
    p_category_delete = sub_category.add_parser('delete')
    p_category_delete.add_argument('-id', '-i', type=int, required=True, dest='id')
    p_category_delete.set_defaults(_binding=('category', 'delete'))
    p_budget = sub.add_parser('budget')
    sub_budget = p_budget.add_subparsers(dest='subcommand')
    p_budget_list = sub_budget.add_parser('list')
    p_budget_list.add_argument('-category', '-c', type=int, required=False, dest='category')
    p_budget_list.add_argument('-month', '-m', type=str, required=False, dest='month')
    p_budget_list.set_defaults(_binding=('budget', 'list'))
    p_budget_add = sub_budget.add_parser('add')
    p_budget_add.add_argument('-category-id', '-c', type=int, required=True, dest='category_id')
    p_budget_add.add_argument('-month', '-m', type=str, required=True, dest='month')
    p_budget_add.add_argument('-amount', '-a', type=int, required=True, dest='amount')
    p_budget_add.set_defaults(_binding=('budget', 'add'))
    p_budget_update = sub_budget.add_parser('update')
    p_budget_update.add_argument('-category-id', '-c', type=int, required=True, dest='category_id')
    p_budget_update.add_argument('-month', '-m', type=str, required=True, dest='month')
    p_budget_update.add_argument('-amount', '-a', type=int, required=False, dest='amount')
    p_budget_update.set_defaults(_binding=('budget', 'update'))
    p_budget_delete = sub_budget.add_parser('delete')
    p_budget_delete.add_argument('-category-id', '-c', type=int, required=True, dest='category_id')
    p_budget_delete.add_argument('-month', '-m', type=str, required=True, dest='month')
    p_budget_delete.set_defaults(_binding=('budget', 'delete'))
    p_expense = sub.add_parser('expense')
    sub_expense = p_expense.add_subparsers(dest='subcommand')
    p_expense_add = sub_expense.add_parser('add')
    p_expense_add.add_argument('-amount', '-a', type=int, required=True, dest='amount')
    p_expense_add.add_argument('-description', '-d', type=str, required=True, dest='description')
    p_expense_add.add_argument('-category', '-c', type=int, required=True, dest='category')
    p_expense_add.add_argument('-expense-date', '-e', type=str, required=False, dest='expense_date')
    p_expense_add.add_argument('-method', '-m', type=str, required=False, default='cash', dest='method')
    p_expense_add.add_argument('-recurring', '-r', action='store_true', dest='recurring')
    p_expense_add.set_defaults(_binding=('expense', 'add'))
    p_expense_list = sub_expense.add_parser('list')
    p_expense_list.add_argument('-category', '-c', type=int, required=False, dest='category')
    p_expense_list.add_argument('-from-date', '-f', type=str, required=False, dest='from_date')
    p_expense_list.add_argument('-to-date', '-t', type=str, required=False, dest='to_date')
    p_expense_list.add_argument('-method', '-m', type=str, required=False, dest='method')
    p_expense_list.set_defaults(_binding=('expense', 'list'))
    p_expense_report = sub_expense.add_parser('report')
    p_expense_report.add_argument('-monthly', '-m', type=str, required=True, dest='monthly')
    p_expense_report.add_argument('-yearly', '-y', type=str, required=True, dest='yearly')
    p_expense_report.set_defaults(_binding=('expense', 'report'))
    p_expense_export = sub_expense.add_parser('export')
    p_expense_export.add_argument('-from-date', '-f', type=str, required=False, dest='from_date')
    p_expense_export.add_argument('-to-date', '-t', type=str, required=False, dest='to_date')
    p_expense_export.add_argument('-output', '-o', type=str, required=True, dest='output')
    p_expense_export.set_defaults(_binding=('expense', 'export'))
    p_expense_recurring = sub_expense.add_parser('recurring')
    p_expense_recurring.set_defaults(_binding=('expense', 'recurring'))
    return parser


def _call(bound, values, deps):
    action, _score = bound
    spec = ADAPTERS[action]
    service = deps['services'][_sanitize(spec['service'])]
    method = getattr(service, _sanitize(spec['method']))
    present = {_normalize(k): v for k, v in values.items()}
    argv = spec.get('argv', {})
    targets = spec.get('targets', {})
    assembled = set(spec.get('assembled', []))
    grouped = {}
    for field_name, (target_param, kind, required) in spec['fields']:
        if field_name in assembled:
            continue  # built from its sibling fields, not from argv
        dest = argv.get(field_name)
        if dest is None or present.get(_normalize(dest)) is None:
            if required:
                raise ValueError(f"missing required field {field_name!r} for {action!r}")
            continue
        value = _transform(kind, present[_normalize(dest)], field_name)
        if targets.get(target_param) is not None:
            grouped.setdefault(target_param, {})[field_name] = value
        else:
            grouped[target_param] = value
    call_kwargs = {}
    for target_param, value in grouped.items():
        model_name = targets.get(target_param)
        if model_name is not None and isinstance(value, dict):
            call_kwargs[_sanitize(target_param)] = getattr(models, model_name)(**value)
        else:
            call_kwargs[_sanitize(target_param)] = value
    return method(**call_kwargs)


def _sanitize(text):
    cleaned = "".join(c if c.isalnum() or c == "_" else "_" for c in str(text))
    cleaned = cleaned.strip("_") or "opt"
    return "_" + cleaned if cleaned[:1].isdigit() else cleaned


def build_cli(db_path=None):
    store = Store(db_path)
    repos = {cls_name: getattr(repositories, cls_name)(store) for cls_name in REPOSITORIES}
    hired = {cls_name: getattr(services, cls_name)(repos) for cls_name in SERVICES}
    entities = {_normalize(name): getattr(models, name) for name in MODELS}
    return build_parser(), {'store': store, 'repos': repos,
                           'services': {**repos, **hired},
                           'entities': entities}


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    _, deps = build_cli(args.db or DEFAULT_DB)
    try:
        return dispatch(parser, args, deps)
    finally:
        deps['store'].close()


def dispatch(parser, args, deps):
    """Run one parsed command against shared dependencies."""
    binding = getattr(args, '_binding', None)
    if binding is None:
        parser.print_usage()
        return 2
    bound = BINDINGS.get(tuple(binding))
    if bound is None:
        print(f"no adapter bound for {' '.join(binding)} — not implemented")
        return 1
    values = {key: value for key, value in vars(args).items()
              if key not in ('command', 'subcommand', '_binding', 'db')}
    try:
        _show(_call(bound, values, deps))
    except Exception as error:
        print(f"error: {error}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

