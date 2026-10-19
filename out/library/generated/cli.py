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


MODELS = ['Book', 'Author', 'Member', 'Loan']
REPOSITORIES = ['BookRepository', 'AuthorRepository', 'MemberRepository', 'LoanRepository']
SERVICES = ['LibraryService']


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
    'add_author': {
        'service': 'AuthorRepository',
        'method': 'create_author',
        'fields': [
            ('name', ('author', 'DIRECT', True)),
            ('birth_year', ('author', 'DIRECT', True)),
            ('biography', ('author', 'DIRECT', False)),
        ],
        'argv': {'name': None, 'birth_year': None, 'biography': None},
        'targets': {'author': 'Author'},
        'assembled': [],
    },
    'add_book': {
        'service': 'BookRepository',
        'method': 'create_book',
        'fields': [
            ('title', ('book', 'DIRECT', True)),
            ('isbn', ('isbn', 'DIRECT', True)),
            ('author_id', ('book', 'LOOKUP_ID', True)),
            ('published_year', ('book', 'DIRECT', True)),
            ('available_copies', ('book', 'DIRECT', False)),
        ],
        'argv': {'title': 'title', 'isbn': 'isbn', 'author_id': 'author_id', 'published_year': 'published_year', 'available_copies': 'copies'},
        'targets': {'book': 'Book', 'isbn': None},
        'assembled': [],
    },
    'add_member': {
        'service': 'MemberRepository',
        'method': 'create_member',
        'fields': [
            ('name', ('member', 'DIRECT', True)),
            ('email', ('email', 'DIRECT', True)),
            ('membership_date', ('member', 'ISO_DATE', False)),
        ],
        'argv': {'name': 'name', 'email': 'email', 'membership_date': None},
        'targets': {'member': 'Member', 'email': None},
        'assembled': [],
    },
    'borrow_book': {
        'service': 'LibraryService',
        'method': 'borrow_book',
        'fields': [
            ('member_id', ('member_id', 'DIRECT', True)),
            ('book_id', ('book_id', 'DIRECT', True)),
        ],
        'argv': {'member_id': 'member_id', 'book_id': 'book_id'},
        'targets': {'member_id': None, 'book_id': None},
        'assembled': [],
    },
    'find_active_members': {
        'service': 'MemberRepository',
        'method': 'find_active_members',
        'fields': [
        ],
        'argv': {},
        'targets': {},
        'assembled': [],
    },
    'get_book_loan_history': {
        'service': 'LoanRepository',
        'method': 'get_book_loan_history',
        'fields': [
            ('book_id', ('book_id', 'DIRECT', True)),
        ],
        'argv': {'book_id': None},
        'targets': {'book_id': None},
        'assembled': [],
    },
    'get_member_loan_history': {
        'service': 'LoanRepository',
        'method': 'get_member_loan_history',
        'fields': [
            ('member_id', ('member_id', 'DIRECT', True)),
        ],
        'argv': {'member_id': 'member_id'},
        'targets': {'member_id': None},
        'assembled': [],
    },
    'get_overdue_loans': {
        'service': 'LoanRepository',
        'method': 'get_overdue_loans',
        'fields': [
        ],
        'argv': {},
        'targets': {},
        'assembled': [],
    },
    'list_authors': {
        'service': 'AuthorRepository',
        'method': 'read_all_authors',
        'fields': [
        ],
        'argv': {},
        'targets': {},
        'assembled': [],
    },
    'list_books': {
        'service': 'BookRepository',
        'method': 'read_all_books',
        'fields': [
        ],
        'argv': {},
        'targets': {},
        'assembled': [],
    },
    'list_books_by_author': {
        'service': 'BookRepository',
        'method': 'filter_books_by_available_copies',
        'fields': [
            ('author_id', ('min_available_copies', 'LOOKUP_ID', True)),
        ],
        'argv': {'author_id': None},
        'targets': {'min_available_copies': None},
        'assembled': [],
    },
    'list_members': {
        'service': 'MemberRepository',
        'method': 'read_all_members',
        'fields': [
        ],
        'argv': {},
        'targets': {},
        'assembled': [],
    },
    'renew_membership': {
        'service': 'LibraryService',
        'method': 'renew_membership',
        'fields': [
            ('member_id', ('member_id', 'DIRECT', True)),
        ],
        'argv': {'member_id': None},
        'targets': {'member_id': None},
        'assembled': [],
    },
    'return_book': {
        'service': 'LibraryService',
        'method': 'return_book',
        'fields': [
            ('loan_id', ('loan_id', 'DIRECT', True)),
        ],
        'argv': {'loan_id': 'loan_id'},
        'targets': {'loan_id': None},
        'assembled': [],
    },
    'search_books': {
        'service': 'LibraryService',
        'method': 'search_books',
        'fields': [
            ('query', ('query', 'DIRECT', True)),
        ],
        'argv': {'query': 'query'},
        'targets': {'query': None},
        'assembled': [],
    },
}


