"""Step F: classify invariants and contract methods into kernel patterns.

This step used to be silent and dominated run time. It now reports one line per
item, which both removes the appearance of a hang and makes the per-item cost
visible in the run log.

**Nothing is discarded here.** Until this change the stage-1 "no domain fits"
answer was filtered out before the document was written, so 62 of the 191 items
across the seven prompts were classified and then thrown away — every one of them
ordinary CRUD, which the classifier had identified correctly. The answers are all
kept now. The gap ids (`NO_MATCH`, `NO_PATTERN_IN_DOMAIN`) are the coverage
report: their count and their texts say which pattern the vocabulary is missing.
`STANDARD_CRUD` is a legitimate answer recording what no named pattern needs to
describe, and is never a finding.
"""

from kernel.classifier.hierarchical_classifier import classify_requirement_2step, load_catalog
from kernel.pattern_catalog import GAP_PATTERN_IDS, NO_PATTERN_IN_DOMAIN, STANDARD_CRUD
from kernel.pattern_shapes import (
    rejection_reason,
    returns_one_record,
    returns_records,
)

# Step C's tag for an invariant that states a behaviour, and so may map onto a
# kernel pattern. Its counterpart, `SCHEMA_KIND`, restates a field declaration
# and is not classified — see `classification_items`.
RULE_KIND = "rule"

# How close the top two answers may be before the classification is reported as
# undecided. The absolute confidence alone cannot say this: a 0.70 that beat a
# 0.69 is a coin-flip and a 0.70 that beat a 0.05 is a decision, and both report
# 0.70. Calibrated against the corpus once the read-shape vocabulary was
# completed; re-derive it whenever the option list changes, for the same reason
# as the checker's confidence floor.
NARROW_MARGIN = 0.15

# The same question asked of **step 1**, which is the more consequential of the
# two: the domain decides which pattern list step 2 even sees, so a near-tied
# domain can put the match in the wrong list entirely, while a near-tied pattern
# keeps it in the right one. Kept as its own constant because the two margins are
# on different scales — the pattern margin is the domain probability times the
# gap between two pattern probabilities, the domain margin is a raw softmax gap —
# so calibrating one does not calibrate the other. 0.15 is a starting point from
# the pattern stage, **not** a measured value for this stage: the first run that
# uses it should be read for how many items it flags before it is trusted.
DOMAIN_NARROW_MARGIN = 0.15

# The three decisions a match carries, so a generator switches on one value
# instead of re-deriving a threshold:
#   "undefined" — the kernel has no answer (NO_MATCH, NO_PATTERN_IN_DOMAIN).
#   "undecided" — the kernel has two answers too close to call; `undecided_stage`
#                 says which stage, and the alternatives and margin are recorded.
#   "decided"   — neither.
DECIDED = "decided"
UNDECIDED = "undecided"
UNDEFINED = "undefined"

STAGE_DOMAIN = "domain"
STAGE_PATTERN = "pattern"


