"""Authoritative command lines carried from requirements into step D.

Step D asks the model to both *discover* command lines in prose and
*transcribe* them onto the surface — and discovery is what fails (a `member`
group the prompt names three times over never surfaces). Discovery is also
what the checker already does deterministically, so the pipeline extracts
the lines once, by the checker's own rules, and hands them to the step as
an authoritative enumerated block — the same move as the entity block.
Anything unparseable stays with the model: prose mentions with no backticks
(the 60 prompt), schema fragments (`UNIQUE(...)`), and flagless multi-word
lines (`product report low-stock`) need judgment, and the block never claims
to be exhaustive — only that each listed line must appear.
"""

import re


def extract_command_lines(requirements):
    """Every backtick span shaped like a command line, in order, deduped.

    Included: spans carrying a `--flag`, plus exactly-two-word plain spans
    (`library overdue`, `category list`). Brackets survive — `[--stock]`
    still marks an optional flag for step D to read. The program word is
    deliberately NOT required: inventory writes `product add` with none, and
    a junk line that slips in costs little (the model judges it, and the
    unbacked-command probe gates what it invents).
    """
    if not isinstance(requirements, str) or not requirements:
        return []
    lines = []
    for span in re.findall(r"`([^`]*)`", requirements):
        text = span.strip()
        if not text or text in lines:
            continue
        if _is_command_line(text):
            lines.append(text)
    return lines


def _is_command_line(text):
    """True for a span shaped like a command line, and nothing else."""
    from kernel.consistency import checks_surface as surface_checks

    tokens = text.split()
    if any(surface_checks.FLAG_TOKEN.match(token) for token in tokens):
        return True
    return (len(tokens) == 2
            and bool(surface_checks.SPAN_WORD.fullmatch(tokens[0]))
            and bool(surface_checks.SPAN_WORD.fullmatch(tokens[1])))


def attribute_lines(spans, entity_names):
    """Attribute each span to `(command, subcommand_or_None, flags)`.

    Attribution rules, in order, each documented with the line that needs it:

    - two leading entities drop the first as program-like: `expense
      category add` is category/add (the prompt's own three-level lines),
      while a single leading entity owns the line (`product add`,
      `budget add`, `expense report monthly` — where `report` is verb-like
      and `monthly` is a value, correctly ignored);
    - a leading non-entity word is a program word and drops (`library member
      add` is member/add; `library borrow --member-id` is bare `borrow`);
    - the subcommand is the next non-flag word only when verb-like
      (`COMMAND_VERB_STEMS`); a value there (`monthly`) means flags attach
      to the command's reading of the line;
    - flags are `(name, required)` pairs straight from the span, brackets
      marking optional, via the checker's own flag reader.

    Returns `[(command, sub, [(flag, required), ...]), ...]` for resolvable
    lines; unresolvable ones (degenerate spans, double-entity collisions
    like a hypothetical `order item add` that no two-level surface can hold)
    are skipped — the model keeps those, and the probe judges them.
    """
    from kernel.consistency import checks_surface as surface_checks
    from kernel.consistency.checks_surface import COMMAND_VERB_STEMS
    from kernel.consistency.naming import normalize

    entities = {normalize(name) for name in entity_names or [] if name}
    attributed = []
    for span in spans or []:
        if not isinstance(span, str):
            continue
        words, flags = _split_span(span)
        if not words:
            continue
        if len(words) >= 2 and normalize(words[0]) in entities and normalize(words[1]) in entities:
            words = words[1:]
        elif entities and normalize(words[0]) not in entities and len(words) > 1:
            # A leading non-entity word is a program word — but only when
            # entities are known at all. With an empty vocabulary every word
            # looks program-like, and dropping `product` from `product add`
            # manufactures a phantom `add` command; keeping tokens[0] is the
            # conservative reading there, and the probe judges the rest.
            words = words[1:]
        command = words[0]
        sub = None
        if len(words) > 1 and not words[1].startswith("-"):
            candidate = words[1].strip("[](),.;:")
            if candidate.lower() in COMMAND_VERB_STEMS:
                sub = candidate
        attributed.append((command, sub, flags))
    return attributed


def _split_span(span):
    """`(word tokens, [(flag, required)])` for one command-line span."""
    from kernel.consistency import checks_surface as surface_checks

    words = []
    flags = []
    for token in span.split():
        match = surface_checks.FLAG_TOKEN.match(token)
        if match is not None:
            flags.append((match.group(1), not token.startswith("[")))
            continue
        stripped = token.strip("[](),.;:")
        if stripped and not stripped.startswith("-"):
            words.append(stripped)
    return words, flags
