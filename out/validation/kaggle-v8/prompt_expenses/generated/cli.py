"""Command line. Every declared verb parses; bound verbs dispatch to
their adapter's service method, unbound ones fail with the reason.

Transforms follow the adapter document: DIRECT passes through, ISO_DATE
validates ISO format, DECIMAL_TO_CENTS converts money to integer cents,
CSV_LIST splits on commas, INT_LIST converts a list to integers,
LOOKUP_ID coerces to int (existence is enforced by the repository's
foreign-key check on write, or by the record lookup itself on read),
BOOL_TO_ONE turns a selector such as --available-only into the
minimum count of one.
"""

from __future__ import annotations

import click
import dataclasses
import datetime
import json
import sys

import models
import errors
from schema import SCHEMA
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
        text = str(value)
        if "T" in text or " " in text:
            return datetime.datetime.fromisoformat(text)
        return datetime.date.fromisoformat(text)
    if kind == "DECIMAL_TO_CENTS":
        return int(round(float(value) * 100))
    if kind == "CSV_LIST":
        items = value if isinstance(value, (list, tuple)) else [value]
        split = []
        for part in items:
            split.extend(p.strip() for p in str(part).split(",") if p.strip())
        return split
    if kind == "INT_LIST":
        items = value if isinstance(value, (list, tuple)) else [value]
        return [int(item) for item in items]
    if kind == "LOOKUP_ID":
        return int(value)
    if kind == "ENUM_LOOKUP":
        return str(value)
    if kind == "BOOL_TO_ONE":
        return 1 if value else 0
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
    if isinstance(result, (dict, tuple)):
        print(json.dumps(result, default=str))
        return
    print(result)