def classify_documents(classifier, documents, log):
    """Classify every invariant and contract method; return every match."""
    catalog = load_catalog()
    items = classification_items(documents)

    if not items:
        log.write("[ok] step patterns: nothing to classify")
        return []

    matches = []
    gaps = []
    standard_crud = 0
    total = len(items)
    signatures = _method_signatures(documents)

    for index, (source, text) in enumerate(items, start=1):
        result = classify_requirement_2step(classifier, text, catalog)
        claimed = result["pattern_id"]
        return_type = signatures.get(source)
        # The classifier's own total describes the pattern it *claimed*, and that
        # is not the recorded one when the claim is corrected. Recording the
        # claim's figure beside the corrected pattern made the two disagree, and
        # the margin — computed as `confidence - runner_up` — then cancelled to
        # exactly 0.0 for every corrected entry (measured: ten of ten), which is
        # below any threshold and reported each one as `undecided` on top of its
        # correction note. `confidence` below is therefore the *recorded*
        # pattern's own figure, and the claim's is kept as `claimed_confidence`.
        claimed_confidence = result["confidence"]

        # The catch-all is `UNKNOWN`, and it is decided here rather than by the
        # model. The "none of these" option is never chosen — measured at 0.000
        # on 30 of the 34 expenses methods and never above 0.036 — so an answer
        # no pattern fits arrives as the *nearest* pattern. A pattern whose
        # return shape cannot be this method's return shape is impossible, so it
        # is replaced by the next candidate that can be right, or by the gap when
        # none can. See `kernel/pattern_shapes._attribute`.
        pattern_id, claimed, rejection = _attribute(result, return_type)
        confidence = _recorded_confidence(result, pattern_id)

        marker = ""
        if pattern_id in GAP_PATTERN_IDS:
            gaps.append((source, pattern_id, text))
            marker = (
                f"  <- UNKNOWN: {rejection}"
                if rejection
                else "  <- GAP: no pattern for this"
            )
        elif rejection:
            # A shape-compatible candidate replaced an impossible claim. Not a
            # gap — an answer — but recorded because the model was wrong and the
            # record should say so rather than quietly agreeing with itself.
            marker = f"  <- corrected: {rejection} (was {claimed})"
        elif pattern_id == STANDARD_CRUD:
            standard_crud += 1

        # The runner-up is recorded because the winner alone cannot say whether an
        # answer was decided or guessed. A 0.70 that beat a 0.69 and a 0.70 that
        # beat a 0.05 are identical without it, and the first is exactly the "same
        # requirement, two verdicts" case this document has to be able to show.
        # It excludes the **recorded** pattern, not the claim — see `_runner_up`.
        # Measured among the answers that are *possible* for this return shape. A
        # corrected entry's best alternative is otherwise the model's claim, whose
        # probability the correction already overrode — which is precisely how the
        # margin came to be 0.0 for ten entries.
        viable = _viable_patterns(result, return_type)
        runner_up_id, runner_up_confidence = _runner_up(result, pattern_id, viable)
        # A margin exists only when there were two answers to choose between. A
        # gap is not a choice, and a shape rule that leaves no candidate standing
        # leaves nothing to compare against; recording a number in either case
        # produced a large *negative* one — the recorded entry's own probability
        # minus the claim's — which is not a margin, and `-0.48` on a gap would
        # mislead anything reading the field. Measured on the seven-prompt corpus:
        # six of the seven gaps carried a negative margin before this.
        if pattern_id in GAP_PATTERN_IDS or runner_up_id is None:
            runner_up_id, runner_up_confidence, margin = None, 0.0, None
        else:
            margin = confidence - runner_up_confidence
        domain_runner_up, domain_runner_up_confidence = _domain_runner_up(result)
        domain_confidence = (result.get("step1_probabilities") or {}).get(
            result.get("domain"), 0.0
        )
        domain_margin = domain_confidence - domain_runner_up_confidence
        decision, undecided_stage = _decide(pattern_id, margin, domain_margin)

        if decision == UNDECIDED and undecided_stage == STAGE_DOMAIN:
            decided = (
                f"  <- undecided (domain): {domain_runner_up} "
                f"at {domain_runner_up_confidence:.2f}"
            )
        elif decision == UNDECIDED:
            decided = (
                f"  <- undecided (pattern): {runner_up_id} "
                f"at {runner_up_confidence:.2f}"
            )
        else:
            decided = ""
        log.write(
            f"  [{index}/{total}] {source} -> {pattern_id} ({confidence:.2f}){marker}{decided}"
        )

        matches.append(
            {
                "source": source,
                "text": text,
                "domain": result["domain"],
                "pattern_id": pattern_id,
                "confidence": round(confidence, 4),
                # One value to switch on, rather than a threshold to re-derive.
                "decision": decision,
                "undecided_stage": undecided_stage,
                "runner_up_pattern_id": runner_up_id,
                "runner_up_confidence": round(runner_up_confidence, 4),
                # None when there was no alternative to compare against — a gap,
                # or an item no candidate can be right for. See above.
                "margin": None if margin is None else round(margin, 4),
                # Step 1's own ambiguity, which nothing recorded before: the domain
                # chooses which pattern list step 2 sees, so this is the more
                # consequential of the two margins. A separate scale from `margin`
                # — see `DOMAIN_NARROW_MARGIN`.
                "domain_runner_up": domain_runner_up,
                "domain_runner_up_confidence": round(domain_runner_up_confidence, 4),
                "domain_margin": round(domain_margin, 4),
                # What the model said, and why it was refused. The claim is kept
                # rather than overwritten because it names the pattern the
                # catalogue is missing: "claimed AGGREGATE_BY_FK_AND_DATE for a
                # method returning List[Expense]" is a specification for the
                # pattern to add, which is the whole point of the gap.
                "claimed_pattern_id": claimed,
                # The classifier's own figure for the claim, present only when it
                # differs from `confidence` — i.e. only when a correction happened —
                # so the two figures a reader might compare are both on record.
                "claimed_confidence": (
                    round(claimed_confidence, 4)
                    if rejection and claimed_confidence != confidence
                    else None
                ),
                "rejection": rejection,
            }
        )

    log.write(
        f"[ok] step patterns: {total} item(s) — {standard_crud} standard CRUD, "
        f"{total - standard_crud - len(gaps)} pattern(s), {len(gaps)} gap(s)"
    )
    for source, pattern_id, text in gaps:
        log.write(f"    gap [{pattern_id}] {source}: {text}")

    return matches


