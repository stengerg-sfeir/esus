"""Identifier normalization and name resolution for the consistency checks.

Each extraction step names entities and services independently, so the same
concept comes back spelled several ways ("wine_id", "WineId", "WineService"
vs "wine_service"). Every cross-reference check resolves a name through this
module rather than comparing raw strings.
"""

import difflib
import re
from dataclasses import dataclass, field

_NON_ALPHANUMERIC = re.compile(r"[^a-z0-9]+")
_ROLE_SUFFIXES = ("repository", "service", "manager", "handler", "repo")

MATCH_EXACT = "exact"
MATCH_VARIANT = "variant"
MATCH_NONE = "none"

# Class-name suffixes that must never appear where a bare entity name is expected.
CLASS_SUFFIXES = ("Repository", "Service")

SUGGESTION_LIMIT = 3
SUGGESTION_CUTOFF = 0.6


def normalize(identifier):
    """Return the comparable form of an identifier ('Wine_ID' -> 'wineid')."""
    return _NON_ALPHANUMERIC.sub("", str(identifier).lower())


def strip_role_suffix(identifier):
    """normalize() with a trailing role word removed ('WineService' -> 'wine')."""
    base = normalize(identifier)
    for suffix in _ROLE_SUFFIXES:
        if base.endswith(suffix) and len(base) > len(suffix):
            return base[: -len(suffix)]
    return base


def match_known(candidate, known_names, strip_roles=False):
    """Resolve `candidate` against `known_names`.

    Returns (MATCH_EXACT | MATCH_VARIANT | MATCH_NONE, resolved_name_or_None).
    MATCH_VARIANT means the two names agree once punctuation and casing (and,
    when `strip_roles` is set, a trailing role word) are removed.
    """
    if not candidate:
        return MATCH_NONE, None
    if candidate in known_names:
        return MATCH_EXACT, candidate

    target = normalize(candidate)
    for name in known_names:
        if normalize(name) == target:
            return MATCH_VARIANT, name

    if strip_roles:
        target = strip_role_suffix(candidate)
        for name in known_names:
            if strip_role_suffix(name) == target:
                return MATCH_VARIANT, name

    return MATCH_NONE, None


def suggest(candidate, known_names, limit=SUGGESTION_LIMIT):
    """Return up to `limit` known names close to `candidate`, for messages."""
    normalized = {}
    for name in known_names:
        normalized.setdefault(normalize(name), name)
    close = difflib.get_close_matches(
        normalize(candidate), list(normalized), n=limit, cutoff=SUGGESTION_CUTOFF
    )
    return [normalized[match] for match in close]


@dataclass
class EntityIndex:
    """The extracted data models, addressable by name with variant resolution."""

    models: list = field(default_factory=list)

    @classmethod
    def from_models(cls, models):
        if not isinstance(models, list):
            models = []
        return cls([model for model in models if isinstance(model, dict)])

    @property
    def names(self):
        return [model.get("name") for model in self.models if model.get("name")]

    def _model(self, entity_name):
        for model in self.models:
            if model.get("name") == entity_name:
                return model
        return {}

    def _fields(self, entity_name):
        fields = self._model(entity_name).get("fields", [])
        if not isinstance(fields, list):
            return []
        return [item for item in fields if isinstance(item, dict)]

    def resolve(self, entity_name):
        """Return (match_tier, declared_model_name_or_None)."""
        return match_known(entity_name, self.names)

    def fields_of(self, entity_name):
        return [item.get("name") for item in self._fields(entity_name) if item.get("name")]

    def primary_keys(self, entity_name):
        return [item.get("name") for item in self._fields(entity_name)
                if item.get("primary_key") and item.get("name")]

    def suggest(self, entity_name, limit=SUGGESTION_LIMIT):
        return suggest(entity_name, self.names, limit)

    def suggest_field(self, entity_name, field_name, limit=SUGGESTION_LIMIT):
        return suggest(field_name, self.fields_of(entity_name), limit)
