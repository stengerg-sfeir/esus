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


MODELS = ['Wine', 'StorageLocation']
REPOSITORIES = ['WineRepository', 'StorageLocationRepository']
SERVICES = ['WineLocationService']


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
    'assign_wine_to_location': {
        'service': 'WineLocationService',
        'method': 'assign_wine_to_location',
        'fields': [
            ('wine_id', ('wine_id', 'DIRECT', True)),
            ('location_id', ('location_id', 'DIRECT', True)),
        ],
        'argv': {'wine_id': None, 'location_id': None},
        'targets': {'wine_id': None, 'location_id': None},
        'assembled': [],
    },
    'create_location': {
        'service': 'StorageLocationRepository',
        'method': 'create_location',
        'fields': [
            ('zone_name', ('zone_name', 'DIRECT', True)),
            ('row_number', ('row_number', 'DIRECT', True)),
            ('shelf_number', ('shelf_number', 'DIRECT', True)),
            ('max_bottle_capacity', ('max_bottle_capacity', 'DIRECT', True)),
        ],
        'argv': {'zone_name': None, 'row_number': None, 'shelf_number': None, 'max_bottle_capacity': None},
        'targets': {'zone_name': None, 'row_number': None, 'shelf_number': None, 'max_bottle_capacity': None},
        'assembled': [],
    },
    'create_wine': {
        'service': 'WineRepository',
        'method': 'create_wine',
        'fields': [
            ('wine_name', ('wine_name', 'DIRECT', True)),
            ('vintage_year', ('vintage_year', 'DIRECT', True)),
            ('wine_type', ('wine_type', 'DIRECT', True)),
            ('country_of_origin', ('country_of_origin', 'DIRECT', True)),
            ('cost_price', ('cost_price', 'DECIMAL_TO_CENTS', True)),
            ('selling_price', ('selling_price', 'DECIMAL_TO_CENTS', True)),
            ('stock_quantity', ('stock_quantity', 'DIRECT', True)),
        ],
        'argv': {'wine_name': None, 'vintage_year': None, 'wine_type': None, 'country_of_origin': None, 'cost_price': None, 'selling_price': None, 'stock_quantity': None},
        'targets': {'wine_name': None, 'vintage_year': None, 'wine_type': None, 'country_of_origin': None, 'cost_price': None, 'selling_price': None, 'stock_quantity': None},
        'assembled': [],
    },
    'delete_location': {
        'service': 'StorageLocationRepository',
        'method': 'delete_location',
        'fields': [
            ('location_id', ('location_id', 'DIRECT', True)),
        ],
        'argv': {'location_id': None},
        'targets': {'location_id': None},
        'assembled': [],
    },
    'delete_wine': {
        'service': 'WineRepository',
        'method': 'delete_wine',
        'fields': [
            ('wine_id', ('wine_id', 'DIRECT', True)),
        ],
        'argv': {'wine_id': None},
        'targets': {'wine_id': None},
        'assembled': [],
    },
    'get_wine_by_location': {
        'service': 'WineLocationService',
        'method': 'get_wine_by_location',
        'fields': [
            ('location_id', ('location_id', 'DIRECT', True)),
        ],
        'argv': {'location_id': None},
        'targets': {'location_id': None},
        'assembled': [],
    },
    'read_all_locations': {
        'service': 'StorageLocationRepository',
        'method': 'read_all_locations',
        'fields': [
        ],
        'argv': {},
        'targets': {},
        'assembled': [],
    },
    'read_all_wines': {
        'service': 'WineRepository',
        'method': 'read_all_wines',
        'fields': [
        ],
        'argv': {},
        'targets': {},
        'assembled': [],
    },
    'read_location_by_id': {
        'service': 'StorageLocationRepository',
        'method': 'read_location_by_id',
        'fields': [
            ('location_id', ('location_id', 'DIRECT', True)),
        ],
        'argv': {'location_id': None},
        'targets': {'location_id': None},
        'assembled': [],
    },
    'read_wine_by_id': {
        'service': 'WineRepository',
        'method': 'read_wine_by_id',
        'fields': [
            ('wine_id', ('wine_id', 'DIRECT', True)),
        ],
        'argv': {'wine_id': None},
        'targets': {'wine_id': None},
        'assembled': [],
    },
    'remove_wine_from_location': {
        'service': 'WineLocationService',
        'method': 'remove_wine_from_location',
        'fields': [
            ('wine_id', ('wine_id', 'DIRECT', True)),
        ],
        'argv': {'wine_id': None},
        'targets': {'wine_id': None},
        'assembled': [],
    },
    'update_location': {
        'service': 'StorageLocationRepository',
        'method': 'update_location',
        'fields': [
            ('location_id', ('location_id', 'DIRECT', True)),
            ('zone_name', ('zone_name', 'DIRECT', False)),
            ('row_number', ('row_number', 'DIRECT', False)),
            ('shelf_number', ('shelf_number', 'DIRECT', False)),
            ('max_bottle_capacity', ('max_bottle_capacity', 'DIRECT', False)),
        ],
        'argv': {'location_id': None, 'zone_name': None, 'row_number': None, 'shelf_number': None, 'max_bottle_capacity': None},
        'targets': {'location_id': None, 'zone_name': None, 'row_number': None, 'shelf_number': None, 'max_bottle_capacity': None},
        'assembled': [],
    },
    'update_wine': {
        'service': 'WineRepository',
        'method': 'update_wine',
        'fields': [
            ('wine_id', ('wine_id', 'DIRECT', True)),
            ('wine_name', ('wine_name', 'DIRECT', False)),
            ('vintage_year', ('vintage_year', 'DIRECT', False)),
            ('wine_type', ('wine_type', 'DIRECT', False)),
            ('country_of_origin', ('country_of_origin', 'DIRECT', False)),
            ('cost_price', ('cost_price', 'DECIMAL_TO_CENTS', False)),
            ('selling_price', ('selling_price', 'DECIMAL_TO_CENTS', False)),
            ('stock_quantity', ('stock_quantity', 'DIRECT', False)),
        ],
        'argv': {'wine_id': None, 'wine_name': None, 'vintage_year': None, 'wine_type': None, 'country_of_origin': None, 'cost_price': None, 'selling_price': None, 'stock_quantity': None},
        'targets': {'wine_id': None, 'wine_name': None, 'vintage_year': None, 'wine_type': None, 'country_of_origin': None, 'cost_price': None, 'selling_price': None, 'stock_quantity': None},
        'assembled': [],
    },
}


BINDINGS = {  # (command, subcommand) -> (action, score)
}


def _normalize(text):
    return "".join(c for c in str(text).lower() if c.isalnum())


def build_parser():
    parser = argparse.ArgumentParser(prog='gui')
    sub = parser.add_subparsers(dest='command')
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


def build_cli():
    store = Store()
    repos = {cls_name: getattr(repositories, cls_name)(store) for cls_name in REPOSITORIES}
    hired = {cls_name: getattr(services, cls_name)(repos) for cls_name in SERVICES}
    entities = {_normalize(name): getattr(models, name) for name in MODELS}
    return build_parser(), {'store': store, 'repos': repos,
                           'services': {**repos, **hired},
                           'entities': entities}


def main(argv=None):
    parser, deps = build_cli()
    return dispatch(parser, parser.parse_args(argv), deps)


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
              if key not in ('command', 'subcommand', '_binding')}
    try:
        _show(_call(bound, values, deps))
    except Exception as error:
        print(f"error: {error}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