ADAPTERS = {
    'budgetadd': {
        'service': 'BudgetRepository',
        'method': 'create',
        'fields': [
            ('category_id', ('category_id', 'LOOKUP_ID', True)),
            ('month', ('month', 'DIRECT', True)),
            ('amount', ('amount_limit_cents', 'DECIMAL_TO_CENTS', True)),
        ],
        'argv': {'category_id': 'category_id', 'month': 'month', 'amount': 'amount'},
        'targets': {'category_id': None, 'month': None, 'amount_limit_cents': None},
        'assembled': [],
        'creates': True,
    },
    'budgetdelete': {
        'service': 'BudgetRepository',
        'method': 'delete',
        'fields': [
            ('category_id', ('category_id', 'LOOKUP_ID', True)),
            ('month', ('month', 'DIRECT', False)),
        ],
        'argv': {'category_id': 'category_id', 'month': 'month'},
        'targets': {'category_id': None, 'month': None},
        'assembled': [],
        'creates': False,
    },
    'budgetlist': {
        'service': 'BudgetRepository',
        'method': 'read_all',
        'fields': [
            ('category', ('category_id', 'LOOKUP_ID', False)),
            ('month', ('month', 'DIRECT', False)),
        ],
        'argv': {'category': 'category', 'month': 'month'},
        'targets': {'category_id': None, 'month': None},
        'assembled': [],
        'creates': False,
    },
    'budgetupdate': {
        'service': 'BudgetRepository',
        'method': 'update',
        'fields': [
            ('category_id', ('category_id', 'LOOKUP_ID', True)),
            ('month', ('month', 'DIRECT', True)),
            ('amount', ('amount_limit_cents', 'DECIMAL_TO_CENTS', False)),
        ],
        'argv': {'category_id': 'category_id', 'month': 'month', 'amount': 'amount'},
        'targets': {'category_id': None, 'month': None, 'amount_limit_cents': None},
        'assembled': [],
        'creates': False,
    },
    'expenseadd': {
        'service': 'ExpenseService',
        'method': 'add_expense',
        'fields': [
            ('amount', ('amount_cents', 'DECIMAL_TO_CENTS', True)),
            ('description', ('description', 'DIRECT', True)),
            ('category', ('category_id', 'LOOKUP_ID', True)),
            ('expense_date', ('expense_date', 'ISO_DATE', False)),
            ('method', ('payment_method', 'DIRECT', False)),
            ('recurring', ('is_recurring', 'DIRECT', False)),
        ],
        'argv': {'amount': 'amount', 'description': 'description', 'category': 'category', 'expense_date': 'expense_date', 'method': 'method', 'recurring': 'recurring'},
        'targets': {'amount_cents': None, 'description': None, 'category_id': None, 'expense_date': None, 'payment_method': None, 'is_recurring': None},
        'assembled': [],
        'creates': True,
    },
    'expensecategoryadd': {
        'service': 'CategoryRepository',
        'method': 'create',
        'fields': [
            ('name', ('name', 'DIRECT', True)),
            ('description', ('description', 'DIRECT', False)),
            ('budget', ('monthly_budget', 'DECIMAL_TO_CENTS', False)),
            ('icon', ('icon', 'DIRECT', False)),
        ],
        'argv': {'name': 'name', 'description': 'description', 'budget': 'budget', 'icon': 'icon'},
        'targets': {'name': None, 'description': None, 'monthly_budget': None, 'icon': None},
        'assembled': [],
        'creates': True,
    },
    'expensecategorydelete': {
        'service': 'CategoryRepository',
        'method': 'delete',
        'fields': [
            ('id', ('id', 'LOOKUP_ID', True)),
        ],
        'argv': {'id': 'id'},
        'targets': {'id': None},
        'assembled': [],
        'creates': False,
    },
    'expensecategorylist': {
        'service': 'CategoryRepository',
        'method': 'read_all',
        'fields': [
        ],
        'argv': {},
        'targets': {},
        'assembled': [],
        'creates': False,
    },
    'expensecategoryupdate': {
        'service': 'CategoryRepository',
        'method': 'update',
        'fields': [
            ('id', ('id', 'LOOKUP_ID', True)),
            ('name', ('name', 'DIRECT', False)),
            ('description', ('description', 'DIRECT', False)),
            ('budget', ('monthly_budget', 'DECIMAL_TO_CENTS', False)),
            ('icon', ('icon', 'DIRECT', False)),
        ],
        'argv': {'id': 'id', 'name': 'name', 'description': 'description', 'budget': 'budget', 'icon': 'icon'},
        'targets': {'id': None, 'name': None, 'description': None, 'monthly_budget': None, 'icon': None},
        'assembled': [],
        'creates': False,
    },
    'expenseexport': {
        'service': 'ExpenseService',
        'method': 'expenseexport',
        'fields': [
            ('from_date', ('from_date', 'ISO_DATE', True)),
            ('to_date', ('to_date', 'ISO_DATE', True)),
            ('output', ('output', 'DIRECT', True)),
        ],
        'argv': {'from_date': 'from_date', 'to_date': 'to_date', 'output': 'output'},
        'targets': {'from_date': None, 'to_date': None, 'output': None},
        'assembled': [],
        'creates': False,
    },
    'expenselist': {
        'service': 'ExpenseService',
        'method': 'list_expenses',
        'fields': [
            ('category', ('category_id', 'LOOKUP_ID', False)),
            ('from_date', ('start_date', 'ISO_DATE', False)),
            ('to_date', ('end_date', 'ISO_DATE', False)),
            ('method', ('payment_method', 'DIRECT', False)),
        ],
        'argv': {'category': 'category', 'from_date': 'from_date', 'to_date': 'to_date', 'method': 'method'},
        'targets': {'category_id': None, 'start_date': None, 'end_date': None, 'payment_method': None},
        'assembled': [],
        'creates': False,
    },
    'expenserecurringdetect': {
        'service': 'ExpenseService',
        'method': 'detect_recurring',
        'fields': [
        ],
        'argv': {},
        'targets': {},
        'assembled': [],
        'creates': False,
    },
    'expensereportmonthly': {
        'service': 'ExpenseService',
        'method': 'expensereportmonthly',
        'fields': [
            ('month', ('month', 'DIRECT', True)),
        ],
        'argv': {'month': 'month'},
        'targets': {'month': None},
        'assembled': [],
        'creates': False,
    },
    'expensereportyearly': {
        'service': 'ExpenseService',
        'method': 'expensereportyearly',
        'fields': [
            ('year', ('year', 'DIRECT', True)),
        ],
        'argv': {'year': None},
        'targets': {'year': None},
        'assembled': [],
        'creates': False,
    },
    'get_yearly_summary_year': {
        'service': 'ExpenseService',
        'method': 'get_yearly_summary',
        'fields': [
            ('year', ('year', 'DIRECT', True)),
        ],
        'argv': {'year': 'year'},
        'targets': {'year': None},
        'assembled': [],
        'creates': False,
    },
}


