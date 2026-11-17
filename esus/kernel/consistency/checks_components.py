"""Consistency checks for the extracted technology components.

Covers the facade and persistence choices, the external access list, and the
crud_services list whose entities must be bare domain model names.
"""

from kernel.consistency.methods import is_missing, is_placeholder
from kernel.consistency.naming import CLASS_SUFFIXES, MATCH_NONE, MATCH_VARIANT, normalize
from kernel.consistency.report import with_suggestions

CRUD_OPERATIONS = ("create", "read_one", "read_all", "update", "delete")
FACADE_TYPES = ("cli", "api", "gui")
NO_TECHNOLOGY = {"", "none"}

# Technologies that mean a command-line parser is being used, so the program is
# expected to have arguments for it to parse. A document that names one of these
# while recording no arguments at all is contradicting itself — which is how the
# hello-world prompt came back with `argparse` and nothing to parse, and no rule
# could see it because the document never said what the parser was for.
PARSER_TECHNOLOGIES = {"argparse", "click", "docopt", "typer"}

# The three parts of a CLI surface, all of which are lists that may be empty.
INVOCATION_PARTS = ("positional", "options", "commands")

# What an option or positional may carry, matching the grammar's `option-type`.
# The field used to be free text, and inventory filled it with `dict`, `none` and
# `positional` — recording its verbs as options of type `dict` and then looping on
# `-add` until the token ceiling. The grammar closes the set now, so a value
# outside it means the document did not come from the current grammar (a
# fallback, or an edit). `list` is the one container, for `--fields name price`.
OPTION_TYPES = ("str", "int", "float", "bool", "list")


def check_components(components, index, report):
    """Validate components; return the crud_services entity names."""
    if not isinstance(components, dict):
        return ()

    _check_facade(components.get("facade"), report)
    _check_persistence(components.get("persistence"), report)
    _check_external_access(components.get("external_access"), report)
    entities = _check_crud_services(components.get("crud_services"), index, report)
    _check_persistence_has_something_to_store(components.get("persistence"), entities, report)
    return entities


def _check_facade(facade, report):
    if not isinstance(facade, dict):
        report.error("invalid_value", "components.facade should be an object")
        return
    facade_type = facade.get("type")
    if facade_type not in FACADE_TYPES:
        report.error(
            "unsupported_value",
            f"components.facade: type '{facade_type}' is not one of {', '.join(FACADE_TYPES)}",
        )
    # `none` is a *value* for a facade's technology, not a placeholder: a program
    # with no arguments needs no parser, and the prompt now says so. The placeholder
    # test therefore excludes it while still catching the junk a model leaves
    # behind ("undefined", "todo", "n/a"). A facade that declares arguments while
    # its technology is `none` is the contradiction, and `inconsistent_facade`
    # reports that instead — so relaxing this loses nothing.
    technology = facade.get("technology")
    if is_missing(technology) or (
        is_placeholder(technology) and _normalized_technology(technology) not in NO_TECHNOLOGY
    ):
        report.warning("invalid_value", f"components.facade: type '{facade_type}' has no technology")

    if "invocation" not in facade:
        # A document written before the CLI surface was recorded. Its silence is
        # not the same statement as an explicit null, so nothing is inferred from
        # it — reporting here would flag every earlier run for a field it could
        # not have written.
        return
    _check_invocation_agrees_with_technology(facade, report)


def _check_invocation_agrees_with_technology(facade, report):
    """The parser and the surface must say the same thing.

    Either half alone is unfalsifiable: `technology: argparse` with no surface
    cannot be wrong, and a surface with no technology cannot be checked. Together
    they contradict each other in two ways, and both were real:

    - the hello-world requirements ask for "a CLI entry point that prints
      Hello, World!" — no arguments — and the prompt's own instruction ("if the
      requirements name none, use cli with technology argparse") produced
      `argparse` anyway;
    - a surface listing options while the technology is `none` would generate a
      program that declares flags nothing parses.
    """
    _check_invocation(facade.get("invocation"), report)
    technology = _normalized_technology(facade.get("technology"))
    invocation = facade.get("invocation")
    if invocation is None and technology in PARSER_TECHNOLOGIES:
        report.warning(
            "inconsistent_facade",
            f"components.facade: technology '{facade.get('technology')}' is a command-line "
            f"parser but invocation is null — the program is declared to take no arguments",
        )
        return
    if _invocation_has_content(invocation) and technology in NO_TECHNOLOGY:
        report.warning(
            "inconsistent_facade",
            f"components.facade: invocation declares arguments but technology is "
            f"{facade.get('technology')!r} — nothing would parse them",
        )


