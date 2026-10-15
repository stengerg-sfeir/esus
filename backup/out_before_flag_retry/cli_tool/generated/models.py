"""Data models. Every field defaults to None: the store assigns integer
primary keys on insert, and updates merge only non-None values."""

from dataclasses import dataclass
from decimal import Decimal
import datetime
from typing import Any, Dict, List, Optional

