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


MODELS = ['Author', 'Post', 'Tag', 'PostTag']
REPOSITORIES = ['AuthorRepository', 'PostRepository', 'TagRepository', 'PostTagRepository']
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
    'create_author': {
        'service': 'AuthorRepository',
        'method': 'create_author',
        'fields': [
            ('name', ('name', 'DIRECT', True)),
            ('email', ('email', 'DIRECT', True)),
        ],
        'argv': {'name': 'name', 'email': 'email'},
        'targets': {'name': None, 'email': None},
        'assembled': [],
        'creates': True,
    },
    'create_post': {
        'service': 'PostRepository',
        'method': 'create_post',
        'fields': [
            ('title', ('title', 'DIRECT', True)),
            ('content', ('content', 'DIRECT', True)),
            ('author_id', ('author_id', 'LOOKUP_ID', True)),
        ],
        'argv': {'title': 'title', 'content': 'content', 'author_id': 'author_id'},
        'targets': {'title': None, 'content': None, 'author_id': None},
        'assembled': [],
        'creates': True,
    },
    'create_post_tag_association': {
        'service': 'PostTagRepository',
        'method': 'create_post_tag_association',
        'fields': [
            ('post_id', ('post_id', 'LOOKUP_ID', True)),
            ('tag_id', ('tag_id', 'LOOKUP_ID', True)),
        ],
        'argv': {'post_id': 'post_id', 'tag_id': 'tag_id'},
        'targets': {'post_id': None, 'tag_id': None},
        'assembled': [],
        'creates': True,
    },
    'create_tag': {
        'service': 'TagRepository',
        'method': 'create_tag',
        'fields': [
            ('name', ('name', 'DIRECT', True)),
        ],
        'argv': {'name': 'name'},
        'targets': {'name': None},
        'assembled': [],
        'creates': True,
    },
    'delete_author': {
        'service': 'AuthorRepository',
        'method': 'delete_author',
        'fields': [
            ('author_id', ('author_id', 'LOOKUP_ID', True)),
        ],
        'argv': {'author_id': 'author_id'},
        'targets': {'author_id': None},
        'assembled': [],
        'creates': False,
    },
    'delete_post': {
        'service': 'PostRepository',
        'method': 'delete_post',
        'fields': [
            ('post_id', ('post_id', 'LOOKUP_ID', True)),
        ],
        'argv': {'post_id': 'post_id'},
        'targets': {'post_id': None},
        'assembled': [],
        'creates': False,
    },
    'delete_tag': {
        'service': 'TagRepository',
        'method': 'delete_tag',
        'fields': [
            ('tag_id', ('tag_id', 'LOOKUP_ID', True)),
        ],
        'argv': {'tag_id': 'tag_id'},
        'targets': {'tag_id': None},
        'assembled': [],
        'creates': False,
    },
    'update_author': {
        'service': 'AuthorRepository',
        'method': 'update_author',
        'fields': [
            ('author_id', ('author_id', 'LOOKUP_ID', True)),
            ('name', ('name', 'DIRECT', True)),
            ('email', ('email', 'DIRECT', True)),
        ],
        'argv': {'author_id': 'author_id', 'name': 'name', 'email': 'email'},
        'targets': {'author_id': None, 'name': None, 'email': None},
        'assembled': [],
        'creates': False,
    },
    'update_post': {
        'service': 'PostRepository',
        'method': 'update_post',
        'fields': [
            ('post_id', ('post_id', 'LOOKUP_ID', True)),
            ('title', ('title', 'DIRECT', True)),
            ('content', ('content', 'DIRECT', True)),
        ],
        'argv': {'post_id': 'post_id', 'title': 'title', 'content': 'content'},
        'targets': {'post_id': None, 'title': None, 'content': None},
        'assembled': [],
        'creates': False,
    },
    'update_tag': {
        'service': 'TagRepository',
        'method': 'update_tag',
        'fields': [
            ('tag_id', ('tag_id', 'LOOKUP_ID', True)),
            ('name', ('name', 'DIRECT', True)),
        ],
        'argv': {'tag_id': 'tag_id', 'name': 'name'},
        'targets': {'tag_id': None, 'name': None},
        'assembled': [],
        'creates': False,
    },
}