def _invocation_has_content(invocation):
    """True when the surface names at least one argument, option or command."""
    if not isinstance(invocation, dict):
        return False
    for part in INVOCATION_PARTS:
        value = invocation.get(part)
        if isinstance(value, list) and value:
            return True
    return False


def _check_invocation(invocation, report):
    """Validate the surface's own shape: names, types, and repeated commands.

    Two defects found by reading the first run's output, each checkable without
    the requirements:

    - **a verb recorded as an option.** inventory's requirements say
      `category update --id`; the document says command `category` with an option
      `-update` of type `dict`. The noun/verb split was inverted, so the option
      carries the name of the subcommand it was meant to be. An option whose type
      is a mapping cannot be a command-line value at all.
    - **a repeated command name.** library lists `member` twice — once with
      `[add, list]` and once with `[history]`. The two would collide in any CLI
      framework, and nothing compared them because the duplicate rules covered
      documents' named lists, not the nested surface.
    """
    if invocation is None:
        # `null` is the recorded answer for a program with no arguments, so it is
        # valid here and says nothing to check. Treating it as a missing object was
        # a defect in the first version of this function, and the tests that pin the
        # silent cases caught it.
        return
    if not isinstance(invocation, dict):
        report.error("invalid_value", "components.facade.invocation should be an object or null")
        return
    _check_cli_args(invocation.get("positional"), "invocation.positional", report)
    _check_cli_options(invocation.get("options"), "invocation.options", report)
    _check_cli_commands(invocation.get("commands"), report)


def _check_cli_options(options, where, report):
    """Check one options list, wherever it sits in the surface.

    The mapping-typed options are reported as **one** finding per list, not one per
    option: inventory declared ten of them across two commands, and ten identical
    warnings for one modelling mistake is noise that hides the rest of the report.
    """
    if options is None:
        return
    if not isinstance(options, list):
        report.error("invalid_value", f"components.facade.{where} should be a list")
        return
    seen = set()
    bad_types = []
    for option in options:
        if not isinstance(option, dict):
            report.error("invalid_value", f"components.facade.{where} has an entry that is not an object")
            continue
        name = option.get("name")
        if is_missing(name):
            report.error("invalid_identifier", f"components.facade.{where} has an option with no name")
            continue
        key = name.strip().lower()
        if key in seen:
            report.warning("duplicate_entry", f"components.facade.{where}: option '{name}' is listed twice")
        seen.add(key)
        type_name = option.get("type")
        if not isinstance(type_name, str) or not type_name.strip():
            report.warning("invalid_value", f"components.facade.{where}: option '{name}' declares no type")
        elif not _is_option_type(type_name):
            bad_types.append(f"{name} ({type_name})")

    if bad_types:
        report.warning(
            "unsupported_value",
            f"components.facade.{where}: {len(bad_types)} option type(s) are outside "
            f"{', '.join(OPTION_TYPES)}: {', '.join(bad_types)}",
        )


def _is_option_type(type_name):
    return type_name.strip().lower() in OPTION_TYPES