BINDINGS = {  # (command, subcommand) -> [(action, score, need)]
    ('budget', 'add'): [('budgetadd', 9, ())],
    ('budget', 'delete'): [('budgetdelete', 11, ())],
    ('budget', 'list'): [('budgetlist', 9, ())],
    ('budget', 'update'): [('budgetupdate', 11, ())],
    ('expense', 'add'): [('expenseadd', 11, ())],
    ('expense', 'category add'): [('expensecategoryadd', 5, ())],
    ('expense', 'category delete'): [('expensecategorydelete', 7, ())],
    ('expense', 'category list'): [('expensecategorylist', 5, ())],
    ('expense', 'category update'): [('expensecategoryupdate', 7, ())],
    ('expense', 'export'): [('expenseexport', 11, ())],
    ('expense', 'list'): [('expenselist', 11, ())],
    ('expense', 'recurring detect'): [('expenserecurringdetect', 7, ())],
    ('expense', 'report monthly'): [('expensereportmonthly', 3, ())],
    ('expense', 'report yearly'): [('get_yearly_summary_year', 3, (('year', 'value', '--year'),)), ('expensereportmonthly', 3, ())],
}


def _normalize(text):
    return "".join(c for c in str(text).lower() if c.isalnum())


def _needs_met(present, need):
    for dest, kind, _flag in need:
        value = present.get(_normalize(dest))
        if kind == 'truthy':
            if not value:
                return False
        elif value is None:
            return False
    return True


def _choose(bound, values):
    """The first choice whose flags are all passed: routes and
    filters before the fallback, which needs nothing."""
    present = {_normalize(k): v for k, v in values.items()}
    for choice in bound:
        if _needs_met(present, choice[2]):
            return choice, present
    return bound[-1], present


def _incomplete(chosen, bound, present):
    """Flags passed that select a choice also needing companions
    (`--category` without `--month`): naming the missing flag beats
    ignoring the one passed."""
    consumed = {dest for dest, _kind, _flag in chosen[2]}
    for action, _score, need in bound:
        if action == chosen[0]:
            continue
        passed = [item for item in need if _needs_met(present, (item,))]
        if not passed or len(passed) == len(need):
            continue
        if any(item[0] in consumed for item in passed):
            continue
        missing = ' and '.join(item[2] for item in need
                               if item not in passed)
        return f'{action!r} also needs {missing}'
    return None


def _error_text(error):
    """A domain error keeps its class name when it carries no text."""
    detail = str(error)
    name = type(error).__name__
    return f'{name}: {detail}' if detail else name


DEFAULT_DB = 'prompt_expenses.db'



