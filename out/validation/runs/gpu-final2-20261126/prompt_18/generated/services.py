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
        with open(file_path, 'r', encoding='utf-8') as handle:
            reader = csv.reader(handle)
            header = next(reader)
            if header != ['id', 'first_name', 'last_name', 'email', 'phone', 'address', 'created_at', 'updated_at']:
                raise errors.AppError("Invalid CSV header: expected ['id', 'first_name', 'last_name', 'email', 'phone', 'address', 'created_at', 'updated_at']")
            valid_count = 0
            for row in reader:
                if len(row) != 8:
                    raise errors.AppError(f'Invalid row length: expected 8 columns, got {len(row)}')
                try:
                    first_name = row[1] if row[1] else None
                    last_name = row[2] if row[2] else None
                    email = row[3] if row[3] else None
                    phone = row[4] if row[4] else None
                    address = row[5] if row[5] else None
                    created_at = _as_date(row[6]) if row[6] else None
                    updated_at = _as_date(row[7]) if row[7] else None
                    contact_id = self._repos['ContactRepository'].create(first_name=first_name, last_name=last_name, email=email, phone=phone, address=address, created_at=created_at, updated_at=updated_at)
                    valid_count += 1
                except Exception as e:
                    continue
        return valid_count

    def export_contacts_to_csv(self, file_path: str = None) -> None:
        """Export contacts to csv. [mechanical CSV export]"""
        records = self._repos['ContactRepository'].read_all()
        start = ''
        end = ''
        filtered = []
        for record in records:
            date = str(getattr(record, 'created_at', None) or '')[:10]
            if start and date < start:
                continue
            if end and date > end:
                continue
            filtered.append(record)
        with open(file_path, 'w', newline='', encoding='utf-8') as handle:
            writer = csv.writer(handle)
            writer.writerow(['id', 'first_name', 'last_name', 'email', 'phone', 'address', 'created_at', 'updated_at'])
            for record in filtered:
                writer.writerow([record.id, '' if record.first_name is None else record.first_name, '' if record.last_name is None else record.last_name, '' if record.email is None else record.email, '' if record.phone is None else record.phone, '' if record.address is None else record.address, '' if record.created_at is None else record.created_at, '' if record.updated_at is None else record.updated_at])