def _check_cli_args(args, where, report):
    """Check the positional arguments' types the same way as an option's."""
    if args is None:
        return
    if not isinstance(args, list):
        report.error("invalid_value", f"components.facade.{where} should be a list")
        return
    seen = set()
    invalid = []
    for argument in args:
        if not isinstance(argument, dict):
            report.error("invalid_value", f"components.facade.{where} has an entry that is not an object")
            continue
        name = argument.get("name")
        if is_missing(name):
            report.error("invalid_identifier", f"components.facade.{where} has an argument with no name")
            continue
        key = name.strip().lower()
        if key in seen:
            report.warning("duplicate_entry", f"components.facade.{where}: argument '{name}' is listed twice")
        seen.add(key)
        type_name = argument.get("type")
        if not isinstance(type_name, str) or not type_name.strip():
            report.warning("invalid_value", f"components.facade.{where}: argument '{name}' declares no type")
        elif not _is_option_type(type_name):
            invalid.append(f"{name} ({type_name})")

    if invalid:
        report.warning(
            "unsupported_value",
            f"components.facade.{where}: {len(invalid)} argument type(s) are outside "
            f"{', '.join(OPTION_TYPES)}: {', '.join(invalid)}",
        )


def _check_cli_commands(commands, report):
    if commands is None:
        return
    if not isinstance(commands, list):
        report.error("invalid_value", "components.facade.invocation.commands should be a list")
        return
    seen = set()
    for command in commands:
        if not isinstance(command, dict):
            report.error("invalid_value", "components.facade.invocation.commands has an entry that is not an object")
            continue
        name = command.get("name")
        if is_missing(name):
            report.error("invalid_identifier", "components.facade.invocation.commands has a command with no name")
            continue
        key = normalize(name)
        if key in seen:
            report.warning("duplicate_entry", f"components.facade.invocation.commands: '{name}' is listed twice")
        seen.add(key)
        _check_cli_options(command.get("options"), f"invocation.commands.{name}.options", report)
        _check_subcommands(name, command.get("subcommands"), report)
        _check_options_are_not_subcommands(name, command, report)


def _check_options_are_not_subcommands(parent, command, report):
    """A word cannot be both an option of a command and one of its subcommands.

    Caught on inventory after the noun/verb correction: `product` gained the right
    subcommands — `[add, list, update, delete, restock, report]` — and kept the same
    verbs as its options, so `add` was both the subcommand that adds a product and
    the flag `-add` of the command containing it. `tool product add --sku` and
    `tool product -add` cannot both be how a product is added, and nothing compared
    the two lists.
    """
    options = command.get("options")
    subcommands = command.get("subcommands")
    if not isinstance(options, list) or not isinstance(subcommands, list):
        return
    subcommand_names = {
        normalize(subcommand.get("name"))
        for subcommand in subcommands
        if isinstance(subcommand, dict) and isinstance(subcommand.get("name"), str)
    }
    repeated = []
    for option in options:
        if not isinstance(option, dict):
            continue
        name = option.get("name")
        if isinstance(name, str) and normalize(name.lstrip("-")) in subcommand_names:
            repeated.append(name)
    if repeated:
        report.warning(
            "invalid_value",
            f"components.facade.invocation.commands.{parent}: option(s) "
            f"{', '.join(repeated)} repeat the name of a subcommand — the same word "
            f"is both a flag and a command",
        )


def _check_subcommands(parent, subcommands, report):
    if subcommands is None:
        return
    if not isinstance(subcommands, list):
        report.error("invalid_value", f"components.facade.invocation.commands.{parent}.subcommands should be a list")
        return
    seen = set()
    for subcommand in subcommands:
        if not isinstance(subcommand, dict):
            report.error(
                "invalid_value",
                f"components.facade.invocation.commands.{parent}.subcommands has an entry that is not an object",
            )
            continue
        name = subcommand.get("name")
        if is_missing(name):
            report.error(
                "invalid_identifier",
                f"components.facade.invocation.commands.{parent}.subcommands has a subcommand with no name",
            )
            continue
        key = normalize(name)
        if key in seen:
            report.warning(
                "duplicate_entry",
                f"components.facade.invocation.commands.{parent}.subcommands: '{name}' is listed twice",
            )
        seen.add(key)
        _check_cli_options(subcommand.get("options"), f"invocation.commands.{parent}.{name}.options", report)