def classification_items(documents):
    """The (source label, text) pairs to classify, in document order.

    Only invariants step C tagged `rule` are classified. A `schema` invariant
    restates a field's own declaration — its type, nullability, uniqueness, key
    or allowed values — so it names no operation and no pattern can be right for
    it: every answer the classifier gives is noise, and measured across the
    seven prompts most of that noise lands *above* the confidence floor and so
    was never even reported. Step C makes the distinction when it writes the
    invariant, where the grammar can enforce it, rather than leaving it to be
    guessed from prose here (`grammar_open.invariant_list`).
    """
    items = []
    for invariant in _rule_invariants(documents.get("invariants")):
        items.append(("invariant", invariant))
    for contract in _dict_list(documents.get("service_contracts")):
        service = contract.get("service_name") or ""
        for method in _dict_list(contract.get("methods")):
            name = method.get("name") or ""
            items.append((f"contract:{service}.{name}", _method_text(name, method)))
    return items


def _method_text(name, method):
    """A method's full signature and description — the evidence a pattern needs.

    Until this change only `name: description` reached step F, so the classifier
    decided from half the evidence: `get_monthly_expenses(month) -> List[Expense]`
    ("Returns expenses for a specific month") and `get_category_spending(...) ->
    int` ("Returns total spending …") looked the same to it, and both were
    classified `AGGREGATE_BY_FK_AND_DATE` — wrong for the first, whose return type
    proves it returns records rather than an aggregate. The parameters and the
    return type are the decisive evidence for the read-shaped patterns, and the
    step that turns a match into code needs them anyway, so the signature is
    classified rather than an abbreviation of it.
    """
    params = ", ".join(
        f"{param.get('name')}: {param.get('type')}"
        for param in _dict_list(method.get("params"))
        if param.get("name")
    )
    return_type = method.get("return_type") or "?"
    description = method.get("description") or ""
    return f"{name}({params}) -> {return_type}: {description}"


def _attribute(result, return_type):
    """The pattern to record: the claim, the next possible one, or the gap.

    Returns `(pattern_id, claimed_pattern_id, rejection_reason)`.

    When the model's claim cannot be right for the method's return type, the
    next-best candidate whose shape *can* be right is taken instead. That matters
    because the refusal is about the claim, not about the domain: for
    `find_expenses_by_category(category_id) -> List[Expense]` the model claimed
    `AGGREGATE_BY_FK` (impossible — an aggregate returns a number) while
    `FILTER_BY_FIELD` sat second at 0.39 and its shape is exactly right, so the
    corrected answer is the filter, not a gap. Only when *no* candidate can be
    right does the item become a gap — and then it is a genuine missing kernel
    feature, named by the claim and the reason.

    The rejection is returned even when a candidate was found, so the record
    says what the model wanted and that it was overruled rather than hiding it.
    """
    claimed = result["pattern_id"]
    rejection = rejection_reason(claimed, return_type)
    if not rejection:
        return claimed, claimed, None

    ranked = sorted(
        (result.get("step2_probabilities") or {}).items(),
        key=lambda pair: -pair[1],
    )
    for candidate, _ in ranked:
        if candidate == claimed:
            continue
        if candidate in GAP_PATTERN_IDS:
            # The sentinel carries no declared shape and is always compatible;
            # reaching it means no real pattern can be right, which *is* the gap.
            break
        # `returns_records` confines the correction to the defect that was
        # actually demonstrated — a read returning records, named as an
        # aggregate. Without it the rule is shape-blind to *family*:
        # `export_to_csv(...) -> bool` was "corrected" to
        # `EXISTS_BY_UNIQUE_COMPOSITE`, also boolean and therefore shape-valid
        # and plainly wrong. A candidate from another return family is a guess,
        # and a guess is what the gap exists to avoid.
        # A read of one record by its key is the same kind of defect for a
        # method that returns one entity, so such a candidate is admitted too.
        if rejection_reason(candidate, return_type) is None and (
                returns_records(candidate) or returns_one_record(candidate)):
            return candidate, claimed, rejection
    return NO_PATTERN_IN_DOMAIN, claimed, rejection


