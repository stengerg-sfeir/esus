"""Evidence-based service grounding.

A method may be added mechanically or by the extractor, but a *custom*
service method should have evidence in the requirements or in the
intentions distilled from them.  Standard CRUD wrappers are implementation
and are exempt; they are generated mechanically.

This module only reports.  It never mutates documents: a human/reviewer
records drops in ``grounding_decisions.json`` and the generator applies them.
"""

from __future__ import annotations

import re

from kernel import codegen

# Verbs that name an operation rather than a domain capability.  A custom
# method with one of these still needs an object token from the requirements.
GENERIC_VERBS = frozenset({
    "get", "list", "read", "create", "update", "delete", "add", "remove",
    "set", "find", "fetch", "check", "validate", "verify",
})

# Small synonym groups for matching intentions such as "confirming" or
# "cancelling" against method names.
VERB_FAMILIES = (
    {"confirm"},
    {"cancel"},
    {"ship"},
    {"search", "find"},
    {"add", "create"},
    {"edit", "update"},
    {"remove", "delete"},
    {"export"},
    {"report"},
    {"borrow"},
    {"return"},
    {"renew"},
)


def _flat(text):
    return "".join(ch for ch in str(text or "").lower() if ch.isalnum())


def _tokens(text):
    return [token for token in re.split(r"[^a-z0-9]+", str(text or "").lower())
            if token]


def _stem(token):
    token = token.lower()
    return token[:5] if len(token) > 5 else token


def _corpus(requirements, intentions, commands=()):
    parts = [requirements or "", *(intentions or ()), *commands]
    return _flat(" ".join(str(part) for part in parts))


def _method_is_standard(method):
    if method.get("mechanical"):
        return True
    name = str(method.get("name") or "").lower()
    # classify_crud treats names such as `search_wines_by_name` as read_one;
    # only the completion pass's known spellings are implementation wrappers.
    return bool(re.match(r"^(?:create|read|read_all|update|delete)_", name))


def _has_token(corpus, token):
    token = _tokens(token)
    return bool(token and _stem(token[0]) in corpus)


def _extra_method(holder, method, corpus):
    """A reason when a custom method has no evidence, else None."""
    if _method_is_standard(method):
        return None
    tokens = _tokens(method.get("name") or "")
    if not tokens:
        return "method name has no searchable tokens"
    verb = tokens[0]
    family = next((group for group in VERB_FAMILIES if verb in group), {verb})
    verb_ok = any(_has_token(corpus, candidate) for candidate in family)
    if verb in GENERIC_VERBS:
        objects = tokens[1:]
        object_ok = any(_has_token(corpus, token) for token in objects)
        if object_ok:
            return None
        return "no requirement/intention evidence for the method's object"
    if verb_ok:
        return None
    return f"no requirement/intention evidence for verb `{verb}`"


def _service_extra_methods(requirements, intentions, services, commands=()):
    corpus = _corpus(requirements, intentions, commands)
    extras = []
    for service in services:
        holder = service.get("service_name")
        if not isinstance(holder, str) or holder.endswith("Repository"):
            continue
        for method in service.get("methods") or []:
            if not isinstance(method, dict):
                continue
            reason = _extra_method(holder, method, corpus)
            if reason:
                extras.append({
                    "holder": holder,
                    "method": method.get("name"),
                    "reason": reason,
                })
    return extras


def _missing_capabilities(intentions, services):
    """Suggested missing capabilities from state/action words in intentions."""
    method_text = _flat(" ".join(
        str(method.get("name") or "")
        for service in services
        for method in service.get("methods") or []
        if isinstance(method, dict)
    ))
    checks = (
        ("confirm", ("confirm",), ("order", "status")),
        ("cancel", ("cancel",), ("order", "status")),
        ("ship", ("ship",), ("order", "status")),
        ("borrow", ("borrow",), ("loan", "book", "member")),
        ("return", ("return",), ("loan", "book", "member")),
        ("renew", ("renew",), ("loan", "book", "member")),
        ("search", ("search", "find"), ()),
        ("export", ("export",), ()),
    )
    missing = []
    for intention in intentions or ():
        flat = _flat(intention)
        for label, stems, domain_words in checks:
            if _stem(label) not in flat:
                continue
            if domain_words and not any(word in flat for word in domain_words):
                continue
            if not any(_stem(stem) in method_text for stem in stems):
                missing.append({
                    "intention": intention,
                    "expected": label,
                })
    return missing


def _ambiguous_aggregate_groups(requirements, intentions, services):
    """Grouped mappings whose empty-group policy is not stated.

    A mapping keyed by a parent entity can either include parents with no
    children as zero, or omit them.  If the requirements never say "each",
    "all", "every", "zero", "empty" or "only ... with", no rule can decide.
    Report the question; do not invent an answer.
    """
    text = " ".join([requirements or "", *(intentions or ())]).lower()
    coverage_phrases = (
        "each category", "all categories", "every category",
        "categories with products", "empty categories", "zero value",
        "non-empty", "nonempty",
    )
    if any(phrase in text for phrase in coverage_phrases):
        return []
    aggregate_words = ("value", "total", "sum", "aggregate", "spend", "count")
    ambiguous = []
    for service in services:
        holder = service.get("service_name")
        if not isinstance(holder, str) or holder.endswith("Repository"):
            continue
        for method in service.get("methods") or []:
            if not isinstance(method, dict):
                continue
            returned = str(method.get("return_type") or "").lower()
            if "dict" not in returned and "mapping" not in returned:
                continue
            label = f"{method.get('name')} {method.get('description')}".lower()
            text = _flat(label)
            if not any(_stem(word) in text for word in aggregate_words):
                continue
            if not re.search(
                    r"(?:^|[^a-z0-9])by[_\s]+"
                    r"(?:categor(?:y|ies)|type|month|year|status)\b"
                    r"|per category", label):
                continue
            ambiguous.append({
                "holder": holder,
                "method": method.get("name"),
                "question": "Should groups with no child rows appear with zero, or be omitted?",
            })
    return ambiguous


def report(requirements, intentions, services, commands=()):
    """The reviewable grounding report for one extracted output."""
    extras = _service_extra_methods(
        requirements, intentions, services, commands)
    missing = _missing_capabilities(intentions, services)
    ambiguous = _ambiguous_aggregate_groups(
        requirements, intentions, services)
    suggestions = {"drop_services": [], "drop_methods": [],
                   "drop_command_verbs": []}
    services_by_name = {service.get("service_name"): service
                        for service in services
                        if isinstance(service.get("service_name"), str)}
    extra_by_holder = {}
    for item in extras:
        extra_by_holder.setdefault(item["holder"], []).append(item["method"])
    for holder, methods in extra_by_holder.items():
        all_methods = {
            method.get("name") for method in
            (services_by_name.get(holder) or {}).get("methods") or []
            if isinstance(method, dict)
        }
        if all_methods and set(methods) == all_methods:
            suggestions["drop_services"].append(holder)
        else:
            suggestions["drop_methods"].extend(
                {"holder": holder, "method": method}
                for method in methods)
    for holder in suggestions["drop_services"]:
        service = services_by_name.get(holder) or {}
        for method in service.get("methods") or []:
            if isinstance(method, dict):
                tokens = _tokens(method.get("name") or "")
                if tokens:
                    suggestions["drop_command_verbs"].append(tokens[0])
    suggestions["drop_command_verbs"] = sorted(set(
        suggestions["drop_command_verbs"]))
    return {
        "extra_methods": extras,
        "missing_capabilities": missing,
        "ambiguous_aggregate_groups": ambiguous,
        "suggested_decisions": suggestions,
    }
