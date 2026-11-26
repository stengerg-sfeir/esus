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


MODELS = ['Category', 'Product']
REPOSITORIES = ['CategoryRepository', 'ProductRepository']
SERVICES = ['InventoryService']


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
    'categoryadd': {
        'service': 'CategoryRepository',
        'method': 'create',
        'fields': [
            ('name', ('name', 'DIRECT', True)),
            ('description', ('description', 'DIRECT', False)),
            ('threshold', ('reorder_threshold', 'DIRECT', False)),
        ],
        'argv': {'name': 'name', 'description': 'description', 'threshold': 'threshold'},
        'targets': {'name': None, 'description': None, 'reorder_threshold': None},
        'assembled': [],
        'creates': True,
    },
    'categorydelete': {
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
    'categorylist': {
        'service': 'CategoryRepository',
        'method': 'read_all',
        'fields': [
        ],
        'argv': {},
        'targets': {},
        'assembled': [],
        'creates': False,
    },
    'categoryupdate': {
        'service': 'CategoryRepository',
        'method': 'update',
        'fields': [
            ('id', ('id', 'LOOKUP_ID', True)),
            ('name', ('name', 'DIRECT', False)),
            ('description', ('description', 'DIRECT', False)),
            ('threshold', ('reorder_threshold', 'DIRECT', False)),
        ],
        'argv': {'id': 'id', 'name': 'name', 'description': 'description', 'threshold': 'threshold'},
        'targets': {'id': None, 'name': None, 'description': None, 'reorder_threshold': None},
        'assembled': [],
        'creates': False,
    },
    'productadd': {
        'service': 'InventoryService',
        'method': 'add_product',
        'fields': [
            ('sku', ('sku', 'DIRECT', True)),
            ('name', ('name', 'DIRECT', True)),
            ('category', ('category_id', 'DIRECT', True)),
            ('price', ('price_cents', 'DECIMAL_TO_CENTS', True)),
            ('stock', ('stock_qty', 'DIRECT', True)),
        ],
        'argv': {'sku': 'sku', 'name': 'name', 'category': 'category', 'price': 'price', 'stock': 'stock'},
        'targets': {'sku': None, 'name': None, 'category_id': None, 'price_cents': None, 'stock_qty': None},
        'assembled': [],
        'creates': True,
    },
    'productdelete': {
        'service': 'InventoryService',
        'method': 'delete_product',
        'fields': [
            ('id', ('id', 'LOOKUP_ID', True)),
        ],
        'argv': {'id': 'id'},
        'targets': {'id': None},
        'assembled': [],
        'creates': False,
    },
    'productlist': {
        'service': 'InventoryService',
        'method': 'list_products',
        'fields': [
            ('category', ('category_id', 'DIRECT', False)),
            ('low_only', ('low_only', 'DIRECT', False)),
        ],
        'argv': {'category': 'category', 'low_only': 'low_only'},
        'targets': {'category_id': None, 'low_only': None},
        'assembled': [],
        'creates': False,
    },
    'productreportlowstock': {
        'service': 'InventoryService',
        'method': 'low_stock_report',
        'fields': [
        ],
        'argv': {},
        'targets': {},
        'assembled': [],
        'creates': False,
    },
    'productreportvalue': {
        'service': 'InventoryService',
        'method': 'stock_value_by_category',
        'fields': [
        ],
        'argv': {},
        'targets': {},
        'assembled': [],
        'creates': False,
    },
    'productrestock': {
        'service': 'InventoryService',
        'method': 'restock',
        'fields': [
            ('id', ('id', 'LOOKUP_ID', True)),
            ('qty', ('qty', 'DIRECT', True)),
        ],
        'argv': {'id': 'id', 'qty': 'qty'},
        'targets': {'id': None, 'qty': None},
        'assembled': [],
        'creates': False,
    },
    'productupdate': {
        'service': 'InventoryService',
        'method': 'update_product',
        'fields': [
            ('id', ('id', 'LOOKUP_ID', True)),
            ('name', ('data', 'DIRECT', False)),
            ('price', ('data', 'DIRECT', False)),
            ('category', ('data', 'DIRECT', False)),
        ],
        'argv': {'id': 'id', 'name': 'name', 'price': 'price', 'category': 'category'},
        'targets': {'id': None, 'data': '__mapping__:'},
        'assembled': [],
        'creates': False,
    },
}