def _method_signatures(documents):
    """source -> the method's declared return type, for rejecting an impossible pattern.

    Only contract methods carry one; an invariant has no signature and cannot be
    checked this way, which is a limit of the method rather than a claim that
    invariants are right.
    """
    signatures = {}
    for contract in _dict_list(documents.get("service_contracts")):
        service = contract.get("service_name") or ""
        for method in _dict_list(contract.get("methods")):
            name = method.get("name") or ""
            signatures[f"contract:{service}.{name}"] = method.get("return_type")
    return signatures


def _recorded_confidence(result, pattern_id):
    """The confidence of the answer being recorded: domain x its own probability.

    The classifier returns the product for the pattern it *chose*, which is the
    record's own confidence only when nothing was corrected. `_attribute` can
    replace an impossible claim, and keeping the claim's figure beside the
    corrected pattern made `margin` cancel to 0.0 for every corrected entry —
    measured on ten of ten, and reported as a near-tie each time.

    A sentinel the model never scored, or a domain-stage short-circuit, has no
    second stage to recompute from, so the classifier's own figure stands.
    """
    probabilities = result.get("step2_probabilities") or {}
    if pattern_id not in probabilities:
        return result["confidence"]
    domain_probability = (result.get("step1_probabilities") or {}).get(
        result.get("domain"), 1.0
    )
    return domain_probability * probabilities[pattern_id]


def _viable_patterns(result, return_type):
    """The candidate ids whose shape can be this method's return type, or None.

    The margin is a question about the *choice*, so it must be asked among answers
    that could have been taken. An impossible claim is not one of them: it lost to
    the shape rule, not to a competitor, so measuring a margin against it says
    nothing about how close the real decision was.

    **None** means the return type is unknown — an invariant carries no signature —
    so every candidate is left in and the margin is measured as before. An
    **empty** set is a different statement, and the reason it is not collapsed
    into None: it says no candidate can be right, which is exactly what makes the
    item a gap. Collapsing it made `_runner_up` fall back to the unfiltered list
    and compare the entry against its own claim.
    """
    if return_type is None:
        return None
    probabilities = result.get("step2_probabilities") or {}
    return {
        candidate
        for candidate in probabilities
        if candidate not in GAP_PATTERN_IDS
        and rejection_reason(candidate, return_type) is None
    }


def _runner_up(result, recorded_pattern_id, viable=None):
    """The best answer **other than the one being recorded**, on the reported scale.

    Excludes the *recorded* pattern, not the model's raw claim. That distinction
    is the whole point: when `_attribute` corrects an impossible claim, the
    corrected pattern is the answer, and excluding the claim instead let the
    answer become its own runner-up. Three `narrow_margin` notes in the corpus
    compared a pattern with itself that way —

        'FILTER_BY_FIELD' ... by a margin of 0.14 over 'FILTER_BY_FIELD'

    — which cannot mean anything, because a margin against the winner can never
    move the answer. `read_budgets_by_category` was claimed `AGGREGATE_BY_FK`
    (0.44), corrected to `FILTER_BY_FIELD` (0.30); the 0.14 is real, the name
    recorded was not.

    `confidence` is the product of the two softmaxes — the domain and then the
    pattern — so the runner-up must be scaled by the same domain probability, or
    the margin compares two different quantities and can even come out negative
    (measured: it did, on inventory's first invariant, before this scaling). The
    margin this produces is therefore `domain * (top1_pattern - top2_pattern)`,
    which is non-negative by construction and comparable with the confidence.

    Empty when the domain stage short-circuited (STANDARD_CRUD, NO_MATCH), since
    then no second stage ran and there is no runner-up to report.

    `viable` restricts the choice to answers whose shape can actually be this
    method's return type — see `_viable_patterns` for why a corrected entry needs
    it.
    """
    probabilities = result.get("step2_probabilities") or {}
    domain_probability = (result.get("step1_probabilities") or {}).get(
        result.get("domain"), 1.0
    )
    ordered = sorted(
        (
            (pattern_id, probability)
            for pattern_id, probability in probabilities.items()
            if pattern_id != recorded_pattern_id
            and (viable is None or pattern_id in viable)
        ),
        key=lambda pair: -pair[1],
    )
    if not ordered:
        return None, 0.0
    pattern_id, probability = ordered[0]
    return pattern_id, domain_probability * probability


