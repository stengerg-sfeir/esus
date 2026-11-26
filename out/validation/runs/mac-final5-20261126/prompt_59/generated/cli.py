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

import argparse
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


MODELS = ['Customer', 'Product', 'Order', 'OrderLine', 'Discount', 'Tax']
REPOSITORIES = ['CustomerRepository', 'ProductRepository', 'OrderRepository', 'OrderLineRepository', 'DiscountRepository', 'TaxRepository']
SERVICES = []


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
    'customeradd': {
        'service': 'CustomerRepository',
        'method': 'create',
        'fields': [
            ('name', ('name', 'DIRECT', False)),
            ('email', ('email', 'DIRECT', False)),
        ],
        'argv': {'name': 'name', 'email': 'email'},
        'targets': {'name': None, 'email': None},
        'assembled': [],
        'creates': True,
    },
    'customerdelete': {
        'service': 'CustomerRepository',
        'method': 'delete',
        'fields': [
            ('customer_id', ('customer_id', 'LOOKUP_ID', True)),
            ('name', ('name', 'DIRECT', False)),
            ('email', ('email', 'DIRECT', False)),
        ],
        'argv': {'customer_id': 'customer_id', 'name': 'name', 'email': 'email'},
        'targets': {'customer_id': None, 'name': None, 'email': None},
        'assembled': [],
        'creates': False,
    },
    'customerupdate': {
        'service': 'CustomerRepository',
        'method': 'update',
        'fields': [
            ('customer_id', ('customer_id', 'LOOKUP_ID', True)),
            ('name', ('name', 'DIRECT', False)),
            ('email', ('email', 'DIRECT', False)),
        ],
        'argv': {'customer_id': 'customer_id', 'name': 'name', 'email': 'email'},
        'targets': {'customer_id': None, 'name': None, 'email': None},
        'assembled': [],
        'creates': False,
    },
    'discountadd': {
        'service': 'DiscountRepository',
        'method': 'create',
        'fields': [
            ('name', ('name', 'DIRECT', False)),
            ('value', ('value', 'DECIMAL_TO_CENTS', False)),
            ('type', ('type', 'DIRECT', False)),
        ],
        'argv': {'name': 'name', 'value': 'value', 'type': 'type'},
        'targets': {'name': None, 'value': None, 'type': None},
        'assembled': [],
        'creates': True,
    },
    'discountdelete': {
        'service': 'DiscountRepository',
        'method': 'delete',
        'fields': [
            ('discount_id', ('discount_id', 'LOOKUP_ID', True)),
            ('name', ('name', 'DIRECT', False)),
            ('value', ('value', 'DECIMAL_TO_CENTS', False)),
            ('type', ('type', 'DIRECT', False)),
        ],
        'argv': {'discount_id': 'discount_id', 'name': 'name', 'value': 'value', 'type': 'type'},
        'targets': {'discount_id': None, 'name': None, 'value': None, 'type': None},
        'assembled': [],
        'creates': False,
    },
    'discountupdate': {
        'service': 'DiscountRepository',
        'method': 'update',
        'fields': [
            ('discount_id', ('discount_id', 'LOOKUP_ID', True)),
            ('name', ('name', 'DIRECT', False)),
            ('value', ('value', 'DECIMAL_TO_CENTS', False)),
            ('type', ('type', 'DIRECT', False)),
        ],
        'argv': {'discount_id': 'discount_id', 'name': 'name', 'value': 'value', 'type': 'type'},
        'targets': {'discount_id': None, 'name': None, 'value': None, 'type': None},
        'assembled': [],
        'creates': False,
    },
    'ordercancel': {
        'service': 'OrderRepository',
        'method': 'cancel_order',
        'fields': [
            ('order_id', ('order_id', 'LOOKUP_ID', True)),
        ],
        'argv': {'order_id': 'order_id'},
        'targets': {'order_id': None},
        'assembled': [],
        'creates': False,
    },
    'orderdelete': {
        'service': 'OrderRepository',
        'method': 'delete',
        'fields': [
            ('order_id', ('order_id', 'LOOKUP_ID', True)),
        ],
        'argv': {'order_id': 'order_id'},
        'targets': {'order_id': None},
        'assembled': [],
        'creates': False,
    },
    'orderlineadd': {
        'service': 'OrderLineRepository',
        'method': 'create',
        'fields': [
            ('order_id', ('order_id', 'LOOKUP_ID', False)),
            ('product_id', ('product_id', 'LOOKUP_ID', False)),
            ('quantity', ('quantity', 'DIRECT', False)),
            ('unit_price', ('unit_price', 'DECIMAL_TO_CENTS', False)),
        ],
        'argv': {'order_id': 'order_id', 'product_id': 'product_id', 'quantity': 'quantity', 'unit_price': 'unit_price'},
        'targets': {'order_id': None, 'product_id': None, 'quantity': None, 'unit_price': None},
        'assembled': [],
        'creates': True,
    },
    'orderlinedelete': {
        'service': 'OrderLineRepository',
        'method': 'delete',
        'fields': [
            ('order_line_id', ('order_line_id', 'LOOKUP_ID', True)),
            ('order_id', ('order_id', 'LOOKUP_ID', False)),
            ('product_id', ('product_id', 'LOOKUP_ID', False)),
            ('quantity', ('quantity', 'DIRECT', False)),
            ('unit_price', ('unit_price', 'DECIMAL_TO_CENTS', False)),
        ],
        'argv': {'order_line_id': 'order_line_id', 'order_id': 'order_id', 'product_id': 'product_id', 'quantity': 'quantity', 'unit_price': 'unit_price'},
        'targets': {'order_line_id': None, 'order_id': None, 'product_id': None, 'quantity': None, 'unit_price': None},
        'assembled': [],
        'creates': False,
    },
    'orderlineupdate': {
        'service': 'OrderLineRepository',
        'method': 'update',
        'fields': [
            ('order_line_id', ('order_line_id', 'LOOKUP_ID', True)),
            ('order_id', ('order_id', 'LOOKUP_ID', False)),
            ('product_id', ('product_id', 'LOOKUP_ID', False)),
            ('quantity', ('quantity', 'DIRECT', False)),
            ('unit_price', ('unit_price', 'DECIMAL_TO_CENTS', False)),
        ],
        'argv': {'order_line_id': 'order_line_id', 'order_id': 'order_id', 'product_id': 'product_id', 'quantity': 'quantity', 'unit_price': 'unit_price'},
        'targets': {'order_line_id': None, 'order_id': None, 'product_id': None, 'quantity': None, 'unit_price': None},
        'assembled': [],
        'creates': False,
    },
    'orderupdate': {
        'service': 'OrderRepository',
        'method': 'update',
        'fields': [
            ('order_id', ('order_id', 'LOOKUP_ID', True)),
        ],
        'argv': {'order_id': 'order_id'},
        'targets': {'order_id': None},
        'assembled': [],
        'creates': False,
    },
    'productadd': {
        'service': 'ProductRepository',
        'method': 'create',
        'fields': [
            ('name', ('name', 'DIRECT', False)),
            ('price', ('price', 'DECIMAL_TO_CENTS', False)),
            ('stock_level', ('stock_level', 'DIRECT', False)),
        ],
        'argv': {'name': 'name', 'price': 'price', 'stock_level': 'stock_level'},
        'targets': {'name': None, 'price': None, 'stock_level': None},
        'assembled': [],
        'creates': True,
    },
    'productdelete': {
        'service': 'ProductRepository',
        'method': 'delete',
        'fields': [
            ('product_id', ('product_id', 'LOOKUP_ID', True)),
            ('name', ('name', 'DIRECT', False)),
            ('price', ('price', 'DECIMAL_TO_CENTS', False)),
            ('stock_level', ('stock_level', 'DIRECT', False)),
        ],
        'argv': {'product_id': 'product_id', 'name': 'name', 'price': 'price', 'stock_level': 'stock_level'},
        'targets': {'product_id': None, 'name': None, 'price': None, 'stock_level': None},
        'assembled': [],
        'creates': False,
    },
    'productupdate': {
        'service': 'ProductRepository',
        'method': 'update',
        'fields': [
            ('product_id', ('product_id', 'LOOKUP_ID', True)),
            ('name', ('name', 'DIRECT', False)),
            ('price', ('price', 'DECIMAL_TO_CENTS', False)),
            ('stock_level', ('stock_level', 'DIRECT', False)),
        ],
        'argv': {'product_id': 'product_id', 'name': 'name', 'price': 'price', 'stock_level': 'stock_level'},
        'targets': {'product_id': None, 'name': None, 'price': None, 'stock_level': None},
        'assembled': [],
        'creates': False,
    },
    'taxadd': {
        'service': 'TaxRepository',
        'method': 'create',
        'fields': [
            ('name', ('name', 'DIRECT', False)),
            ('rate', ('rate', 'DIRECT', False)),
        ],
        'argv': {'name': 'name', 'rate': 'rate'},
        'targets': {'name': None, 'rate': None},
        'assembled': [],
        'creates': True,
    },
    'taxdelete': {
        'service': 'TaxRepository',
        'method': 'delete',
        'fields': [
            ('tax_id', ('tax_id', 'LOOKUP_ID', True)),
            ('name', ('name', 'DIRECT', False)),
            ('rate', ('rate', 'DIRECT', False)),
        ],
        'argv': {'tax_id': 'tax_id', 'name': 'name', 'rate': 'rate'},
        'targets': {'tax_id': None, 'name': None, 'rate': None},
        'assembled': [],
        'creates': False,
    },
    'taxupdate': {
        'service': 'TaxRepository',
        'method': 'update',
        'fields': [
            ('tax_id', ('tax_id', 'LOOKUP_ID', True)),
            ('name', ('name', 'DIRECT', False)),
            ('rate', ('rate', 'DIRECT', False)),
        ],
        'argv': {'tax_id': 'tax_id', 'name': 'name', 'rate': 'rate'},
        'targets': {'tax_id': None, 'name': None, 'rate': None},
        'assembled': [],
        'creates': False,
    },
}


