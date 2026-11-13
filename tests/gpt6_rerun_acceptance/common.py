"""Reuse the direct-output acceptance harness for the 2026-11-13 rerun."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_source = Path(__file__).resolve().parent.parent / "chatgpt_acceptance" / "common.py"
_spec = importlib.util.spec_from_file_location("_gpt6_acceptance_common", _source)
if _spec is None or _spec.loader is None:
    raise ImportError(f"cannot load {_source}")
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)

for _name in dir(_module):
    if not _name.startswith("_"):
        globals()[_name] = getattr(_module, _name)