COMMANDS = {'expense': {'subcommands': {'category': {'subcommands': {'add': {'binding': ('expense', 'category add'),
                                                                  'plans': [{'flags': ['--name', '-n'],
                                                                             'dest': 'name',
                                                                             'otype': 'str',
                                                                             'required': True,
                                                                             'default': None},
                                                                            {'flags': ['--description', '-d'],
                                                                             'dest': 'description',
                                                                             'otype': 'str',
                                                                             'required': False,
                                                                             'default': None},
                                                                            {'flags': ['--budget', '-b'],
                                                                             'dest': 'budget',
                                                                             'otype': 'int',
                                                                             'required': False,
                                                                             'default': None},
                                                                            {'flags': ['--icon', '-i'],
                                                                             'dest': 'icon',
                                                                             'otype': 'str',
                                                                             'required': False,
                                                                             'default': None}]},
                                                          'list': {'binding': ('expense', 'category list'),
                                                                   'plans': []},
                                                          'update': {'binding': ('expense',
                                                                                 'category update'),
                                                                     'plans': [{'flags': ['--id', '-i'],
                                                                                'dest': 'id',
                                                                                'otype': 'int',
                                                                                'required': True,
                                                                                'default': None},
                                                                               {'flags': ['--name', '-n'],
                                                                                'dest': 'name',
                                                                                'otype': 'str',
                                                                                'required': False,
                                                                                'default': None},
                                                                               {'flags': ['--description',
                                                                                          '-d'],
                                                                                'dest': 'description',
                                                                                'otype': 'str',
                                                                                'required': False,
                                                                                'default': None},
                                                                               {'flags': ['--budget', '-b'],
                                                                                'dest': 'budget',
                                                                                'otype': 'int',
                                                                                'required': False,
                                                                                'default': None},
                                                                               {'flags': ['--icon'],
                                                                                'dest': 'icon',
                                                                                'otype': 'str',
                                                                                'required': False,
                                                                                'default': None}]},
                                                          'delete': {'binding': ('expense',
                                                                                 'category delete'),
                                                                     'plans': [{'flags': ['--id', '-i'],
                                                                                'dest': 'id',
                                                                                'otype': 'int',
                                                                                'required': True,
                                                                                'default': None}]}}},
                             'add': {'binding': ('expense', 'add'),
                                     'plans': [{'flags': ['--amount', '-a'],
                                                'dest': 'amount',
                                                'otype': 'int',
                                                'required': True,
                                                'default': None},
                                               {'flags': ['--description', '-d'],
                                                'dest': 'description',
                                                'otype': 'str',
                                                'required': True,
                                                'default': None},
                                               {'flags': ['--category', '-c'],
                                                'dest': 'category',
                                                'otype': 'int',
                                                'required': True,
                                                'default': None},
                                               {'flags': ['--expense-date', '-e'],
                                                'dest': 'expense_date',
                                                'otype': 'str',
                                                'required': False,
                                                'default': None},
                                               {'flags': ['--method', '-m'],
                                                'dest': 'method',
                                                'otype': 'str',
                                                'required': False,
                                                'default': None},
                                               {'flags': ['--recurring', '-r'],
                                                'dest': 'recurring',
                                                'otype': 'bool',
                                                'required': False,
                                                'default': None}]},
                             'list': {'binding': ('expense', 'list'),
                                      'plans': [{'flags': ['--category', '-c'],
                                                 'dest': 'category',
                                                 'otype': 'int',
                                                 'required': False,
                                                 'default': None},
                                                {'flags': ['--from-date', '-f'],
                                                 'dest': 'from_date',
                                                 'otype': 'str',
                                                 'required': False,
                                                 'default': None},
                                                {'flags': ['--to-date', '-t'],
                                                 'dest': 'to_date',
                                                 'otype': 'str',
                                                 'required': False,
                                                 'default': None},
                                                {'flags': ['--method', '-m'],
                                                 'dest': 'method',
                                                 'otype': 'str',
                                                 'required': False,
                                                 'default': None}]},
                             'report': {'subcommands': {'monthly': {'binding': ('expense', 'report monthly'),
                                                                    'plans': [{'flags': ['--month', '-m'],
                                                                               'dest': 'month',
                                                                               'otype': 'str',
                                                                               'required': True,
                                                                               'default': None}]},
                                                        'yearly': {'binding': ('expense', 'report yearly'),
                                                                   'plans': [{'flags': ['--year', '-y'],
                                                                              'dest': 'year',
                                                                              'otype': 'int',
                                                                              'required': True,
                                                                              'default': None},
                                                                             {'flags': ['--month'],
                                                                              'dest': 'month',
                                                                              'otype': 'str',
                                                                              'required': False,
                                                                              'default': None}]}}},
                             'export': {'binding': ('expense', 'export'),
                                        'plans': [{'flags': ['--from-date', '-f'],
                                                   'dest': 'from_date',
                                                   'otype': 'str',
                                                   'required': True,
                                                   'default': None},
                                                  {'flags': ['--to-date', '-t'],
                                                   'dest': 'to_date',
                                                   'otype': 'str',
                                                   'required': True,
                                                   'default': None},
                                                  {'flags': ['--output', '-o'],
                                                   'dest': 'output',
                                                   'otype': 'str',
                                                   'required': True,
                                                   'default': None}]},
                             'recurring': {'subcommands': {'detect': {'binding': ('expense',
                                                                                  'recurring detect'),
                                                                      'plans': []}}}}},
 'budget': {'subcommands': {'list': {'binding': ('budget', 'list'),
                                     'plans': [{'flags': ['--category', '-c'],
                                                'dest': 'category',
                                                'otype': 'str',
                                                'required': False,
                                                'default': None},
                                               {'flags': ['--month', '-m'],
                                                'dest': 'month',
                                                'otype': 'str',
                                                'required': False,
                                                'default': None}]},
                            'add': {'binding': ('budget', 'add'),
                                    'plans': [{'flags': ['--category-id', '-c'],
                                               'dest': 'category_id',
                                               'otype': 'int',
                                               'required': True,
                                               'default': None},
                                              {'flags': ['--month', '-m'],
                                               'dest': 'month',
                                               'otype': 'str',
                                               'required': True,
                                               'default': None},
                                              {'flags': ['--amount', '-a'],
                                               'dest': 'amount',
                                               'otype': 'int',
                                               'required': True,
                                               'default': None}]},
                            'update': {'binding': ('budget', 'update'),
                                       'plans': [{'flags': ['--category-id', '-c'],
                                                  'dest': 'category_id',
                                                  'otype': 'int',
                                                  'required': True,
                                                  'default': None},
                                                 {'flags': ['--month', '-m'],
                                                  'dest': 'month',
                                                  'otype': 'str',
                                                  'required': True,
                                                  'default': None},
                                                 {'flags': ['--amount', '-a'],
                                                  'dest': 'amount',
                                                  'otype': 'int',
                                                  'required': False,
                                                  'default': None}]},
                            'delete': {'binding': ('budget', 'delete'),
                                       'plans': [{'flags': ['--category-id', '-c'],
                                                  'dest': 'category_id',
                                                  'otype': 'int',
                                                  'required': True,
                                                  'default': None},
                                                 {'flags': ['--month', '-m'],
                                                  'dest': 'month',
                                                  'otype': 'str',
                                                  'required': False,
                                                  'default': None}]}}}}


