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
    'filter_books_by_available_copies': {
        'service': 'BookRepository',
        'method': 'filter_books_by_available_copies',
        'fields': [
            ('min_available_copies', ('min_available_copies', 'BOOL_TO_ONE', False)),
        ],
        'argv': {'min_available_copies': 'available_only'},
        'targets': {'min_available_copies': None},
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
    'find_books_by_author_author': {
        'service': 'AuthorRepository',
        'method': 'find_books_by_author',
        'fields': [
            ('author_id', ('author_id', 'DIRECT', True)),
        ],
        'argv': {'author_id': 'author'},
        'targets': {'author_id': None},
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
    ('book', 'list'): [('find_books_by_author_author', 5, (('author', 'value', '--author'),)), ('filter_books_by_available_copies', 5, (('available_only', 'truthy', '--available-only'),)), ('list_books', 5, ())],
    ('book', 'search'): [('search_books', 7, ())],
    ('borrow', None): [('borrow_book', 7, ())],
    ('member', 'add'): [('add_member', 5, ())],
    ('member', 'history'): [('get_member_loan_history', 7, ())],
    ('member', 'list'): [('find_active_members', 5, (('active_only', 'truthy', '--active-only'),)), ('list_members', 5, ())],
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


DEFAULT_DB = 'library.db'



COMMANDS = {'book': {'subcommands': {'add': {'binding': ('book', 'add'),
                                  'plans': [{'flags': ['--title', '-t'],
                                             'dest': 'title',
                                             'otype': 'str',
                                             'required': True,
                                             'default': None},
                                            {'flags': ['--isbn'],
                                             'dest': 'isbn',
                                             'otype': 'str',
                                             'required': True,
                                             'default': None},
                                            {'flags': ['--author-id'],
                                             'dest': 'author_id',
                                             'otype': 'int',
                                             'required': True,
                                             'default': None},
                                            {'flags': ['--published-year'],
                                             'dest': 'published_year',
                                             'otype': 'int',
                                             'required': True,
                                             'default': None},
                                            {'flags': ['--copies'],
                                             'dest': 'copies',
                                             'otype': 'int',
                                             'required': True,
                                             'default': None}]},
                          'list': {'binding': ('book', 'list'),
                                   'plans': [{'flags': ['--author', '-a'],
                                              'dest': 'author',
                                              'otype': 'int',
                                              'required': False,
                                              'default': None},
                                             {'flags': ['--available-only'],
                                              'dest': 'available_only',
                                              'otype': 'bool',
                                              'required': False,
                                              'default': None}]},
                          'search': {'binding': ('book', 'search'),
                                     'plans': [{'flags': ['--query', '-q'],
                                                'dest': 'query',
                                                'otype': 'str',
                                                'required': True,
                                                'default': None}]}}},
 'member': {'subcommands': {'add': {'binding': ('member', 'add'),
                                    'plans': [{'flags': ['--name', '-n'],
                                               'dest': 'name',
                                               'otype': 'str',
                                               'required': True,
                                               'default': None},
                                              {'flags': ['--email', '-e'],
                                               'dest': 'email',
                                               'otype': 'str',
                                               'required': True,
                                               'default': None}]},
                            'list': {'binding': ('member', 'list'),
                                     'plans': [{'flags': ['--active-only', '-a'],
                                                'dest': 'active_only',
                                                'otype': 'bool',
                                                'required': False,
                                                'default': None}]},
                            'history': {'binding': ('member', 'history'),
                                        'plans': [{'flags': ['--member-id'],
                                                   'dest': 'member_id',
                                                   'otype': 'int',
                                                   'required': True,
                                                   'default': None}]}}},
 'borrow': {'binding': ('borrow', None),
            'plans': [{'flags': ['--member-id'],
                       'dest': 'member_id',
                       'otype': 'int',
                       'required': True,
                       'default': None},
                      {'flags': ['--book-id'],
                       'dest': 'book_id',
                       'otype': 'int',
                       'required': True,
                       'default': None}]},
 'return': {'binding': ('return', None),
            'plans': [{'flags': ['--loan-id'],
                       'dest': 'loan_id',
                       'otype': 'int',
                       'required': True,
                       'default': None}]},
 'overdue': {'binding': ('overdue', None), 'plans': []}}


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
        group = click.Group(name)
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


@click.group('library')
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
        cli.main(args=argv, prog_name='library',
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

