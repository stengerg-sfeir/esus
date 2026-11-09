"""Behavior acceptance for a freshly generated library package.

Run only after real extraction and generation have populated ``OUT_DIR``::

    python3.12 tests/e2e_library_acceptance.py /private/tmp/esus-library-e2e

This test invokes the generated CLI in fresh processes and inspects only its
SQLite database. It never edits generated modules. The database and a JSON
result record stay beside the extraction and raw model answers for diagnosis.
"""

import datetime as dt
import inspect
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path


def fail(message):
    raise AssertionError(message)


def cli(cli_path, database, *args, expected=0):
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(
        [sys.executable, str(cli_path), "--db", str(database), *args],
        check=False, capture_output=True, text=True, env=env)
    if result.returncode != expected:
        fail(f"CLI {args!r} returned {result.returncode}, expected {expected}. "
             f"stdout={result.stdout!r}; stderr={result.stderr!r}")
    return result


def json_rows(output):
    rows = []
    for line in output.splitlines():
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def table_with(connection, required_columns):
    names = [row[0] for row in connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%'")]
    for name in names:
        escaped = name.replace('"', '""')
        columns = {row[1] for row in connection.execute(
            f'PRAGMA table_info("{escaped}")')}
        if set(required_columns) <= columns:
            return name, columns
    fail(f"no generated SQLite table has columns {sorted(required_columns)}")


def quoted(name):
    return '"' + name.replace('"', '""') + '"'


def rows_for(connection, table, **criteria):
    where = " AND ".join(f"{quoted(key)} = ?" for key in criteria)
    query = f"SELECT * FROM {quoted(table)}"
    params = ()
    if where:
        query += " WHERE " + where
        params = tuple(criteria.values())
    cursor = connection.execute(query, params)
    columns = [item[0] for item in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def unique_index_for(connection, table, column):
    for index in connection.execute(f"PRAGMA index_list({quoted(table)})"):
        if not index[2]:
            continue
        fields = [item[2] for item in connection.execute(
            f"PRAGMA index_info({quoted(index[1])})")]
        if fields == [column]:
            return True
    return False


def foreign_key(connection, table, source, target_table, target_column):
    return any(
        row[3] == source and row[2].lower() == target_table.lower()
        and row[4] == target_column and row[6].upper() == "CASCADE"
        for row in connection.execute(f"PRAGMA foreign_key_list({quoted(table)})"))



def generated_deps(out_dir, database):
    """The generated package's own wiring (`cli.build_cli`), in-process.

    The CLI has no command for some methods the prompt asks for (service
    `renew_membership`, repository finders), so they are called through the
    package exactly as the CLI calls its services. Nothing is edited and no
    bytecode is written beside the generated modules.
    """
    sys.dont_write_bytecode = True
    generated = str(Path(out_dir) / "generated")
    if generated not in sys.path:
        sys.path.insert(0, generated)
    import cli as generated_cli
    built = generated_cli.build_cli(str(database))
    # The click backend returns the dependencies; argparse returns (parser, deps).
    return built[1] if isinstance(built, tuple) else built


def need(owner, name, why):
    method = getattr(owner, name, None)
    if not callable(method):
        fail(f"{why}: {type(owner).__name__}.{name} is missing "
             f"(has {sorted(m for m in dir(owner) if not m.startswith('_'))})")
    return method


def need_any(owner, names, why):
    """A method under any of the names two extraction runs may choose."""
    for name in names:
        method = getattr(owner, name, None)
        if callable(method):
            return method
    fail(f"{why}: {type(owner).__name__} has none of {sorted(names)} "
         f"(has {sorted(m for m in dir(owner) if not m.startswith('_'))})")


def key_of(created):
    """The id a create returned, whether it came back as an int or a record."""
    return created if isinstance(created, int) else getattr(created, "id")


def missing(read):
    """True when a read reports absence as None or as a not-found error."""
    try:
        return read() is None
    except Exception as error:  # noqa: BLE001 - the error name is the contract
        return "NotFound" in type(error).__name__


def raises_not_found(call):
    try:
        call()
    except Exception as error:  # noqa: BLE001
        return "NotFound" in type(error).__name__
    return False


def ids(records):
    return sorted(record.id for record in records)


def prompt_behavior_checks(out_dir, passed):
    """Behaviors the prompt defines that the main scenario does not reach.

    A loan due exactly today is not overdue (`due_date < today`); a failed
    inventory write rolls back a return as it does a borrow; `--biography`
    is stored; IDs auto-increment.
    """
    cli_path = Path(out_dir) / "generated" / "cli.py"
    database = Path(tempfile.mkdtemp(prefix="library-behavior-",
                                     dir=out_dir)) / "behavior.sqlite3"
    cli(cli_path, database, "author", "add", "--name", "Bio Author",
        "--birth-year", "1900", "--biography", "about the author")
    cli(cli_path, database, "member", "add", "--name", "Behavior Member",
        "--email", "behavior@example.test")
    for number in (1, 2):
        cli(cli_path, database, "book", "add", "--title", f"Behavior {number}",
            "--isbn", f"BEHAVIOR-{number}", "--author-id", "1",
            "--published-year", "2000", "--copies", "2")
    cli(cli_path, database, "borrow", "--member-id", "1", "--book-id", "1")
    cli(cli_path, database, "borrow", "--member-id", "1", "--book-id", "2")
    connection = sqlite3.connect(database)
    author_table, _ = table_with(connection, {"id", "name", "biography"})
    book_table, _ = table_with(connection, {"id", "isbn", "available_copies"})
    loan_table, _ = table_with(connection, {"id", "due_date", "return_date"})
    if rows_for(connection, author_table, id=1)[0]["biography"] \
            != "about the author":
        fail("author add --biography did not store the biography")
    for table in (name for (name,) in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%'")):
        statement = connection.execute(
            "SELECT sql FROM sqlite_master WHERE name=?", (table,)).fetchone()[0]
        if "AUTOINCREMENT" not in statement.upper():
            fail(f"table {table} does not auto-increment its id: {statement!r}")
    today = dt.date.today()
    for loan, due in ((1, today), (2, today - dt.timedelta(days=1))):
        connection.execute(
            f"UPDATE {quoted(loan_table)} SET due_date=? WHERE id=?",
            (due.isoformat(), loan))
    connection.commit()
    connection.close()
    overdue = {row.get("id") for row in json_rows(
        cli(cli_path, database, "overdue").stdout)}
    if overdue != {2}:
        fail(f"only the loan due before today is overdue, not the one due "
             f"today: {sorted(overdue)}")
    passed("a loan due today is not overdue; a loan due yesterday is; "
           "--biography is stored; every table auto-increments its id")

    connection = sqlite3.connect(database)
    connection.execute(
        f"CREATE TRIGGER fail_return_copy BEFORE UPDATE OF available_copies "
        f"ON {quoted(book_table)} BEGIN SELECT RAISE(ABORT, 'injected failure'); "
        f"END")
    connection.commit()
    copies_before = rows_for(connection, book_table, id=2)[0]["available_copies"]
    connection.close()
    failed = cli(cli_path, database, "return", "--loan-id", "2", expected=1)
    connection = sqlite3.connect(database)
    connection.execute("DROP TRIGGER fail_return_copy")
    loan = rows_for(connection, loan_table, id=2)[0]
    copies_after = rows_for(connection, book_table, id=2)[0]["available_copies"]
    connection.commit()
    connection.close()
    if loan["return_date"] is not None or loan["status"] != "active" \
            or copies_after != copies_before:
        fail(f"a failed inventory write did not roll back the return: "
             f"{loan}, copies {copies_before} -> {copies_after}")
    if "injected failure" not in failed.stdout + failed.stderr:
        fail("the failed return did not report the injected failure")
    passed("a return rolls back its loan update when the inventory write fails")


def prompt_required_checks(out_dir, passed):
    """Methods the prompt names that the CLI does not reach."""
    today = dt.date.today()
    tmp = tempfile.mkdtemp(prefix="library-service-", dir=out_dir)
    deps = generated_deps(out_dir, Path(tmp) / "service.sqlite3")
    repos, services = deps["repos"], deps["services"]
    authors = repos["AuthorRepository"]
    books = repos["BookRepository"]
    members = repos["MemberRepository"]
    loans = repos["LoanRepository"]

    def create(repo, **values):
        return key_of(need(repo, "create", "repository CRUD")(**values))

    # Repository CRUD (prompt items 5-8): create, read one, read all, update,
    # delete, on every repository.
    author = create(authors, name="Crud Author", birth_year=1900)
    book = create(books, title="Crud Book", isbn="CRUD-1", published_year=2001,
                  available_copies=2, author_id=author)
    member = create(members, name="Crud Member", email="crud@example.test")
    loan = create(loans, book_id=book, member_id=member, loan_date=today,
                  due_date=today + dt.timedelta(days=14), status="active")
    for repo, key, field, value in (
            (authors, author, "name", "Crud Author Renamed"),
            (books, book, "title", "Crud Book Renamed"),
            (members, member, "name", "Crud Member Renamed"),
            (loans, loan, "status", "returned")):
        label = type(repo).__name__
        if getattr(need(repo, "read_one", label)(key), field.split()[0]) is None:
            fail(f"{label}.read_one did not return the created record")
        if key not in ids(need(repo, "read_all", label)()):
            fail(f"{label}.read_all did not list the created record")
        need(repo, "update", label)(key, **{field: value})
        if getattr(repo.read_one(key), field) != value:
            fail(f"{label}.update did not persist {field}")
    for repo, key in ((loans, loan), (members, member), (books, book),
                      (authors, author)):
        need(repo, "delete", type(repo).__name__)(key)
        if not missing(lambda repo=repo, key=key: repo.read_one(key)):
            fail(f"{type(repo).__name__}.delete did not remove the record")
    passed("prompt-required: create/read/update/delete on all four repositories")

    # Finders (prompt items 5-8) on a fresh set of rows.
    ada = create(authors, name="Finder Ada", birth_year=1815)
    bob = create(authors, name="Finder Bob", birth_year=1900)
    first = create(books, title="First", isbn="FIND-1", published_year=1843,
                   available_copies=1, author_id=ada)
    second = create(books, title="Second", isbn="FIND-2", published_year=1844,
                    available_copies=0, author_id=ada)
    third = create(books, title="Third", isbn="FIND-3", published_year=1900,
                   available_copies=1, author_id=bob)
    by_author = need(authors, "find_books_by_author", "find books by author")(ada)
    if ids(by_author) != sorted([first, second]):
        fail(f"find books by author returned {ids(by_author)}")
    in_stock = need(books, "filter_by_available_copies",
                    "filter by available copies")()
    if not {first, third} <= set(ids(in_stock)) or second in ids(in_stock):
        fail(f"filter by available copies should drop zero-copy books: "
             f"{ids(in_stock)}")
    live = create(members, name="Finder Live", email="live@example.test")
    dormant = create(members, name="Finder Dormant", email="dormant2@example.test")
    members.update(dormant, is_active=False)
    active = ids(need_any(members, ("find_active_members",
                                   "get_active_members"),
                          "find active members")())
    inactive = ids(need_any(members, ("find_inactive_members",
                                      "get_inactive_members"),
                            "find inactive members")())
    if live not in active or dormant in active or dormant not in inactive \
            or live in inactive:
        fail(f"active/inactive finders disagree: {active} / {inactive}")
    day = dt.timedelta(days=1)
    open_loan = create(loans, book_id=first, member_id=live, loan_date=today,
                       due_date=today + day, status="active")
    late_loan = create(loans, book_id=third, member_id=live,
                       loan_date=today - 20 * day, due_date=today - day,
                       status="active")
    done_loan = create(loans, book_id=third, member_id=dormant,
                       loan_date=today - 30 * day, due_date=today - 16 * day,
                       status="active")
    loans.update(done_loan, return_date=today - 10 * day, status="returned")
    now_active = ids(need(loans, "find_active_loans", "find active loans")())
    if open_loan not in now_active or done_loan in now_active:
        fail(f"find active loans should drop returned loans: {now_active}")
    overdue = ids(need(loans, "find_overdue_loans", "find overdue loans")())
    if late_loan not in overdue or open_loan in overdue or done_loan in overdue:
        fail(f"find overdue loans should keep only unreturned past-due: "
             f"{overdue}")
    history = ids(need(loans, "get_member_loan_history",
                       "member loan history")(live))
    if history != sorted([open_loan, late_loan]):
        fail(f"member loan history returned {history}")
    of_book = ids(need(loans, "get_book_loan_history",
                       "book loan history")(third))
    if of_book != sorted([late_loan, done_loan]):
        fail(f"book loan history returned {of_book}")
    passed("prompt-required: repository finders (books by author, stock, "
           "active/inactive members, active/overdue loans, member and book "
           "loan history)")

    # LibraryService.renew_membership (prompt item 9): toggles is_active.
    # The prompt names only LibraryService; an older extraction split the
    # per-entity services, so look the method up wherever it was emitted.
    renew = next((getattr(service, "renew_membership")
                  for service in services.values()
                  if hasattr(service, "renew_membership")), None)
    if renew is None:
        fail("no generated service implements renew_membership")
    renew(live)
    if members.read_one(live).is_active is not False:
        fail("renew_membership should switch an active member off")
    renew(live)
    if members.read_one(live).is_active is not True:
        fail("renew_membership should switch it back on")
    if not raises_not_found(lambda: renew(999999)):
        fail("renew_membership on an unknown member should raise a not-found "
             "error")
    passed("prompt-required: renew_membership toggles is_active and rejects "
           "an unknown member")
    deps["store"].close()


def extra_service_checks(out_dir, passed):
    """Service methods the extraction added; the prompt does not ask for them.

    LibraryService in the prompt has five methods. The generated services also
    carry update/delete/read-by-id methods per entity. They are exercised on
    the happy path, and reported as extras so a pass here is never read as a
    prompt requirement.
    """
    tmp = tempfile.mkdtemp(prefix="library-extra-", dir=out_dir)
    deps = generated_deps(out_dir, Path(tmp) / "extra.sqlite3")
    repos, services = deps["repos"], deps["services"]
    entity_services = ("AuthorService", "BookService", "MemberService",
                       "LoanService")
    if not all(name in services for name in entity_services):
        # The prompt asks for one LibraryService, not per-entity services.
        # Current extraction completes the services it was given and does
        # not invent missing classes, so this optional check has nothing to
        # exercise; count it as passed rather than requiring architecture
        # the prompt never requested.
        passed("EXTRA (not requested by the prompt): no per-entity services "
               "were invented; LibraryService is the declared surface")
        deps["store"].close()
        return
    today = dt.date.today()
    author_service = services["AuthorService"]
    book_service = services["BookService"]
    member_service = services["MemberService"]
    loan_service = services["LoanService"]
    author = key_of(repos["AuthorRepository"].create(
        name="Extra Author", birth_year=1950))
    member = key_of(repos["MemberRepository"].create(
        name="Extra Member", email="extra@example.test"))
    book = key_of(repos["BookRepository"].create(
        title="Extra Book", isbn="EXTRA-1", published_year=2000,
        available_copies=1, author_id=author))
    loan = key_of(repos["LoanRepository"].create(
        book_id=book, member_id=member, loan_date=today,
        due_date=today + dt.timedelta(days=14), status="active"))

    for service, read, update, delete, listing, key, field, value in (
            (author_service, "read_author_by_id", "update_author",
             "delete_author", "read_all_authors", author, "name", "Renamed A"),
            (book_service, "read_book_by_id", "update_book", "delete_book",
             None, book, "title", "Renamed B"),
            (member_service, "read_member_by_id", "update_member",
             "delete_member", None, member, "name", "Renamed M")):
        label = type(service).__name__
        if getattr(need(service, read, label)(key), field) is None:
            fail(f"{label}.{read} did not return the record")
        if not missing(lambda s=service, r=read: s_call(s, r, 999999)):
            fail(f"{label}.{read} on an unknown id should be None or not-found")
        if listing and key not in ids(need(service, listing, label)()):
            fail(f"{label}.{listing} did not list the record")
        need(service, update, label)(key, **{field: value})
        if getattr(getattr(service, read)(key), field) != value:
            fail(f"{label}.{update} did not persist {field}")
    if loan not in ids(need(loan_service, "read_all_loans", "LoanService")()):
        fail("LoanService.read_all_loans did not list the loan")
    if getattr(need(loan_service, "read_loan_by_id", "LoanService")(loan),
               "id") != loan:
        fail("LoanService.read_loan_by_id did not return the loan")
    if ids(need(loan_service, "get_book_loan_history", "LoanService")(book)) \
            != [loan]:
        fail("LoanService.get_book_loan_history did not return the loan")
    # Deleting a book removes its loan through the declared cascade.
    need(book_service, "delete_book", "BookService")(book)
    if not missing(lambda: book_service.read_book_by_id(book)):
        fail("BookService.delete_book did not remove the book")
    if not missing(lambda: loan_service.read_loan_by_id(loan)):
        fail("deleting the book did not cascade to its loan")
    need(member_service, "delete_member", "MemberService")(member)
    if not missing(lambda: member_service.read_member_by_id(member)):
        fail("MemberService.delete_member did not remove the member")
    need(author_service, "delete_author", "AuthorService")(author)
    if not missing(lambda: author_service.read_author_by_id(author)):
        fail("AuthorService.delete_author did not remove the author")
    passed("EXTRA (not requested by the prompt): service update, delete, "
           "read-by-id and read-all methods added by the extraction")
    deps["store"].close()


def s_call(service, name, *args):
    return getattr(service, name)(*args)


def run(out_dir):
    out_dir = Path(out_dir).resolve()
    cli_path = out_dir / "generated" / "cli.py"
    if not cli_path.is_file():
        fail(f"generated CLI is missing: {cli_path}")
    database_dir = Path(tempfile.mkdtemp(prefix="library-e2e-", dir=out_dir))
    database = database_dir / "acceptance.sqlite3"
    results = {"status": "running", "checks": [], "database": str(database)}

    def passed(name):
        results["checks"].append(name)

    # Real user-facing setup: author and member before books and loans.
    cli(cli_path, database, "author", "add", "--name", "Ada Shared",
        "--birth-year", "1815")
    cli(cli_path, database, "author", "add", "--name", "Grace Hopper",
        "--birth-year", "1906")
    cli(cli_path, database, "member", "add", "--name", "Test Member",
        "--email", "member@example.test")
    cli(cli_path, database, "book", "add", "--title", "Shared Engines",
        "--isbn", "SHARED-001", "--author-id", "1",
        "--published-year", "1843", "--copies", "1")
    cli(cli_path, database, "book", "add", "--title", "Other Design",
        "--isbn", "LIB-002", "--author-id", "2",
        "--published-year", "1950")

    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    book_table, book_columns = table_with(
        connection, {"id", "isbn", "author_id", "available_copies"})
    author_table, _ = table_with(connection, {"id", "name", "birth_year"})
    member_table, _ = table_with(connection, {"id", "email"})
    loan_table, loan_columns = table_with(
        connection, {"id", "book_id", "member_id", "loan_date", "due_date",
                     "return_date", "status"})
    books = rows_for(connection, book_table)
    if len(books) != 2:
        fail(f"expected two books after setup; found {len(books)}")
    first = next(row for row in books if row["isbn"] == "SHARED-001")
    second = next(row for row in books if row["isbn"] == "LIB-002")
    if (first["author_id"], first["available_copies"]) != (1, 1):
        fail(f"author FK or requested copy count is wrong: {first}")
    if (second["author_id"], second["available_copies"]) != (2, 1):
        fail(f"author FK or default copy count is wrong: {second}")
    if not unique_index_for(connection, book_table, "isbn"):
        fail("SQLite does not enforce unique ISBN")
    if not unique_index_for(connection, member_table, "email"):
        fail("SQLite does not enforce unique member email")
    if not foreign_key(connection, book_table, "author_id", author_table, "id"):
        fail("Book.author_id is not a cascading foreign key to Author.id")
    if not foreign_key(connection, loan_table, "book_id", book_table, "id"):
        fail("Loan.book_id is not a cascading foreign key to Book.id")
    if not foreign_key(connection, loan_table, "member_id", member_table, "id"):
        fail("Loan.member_id is not a cascading foreign key to Member.id")
    member = rows_for(connection, member_table, id=1)[0]
    if dt.date.fromisoformat(str(member["membership_date"])[:10]) != dt.date.today():
        fail(f"new member did not default membership_date to today: {member}")
    if connection.execute("PRAGMA foreign_key_check").fetchall():
        fail("SQLite reports a foreign-key violation after setup")
    connection.close()
    passed("author/member/book creation, FK wiring, uniqueness, and copy default")

    # CLI filters and search must use the author relation and boolean presence.
    by_author = json_rows(cli(cli_path, database, "book", "list", "--author",
                              "1").stdout)
    if [row.get("isbn") for row in by_author] != ["SHARED-001"]:
        fail(f"--author did not filter on Book.author_id: {by_author}")
    available = json_rows(cli(cli_path, database, "book", "list",
                              "--available-only").stdout)
    if len(available) != 2:
        fail(f"--available-only should return both available books: {available}")
    by_title_and_isbn = json_rows(cli(cli_path, database, "book", "search",
                                      "--query", "shared").stdout)
    if [row.get("isbn") for row in by_title_and_isbn] != ["SHARED-001"]:
        fail("search did not match case-insensitive title/ISBN substring once: "
             f"{by_title_and_isbn}")
    by_author_name = json_rows(cli(cli_path, database, "book", "search",
                                   "--query", "grace").stdout)
    if [row.get("isbn") for row in by_author_name] != ["LIB-002"]:
        fail(f"search did not match author name: {by_author_name}")
    # The ISBN alone must match, whatever the case: "lib-002" is in no title
    # and no author name, only in the stored ISBN "LIB-002".
    by_isbn_only = json_rows(cli(cli_path, database, "book", "search",
                                 "--query", "lib-002").stdout)
    if [row.get("isbn") for row in by_isbn_only] != ["LIB-002"]:
        fail(f"search did not match an ISBN substring in any case: "
             f"{by_isbn_only}")
    missing_isbn = json_rows(cli(cli_path, database, "book", "search",
                                 "--query", "NO-SUCH-ISBN").stdout)
    if missing_isbn:
        fail(f"an ISBN miss should be an empty result: {missing_isbn}")
    passed("author filter, boolean availability flag, and deduplicated cross-field search")

    # Duplicate constraints must fail without inserting a second row.
    duplicate_book = cli(
        cli_path, database, "book", "add", "--title", "Duplicate",
        "--isbn", "SHARED-001", "--author-id", "1",
        "--published-year", "1844", expected=1)
    duplicate_member = cli(
        cli_path, database, "member", "add", "--name", "Duplicate",
        "--email", "member@example.test", expected=1)
    if not (duplicate_book.stdout + duplicate_book.stderr):
        fail("duplicate ISBN failed without explaining the error")
    if not (duplicate_member.stdout + duplicate_member.stderr):
        fail("duplicate email failed without explaining the error")
    connection = sqlite3.connect(database)
    if len(rows_for(connection, book_table)) != 2 \
            or len(rows_for(connection, member_table)) != 1:
        fail("a rejected duplicate partially inserted a row")
    connection.close()
    passed("duplicate ISBN and email rejection")

    # `member list` without its flag must list everyone; with it, only the
    # active. The inactive member is set up in the fixture, as the aged loan
    # below is, because the requested CLI has no command to deactivate.
    cli(cli_path, database, "member", "add", "--name", "Dormant Member",
        "--email", "dormant@example.test")
    connection = sqlite3.connect(database)
    connection.execute(
        f"UPDATE {quoted(member_table)} SET is_active=0 WHERE email=?",
        ("dormant@example.test",))
    connection.commit()
    connection.close()
    everyone = json_rows(cli(cli_path, database, "member", "list").stdout)
    if {row.get("email") for row in everyone} != {
            "member@example.test", "dormant@example.test"}:
        fail(f"member list without a flag should list every member: {everyone}")
    active_members = json_rows(cli(cli_path, database, "member", "list",
                                   "--active-only").stdout)
    if [row.get("email") for row in active_members] != ["member@example.test"]:
        fail(f"member list --active-only should list only active members: "
             f"{active_members}")
    passed("member list lists everyone, and --active-only only the active")

    cli(cli_path, database, "book", "add", "--title", "Transaction Test",
        "--isbn", "LIB-003", "--author-id", "2",
        "--published-year", "2000", "--copies", "1")
    connection = sqlite3.connect(database)
    connection.execute(
        f"CREATE TRIGGER fail_book_copy_update BEFORE UPDATE OF available_copies "
        f"ON {quoted(book_table)} BEGIN SELECT RAISE(ABORT, 'injected failure'); END")
    connection.commit()
    connection.close()
    failed_borrow = cli(cli_path, database, "borrow", "--member-id", "1",
                        "--book-id", "3", expected=1)
    connection = sqlite3.connect(database)
    connection.execute("DROP TRIGGER fail_book_copy_update")
    if rows_for(connection, book_table, id=3)[0]["available_copies"] != 1 \
            or rows_for(connection, loan_table):
        fail("a failed inventory write did not roll back the new loan")
    connection.commit()
    connection.close()
    if "injected failure" not in (failed_borrow.stdout + failed_borrow.stderr):
        fail("the atomicity fixture did not reach the injected inventory failure")
    passed("borrow transaction rolls back a loan when inventory update fails")

    # Borrow the final copy; an unsuccessful second borrow cannot create a loan.
    cli(cli_path, database, "borrow", "--member-id", "1", "--book-id", "1")
    connection = sqlite3.connect(database)
    loan_rows = rows_for(connection, loan_table)
    if len(loan_rows) != 1:
        fail(f"first borrow should create one loan, found {len(loan_rows)}")
    loan = loan_rows[0]
    loan_day = dt.date.fromisoformat(str(loan["loan_date"])[:10])
    due_day = dt.date.fromisoformat(str(loan["due_date"])[:10])
    if due_day - loan_day != dt.timedelta(days=14):
        fail(f"due date is not 14 calendar days after loan date: {loan}")
    if rows_for(connection, book_table, id=1)[0]["available_copies"] != 0:
        fail("borrowing the final copy did not leave a valid zero count")
    connection.close()
    second_borrow = cli(cli_path, database, "borrow", "--member-id", "1",
                        "--book-id", "1", expected=1)
    connection = sqlite3.connect(database)
    if len(rows_for(connection, loan_table)) != 1 \
            or rows_for(connection, book_table, id=1)[0]["available_copies"] != 0:
        fail("a rejected second borrow partially changed loan or inventory")
    connection.close()
    if not (second_borrow.stdout + second_borrow.stderr):
        fail("a rejected second borrow did not report an error")
    available_after = json_rows(cli(cli_path, database, "book", "list",
                                    "--available-only").stdout)
    if {row.get("isbn") for row in available_after} != {"LIB-002", "LIB-003"}:
        fail(f"available-only included a zero-copy book: {available_after}")
    passed("14-day due date, final-copy borrow, and no partial second borrow")

    # Create a second loan through the CLI, age it in the test fixture, then
    # exercise overdue projection, late return and repeat-return protection.
    cli(cli_path, database, "borrow", "--member-id", "1", "--book-id", "2")
    connection = sqlite3.connect(database)
    overdue_id = max(row["id"] for row in rows_for(connection, loan_table))
    old_due_date = (dt.date.today() - dt.timedelta(days=1)).isoformat()
    connection.execute(
        f"UPDATE {quoted(loan_table)} SET due_date=? WHERE id=?",
        (old_due_date, overdue_id))
    connection.commit()
    stored = rows_for(connection, loan_table, id=overdue_id)[0]
    if stored["status"] != "active":
        fail(f"overdue status should be derived; persisted status was {stored['status']!r}")
    connection.close()
    overdue = json_rows(cli(cli_path, database, "overdue").stdout)
    projected = next((row for row in overdue if row.get("id") == overdue_id), None)
    if projected is None or projected.get("status") != "overdue":
        fail(f"overdue read did not derive overdue status: {overdue}")
    cli(cli_path, database, "return", "--loan-id", str(overdue_id))
    connection = sqlite3.connect(database)
    returned = rows_for(connection, loan_table, id=overdue_id)[0]
    returned_day = dt.date.fromisoformat(str(returned["return_date"])[:10])
    if returned["status"] != "returned" or returned_day != dt.date.today():
        fail(f"late return did not set today's date and returned status: {returned}")
    if rows_for(connection, book_table, id=2)[0]["available_copies"] != 1:
        fail("return did not restore exactly one copy")
    connection.close()
    repeat = cli(cli_path, database, "return", "--loan-id", str(overdue_id),
                 expected=1)
    message = repeat.stdout + repeat.stderr
    if "AlreadyReturnedLoanError" not in message:
        fail(f"repeat return did not raise AlreadyReturnedLoanError: {message!r}")
    connection = sqlite3.connect(database)
    if rows_for(connection, book_table, id=2)[0]["available_copies"] != 1:
        fail("repeat return incremented inventory a second time")
    connection.close()
    passed("derived overdue status, late return, and duplicate-return protection")

    history = json_rows(cli(cli_path, database, "member", "history",
                            "--member-id", "1").stdout)
    if sorted(row.get("id") for row in history) != sorted(
            [1, overdue_id]) or any(row.get("member_id") != 1 for row in history):
        fail(f"member history should list exactly member 1's loans: {history}")
    other = json_rows(cli(cli_path, database, "member", "history",
                          "--member-id", "2").stdout)
    if other:
        fail(f"a member with no loans should have an empty history: {other}")
    passed("member history lists that member's loans only")

    # The surface is the requested one: `return` takes `--loan-id` itself, and
    # a `return loan` subcommand repeating it is not part of the CLI.
    extra = cli(cli_path, database, "return", "loan", "--loan-id", "1",
                expected=2)
    if "No such command" not in (extra.stdout + extra.stderr) \
            and "unexpected extra argument" not in (extra.stdout + extra.stderr):
        fail("`return loan` should be rejected as an unknown form: "
             f"{extra.stdout + extra.stderr!r}")
    passed("no subcommand beyond the requested CLI surface")

    # Rejected input is reported by name and changes nothing.
    connection = sqlite3.connect(database)
    before = {table: len(rows_for(connection, table))
              for table in (author_table, book_table, member_table,
                            loan_table)}
    joined = rows_for(connection, member_table, id=1)[0]["membership_date"]
    connection.close()
    if str(joined)[:10] != dt.date.today().isoformat():
        fail(f"membership_date should default to today, got {joined!r}")
    for marker, args in (
            ("NotFound", ("book", "add", "--title", "Orphan", "--isbn",
                          "ORPHAN-1", "--author-id", "999",
                          "--published-year", "2000")),
            ("Negative", ("book", "add", "--title", "Negative", "--isbn",
                          "NEG-1", "--author-id", "1", "--published-year",
                          "2000", "--copies", "-1")),
            ("NotFound", ("borrow", "--member-id", "999", "--book-id", "2")),
            ("NotFound", ("borrow", "--member-id", "1", "--book-id", "999")),
            ("NotFound", ("return", "--loan-id", "999"))):
        refused = cli(cli_path, database, *args, expected=1)
        if marker not in refused.stdout + refused.stderr:
            fail(f"{' '.join(args)} should be refused with a {marker} error: "
                 f"{refused.stdout + refused.stderr!r}")
    if json_rows(cli(cli_path, database, "book", "list", "--author",
                     "999").stdout):
        fail("book list --author with an unknown author should be empty")
    connection = sqlite3.connect(database)
    after = {table: len(rows_for(connection, table))
             for table in (author_table, book_table, member_table,
                           loan_table)}
    connection.close()
    if after != before:
        fail(f"a rejected command changed stored rows: {before} -> {after}")
    passed("rejected input is named and changes nothing; membership_date "
           "defaults to today")

    # A new connection observes persisted state; deletion cascades through the
    # generated relation, including loans belonging to the deleted author's book.
    connection = sqlite3.connect(database)
    connection.execute("PRAGMA foreign_keys=ON")
    if len(rows_for(connection, loan_table)) != 2:
        fail("reopening SQLite did not preserve both loans")
    connection.execute(f"DELETE FROM {quoted(author_table)} WHERE id=2")
    connection.commit()
    if rows_for(connection, book_table, id=2) or rows_for(connection, loan_table, id=overdue_id):
        fail("deleting Author did not cascade to its Book and Loan")
    if connection.execute("PRAGMA foreign_key_check").fetchall():
        fail("cascade deletion left a foreign-key violation")
    connection.close()
    passed("reopened database persistence and author/book/loan cascade")

    prompt_behavior_checks(out_dir, passed)
    prompt_required_checks(out_dir, passed)
    extra_service_checks(out_dir, passed)

    results["status"] = "passed"
    results["created_at"] = dt.datetime.now().astimezone().isoformat()
    result_path = out_dir / "e2e_results.json"
    result_path.write_text(json.dumps(results, indent=2) + "\n",
                           encoding="utf-8")
    print(f"PASS: {len(results['checks'])} end-to-end checks")
    print(f"database: {database}")
    print(f"results: {result_path}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} OUT_DIR", file=sys.stderr)
        raise SystemExit(2)
    try:
        raise SystemExit(run(sys.argv[1]))
    except AssertionError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        raise SystemExit(1)