def _check_persistence(persistence, report):
    if not isinstance(persistence, dict):
        report.error("invalid_value", "components.persistence should be an object")
        return
    required = persistence.get("required")
    if not isinstance(required, bool):
        report.error("invalid_value", f"components.persistence: required should be a boolean, found {required!r}")
        return

    technology = persistence.get("technology")
    if required and _normalized_technology(technology) in NO_TECHNOLOGY:
        report.warning("invalid_value", f"components.persistence: required=true but technology is {technology!r}")
    if not required and _normalized_technology(technology) not in NO_TECHNOLOGY:
        report.warning("invalid_value", f"components.persistence: required=false but technology is {technology!r}")


def _normalized_technology(technology):
    return technology.strip().lower() if isinstance(technology, str) else ""


def _check_persistence_has_something_to_store(persistence, entities, report):
    """required=true with no crud entity is self-contradictory.

    The two fields disagree about whether anything is stored at all: persistence
    says it must be, crud_services names nothing to store. Nothing checked that
    pair, and the consequence is worse than silent — step H falls back to
    persisting every modelled entity when crud_services is empty, so the
    contradiction manufactures a repository list from entities the requirements
    never mentioned. That is what produced the CSV-to-JSON prompt's invented
    e-commerce schema: it declared sqlite, named no entity, and step H then
    emitted repositories for the four entities step B had made up.
    """
    if not isinstance(persistence, dict) or persistence.get("required") is not True:
        return
    if entities:
        return
    report.warning(
        "invalid_value",
        "components: persistence.required=true but crud_services is empty — "
        "nothing is named to persist",
    )


def _check_external_access(external_access, report):
    if external_access is None:
        return
    if not isinstance(external_access, list):
        report.error("invalid_value", "components.external_access should be a list")
        return
    for item in external_access:
        if is_missing(item):
            report.error("invalid_value", "components.external_access contains an entry that is not a string")
        elif is_placeholder(item):
            report.warning("placeholder_value", f"components.external_access contains the placeholder {item!r}")


def _check_crud_services(crud_services, index, report):
    if not isinstance(crud_services, list):
        report.error("invalid_value", "components.crud_services should be a list")
        return ()

    entities = []
    seen = set()
    for item in crud_services:
        if not isinstance(item, dict):
            report.error("invalid_value", "components.crud_services contains an entry that is not an object")
            continue
        entity = item.get("entity")
        if is_missing(entity):
            report.error("invalid_identifier", "components.crud_services has an entry with no entity")
            continue

        key = entity.strip().lower()
        if key in seen:
            report.warning("duplicate_entry", f"components.crud_services: '{entity}' is listed more than once")
        seen.add(key)
        entities.append(entity)

        _check_crud_entity(entity, index, report)
        _check_crud_operations(item.get("operations"), entity, report)

    return tuple(entities)


def _check_crud_entity(entity, index, report):
    if entity.endswith(CLASS_SUFFIXES):
        report.error(
            "class_name_entity",
            f"components.crud_services: '{entity}' is a class name, not a domain entity",
        )
        return
    if not index.names:
        return

    tier, resolved = index.resolve(entity)
    if tier is MATCH_NONE:
        report.warning(
            "unknown_reference",
            with_suggestions(
                f"components.crud_services: '{entity}' not found in data_models",
                index.suggest(entity),
            ),
        )
    elif tier is MATCH_VARIANT:
        report.warning(
            "name_variant",
            f"components.crud_services: '{entity}' is spelled '{resolved}' in data_models",
        )


def _check_crud_operations(operations, entity, report):
    if not isinstance(operations, list):
        report.error("invalid_value", f"components.crud_services: '{entity}' operations should be a list")
        return
    if not operations:
        report.warning("empty_section", f"components.crud_services: '{entity}' declares no operations")
        return
    for operation in operations:
        if operation not in CRUD_OPERATIONS:
            report.error(
                "unsupported_value",
                f"components.crud_services: '{entity}' declares unknown operation '{operation}'",
            )