def _make_option(plan):
    attrs = {}
    otype = plan.get('otype')
    if otype == 'bool':
        attrs['is_flag'] = True
        attrs['default'] = bool(plan.get('default'))
    elif otype == 'list':
        attrs['multiple'] = True
        attrs['type'] = str
    else:
        attrs['type'] = {'str': str, 'int': int,
                         'float': float}.get(otype, str)
        attrs['required'] = bool(plan.get('required'))
        if plan.get('default') is not None:
            attrs['default'] = plan['default']
    return click.Option(list(plan['flags']) + [plan['dest']], **attrs)


def _make_command(name, spec):
    if 'subcommands' in spec:
        params = [_make_option(dict(plan, required=False))
                  for plan in spec.get('plans', [])]
        callback = None
        if 'binding' in spec:
            def callback(ctx, **kwargs):
                if ctx.invoked_subcommand is None:
                    return _dispatch(spec['binding'], kwargs, ctx.obj)
            callback = click.pass_context(callback)
        group = click.Group(name, params=params, callback=callback,
                            invoke_without_command=('binding' in spec))
        for child_name, child in spec['subcommands'].items():
            group.add_command(_make_command(child_name, child))
        return group
    def callback(deps, **kwargs):
        return _dispatch(spec['binding'], kwargs, deps)
    params = [_make_option(plan) for plan in spec.get('plans', [])]
    return click.Command(name, params=params,
                         callback=click.pass_obj(callback))