BINDINGS = {  # (command, subcommand) -> [(action, score, need)]
    ('Customer', 'add'): [('customeradd', 9, ())],
    ('Customer', 'delete'): [('customerdelete', 11, ())],
    ('Customer', 'update'): [('customerupdate', 11, ())],
    ('Discount', 'add'): [('discountadd', 9, ())],
    ('Discount', 'delete'): [('discountdelete', 11, ())],
    ('Discount', 'update'): [('discountupdate', 11, ())],
    ('Order', 'cancel'): [('ordercancel', 11, ())],
    ('Order', 'delete'): [('orderdelete', 11, ())],
    ('Order', 'update'): [('orderupdate', 11, ())],
    ('OrderLine', 'add'): [('orderlineadd', 9, ())],
    ('OrderLine', 'delete'): [('orderlinedelete', 11, ())],
    ('OrderLine', 'update'): [('orderlineupdate', 11, ())],
    ('Product', 'add'): [('productadd', 9, ())],
    ('Product', 'delete'): [('productdelete', 11, ())],
    ('Product', 'update'): [('productupdate', 11, ())],
    ('Tax', 'add'): [('taxadd', 9, ())],
    ('Tax', 'delete'): [('taxdelete', 11, ())],
    ('Tax', 'update'): [('taxupdate', 11, ())],
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


DEFAULT_DB = 'prompt_59.db'


def build_parser():
    parser = argparse.ArgumentParser(prog='prompt_59')
    parser.add_argument('--db', default=None,
                        help=('SQLite file for record storage (default: ' + DEFAULT_DB + ' in the working directory; use :memory: to stay in memory)'))
    sub = parser.add_subparsers(dest='command')
    p_Order = sub.add_parser('Order')
    sub_Order = p_Order.add_subparsers(dest='subcommand')
    p_Order_cancel = sub_Order.add_parser('cancel')
    p_Order_cancel.add_argument('--order-id', type=int, required=True, dest='order_id')
    p_Order_cancel.set_defaults(_binding=('Order', 'cancel'))
    p_Order_update = sub_Order.add_parser('update')
    p_Order_update.add_argument('--order-id', type=int, required=True, dest='order_id')
    p_Order_update.set_defaults(_binding=('Order', 'update'))
    p_Order_delete = sub_Order.add_parser('delete')
    p_Order_delete.add_argument('--order-id', type=int, required=True, dest='order_id')
    p_Order_delete.set_defaults(_binding=('Order', 'delete'))
    p_Customer = sub.add_parser('Customer')
    sub_Customer = p_Customer.add_subparsers(dest='subcommand')
    p_Customer_add = sub_Customer.add_parser('add')
    p_Customer_add.add_argument('--name', type=str, required=False, dest='name')
    p_Customer_add.add_argument('--email', type=str, required=False, dest='email')
    p_Customer_add.set_defaults(_binding=('Customer', 'add'))
    p_Customer_update = sub_Customer.add_parser('update')
    p_Customer_update.add_argument('--customer-id', type=int, required=True, dest='customer_id')
    p_Customer_update.add_argument('--name', type=str, required=False, dest='name')
    p_Customer_update.add_argument('--email', type=str, required=False, dest='email')
    p_Customer_update.set_defaults(_binding=('Customer', 'update'))
    p_Customer_delete = sub_Customer.add_parser('delete')
    p_Customer_delete.add_argument('--customer-id', type=int, required=True, dest='customer_id')
    p_Customer_delete.add_argument('--name', type=str, required=False, dest='name')
    p_Customer_delete.add_argument('--email', type=str, required=False, dest='email')
    p_Customer_delete.set_defaults(_binding=('Customer', 'delete'))
    p_Product = sub.add_parser('Product')
    sub_Product = p_Product.add_subparsers(dest='subcommand')
    p_Product_add = sub_Product.add_parser('add')
    p_Product_add.add_argument('--name', type=str, required=False, dest='name')
    p_Product_add.add_argument('--price', type=int, required=False, dest='price')
    p_Product_add.add_argument('--stock-level', type=int, required=False, dest='stock_level')
    p_Product_add.set_defaults(_binding=('Product', 'add'))
    p_Product_update = sub_Product.add_parser('update')
    p_Product_update.add_argument('--product-id', type=int, required=True, dest='product_id')
    p_Product_update.add_argument('--name', type=str, required=False, dest='name')
    p_Product_update.add_argument('--price', type=int, required=False, dest='price')
    p_Product_update.add_argument('--stock-level', type=int, required=False, dest='stock_level')
    p_Product_update.set_defaults(_binding=('Product', 'update'))
    p_Product_delete = sub_Product.add_parser('delete')
    p_Product_delete.add_argument('--product-id', type=int, required=True, dest='product_id')
    p_Product_delete.add_argument('--name', type=str, required=False, dest='name')
    p_Product_delete.add_argument('--price', type=int, required=False, dest='price')
    p_Product_delete.add_argument('--stock-level', type=int, required=False, dest='stock_level')
    p_Product_delete.set_defaults(_binding=('Product', 'delete'))
    p_OrderLine = sub.add_parser('OrderLine')
    sub_OrderLine = p_OrderLine.add_subparsers(dest='subcommand')
    p_OrderLine_add = sub_OrderLine.add_parser('add')
    p_OrderLine_add.add_argument('--order-id', type=int, required=False, dest='order_id')
    p_OrderLine_add.add_argument('--product-id', type=int, required=False, dest='product_id')
    p_OrderLine_add.add_argument('--quantity', type=int, required=False, dest='quantity')
    p_OrderLine_add.add_argument('--unit-price', type=int, required=False, dest='unit_price')
    p_OrderLine_add.set_defaults(_binding=('OrderLine', 'add'))
    p_OrderLine_update = sub_OrderLine.add_parser('update')
    p_OrderLine_update.add_argument('--order-line-id', type=int, required=True, dest='order_line_id')
    p_OrderLine_update.add_argument('--order-id', type=int, required=False, dest='order_id')
    p_OrderLine_update.add_argument('--product-id', type=int, required=False, dest='product_id')
    p_OrderLine_update.add_argument('--quantity', type=int, required=False, dest='quantity')
    p_OrderLine_update.add_argument('--unit-price', type=int, required=False, dest='unit_price')
    p_OrderLine_update.set_defaults(_binding=('OrderLine', 'update'))
    p_OrderLine_delete = sub_OrderLine.add_parser('delete')
    p_OrderLine_delete.add_argument('--order-line-id', type=int, required=True, dest='order_line_id')
    p_OrderLine_delete.add_argument('--order-id', type=int, required=False, dest='order_id')
    p_OrderLine_delete.add_argument('--product-id', type=int, required=False, dest='product_id')
    p_OrderLine_delete.add_argument('--quantity', type=int, required=False, dest='quantity')
    p_OrderLine_delete.add_argument('--unit-price', type=int, required=False, dest='unit_price')
    p_OrderLine_delete.set_defaults(_binding=('OrderLine', 'delete'))
    p_Discount = sub.add_parser('Discount')
    sub_Discount = p_Discount.add_subparsers(dest='subcommand')
    p_Discount_add = sub_Discount.add_parser('add')
    p_Discount_add.add_argument('--name', type=str, required=False, dest='name')
    p_Discount_add.add_argument('--value', type=int, required=False, dest='value')
    p_Discount_add.add_argument('--type', type=str, required=False, dest='type')
    p_Discount_add.set_defaults(_binding=('Discount', 'add'))
    p_Discount_update = sub_Discount.add_parser('update')
    p_Discount_update.add_argument('--discount-id', type=int, required=True, dest='discount_id')
    p_Discount_update.add_argument('--name', type=str, required=False, dest='name')
    p_Discount_update.add_argument('--value', type=int, required=False, dest='value')
    p_Discount_update.add_argument('--type', type=str, required=False, dest='type')
    p_Discount_update.set_defaults(_binding=('Discount', 'update'))
    p_Discount_delete = sub_Discount.add_parser('delete')
    p_Discount_delete.add_argument('--discount-id', type=int, required=True, dest='discount_id')
    p_Discount_delete.add_argument('--name', type=str, required=False, dest='name')
    p_Discount_delete.add_argument('--value', type=int, required=False, dest='value')
    p_Discount_delete.add_argument('--type', type=str, required=False, dest='type')
    p_Discount_delete.set_defaults(_binding=('Discount', 'delete'))
    p_Tax = sub.add_parser('Tax')
    sub_Tax = p_Tax.add_subparsers(dest='subcommand')
    p_Tax_add = sub_Tax.add_parser('add')
    p_Tax_add.add_argument('--name', type=str, required=False, dest='name')
    p_Tax_add.add_argument('--rate', type=int, required=False, dest='rate')
    p_Tax_add.set_defaults(_binding=('Tax', 'add'))
    p_Tax_update = sub_Tax.add_parser('update')
    p_Tax_update.add_argument('--tax-id', type=int, required=True, dest='tax_id')
    p_Tax_update.add_argument('--name', type=str, required=False, dest='name')
    p_Tax_update.add_argument('--rate', type=int, required=False, dest='rate')
    p_Tax_update.set_defaults(_binding=('Tax', 'update'))
    p_Tax_delete = sub_Tax.add_parser('delete')
    p_Tax_delete.add_argument('--tax-id', type=int, required=True, dest='tax_id')
    p_Tax_delete.add_argument('--name', type=str, required=False, dest='name')
    p_Tax_delete.add_argument('--rate', type=int, required=False, dest='rate')
    p_Tax_delete.set_defaults(_binding=('Tax', 'delete'))
    return parser


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
    binding = (getattr(args, '_binding', None)
               or getattr(args, '_parent_binding', None))
    if binding is None:
        parser.print_usage()
        return 2
    bound = BINDINGS.get(tuple(binding))
    if bound is None:
        print(f"no adapter bound for {' '.join(binding)} — not implemented")
        return 1
    values = {key: value for key, value in vars(args).items()
              if key not in ('command', 'subcommand', '_binding',
                             '_parent_binding', 'db')}
    choice, present = _choose(bound, values)
    trouble = _incomplete(choice, bound, present)
    if trouble:
        print(f"error: {' '.join(binding)}: {trouble}")
        return 1
    try:
        _show(_call(choice, values, deps))
    except Exception as error:
        print(f"error: {_error_text(error)}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

