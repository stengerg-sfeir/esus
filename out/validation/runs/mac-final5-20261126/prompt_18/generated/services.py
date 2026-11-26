"""Services. A method with the same name as a repository method delegates
to it; anything else raises NotImplementedError with its work order.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple, Union

import calendar
import csv
import datetime
import json

import models
import errors
from store import match_criterion


def _holds(actual, operator, expected):
    """Twin of `store._holds`: the operators filter composition reuses."""
    if operator == "eq":
        return actual == expected
    if operator == "ge":
        return actual is not None and actual >= expected
    if operator == "le":
        return actual is not None and actual <= expected
    if operator == "gt":
        return actual is not None and actual > expected
    if operator == "lt":
        return actual is not None and actual < expected
    raise ValueError(f"unknown operator {operator!r}")


def _as_date(value):
    """Accept an ISO string or a date object; return a date or None."""
    if value is None or isinstance(value, datetime.date):
        return value
    return datetime.date.fromisoformat(str(value))



class ContactService:

    def __init__(self, repos):
        self._repos = repos


    def import_contacts_from_csv(self, file_path: str = None) -> int:
        """Import contacts from csv. [llm-written by server — review]"""
        with open(file_path, mode='r', encoding='utf-8') as file:
            reader = csv.DictReader(file)
            invalid_rows = 0
            for row in reader:
                try:
                    first_name = row.get('first_name')
                    last_name = row.get('last_name')
                    email = row.get('email')
                    phone = row.get('phone')
                    address = row.get('address')
                    if not first_name or not last_name:
                        invalid_rows += 1
                        continue
                    created_at_str = row.get('created_at')
                    updated_at_str = row.get('updated_at')
                    created_at = _as_date(created_at_str)
                    updated_at = _as_date(updated_at_str)
                    contact_data = {'first_name': first_name, 'last_name': last_name, 'email': email, 'phone': phone, 'address': address, 'created_at': created_at, 'updated_at': updated_at}
                    contact_id = self._repos['ContactRepository'].create(first_name=first_name, last_name=last_name, email=email, phone=phone, address=address, created_at=created_at, updated_at=updated_at)
                except (ValueError, KeyError) as e:
                    invalid_rows += 1
            return invalid_rows
