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


    def export_contacts_to_csv(self) -> None:
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
        with open('contact.csv', 'w', newline='', encoding='utf-8') as handle:
            writer = csv.writer(handle)
            writer.writerow(['id', 'first_name', 'last_name', 'email', 'phone', 'address', 'created_at', 'updated_at'])
            for record in filtered:
                writer.writerow([record.id, '' if record.first_name is None else record.first_name, '' if record.last_name is None else record.last_name, '' if record.email is None else record.email, '' if record.phone is None else record.phone, '' if record.address is None else record.address, '' if record.created_at is None else record.created_at, '' if record.updated_at is None else record.updated_at])

    def import_contacts_from_csv(self, first_name: str = None, last_name: str = None, email: str = None, created_at: datetime.datetime = None, updated_at: datetime.datetime = None, file_path: str = None) -> int:
        """Import contacts from csv. [llm-written by server — review]"""
        with open(file_path, 'r', encoding='utf-8') as handle:
            reader = csv.reader(handle)
            header = next(reader)
            if header != ['id', 'first_name', 'last_name', 'email', 'phone', 'address', 'created_at', 'updated_at']:
                raise errors.AppError('Invalid CSV format: missing or incorrect header')
            invalid_rows = 0
            for row in reader:
                try:
                    row_id = int(row[0]) if row[0] else None
                    first_name = row[1] if row[1] else None
                    last_name = row[2] if row[2] else None
                    email = row[3] if row[3] else None
                    phone = row[4] if row[4] else None
                    address = row[5] if row[5] else None
                    created_at_str = row[6] if row[6] else None
                    updated_at_str = row[7] if row[7] else None
                    created_at = _as_date(created_at_str) if created_at_str else None
                    updated_at = _as_date(updated_at_str) if updated_at_str else None
                    if first_name is not None and first_name != '' and (first_name != self._repos['ContactRepository'].read_all(first_name=first_name, last_name=last_name, email=email, phone=phone, address=address, created_at=created_at, updated_at=updated_at)[0].first_name):
                        pass
                    if first_name is not None and first_name != '':
                        if not (first_name == first_name or first_name == first_name):
                            continue
                    if last_name is not None and last_name != '':
                        if not (last_name == last_name or last_name == last_name):
                            continue
                    if email is not None and email != '':
                        if not (email == email or email == email):
                            continue
                    if created_at is not None:
                        if not (created_at == created_at or created_at == created_at):
                            continue
                    if updated_at is not None:
                        if not (updated_at == updated_at or updated_at == updated_at):
                            continue
                    existing_contact = self._repos['ContactRepository'].read_one(id=row_id)
                    if existing_contact:
                        self._repos['ContactRepository'].update(id=row_id, first_name=first_name, last_name=last_name, email=email, phone=phone, address=address, created_at=created_at, updated_at=updated_at)
                    else:
                        new_contact_id = self._repos['ContactRepository'].create(first_name=first_name, last_name=last_name, email=email, phone=phone, address=address, created_at=created_at, updated_at=updated_at)
                        created_contact = self._repos['ContactRepository'].read_one(id=new_contact_id.id)
                        if created_contact:
                            self._repos['ContactRepository'].update(id=new_contact_id.id, first_name=first_name, last_name=last_name, email=email, phone=phone, address=address, created_at=created_at, updated_at=updated_at)
                except (ValueError, IndexError) as e:
                    invalid_rows += 1
                    continue
            if invalid_rows > 0:
                raise errors.AppError(f'Invalid rows found during import: {invalid_rows}')
            return invalid_rows
