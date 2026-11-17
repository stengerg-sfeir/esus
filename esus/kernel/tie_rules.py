"""Which near-tied classifications need a human, and which are already decided.

Step F records `decision: undecided` when the top two answers were too close to
call (`classification.NARROW_MARGIN`, `DOMAIN_NARROW_MARGIN`). A rerun can land
on the other answer, so an undecided entry is a coin flip — unless both sides
compile to the same body. The table below lists exactly those pairs, with the
rule that resolves each one; the generator implements the rule instead of
branching on the recorded winner, and its tests pin that swapping the two
yields identical code.

Anything undecided whose pair is not in the table changes the generated body
(a guard means a different check), and neither the classifier nor the generator
has the information to choose: the requirements text itself does not say. Those
go to the user (`review_ties.py`), and the answer persists in `decisions.json`.
A future tie with a pair outside the table is a genuinely new ambiguity, so it
escalates to the ask queue rather than being guessed at.
"""

# Domains that mean "a plain method, no special pattern". A domain-stage tie
# between two of these never changes a body.
PLAIN_DOMAINS = frozenset({"STANDARD_CRUD", "REPO_QUERY"})

# Candidate pair -> (rule id, what the generator emits for either side).
EQUIVALENT = {
    frozenset({"STANDARD_CRUD", "REPO_QUERY"}): (
        "plain-method",
        "a plain method with no guard; the domain tie never changes a body",
    ),
    frozenset({"FILTER_BY_FIELD", "FILTER_WITH_PAGINATION"}): (
        "signature-pagination",
        "the signature decides: pagination params mean a paginated filter, "
        "otherwise a plain filter",
    ),
    frozenset({"AGGREGATE_BY_FK", "AGGREGATE_BY_FK_AND_DATE"}): (
        "fk-exists",
        "a foreign-key existence check; the date narrows nothing in code",
    ),
    frozenset({"EXISTS_BY_UNIQUE_COMPOSITE", "AGGREGATE_BY_FK"}): (
        "fk-exists",
        "a foreign-key existence check under either name",
    ),
    frozenset({"READ_ALL", "THRESHOLD_SCAN"}): (
        "list-matching",
        "return the matching records; with no threshold parameter both "
        "reduce to the same read",
    ),
}

UNDECIDED = "undecided"
STAGE_DOMAIN = "domain"


def pair_of(entry):
    """The two tied answers, or None when the entry is not a tie.

    None also covers a decided entry, a gap (`undefined`), and an undecided
    entry missing a side — the last being unprovable, hence unresolvable.
    """
    if not isinstance(entry, dict) or entry.get("decision") != UNDECIDED:
        return None
    if entry.get("undecided_stage") == STAGE_DOMAIN:
        first, second = entry.get("domain"), entry.get("domain_runner_up")
    else:
        first, second = entry.get("pattern_id"), entry.get("runner_up_pattern_id")
    if not isinstance(first, str) or not isinstance(second, str):
        return None
    if not first.strip() or not second.strip():
        return None
    return frozenset({first, second})


def resolution_rule(entry):
    """The rule id resolving a harmless tie, or None when a human must decide."""
    pair = pair_of(entry)
    if pair is None or pair not in EQUIVALENT:
        return None
    return EQUIVALENT[pair][0]


def needs_user(entry):
    """True when an entry is an undecided tie no rule resolves.

    Decided entries, gaps, and table-covered ties are False. An undecided entry
    with a missing side is True: harmlessness cannot be shown, so it is asked.
    """
    if not isinstance(entry, dict) or entry.get("decision") != UNDECIDED:
        return False
    return resolution_rule(entry) is None


def alternative_of(entry):
    """The other side of a tie as a pattern id, or None when there is none.

    Pattern-stage ties name their runner-up directly. Domain-stage ties only
    have a concrete alternative when the other domain is plain (a guard domain
    was never classified, so its pattern is unknown) — and both plain domains
    are themselves legitimate pattern ids.
    """
    if not isinstance(entry, dict) or entry.get("decision") != UNDECIDED:
        return None
    if entry.get("undecided_stage") == STAGE_DOMAIN:
        other = entry.get("domain_runner_up")
        return other if isinstance(other, str) and other in PLAIN_DOMAINS else None
    other = entry.get("runner_up_pattern_id")
    return other if isinstance(other, str) and other.strip() else None


def effective_directive(entry):
    """The one thing a code generator must do with a match: import this.

    Returns `(kind, payload`, where kind is one of:

    - `"pattern"` — implement `payload`, the recorded pattern id. Decided
      matches (including human-decided ones) and plain answers land here.
    - `"rule"` — implement `payload`, a rule id from `EQUIVALENT` (e.g.
      `"signature-pagination"`). The recorded winner is just a label: swapping
      it with the runner-up must yield identical code, which the generator
      pins with a swap test per rule.
    - `"llm-gap"` — no pattern covers this; `payload` carries the context to
      decide from (method, entities, claimed-but-refused pattern). The
      generator reasons from `payload`, built by
      `kernel.generator_context.build_gap_context`.
    - `"llm-tie"` — an undecided tie outside the table with no recorded human
      answer; `payload` carries both candidates. This means the review was
      skipped for a body-changing tie: the generator must not guess silently
      but escalate (ask, or refuse the run).

    A generator that branches on anything else — the raw confidence, the
    recorded winner of a ruled tie — is reimplementing this table, and will
    drift from it. There is exactly one definition.
    """
    if not isinstance(entry, dict):
        return ("llm-tie", {"reason": "not a match entry", "candidates": []})
    decision = entry.get("decision")
    if decision == UNDECIDED:
        rule = resolution_rule(entry)
        if rule is not None:
            return ("rule", rule)
        candidates = [
            name for name in (entry.get("pattern_id"), alternative_of(entry))
            if isinstance(name, str)
        ]
        return ("llm-tie", {"text": entry.get("text"), "candidates": candidates})
    pattern_id = entry.get("pattern_id")
    if decision == "undefined" or pattern_id in ("NO_MATCH", "NO_PATTERN_IN_DOMAIN"):
        return ("llm-gap", {
            "text": entry.get("text"),
            "source": entry.get("source"),
            "claimed_pattern_id": entry.get("claimed_pattern_id"),
            "rejection": entry.get("rejection"),
        })
    return ("pattern", pattern_id)
