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


MODELS = []
REPOSITORIES = []
SERVICES = []


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
}


BINDINGS = {  # (command, subcommand) -> (action, score)
}


def _normalize(text):
    return "".join(c for c in str(text).lower() if c.isalnum())


def build_parser():
    parser = argparse.ArgumentParser(prog='cli_tool')
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