BINDINGS = {  # (command, subcommand) -> [(action, score, need)]
    ('category', 'add'): [('categoryadd', 9, ())],
    ('category', 'delete'): [('categorydelete', 11, ())],
    ('category', 'list'): [('categorylist', 9, ())],
    ('category', 'update'): [('categoryupdate', 11, ())],
    ('product', 'add'): [('productadd', 7, ())],
    ('product', 'delete'): [('productdelete', 7, ())],
    ('product', 'list'): [('productlist', 3, ())],
    ('product', 'report low-stock'): [('productreportlowstock', 7, ())],
    ('product', 'report value'): [('productreportvalue', 5, ())],
    ('product', 'restock'): [('productrestock', 3, ())],
    ('product', 'update'): [('productupdate', 7, ())],
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


DEFAULT_DB = 'prompt_inventory.db'



COMMANDS = {'product': {'subcommands': {'add': {'binding': ('product', 'add'),
                                     'plans': [{'flags': ['--sku', '-s'],
                                                'dest': 'sku',
                                                'otype': 'str',
                                                'required': True,
                                                'default': None},
                                               {'flags': ['--name', '-n'],
                                                'dest': 'name',
                                                'otype': 'str',
                                                'required': True,
                                                'default': None},
                                               {'flags': ['--category', '-c'],
                                                'dest': 'category',
                                                'otype': 'int',
                                                'required': True,
                                                'default': None},
                                               {'flags': ['--price', '-p'],
                                                'dest': 'price',
                                                'otype': 'int',
                                                'required': True,
                                                'default': None},
                                               {'flags': ['--stock', '-q'],
                                                'dest': 'stock',
                                                'otype': 'int',
                                                'required': True,
                                                'default': None}]},
                             'list': {'binding': ('product', 'list'),
                                      'plans': [{'flags': ['--category', '-c'],
                                                 'dest': 'category',
                                                 'otype': 'int',
                                                 'required': False,
                                                 'default': None},
                                                {'flags': ['--low-only', '-l'],
                                                 'dest': 'low_only',
                                                 'otype': 'bool',
                                                 'required': False,
                                                 'default': None}]},
                             'update': {'binding': ('product', 'update'),
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
                                                  {'flags': ['--price', '-p'],
                                                   'dest': 'price',
                                                   'otype': 'int',
                                                   'required': False,
                                                   'default': None},
                                                  {'flags': ['--category', '-c'],
                                                   'dest': 'category',
                                                   'otype': 'int',
                                                   'required': False,
                                                   'default': None}]},
                             'delete': {'binding': ('product', 'delete'),
                                        'plans': [{'flags': ['--id', '-i'],
                                                   'dest': 'id',
                                                   'otype': 'int',
                                                   'required': True,
                                                   'default': None}]},
                             'restock': {'binding': ('product', 'restock'),
                                         'plans': [{'flags': ['--id', '-i'],
                                                    'dest': 'id',
                                                    'otype': 'int',
                                                    'required': True,
                                                    'default': None},
                                                   {'flags': ['--qty', '-q'],
                                                    'dest': 'qty',
                                                    'otype': 'int',
                                                    'required': True,
                                                    'default': None}]},
                             'report': {'subcommands': {'low-stock': {'binding': ('product',
                                                                                  'report low-stock'),
                                                                      'plans': []},
                                                        'value': {'binding': ('product', 'report value'),
                                                                  'plans': []}}}}},
 'category': {'subcommands': {'add': {'binding': ('category', 'add'),
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
                                                {'flags': ['--threshold', '-t'],
                                                 'dest': 'threshold',
                                                 'otype': 'int',
                                                 'required': False,
                                                 'default': None}]},
                              'list': {'binding': ('category', 'list'), 'plans': []},
                              'update': {'binding': ('category', 'update'),
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
                                                   {'flags': ['--description', '-d'],
                                                    'dest': 'description',
                                                    'otype': 'str',
                                                    'required': False,
                                                    'default': None},
                                                   {'flags': ['--threshold', '-t'],
                                                    'dest': 'threshold',
                                                    'otype': 'int',
                                                    'required': False,
                                                    'default': None}]},
                              'delete': {'binding': ('category', 'delete'),
                                         'plans': [{'flags': ['--id', '-i'],
                                                    'dest': 'id',
                                                    'otype': 'int',
                                                    'required': True,
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


@click.group('prompt_inventory')
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
        cli.main(args=argv, prog_name='prompt_inventory',
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

