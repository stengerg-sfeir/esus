"""The behavioural contract every store backend must satisfy.

Generated bodies are written against this contract, not against SQLite.
`codegen_store_template.py` is the default implementation; a replacement
store may live anywhere, but it must provide the same reads, writes and
value semantics. The generator renders the prompt facts below instead of
naming the implementation, so swapping the template does not leave stale
SQLite advice in the ask.
"""

from dataclasses import dataclass
from typing import Tuple


@dataclass(frozen=True)
class StoreContract:
    """What a body may assume about the store it is handed."""

    name: str
    template: str
    read_shape: str
    criteria_operators: Tuple[str, ...]
    text_search: str
    date_read: str
    date_write: str
    mutation: str


SQLITE_STORE = StoreContract(
    name="sqlite",
    template="codegen_store_template.py",
    read_shape="plain records (dicts)",
    criteria_operators=("eq", "ge", "le", "gt", "lt"),
    text_search="case-insensitive substring",
    date_read=("restores declared `date`/`datetime` fields to "
               "`datetime.date`/`datetime.datetime` objects on read"),
    date_write=("normalizes `datetime.date`/`datetime.datetime` values to "
                "ISO text on write"),
    mutation=("changing a record or dataclass does not save it; call "
              "`update`"),
)

DEFAULT_STORE = SQLITE_STORE