BINDINGS = {  # (command, subcommand) -> [(action, score, need)]
    ('book', 'add'): [('add_book', 5, ())],
    ('book', 'list'): [('list_books', 5, ())],
    ('book', 'search'): [('search_books', 7, ())],
    ('borrow', None): [('borrow_book', 7, ())],
    ('member', 'add'): [('add_member', 5, ())],
    ('member', 'history'): [('get_member_loan_history', 7, ())],
    ('member', 'list'): [('find_active_members', 5, (('active_only', 'truthy', '-active-only'),)), ('list_members', 5, ())],
    ('overdue', None): [('get_overdue_loans', 7, ())],
    ('return', None): [('return_book', 7, ())],
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
    (`-category` without `-month`): naming the missing flag beats
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


DEFAULT_DB = 'library.db'


def build_parser():
    parser = argparse.ArgumentParser(prog='library')
    parser.add_argument('--db', default=None,
                        help=('SQLite file for record storage (default: ' + DEFAULT_DB + ' in the working directory; use :memory: to stay in memory)'))
    sub = parser.add_subparsers(dest='command')
    p_book = sub.add_parser('book')
    sub_book = p_book.add_subparsers(dest='subcommand')
    p_book_add = sub_book.add_parser('add')
    p_book_add.add_argument('-title', '-t', type=str, required=True, dest='title')
    p_book_add.add_argument('--isbn', type=str, required=True, dest='isbn')
    p_book_add.add_argument('--author-id', type=int, required=True, dest='author_id')
    p_book_add.add_argument('--published-year', type=int, required=True, dest='published_year')
    p_book_add.add_argument('--copies', type=int, required=True, dest='copies')
    p_book_add.set_defaults(_binding=('book', 'add'))
    p_book_list = sub_book.add_parser('list')
    p_book_list.add_argument('-author', '-a', action='store_true', dest='author')
    p_book_list.set_defaults(_binding=('book', 'list'))
    p_book_search = sub_book.add_parser('search')
    p_book_search.add_argument('-query', '-q', type=str, required=True, dest='query')
    p_book_search.set_defaults(_binding=('book', 'search'))
    p_member = sub.add_parser('member')
    sub_member = p_member.add_subparsers(dest='subcommand')
    p_member_add = sub_member.add_parser('add')
    p_member_add.add_argument('-name', '-n', type=str, required=True, dest='name')
    p_member_add.add_argument('-email', '-e', type=str, required=True, dest='email')
    p_member_add.set_defaults(_binding=('member', 'add'))
    p_member_list = sub_member.add_parser('list')
    p_member_list.add_argument('-active-only', '-a', action='store_true', dest='active_only')
    p_member_list.set_defaults(_binding=('member', 'list'))
    p_member_history = sub_member.add_parser('history')
    p_member_history.add_argument('--member-id', type=int, required=True, dest='member_id')
    p_member_history.set_defaults(_binding=('member', 'history'))
    p_borrow = sub.add_parser('borrow')
    p_borrow.add_argument('--member-id', type=int, required=True, dest='member_id')
    p_borrow.add_argument('--book-id', type=int, required=True, dest='book_id')
    p_borrow.set_defaults(_binding=('borrow', None))
    p_return = sub.add_parser('return')
    p_return.add_argument('--loan-id', type=int, required=True, dest='loan_id')
    p_return.set_defaults(_binding=('return', None))
    p_overdue = sub.add_parser('overdue')
    p_overdue.set_defaults(_binding=('overdue', None))
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
    choice, present = _choose(bound, values)
    trouble = _incomplete(choice, bound, present)
    if trouble:
        print(f"error: {' '.join(binding)}: {trouble}")
        return 1
    try:
        _show(_call(choice, values, deps))
    except Exception as error:
        print(f"error: {error}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