def _domain_runner_up(result):
    """The second-best **domain** and its probability, or `(None, 0.0)`.

    Step 1 decides which pattern list step 2 even sees, so its ambiguity is the
    more consequential of the two and was unrecorded until now: `_runner_up`
    reads only `step2_probabilities`, and returns nothing at all when step 1
    short-circuits (`STANDARD_CRUD`, `NO_MATCH`). A near-tie between `REPO_QUERY`
    and `STANDARD_CRUD` decides between "here is the pattern" and "no pattern is
    needed" — and left no trace. The distribution is already returned by the
    classifier, so recording this costs nothing.

    Unlike `_runner_up` this is a raw softmax gap, not a product — see
    `DOMAIN_NARROW_MARGIN` for why the two thresholds are separate constants.
    """
    probabilities = result.get("step1_probabilities") or {}
    winner = result.get("domain")
    ordered = sorted(
        (
            (domain_id, probability)
            for domain_id, probability in probabilities.items()
            if domain_id != winner
        ),
        key=lambda pair: -pair[1],
    )
    if not ordered:
        return None, 0.0
    domain_id, probability = ordered[0]
    return domain_id, probability


def _decide(pattern_id, margin, domain_margin):
    """`(decision, undecided_stage)` — the two categories, plus decided.

    `undefined` is answered first: a gap is a gap whatever the margins say, and
    calling it `undecided` would route a missing pattern to a generator as a
    choice between two patterns it does not have.

    Then the **domain** stage before the pattern stage, deliberately: when both
    are near-tied the domain is the one worth reporting, because it decides
    whether step 2's candidates were the right list at all. Reporting the pattern
    margin there would describe a choice among the wrong options.
    """
    if pattern_id in GAP_PATTERN_IDS:
        return UNDEFINED, None
    if domain_runner_up_is_narrow(domain_margin):
        return UNDECIDED, STAGE_DOMAIN
    if _is_narrow_pattern_margin(margin):
        return UNDECIDED, STAGE_PATTERN
    return DECIDED, None


def _is_narrow_pattern_margin(margin):
    """True when there *was* an alternative and the two were too close to call.

    A `None` margin means there was nothing to compare against — a gap, or an
    item no candidate can be right for — so there is no near-tie to report. Read
    as a plain `<` it raised `TypeError: '<' not supported between instances of
    'NoneType' and 'float'`, which is what the first run of this change did.
    """
    return margin is not None and margin < NARROW_MARGIN


def domain_runner_up_is_narrow(domain_margin):
    """True when step 1's top two domains were too close to call."""
    return domain_margin < DOMAIN_NARROW_MARGIN


def _rule_invariants(value):
    """The text of every invariant tagged `rule`."""
    texts = []
    for item in _invariants(value):
        kind, text = item
        if kind == RULE_KIND:
            texts.append(text)
    return texts


def _invariants(value):
    """Every invariant as a (kind, text) pair, accepting either document shape.

    The tagged shape is what step C writes now. The bare-string shape is read
    too, so an output directory produced before this change still classifies
    instead of silently yielding nothing — there, every invariant was
    classified, which is the behaviour being replaced.
    """
    if not isinstance(value, list):
        return []
    pairs = []
    for item in value:
        if isinstance(item, str):
            if item.strip():
                pairs.append((RULE_KIND, item.strip()))
        elif isinstance(item, dict):
            text = item.get("text")
            if isinstance(text, str) and text.strip():
                pairs.append((item.get("kind"), text.strip()))
    return pairs


def _string_list(value):
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _dict_list(value):
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]
