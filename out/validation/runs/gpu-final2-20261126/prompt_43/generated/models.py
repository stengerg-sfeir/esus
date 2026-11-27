"""Data models. The store assigns integer primary keys on insert,
and updates merge only non-None values. Explicit application defaults
from the requirements are preserved on the dataclasses."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import datetime
from typing import Any, Dict, List, Literal, Optional



@dataclass
class Priority:
    id: int = None
    name: str = None


@dataclass
class Project:
    id: int = None
    name: str = None
    description: Optional[str] = None
    created_at: datetime.datetime = None
    updated_at: datetime.datetime = None


@dataclass
class Status:
    id: int = None
    name: str = None


@dataclass
class Task:
    id: int = None
    title: str = None
    description: Optional[str] = None
    project_id: int = None
    priority: str = None
    status: str = None
    due_date: Optional[datetime.date] = None
    created_at: datetime.datetime = None
    updated_at: datetime.datetime = None
