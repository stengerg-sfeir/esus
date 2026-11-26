from __future__ import annotations

SCHEMA = {'Order': {'primary_key': 'id',
           'fields': [{'name': 'id',
                       'type': 'int',
                       'primary_key': True,
                       'nullable': False,
                       'unique': True,
                       'foreign_key': None,
                       'default': None},
                      {'name': 'status',
                       'type': 'string',
                       'primary_key': False,
                       'nullable': False,
                       'unique': False,
                       'foreign_key': None,
                       'default': None}]}}
