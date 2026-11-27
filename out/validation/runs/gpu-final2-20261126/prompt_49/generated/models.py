"""Data models. The store assigns integer primary keys on insert,
and updates merge only non-None values. Explicit application defaults
from the requirements are preserved on the dataclasses."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import datetime
from typing import Any, Dict, List, Literal, Optional



@dataclass
class Department:
    department_id: int = None
    department_name: str = None


@dataclass
class Employee:
    employee_id: int = None
    first_name: str = None
    last_name: str = None
    email: str = None
    department_id: int = None
