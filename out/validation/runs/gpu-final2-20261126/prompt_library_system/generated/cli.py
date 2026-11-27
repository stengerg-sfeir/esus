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


MODELS = ['Author', 'Book', 'Loan', 'Member']
REPOSITORIES = ['AuthorRepository', 'BookRepository', 'LoanRepository', 'MemberRepository']
SERVICES = ['LibraryService']


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
    'authoradd': {
        'service': 'AuthorRepository',
        'method': 'create',
        'fields': [
            ('name', ('name', 'DIRECT', True)),
            ('birth_year', ('birth_year', 'DIRECT', True)),
            ('biography', ('biography', 'DIRECT', False)),
        ],
        'argv': {'name': 'name', 'birth_year': 'birth_year', 'biography': 'biography'},
        'targets': {'name': None, 'birth_year': None, 'biography': None},
        'assembled': [],
        'creates': True,
    },
    'authordelete': {
        'service': 'AuthorRepository',
        'method': 'delete',
        'fields': [
            ('id', ('id', 'LOOKUP_ID', True)),
            ('name', ('name', 'DIRECT', False)),
            ('birth_year', ('birth_year', 'DIRECT', False)),
            ('biography', ('biography', 'DIRECT', False)),
        ],
        'argv': {'id': 'id', 'name': 'name', 'birth_year': 'birth_year', 'biography': 'biography'},
        'targets': {'id': None, 'name': None, 'birth_year': None, 'biography': None},
        'assembled': [],
        'creates': False,
    },
    'authorlist': {
        'service': 'AuthorRepository',
        'method': 'read_all',
        'fields': [
            ('name', ('name', 'DIRECT', False)),
            ('birth_year', ('birth_year', 'DIRECT', False)),
            ('biography', ('biography', 'DIRECT', False)),
        ],
        'argv': {'name': 'name', 'birth_year': 'birth_year', 'biography': 'biography'},
        'targets': {'name': None, 'birth_year': None, 'biography': None},
        'assembled': [],
        'creates': False,
    },
    'authorupdate': {
        'service': 'AuthorRepository',
        'method': 'update',
        'fields': [
            ('id', ('id', 'LOOKUP_ID', True)),
            ('name', ('name', 'DIRECT', False)),
            ('birth_year', ('birth_year', 'DIRECT', False)),
            ('biography', ('biography', 'DIRECT', False)),
        ],
        'argv': {'id': 'id', 'name': 'name', 'birth_year': 'birth_year', 'biography': 'biography'},
        'targets': {'id': None, 'name': None, 'birth_year': None, 'biography': None},
        'assembled': [],
        'creates': False,
    },
    'bookadd': {
        'service': 'BookRepository',
        'method': 'create',
        'fields': [
            ('author_id', ('author_id', 'LOOKUP_ID', True)),
            ('title', ('title', 'DIRECT', True)),
            ('isbn', ('isbn', 'DIRECT', True)),
            ('published_year', ('published_year', 'DIRECT', True)),
            ('available_copies', ('available_copies', 'DIRECT', False)),
        ],
        'argv': {'author_id': 'author_id', 'title': 'title', 'isbn': 'isbn', 'published_year': 'published_year', 'available_copies': 'copies'},
        'targets': {'author_id': None, 'title': None, 'isbn': None, 'published_year': None, 'available_copies': None},
        'assembled': [],
        'creates': True,
    },
    'bookdelete': {
        'service': 'BookRepository',
        'method': 'delete',
        'fields': [
            ('id', ('id', 'LOOKUP_ID', True)),
            ('title', ('title', 'DIRECT', False)),
            ('isbn', ('isbn', 'DIRECT', False)),
            ('published_year', ('published_year', 'DIRECT', False)),
            ('available_copies', ('available_copies', 'DIRECT', False)),
            ('author_id', ('author_id', 'LOOKUP_ID', False)),
        ],
        'argv': {'id': 'id', 'title': 'title', 'isbn': 'isbn', 'published_year': 'published_year', 'available_copies': 'available_copies', 'author_id': 'author_id'},
        'targets': {'id': None, 'title': None, 'isbn': None, 'published_year': None, 'available_copies': None, 'author_id': None},
        'assembled': [],
        'creates': False,
    },
    'booklist': {
        'service': 'BookRepository',
        'method': 'read_all',
        'fields': [
            ('author_id', ('author_id', 'LOOKUP_ID', False)),
            ('available_only', ('available_copies', 'BOOL_TO_ONE', False)),
        ],
        'argv': {'author_id': 'author', 'available_only': 'available_only'},
        'targets': {'author_id': None, 'available_copies': None},
        'assembled': [],
        'creates': False,
    },
    'booksearch': {
        'service': 'LibraryService',
        'method': 'search_books',
        'fields': [
            ('query', ('query', 'DIRECT', True)),
        ],
        'argv': {'query': 'query'},
        'targets': {'query': None},
        'assembled': [],
        'creates': False,
    },
    'bookupdate': {
        'service': 'BookRepository',
        'method': 'update',
        'fields': [
            ('id', ('id', 'LOOKUP_ID', True)),
            ('title', ('title', 'DIRECT', False)),
            ('isbn', ('isbn', 'DIRECT', False)),
            ('published_year', ('published_year', 'DIRECT', False)),
            ('available_copies', ('available_copies', 'DIRECT', False)),
            ('author_id', ('author_id', 'LOOKUP_ID', False)),
        ],
        'argv': {'id': 'id', 'title': 'title', 'isbn': 'isbn', 'published_year': 'published_year', 'available_copies': 'available_copies', 'author_id': 'author_id'},
        'targets': {'id': None, 'title': None, 'isbn': None, 'published_year': None, 'available_copies': None, 'author_id': None},
        'assembled': [],
        'creates': False,
    },
    'borrow': {
        'service': 'LibraryService',
        'method': 'borrow_book',
        'fields': [
            ('member_id', ('member_id', 'LOOKUP_ID', True)),
            ('book_id', ('book_id', 'LOOKUP_ID', True)),
        ],
        'argv': {'member_id': 'member_id', 'book_id': 'book_id'},
        'targets': {'member_id': None, 'book_id': None},
        'assembled': [],
        'creates': False,
    },
    'loanadd': {
        'service': 'LoanRepository',
        'method': 'create',
        'fields': [
            ('book_id', ('book_id', 'LOOKUP_ID', False)),
            ('member_id', ('member_id', 'LOOKUP_ID', False)),
            ('loan_date', ('loan_date', 'ISO_DATE', False)),
            ('due_date', ('due_date', 'ISO_DATE', False)),
            ('return_date', ('return_date', 'ISO_DATE', False)),
            ('status', ('status', 'DIRECT', False)),
        ],
        'argv': {'book_id': 'book_id', 'member_id': 'member_id', 'loan_date': 'loan_date', 'due_date': 'due_date', 'return_date': 'return_date', 'status': 'status'},
        'targets': {'book_id': None, 'member_id': None, 'loan_date': None, 'due_date': None, 'return_date': None, 'status': None},
        'assembled': [],
        'creates': True,
    },
    'loandelete': {
        'service': 'LoanRepository',
        'method': 'delete',
        'fields': [
            ('id', ('id', 'LOOKUP_ID', True)),
            ('book_id', ('book_id', 'LOOKUP_ID', False)),
            ('member_id', ('member_id', 'LOOKUP_ID', False)),
            ('loan_date', ('loan_date', 'ISO_DATE', False)),
            ('due_date', ('due_date', 'ISO_DATE', False)),
            ('return_date', ('return_date', 'ISO_DATE', False)),
            ('status', ('status', 'DIRECT', False)),
        ],
        'argv': {'id': 'id', 'book_id': 'book_id', 'member_id': 'member_id', 'loan_date': 'loan_date', 'due_date': 'due_date', 'return_date': 'return_date', 'status': 'status'},
        'targets': {'id': None, 'book_id': None, 'member_id': None, 'loan_date': None, 'due_date': None, 'return_date': None, 'status': None},
        'assembled': [],
        'creates': False,
    },
    'loanlist': {
        'service': 'LoanRepository',
        'method': 'read_all',
        'fields': [
            ('book_id', ('book_id', 'LOOKUP_ID', False)),
            ('member_id', ('member_id', 'LOOKUP_ID', False)),
            ('loan_date', ('loan_date', 'ISO_DATE', False)),
            ('due_date', ('due_date', 'ISO_DATE', False)),
            ('return_date', ('return_date', 'ISO_DATE', False)),
            ('status', ('status', 'DIRECT', False)),
        ],
        'argv': {'book_id': 'book_id', 'member_id': 'member_id', 'loan_date': 'loan_date', 'due_date': 'due_date', 'return_date': 'return_date', 'status': 'status'},
        'targets': {'book_id': None, 'member_id': None, 'loan_date': None, 'due_date': None, 'return_date': None, 'status': None},
        'assembled': [],
        'creates': False,
    },
    'loanupdate': {
        'service': 'LoanRepository',
        'method': 'update',
        'fields': [
            ('id', ('id', 'LOOKUP_ID', True)),
            ('book_id', ('book_id', 'LOOKUP_ID', False)),
            ('member_id', ('member_id', 'LOOKUP_ID', False)),
            ('loan_date', ('loan_date', 'ISO_DATE', False)),
            ('due_date', ('due_date', 'ISO_DATE', False)),
            ('return_date', ('return_date', 'ISO_DATE', False)),
            ('status', ('status', 'DIRECT', False)),
        ],
        'argv': {'id': 'id', 'book_id': 'book_id', 'member_id': 'member_id', 'loan_date': 'loan_date', 'due_date': 'due_date', 'return_date': 'return_date', 'status': 'status'},
        'targets': {'id': None, 'book_id': None, 'member_id': None, 'loan_date': None, 'due_date': None, 'return_date': None, 'status': None},
        'assembled': [],
        'creates': False,
    },
    'memberadd': {
        'service': 'MemberRepository',
        'method': 'create',
        'fields': [
            ('name', ('name', 'DIRECT', True)),
            ('email', ('email', 'DIRECT', True)),
            ('membership_date', ('membership_date', 'ISO_DATE', True)),
            ('is_active', ('is_active', 'DIRECT', True)),
        ],
        'argv': {'name': 'name', 'email': 'email', 'membership_date': 'membership_date', 'is_active': 'is_active'},
        'targets': {'name': None, 'email': None, 'membership_date': None, 'is_active': None},
        'assembled': [],
        'creates': True,
    },
    'memberdelete': {
        'service': 'MemberRepository',
        'method': 'delete',
        'fields': [
            ('id', ('id', 'LOOKUP_ID', True)),
            ('name', ('name', 'DIRECT', False)),
            ('email', ('email', 'DIRECT', False)),
            ('membership_date', ('membership_date', 'ISO_DATE', False)),
            ('is_active', ('is_active', 'DIRECT', False)),
        ],
        'argv': {'id': 'id', 'name': 'name', 'email': 'email', 'membership_date': 'membership_date', 'is_active': 'is_active'},
        'targets': {'id': None, 'name': None, 'email': None, 'membership_date': None, 'is_active': None},
        'assembled': [],
        'creates': False,
    },
    'memberhistory': {
        'service': 'LoanRepository',
        'method': 'get_member_loan_history',
        'fields': [
            ('member_id', ('member_id', 'LOOKUP_ID', True)),
        ],
        'argv': {'member_id': 'member_id'},
        'targets': {'member_id': None},
        'assembled': [],
        'creates': False,
    },
    'memberlist': {
        'service': 'MemberRepository',
        'method': 'read_all',
        'fields': [
            ('active_only', ('is_active', 'DIRECT', False)),
        ],
        'argv': {'active_only': 'active_only'},
        'targets': {'is_active': None},
        'assembled': [],
        'creates': False,
    },
    'memberupdate': {
        'service': 'MemberRepository',
        'method': 'update',
        'fields': [
            ('id', ('id', 'LOOKUP_ID', True)),
            ('name', ('name', 'DIRECT', False)),
            ('email', ('email', 'DIRECT', False)),
            ('membership_date', ('membership_date', 'ISO_DATE', False)),
            ('is_active', ('is_active', 'DIRECT', False)),
        ],
        'argv': {'id': 'id', 'name': 'name', 'email': 'email', 'membership_date': 'membership_date', 'is_active': 'is_active'},
        'targets': {'id': None, 'name': None, 'email': None, 'membership_date': None, 'is_active': None},
        'assembled': [],
        'creates': False,
    },
    'overdue': {
        'service': 'LibraryService',
        'method': 'get_overdue_loans',
        'fields': [
        ],
        'argv': {},
        'targets': {},
        'assembled': [],
        'creates': False,
    },
    'return': {
        'service': 'LibraryService',
        'method': 'return_book',
        'fields': [
            ('loan_id', ('loan_id', 'LOOKUP_ID', True)),
        ],
        'argv': {'loan_id': 'loan_id'},
        'targets': {'loan_id': None},
        'assembled': [],
        'creates': False,
    },
}


