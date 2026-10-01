"""The pattern vocabulary: the catalogues, the domains, and the answer sentinels.

One dependency-free home for what a `pattern_id` may be, so the classifier that
produces the ids and the checker that validates them cannot disagree. The
classifier imports this module; nothing here imports `llama_cpp`, so the checker
can use it without pulling in the model runtime.

**Three answers are not patterns, and they used to be one bucket.** The domain
stage offered a single option, `CUSTOM_OR_NONE`, documented as "Basic CRUD
(create/read/update/delete by id) or non-standard custom business logic" — two
opposite answers in one id. `classification.py` then discarded that id entirely,
so a requirement that had no pattern left no trace at all: 62 of the 191 items
across the seven prompts, every one of them ordinary CRUD that was *correctly*
identified and then thrown away. The gap and the legitimate answer were deleted
together because one id could not tell them apart.

They are now three ids with three meanings, so nothing has to be discarded:

- `STANDARD_CRUD` — plain create/read/update/delete by id. The correct answer for
  most repository methods, and **not** a gap: no named pattern describes it.
- `NO_MATCH` — fits no domain at all. A gap: the vocabulary lacks the concept.
- `NO_PATTERN_IN_DOMAIN` — the domain fits, but no pattern inside it does. A gap:
  the catalogue lacks the pattern.

The two gaps are the coverage report. Counting them, and reading the texts that
produce them, says which pattern to add next — measured rather than guessed.
"""

import json
from pathlib import Path

KERNEL_DIR = Path(__file__).resolve().parent

CATALOGUE_PATHS = {
    "REPO_QUERY": KERNEL_DIR / "repo_patterns" / "patterns.json",
    "SERVICE_GUARD": KERNEL_DIR / "service_patterns" / "patterns.json",
}

# Step 1 domain options. The last two short-circuit step 2: they are answers in
# their own right, not domains that contain patterns.
DOMAINS = (
    {
        "id": "REPO_QUERY",
        "name": "Repository Query or Aggregate",
        "description": "Database query, filtered list, SQL aggregation, sum, count, pagination, or uniqueness check.",
    },
    {
        "id": "SERVICE_GUARD",
        "name": "Service Invariant or Business Rule Guard",
        "description": "Validation check, budget overflow, stock sufficiency, capacity quota, or pricing rule.",
    },
    {
        "id": "STANDARD_CRUD",
        "name": "Standard CRUD by Primary Key",
        "description": (
            "A plain create, read, update or delete of a single record identified by its "
            "primary key. Every repository has these and no named pattern describes them, so "
            "this is a complete and correct answer rather than a gap."
        ),
    },
    {
        "id": "NO_MATCH",
        "name": "None of the Above",
        "description": (
            "The statement is not a repository query, not a business-rule guard, and not plain "
            "CRUD. Use this only when no domain above fits, because it records a gap in the "
            "vocabulary rather than classifying anything."
        ),
    },
)

STANDARD_CRUD = "STANDARD_CRUD"
NO_MATCH = "NO_MATCH"

# A domain answer that ends the classification: there is no step 2 to run.
NO_DOMAIN_IDS = frozenset({STANDARD_CRUD, NO_MATCH})

# Step 2's "matches none of these" option, offered alongside each domain's
# patterns. It says the domain is right and the pattern list is incomplete.
NO_PATTERN_IN_DOMAIN = "NO_PATTERN_IN_DOMAIN"

# The gap ids, which a report may count, as opposed to STANDARD_CRUD, which is a
# legitimate answer and never a finding.
GAP_PATTERN_IDS = frozenset({NO_MATCH, NO_PATTERN_IN_DOMAIN})

# Every id a match may carry that is not a catalogue pattern.
SENTINEL_PATTERN_IDS = frozenset({STANDARD_CRUD}) | GAP_PATTERN_IDS

NO_PATTERN_IN_DOMAIN_OPTION = {
    "pattern_id": NO_PATTERN_IN_DOMAIN,
    "name": "No Standard Pattern in This Group",
    "description": (
        "The domain is right but none of the patterns listed in it fits. Records a gap in the "
        "catalogue rather than classifying anything."
    ),
}


def load_catalog():
    """The patterns of each domain, keyed by domain id."""
    catalog = {domain: [] for domain in CATALOGUE_PATHS}
    for domain, path in CATALOGUE_PATHS.items():
        with open(path, "r", encoding="utf-8") as handle:
            catalog[domain] = json.load(handle)
    return catalog


def catalogue_pattern_ids():
    """Every pattern id the two catalogue files define."""
    ids = set()
    for path in CATALOGUE_PATHS.values():
        with open(path, "r", encoding="utf-8") as handle:
            for entry in json.load(handle):
                pattern_id = entry.get("pattern_id")
                if pattern_id:
                    ids.add(pattern_id)
    return ids


def known_pattern_ids():
    """Every pattern id a match may carry: the catalogues plus the sentinels."""
    return catalogue_pattern_ids() | SENTINEL_PATTERN_IDS


def domain_ids():
    return tuple(domain["id"] for domain in DOMAINS)