BINDINGS = {  # (command, subcommand) -> [(action, score, need)]
    ('Author', 'add'): [('create_author', 8, ())],
    ('Author', 'delete'): [('delete_author', 11, ())],
    ('Author', 'update'): [('update_author', 11, ())],
    ('Post', 'add'): [('create_post', 8, ())],
    ('Post', 'delete'): [('delete_post', 11, ())],
    ('Post', 'update'): [('update_post', 11, ())],
    ('PostTag', 'add'): [('create_post_tag_association', 8, ())],
    ('Tag', 'add'): [('create_tag', 8, ())],
    ('Tag', 'delete'): [('delete_tag', 11, ())],
    ('Tag', 'update'): [('update_tag', 11, ())],
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


DEFAULT_DB = 'prompt_23.db'


def build_parser():
    parser = argparse.ArgumentParser(prog='prompt_23')
    parser.add_argument('--db', default=None,
                        help=('SQLite file for record storage (default: ' + DEFAULT_DB + ' in the working directory; use :memory: to stay in memory)'))
    sub = parser.add_subparsers(dest='command')
    p_Author = sub.add_parser('Author')
    sub_Author = p_Author.add_subparsers(dest='subcommand')
    p_Author_add = sub_Author.add_parser('add')
    p_Author_add.add_argument('--name', type=str, required=True, dest='name')
    p_Author_add.add_argument('--email', type=str, required=True, dest='email')
    p_Author_add.set_defaults(_binding=('Author', 'add'))
    p_Author_update = sub_Author.add_parser('update')
    p_Author_update.add_argument('--author-id', type=int, required=True, dest='author_id')
    p_Author_update.add_argument('--name', type=str, required=True, dest='name')
    p_Author_update.add_argument('--email', type=str, required=True, dest='email')
    p_Author_update.set_defaults(_binding=('Author', 'update'))
    p_Author_delete = sub_Author.add_parser('delete')
    p_Author_delete.add_argument('--author-id', type=int, required=True, dest='author_id')
    p_Author_delete.set_defaults(_binding=('Author', 'delete'))
    p_Post = sub.add_parser('Post')
    sub_Post = p_Post.add_subparsers(dest='subcommand')
    p_Post_add = sub_Post.add_parser('add')
    p_Post_add.add_argument('--title', type=str, required=True, dest='title')
    p_Post_add.add_argument('--content', type=str, required=True, dest='content')
    p_Post_add.add_argument('--author-id', type=int, required=True, dest='author_id')
    p_Post_add.set_defaults(_binding=('Post', 'add'))
    p_Post_update = sub_Post.add_parser('update')
    p_Post_update.add_argument('--post-id', type=int, required=True, dest='post_id')
    p_Post_update.add_argument('--title', type=str, required=True, dest='title')
    p_Post_update.add_argument('--content', type=str, required=True, dest='content')
    p_Post_update.set_defaults(_binding=('Post', 'update'))
    p_Post_delete = sub_Post.add_parser('delete')
    p_Post_delete.add_argument('--post-id', type=int, required=True, dest='post_id')
    p_Post_delete.set_defaults(_binding=('Post', 'delete'))
    p_Tag = sub.add_parser('Tag')
    sub_Tag = p_Tag.add_subparsers(dest='subcommand')
    p_Tag_add = sub_Tag.add_parser('add')
    p_Tag_add.add_argument('--name', type=str, required=True, dest='name')
    p_Tag_add.set_defaults(_binding=('Tag', 'add'))
    p_Tag_update = sub_Tag.add_parser('update')
    p_Tag_update.add_argument('--tag-id', type=int, required=True, dest='tag_id')
    p_Tag_update.add_argument('--name', type=str, required=True, dest='name')
    p_Tag_update.set_defaults(_binding=('Tag', 'update'))
    p_Tag_delete = sub_Tag.add_parser('delete')
    p_Tag_delete.add_argument('--tag-id', type=int, required=True, dest='tag_id')
    p_Tag_delete.set_defaults(_binding=('Tag', 'delete'))
    p_PostTag = sub.add_parser('PostTag')
    sub_PostTag = p_PostTag.add_subparsers(dest='subcommand')
    p_PostTag_add = sub_PostTag.add_parser('add')
    p_PostTag_add.add_argument('--post-id', type=int, required=True, dest='post_id')
    p_PostTag_add.add_argument('--tag-id', type=int, required=True, dest='tag_id')
    p_PostTag_add.set_defaults(_binding=('PostTag', 'add'))
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

