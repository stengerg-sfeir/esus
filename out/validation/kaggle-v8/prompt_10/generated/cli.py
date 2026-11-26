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


MODELS = ['Note']
REPOSITORIES = ['NoteRepository']
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
    'create_note': {
        'service': 'NoteRepository',
        'method': 'create',
        'fields': [
            ('title', ('title', 'DIRECT', True)),
            ('content', ('content', 'DIRECT', True)),
            ('creation_date', ('creation_date', 'ISO_DATE', True)),
        ],
        'argv': {'title': 'title', 'content': 'content', 'creation_date': 'creation_date'},
        'targets': {'title': None, 'content': None, 'creation_date': None},
        'assembled': [],
        'creates': True,
    },
    'delete_note': {
        'service': 'NoteRepository',
        'method': 'delete',
        'fields': [
            ('id', ('id', 'LOOKUP_ID', True)),
            ('title', ('title', 'DIRECT', False)),
            ('content', ('content', 'DIRECT', False)),
            ('creation_date', ('creation_date', 'ISO_DATE', False)),
        ],
        'argv': {'id': 'id', 'title': 'title', 'content': 'content', 'creation_date': 'creation_date'},
        'targets': {'id': None, 'title': None, 'content': None, 'creation_date': None},
        'assembled': [],
        'creates': False,
    },
    'list_notes': {
        'service': 'NoteRepository',
        'method': 'read_all',
        'fields': [
            ('title', ('title', 'DIRECT', False)),
            ('content', ('content', 'DIRECT', False)),
            ('creation_date', ('creation_date', 'ISO_DATE', False)),
        ],
        'argv': {'title': 'title', 'content': 'content', 'creation_date': 'creation_date'},
        'targets': {'title': None, 'content': None, 'creation_date': None},
        'assembled': [],
        'creates': False,
    },
    'update_note': {
        'service': 'NoteRepository',
        'method': 'update',
        'fields': [
            ('id', ('id', 'LOOKUP_ID', True)),
            ('title', ('title', 'DIRECT', True)),
            ('content', ('content', 'DIRECT', True)),
            ('creation_date', ('creation_date', 'ISO_DATE', False)),
        ],
        'argv': {'id': 'id', 'title': 'title', 'content': 'content', 'creation_date': 'creation_date'},
        'targets': {'id': None, 'title': None, 'content': None, 'creation_date': None},
        'assembled': [],
        'creates': False,
    },
}


BINDINGS = {  # (command, subcommand) -> [(action, score, need)]
    ('Note', 'add'): [('create_note', 8, ())],
    ('Note', 'delete'): [('delete_note', 11, ())],
    ('Note', 'list'): [('list_notes', 9, ())],
    ('Note', 'update'): [('update_note', 11, ())],
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


DEFAULT_DB = 'prompt_10.db'


def build_parser():
    parser = argparse.ArgumentParser(prog='prompt_10')
    parser.add_argument('--db', default=None,
                        help=('SQLite file for record storage (default: ' + DEFAULT_DB + ' in the working directory; use :memory: to stay in memory)'))
    sub = parser.add_subparsers(dest='command')
    p_Note = sub.add_parser('Note')
    sub_Note = p_Note.add_subparsers(dest='subcommand')
    p_Note_add = sub_Note.add_parser('add')
    p_Note_add.add_argument('--title', type=str, required=True, dest='title')
    p_Note_add.add_argument('--content', type=str, required=True, dest='content')
    p_Note_add.add_argument('--creation-date', type=str, required=True, dest='creation_date')
    p_Note_add.set_defaults(_binding=('Note', 'add'))
    p_Note_list = sub_Note.add_parser('list')
    p_Note_list.add_argument('--title', type=str, required=False, dest='title')
    p_Note_list.add_argument('--content', type=str, required=False, dest='content')
    p_Note_list.add_argument('--creation-date', type=str, required=False, dest='creation_date')
    p_Note_list.set_defaults(_binding=('Note', 'list'))
    p_Note_update = sub_Note.add_parser('update')
    p_Note_update.add_argument('--id', type=int, required=True, dest='id')
    p_Note_update.add_argument('--title', type=str, required=True, dest='title')
    p_Note_update.add_argument('--content', type=str, required=True, dest='content')
    p_Note_update.add_argument('--creation-date', type=str, required=False, dest='creation_date')
    p_Note_update.set_defaults(_binding=('Note', 'update'))
    p_Note_delete = sub_Note.add_parser('delete')
    p_Note_delete.add_argument('--id', type=int, required=True, dest='id')
    p_Note_delete.add_argument('--title', type=str, required=False, dest='title')
    p_Note_delete.add_argument('--content', type=str, required=False, dest='content')
    p_Note_delete.add_argument('--creation-date', type=str, required=False, dest='creation_date')
    p_Note_delete.set_defaults(_binding=('Note', 'delete'))
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

