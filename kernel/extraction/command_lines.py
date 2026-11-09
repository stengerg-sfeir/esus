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

**Nested groups.** The surface has a command and one level of subcommands. A
prompt that nests groups (`expense category add --name`, `expense report
monthly --month`) fits it by letting a subcommand name be a *path* of words
(`category add`, `report monthly`), which the generated CLI splits into nested
groups. `uses_paths` decides when a prompt does that, and everything about
paths is gated on it: a prompt without such lines is read exactly as before.
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
    from kernel.consistency import checks_surface as surface_checks

    if not isinstance(requirements, str) or not requirements:
        return []
    lines = []
    for span in re.findall(r"`([^`]*)`", requirements):
        text = span.strip()
        if not text or text in lines:
            continue
        if _is_command_line(text):
            lines.append(text)
    # A flagless three-word line (`product report low-stock`) is a command
    # path, but the base rule intentionally leaves it to the model when the
    # rest of the prompt has no paths.  When its first word is already a
    # command named by another line, it is not ambiguous: include it so the
    # path builder can put it on the surface.  Adding it may be what makes
    # `uses_paths` true, so re-run the flagless-path pass after the first add.
    if not uses_paths(lines):
        known = {words[0] for words in _word_lists(lines) if words}
        for span in re.findall(r"`([^`]*)`", requirements):
            text = span.strip()
            words = text.split()
            if (len(words) == 3
                    and all(surface_checks.SPAN_WORD.fullmatch(word)
                            for word in words)
                    and words[0] in known
                    and text not in lines):
                lines.append(text)
    if uses_paths(lines):
        lines = _with_flagless_paths(requirements, lines)
    return lines


def program_word(spans):
    """The word that starts every command line, or None.

    A program name appears on every line of its own prompt (`library` on all
    fifteen of library's), so a first word shared by all of them is the
    program, and a first word that some line lacks is a group (`expense` on
    `expense add` beside `budget list`). One line cannot say which, so at
    least two are needed.
    """
    lists = [words for words in _word_lists(spans) if words]
    if len(lists) < 2:
        return None
    firsts = {words[0] for words in lists}
    return lists[0][0] if len(firsts) == 1 else None


def uses_paths(spans):
    """True when some line has three or more words below the program.

    That is the one shape the two-level surface cannot hold as written, and
    the only one this module treats differently: library's lines never have
    it, so library is read as it always was.
    """
    lists = [words for words in _word_lists(spans) if words]
    if len(lists) < 2:
        return False
    drop = 1 if program_word(spans) else 0
    return any(len(words) - drop >= 3 for words in lists)


def path_attribution(spans):
    """`[(command, path_or_None, flags)]` when the prompt nests groups.

    The first word below the program is the command and the rest of the line,
    as written and joined by single spaces, is the subcommand's name:
    `expense category add --name` is `expense` / `category add`, and `expense
    report monthly --month` is `expense` / `report monthly`.
    """
    program = program_word(spans)
    attributed = []
    for span in spans or []:
        if not isinstance(span, str):
            continue
        words, flags = _split_span(span)
        if program and words and words[0] == program:
            words = words[1:]
        if not words:
            continue
        attributed.append((words[0], " ".join(words[1:]) or None, flags))
    return attributed


def _word_lists(spans):
    return [_split_span(span)[0] for span in spans or [] if isinstance(span, str)]


def _with_flagless_paths(requirements, lines):
    """Add the flagless three-word lines of a prompt that nests groups.

    `expense category list` and `expense recurring detect` carry no flag, so
    the base rule skips them as ambiguous. In a prompt whose other lines
    already nest, a backticked span of three plain words starting with a
    command word the lines use is one more path.
    """
    from kernel.consistency import checks_surface as surface_checks

    known = {words[0] for words in _word_lists(lines) if words}
    kept = []
    for span in re.findall(r"`([^`]*)`", requirements):
        text = span.strip()
        if not text or text in kept:
            continue
        words = text.split()
        flagless_path = (len(words) == 3
                         and all(surface_checks.SPAN_WORD.fullmatch(w) for w in words)
                         and words[0] in known)
        if text in lines or flagless_path:
            kept.append(text)
    return kept


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

    if uses_paths(spans):
        return path_attribution(spans)
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