BINDINGS = {  # (command, subcommand) -> [(action, score, need)]
    ('Loan', 'add'): [('loanadd', 9, ())],
    ('Loan', 'delete'): [('loandelete', 11, ())],
    ('Loan', 'list'): [('loanlist', 9, ())],
    ('Loan', 'update'): [('loanupdate', 11, ())],
    ('author', 'add'): [('authoradd', 9, ())],
    ('author', 'delete'): [('authordelete', 11, ())],
    ('author', 'list'): [('authorlist', 9, ())],
    ('author', 'update'): [('authorupdate', 11, ())],
    ('book', 'add'): [('bookadd', 9, ())],
    ('book', 'delete'): [('bookdelete', 11, ())],
    ('book', 'list'): [('booklist', 9, ())],
    ('book', 'search'): [('booksearch', 3, ())],
    ('book', 'update'): [('bookupdate', 11, ())],
    ('borrow', None): [('borrow', 7, ())],
    ('member', 'add'): [('memberadd', 9, ())],
    ('member', 'delete'): [('memberdelete', 11, ())],
    ('member', 'history'): [('memberhistory', 7, ())],
    ('member', 'list'): [('memberlist', 9, ())],
    ('member', 'update'): [('memberupdate', 11, ())],
    ('overdue', None): [('overdue', 7, ())],
    ('return', None): [('return', 7, ())],
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


DEFAULT_DB = 'prompt_library_system.db'



COMMANDS = {'book': {'subcommands': {'add': {'binding': ('book', 'add'),
                                  'plans': [{'flags': ['--author-id', '-a'],
                                             'dest': 'author_id',
                                             'otype': 'int',
                                             'required': True,
                                             'default': None},
                                            {'flags': ['--title'],
                                             'dest': 'title',
                                             'otype': 'str',
                                             'required': True,
                                             'default': None},
                                            {'flags': ['--isbn'],
                                             'dest': 'isbn',
                                             'otype': 'str',
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
                                             'required': False,
                                             'default': '1'}]},
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
                                                'default': None}]},
                          'update': {'binding': ('book', 'update'),
                                     'plans': [{'flags': ['--id'],
                                                'dest': 'id',
                                                'otype': 'int',
                                                'required': True,
                                                'default': None},
                                               {'flags': ['--title'],
                                                'dest': 'title',
                                                'otype': 'str',
                                                'required': False,
                                                'default': None},
                                               {'flags': ['--isbn'],
                                                'dest': 'isbn',
                                                'otype': 'str',
                                                'required': False,
                                                'default': None},
                                               {'flags': ['--published-year'],
                                                'dest': 'published_year',
                                                'otype': 'int',
                                                'required': False,
                                                'default': None},
                                               {'flags': ['--available-copies'],
                                                'dest': 'available_copies',
                                                'otype': 'int',
                                                'required': False,
                                                'default': None},
                                               {'flags': ['--author-id'],
                                                'dest': 'author_id',
                                                'otype': 'int',
                                                'required': False,
                                                'default': None}]},
                          'delete': {'binding': ('book', 'delete'),
                                     'plans': [{'flags': ['--id'],
                                                'dest': 'id',
                                                'otype': 'int',
                                                'required': True,
                                                'default': None},
                                               {'flags': ['--title'],
                                                'dest': 'title',
                                                'otype': 'str',
                                                'required': False,
                                                'default': None},
                                               {'flags': ['--isbn'],
                                                'dest': 'isbn',
                                                'otype': 'str',
                                                'required': False,
                                                'default': None},
                                               {'flags': ['--published-year'],
                                                'dest': 'published_year',
                                                'otype': 'int',
                                                'required': False,
                                                'default': None},
                                               {'flags': ['--available-copies'],
                                                'dest': 'available_copies',
                                                'otype': 'int',
                                                'required': False,
                                                'default': None},
                                               {'flags': ['--author-id'],
                                                'dest': 'author_id',
                                                'otype': 'int',
                                                'required': False,
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
                                               'default': None},
                                              {'flags': ['--membership-date'],
                                               'dest': 'membership_date',
                                               'otype': 'str',
                                               'required': False,
                                               'default': None},
                                              {'flags': ['--is-active'],
                                               'dest': 'is_active',
                                               'otype': 'bool',
                                               'required': False,
                                               'default': None}]},
                            'list': {'binding': ('member', 'list'),
                                     'plans': [{'flags': ['--active-only', '-a'],
                                                'dest': 'active_only',
                                                'otype': 'bool',
                                                'required': False,
                                                'default': None}]},
                            'history': {'binding': ('member', 'history'),
                                        'plans': [{'flags': ['--member-id', '-m'],
                                                   'dest': 'member_id',
                                                   'otype': 'int',
                                                   'required': True,
                                                   'default': None}]},
                            'update': {'binding': ('member', 'update'),
                                       'plans': [{'flags': ['--id'],
                                                  'dest': 'id',
                                                  'otype': 'int',
                                                  'required': True,
                                                  'default': None},
                                                 {'flags': ['--name'],
                                                  'dest': 'name',
                                                  'otype': 'str',
                                                  'required': False,
                                                  'default': None},
                                                 {'flags': ['--email'],
                                                  'dest': 'email',
                                                  'otype': 'str',
                                                  'required': False,
                                                  'default': None},
                                                 {'flags': ['--membership-date'],
                                                  'dest': 'membership_date',
                                                  'otype': 'str',
                                                  'required': False,
                                                  'default': None},
                                                 {'flags': ['--is-active'],
                                                  'dest': 'is_active',
                                                  'otype': 'bool',
                                                  'required': False,
                                                  'default': None}]},
                            'delete': {'binding': ('member', 'delete'),
                                       'plans': [{'flags': ['--id'],
                                                  'dest': 'id',
                                                  'otype': 'int',
                                                  'required': True,
                                                  'default': None},
                                                 {'flags': ['--name'],
                                                  'dest': 'name',
                                                  'otype': 'str',
                                                  'required': False,
                                                  'default': None},
                                                 {'flags': ['--email'],
                                                  'dest': 'email',
                                                  'otype': 'str',
                                                  'required': False,
                                                  'default': None},
                                                 {'flags': ['--membership-date'],
                                                  'dest': 'membership_date',
                                                  'otype': 'str',
                                                  'required': False,
                                                  'default': None},
                                                 {'flags': ['--is-active'],
                                                  'dest': 'is_active',
                                                  'otype': 'bool',
                                                  'required': False,
                                                  'default': None}]}}},
 'borrow': {'binding': ('borrow', None),
            'plans': [{'flags': ['--member-id', '-m'],
                       'dest': 'member_id',
                       'otype': 'int',
                       'required': True,
                       'default': None},
                      {'flags': ['--book-id', '-b'],
                       'dest': 'book_id',
                       'otype': 'int',
                       'required': True,
                       'default': None}]},
 'return': {'binding': ('return', None),
            'plans': [{'flags': ['--loan-id', '-l'],
                       'dest': 'loan_id',
                       'otype': 'int',
                       'required': True,
                       'default': None}]},
 'overdue': {'binding': ('overdue', None), 'plans': []},
 'author': {'subcommands': {'add': {'binding': ('author', 'add'),
                                    'plans': [{'flags': ['--name', '-n'],
                                               'dest': 'name',
                                               'otype': 'str',
                                               'required': True,
                                               'default': None},
                                              {'flags': ['--birth-year', '-b'],
                                               'dest': 'birth_year',
                                               'otype': 'int',
                                               'required': True,
                                               'default': None},
                                              {'flags': ['--biography', '-i'],
                                               'dest': 'biography',
                                               'otype': 'str',
                                               'required': False,
                                               'default': None}]},
                            'list': {'binding': ('author', 'list'),
                                     'plans': [{'flags': ['--name'],
                                                'dest': 'name',
                                                'otype': 'str',
                                                'required': False,
                                                'default': None},
                                               {'flags': ['--birth-year'],
                                                'dest': 'birth_year',
                                                'otype': 'int',
                                                'required': False,
                                                'default': None},
                                               {'flags': ['--biography'],
                                                'dest': 'biography',
                                                'otype': 'str',
                                                'required': False,
                                                'default': None}]},
                            'update': {'binding': ('author', 'update'),
                                       'plans': [{'flags': ['--id'],
                                                  'dest': 'id',
                                                  'otype': 'int',
                                                  'required': True,
                                                  'default': None},
                                                 {'flags': ['--name'],
                                                  'dest': 'name',
                                                  'otype': 'str',
                                                  'required': False,
                                                  'default': None},
                                                 {'flags': ['--birth-year'],
                                                  'dest': 'birth_year',
                                                  'otype': 'int',
                                                  'required': False,
                                                  'default': None},
                                                 {'flags': ['--biography'],
                                                  'dest': 'biography',
                                                  'otype': 'str',
                                                  'required': False,
                                                  'default': None}]},
                            'delete': {'binding': ('author', 'delete'),
                                       'plans': [{'flags': ['--id'],
                                                  'dest': 'id',
                                                  'otype': 'int',
                                                  'required': True,
                                                  'default': None},
                                                 {'flags': ['--name'],
                                                  'dest': 'name',
                                                  'otype': 'str',
                                                  'required': False,
                                                  'default': None},
                                                 {'flags': ['--birth-year'],
                                                  'dest': 'birth_year',
                                                  'otype': 'int',
                                                  'required': False,
                                                  'default': None},
                                                 {'flags': ['--biography'],
                                                  'dest': 'biography',
                                                  'otype': 'str',
                                                  'required': False,
                                                  'default': None}]}}},
 'Loan': {'subcommands': {'add': {'binding': ('Loan', 'add'),
                                  'plans': [{'flags': ['--book-id'],
                                             'dest': 'book_id',
                                             'otype': 'int',
                                             'required': False,
                                             'default': None},
                                            {'flags': ['--member-id'],
                                             'dest': 'member_id',
                                             'otype': 'int',
                                             'required': False,
                                             'default': None},
                                            {'flags': ['--loan-date'],
                                             'dest': 'loan_date',
                                             'otype': 'str',
                                             'required': False,
                                             'default': None},
                                            {'flags': ['--due-date'],
                                             'dest': 'due_date',
                                             'otype': 'str',
                                             'required': False,
                                             'default': None},
                                            {'flags': ['--return-date'],
                                             'dest': 'return_date',
                                             'otype': 'str',
                                             'required': False,
                                             'default': None},
                                            {'flags': ['--status'],
                                             'dest': 'status',
                                             'otype': 'str',
                                             'required': False,
                                             'default': None}]},
                          'list': {'binding': ('Loan', 'list'),
                                   'plans': [{'flags': ['--book-id'],
                                              'dest': 'book_id',
                                              'otype': 'int',
                                              'required': False,
                                              'default': None},
                                             {'flags': ['--member-id'],
                                              'dest': 'member_id',
                                              'otype': 'int',
                                              'required': False,
                                              'default': None},
                                             {'flags': ['--loan-date'],
                                              'dest': 'loan_date',
                                              'otype': 'str',
                                              'required': False,
                                              'default': None},
                                             {'flags': ['--due-date'],
                                              'dest': 'due_date',
                                              'otype': 'str',
                                              'required': False,
                                              'default': None},
                                             {'flags': ['--return-date'],
                                              'dest': 'return_date',
                                              'otype': 'str',
                                              'required': False,
                                              'default': None},
                                             {'flags': ['--status'],
                                              'dest': 'status',
                                              'otype': 'str',
                                              'required': False,
                                              'default': None}]},
                          'update': {'binding': ('Loan', 'update'),
                                     'plans': [{'flags': ['--id'],
                                                'dest': 'id',
                                                'otype': 'int',
                                                'required': True,
                                                'default': None},
                                               {'flags': ['--book-id'],
                                                'dest': 'book_id',
                                                'otype': 'int',
                                                'required': False,
                                                'default': None},
                                               {'flags': ['--member-id'],
                                                'dest': 'member_id',
                                                'otype': 'int',
                                                'required': False,
                                                'default': None},
                                               {'flags': ['--loan-date'],
                                                'dest': 'loan_date',
                                                'otype': 'str',
                                                'required': False,
                                                'default': None},
                                               {'flags': ['--due-date'],
                                                'dest': 'due_date',
                                                'otype': 'str',
                                                'required': False,
                                                'default': None},
                                               {'flags': ['--return-date'],
                                                'dest': 'return_date',
                                                'otype': 'str',
                                                'required': False,
                                                'default': None},
                                               {'flags': ['--status'],
                                                'dest': 'status',
                                                'otype': 'str',
                                                'required': False,
                                                'default': None}]},
                          'delete': {'binding': ('Loan', 'delete'),
                                     'plans': [{'flags': ['--id'],
                                                'dest': 'id',
                                                'otype': 'int',
                                                'required': True,
                                                'default': None},
                                               {'flags': ['--book-id'],
                                                'dest': 'book_id',
                                                'otype': 'int',
                                                'required': False,
                                                'default': None},
                                               {'flags': ['--member-id'],
                                                'dest': 'member_id',
                                                'otype': 'int',
                                                'required': False,
                                                'default': None},
                                               {'flags': ['--loan-date'],
                                                'dest': 'loan_date',
                                                'otype': 'str',
                                                'required': False,
                                                'default': None},
                                               {'flags': ['--due-date'],
                                                'dest': 'due_date',
                                                'otype': 'str',
                                                'required': False,
                                                'default': None},
                                               {'flags': ['--return-date'],
                                                'dest': 'return_date',
                                                'otype': 'str',
                                                'required': False,
                                                'default': None},
                                               {'flags': ['--status'],
                                                'dest': 'status',
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


@click.group('prompt_library_system')
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
        cli.main(args=argv, prog_name='prompt_library_system',
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