def _call(bound, values, deps):
    action = bound[0]
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
        given = present.get(_normalize(dest)) if dest is not None else None
        # An absent no-value flag parses as False: it was not given, so the
        # method's own default applies (`member list` without --active-only
        # lists everyone, not the inactive).
        if given is None or given is False:
            if required and given is None:
                raise ValueError(f"missing required field {field_name!r} for {action!r}")
            if given is None and spec.get('creates') and str(field_name).endswith('date') and str(field_name) not in ('due_date', 'return_date', 'start_date', 'end_date', 'birth_date'):
                given = datetime.date.today()
            else:
                continue
        value = _transform(kind, given, field_name)
        if targets.get(target_param) and targets[target_param].startswith('__mapping__:'):
            grouped.setdefault(target_param, {})[field_name] = value
        elif targets.get(target_param) is not None:
            grouped.setdefault(target_param, {})[field_name] = value
        else:
            grouped[target_param] = value
    call_kwargs = {}
    for target_param, value in grouped.items():
        model_name = targets.get(target_param)
        if model_name and model_name.startswith('__mapping__:'):
            call_kwargs[_sanitize(target_param)] = value
        elif model_name is not None and isinstance(value, dict):
            call_kwargs[_sanitize(target_param)] = getattr(models, model_name)(**value)
        else:
            call_kwargs[_sanitize(target_param)] = value
    return method(**call_kwargs)


def _sanitize(text):
    cleaned = "".join(c if c.isalnum() or c == "_" else "_" for c in str(text))
    cleaned = cleaned.strip("_") or "opt"
    return "_" + cleaned if cleaned[:1].isdigit() else cleaned


def build_cli(db_path=None):
    store = Store(db_path, SCHEMA)
    repos = {cls_name: getattr(repositories, cls_name)(store) for cls_name in REPOSITORIES}
    hired = {cls_name: getattr(services, cls_name)(repos) for cls_name in SERVICES}
    entities = {_normalize(name): getattr(models, name) for name in MODELS}
    return {'store': store, 'repos': repos,
            'services': {**repos, **hired},
            'entities': entities}


def _dispatch(binding, values, deps):
    """Run one click command against shared dependencies."""
    bound = BINDINGS.get(tuple(binding))
    if bound is None:
        raise click.ClickException(
            f"no adapter bound for {' '.join(binding)} — not implemented")
    choice, present = _choose(bound, values)
    trouble = _incomplete(choice, bound, present)
    if trouble:
        raise click.ClickException(
            f"{' '.join(binding)}: {trouble}")
    try:
        _show(_call(choice, values, deps))
    except click.ClickException:
        raise
    except Exception as error:
        raise click.ClickException(_error_text(error)) from error
    return 0


@click.group('prompt_expenses')
@click.option('--db', default=None,
              help=('SQLite file for record storage (default: ' + DEFAULT_DB + ' in the working directory; use :memory: to stay in memory)'))
@click.pass_context
def cli(ctx, db):
    deps = build_cli(db or DEFAULT_DB)
    ctx.obj = deps
    ctx.call_on_close(lambda: deps['store'].close())


for _name, _spec in COMMANDS.items():
    cli.add_command(_make_command(_name, _spec))


def main(argv=None):
    try:
        cli.main(args=argv, prog_name='prompt_expenses',
                 standalone_mode=False)
    except click.exceptions.Exit as error:
        return error.exit_code
    except click.ClickException as error:
        error.show()
        return error.exit_code
    except click.Abort:
        click.echo('Aborted!', err=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

