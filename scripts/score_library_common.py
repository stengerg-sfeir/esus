#!/usr/bin/env python3
"""Common, prompt-derived behavior score for the ESUS and GPT-6 libraries.

Both apps use different module layouts and output formats. This evaluator uses
their CLI for creation and database inspection, plus a small adapter for the
service/repository methods that have no CLI command.
"""

import ast
import os
import sqlite3
import subprocess
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
import e2e_library_acceptance as lib  # noqa: E402

PY = sys.executable
ESUS = ROOT / "out" / "library_correct"
GPT = Path("/var/folders/kk/xjh_78x515g6lld88l0c_q2m0000gp/T/esus-library-gpt-raw")


def q(name):
    return lib.quoted(name)


def table_map(db):
    connection = sqlite3.connect(db)
    try:
        return {
            "author": lib.table_with(connection, {"id", "name", "birth_year"})[0],
            "book": lib.table_with(connection, {"id", "isbn", "available_copies"})[0],
            "member": lib.table_with(connection, {"id", "email", "is_active"})[0],
            "loan": lib.table_with(connection, {"id", "due_date", "return_date"})[0],
        }
    finally:
        connection.close()


class EsusAdapter:
    def __init__(self, database):
        deps = lib.generated_deps(ESUS, database)
        self.deps = deps
        self.repos = deps["repos"]
        self.services = deps["services"]
        self.db = Path(database)
        self.source = ESUS / "generated"
        self.kind = "esus"

    def close(self):
        self.deps["store"].close()

    def create_author(self, name, birth_year, biography=""):
        return lib.key_of(self.repos["AuthorRepository"].create(
            name=name, birth_year=birth_year, biography=biography))

    def create_book(self, title, isbn, author_id, published_year=2000,
                    available_copies=1):
        return lib.key_of(self.repos["BookRepository"].create(
            title=title, isbn=isbn, author_id=author_id,
            published_year=published_year, available_copies=available_copies))

    def create_member(self, name, email):
        return lib.key_of(self.repos["MemberRepository"].create(
            name=name, email=email))

    def create_loan(self, book_id, member_id, loan_date, due_date,
                    status="active"):
        return lib.key_of(self.repos["LoanRepository"].create(
            book_id=book_id, member_id=member_id, loan_date=loan_date,
            due_date=due_date, status=status))

    def get_author(self, key):
        return self.repos["AuthorRepository"].read_one(key)

    def get_book(self, key):
        return self.repos["BookRepository"].read_one(key)

    def get_member(self, key):
        return self.repos["MemberRepository"].read_one(key)

    def get_loan(self, key):
        return self.repos["LoanRepository"].read_one(key)

    def list_books(self):
        return self.repos["BookRepository"].read_all()

    def list_loans(self):
        return self.repos["LoanRepository"].read_all()

    def search(self, query):
        return self.services["BookService"].search_books(query)

    def books_by_author(self, key):
        return self.repos["AuthorRepository"].find_books_by_author(key)

    def available_books(self):
        return self.repos["BookRepository"].filter_by_available_copies()

    def active_members(self):
        return self.repos["MemberRepository"].get_active_members()

    def inactive_members(self):
        return self.repos["MemberRepository"].get_inactive_members()

    def active_loans(self):
        return self.repos["LoanRepository"].find_active_loans()

    def overdue_loans(self):
        return self.services["LoanService"].get_overdue_loans()

    def member_history(self, key):
        return self.services["LoanService"].get_member_loan_history(key)

    def book_history(self, key):
        return self.services["LoanService"].get_book_loan_history(key)

    def renew(self, key):
        return self.services["MemberService"].renew_membership(key)

    def borrow(self, member_id, book_id):
        self.services["LoanService"].create_loan(member_id, book_id)
        return self.list_loans()[-1]

    def return_loan(self, key):
        return self.services["LoanService"].return_loan(key)

    def update(self, repo, key, **fields):
        self.repos[repo].update(key, **fields)

    def set_due(self, key, due):
        self.deps["store"].update("Loan", "id", key, {"due_date": due})

    def delete(self, repo, key):
        self.repos[repo].delete(key)

    def cli(self, db, *args):
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        return subprocess.run(
            [PY, str(ESUS / "generated" / "cli.py"), "--db", str(db), *args],
            capture_output=True, text=True, env=env)


class GptAdapter:
    def __init__(self, database):
        sys.path.insert(0, str(GPT))
        from library_system.database import Database
        from library_system.models import Author, Book, Loan, Member
        from library_system.service import LibraryService
        self.models = dict(Author=Author, Book=Book, Loan=Loan, Member=Member)
        self.db_obj = Database(database)
        self.service = LibraryService(self.db_obj)
        self.db = Path(database)
        self.source = GPT / "library_system"
        self.kind = "gpt"

    def close(self):
        pass

    def create_author(self, name, birth_year, biography=""):
        return self.service.add_author(self.models["Author"](
            name=name, birth_year=birth_year, biography=biography)).id

    def create_book(self, title, isbn, author_id, published_year=2000,
                    available_copies=1):
        return self.service.add_book(self.models["Book"](
            title=title, isbn=isbn, author_id=author_id,
            published_year=published_year,
            available_copies=available_copies)).id

    def create_member(self, name, email):
        return self.service.add_member(self.models["Member"](
            name=name, email=email)).id

    def create_loan(self, book_id, member_id, loan_date, due_date,
                    status="active"):
        return self.service.loans.create(self.models["Loan"](
            book_id=book_id, member_id=member_id, loan_date=loan_date,
            due_date=due_date, status=status)).id

    def get_author(self, key):
        return self.service.authors.get(key)

    def get_book(self, key):
        return self.service.books.get(key)

    def get_member(self, key):
        return self.service.members.get(key)

    def get_loan(self, key):
        return self.service.loans.get(key)

    def list_books(self):
        return self.service.books.list_all()

    def list_loans(self):
        return self.service.loans.list_all()

    def search(self, query):
        return self.service.search_books(query)

    def books_by_author(self, key):
        return self.service.authors.find_books_by_author(key)

    def available_books(self):
        return self.service.books.list_all(available_only=True)

    def active_members(self):
        return self.service.members.find_active_members()

    def inactive_members(self):
        return self.service.members.find_inactive_members()

    def active_loans(self):
        return self.service.loans.find_active_loans()

    def overdue_loans(self):
        return self.service.get_overdue_loans()

    def member_history(self, key):
        return self.service.loans.find_member_loan_history(key)

    def book_history(self, key):
        return self.service.loans.find_book_loan_history(key)

    def renew(self, key):
        return self.service.renew_membership(key)

    def borrow(self, member_id, book_id):
        return self.service.borrow_book(member_id, book_id)

    def return_loan(self, key):
        return self.service.return_book(key)

    def update(self, repo, key, **fields):
        entity = self._entity(repo)
        record = getattr(self.service, repo).get(key)
        for name, value in fields.items():
            setattr(record, name, value)
        getattr(self.service, repo).update(record)

    def set_due(self, key, due):
        record = self.service.loans.get(key)
        record.due_date = due
        self.service.loans.update(record)

    def delete(self, repo, key):
        getattr(self.service, repo).delete(key)

    @staticmethod
    def _entity(repo):
        return {"authors": "author", "books": "book", "members": "member",
                "loans": "loan"}[repo]

    def cli(self, db, *args):
        env = dict(os.environ, PYTHONPATH=str(GPT),
                   PYTHONDONTWRITEBYTECODE="1")
        return subprocess.run(
            [PY, "-m", "library_system", "--db", str(db), *args],
            capture_output=True, text=True, env=env)


def source_text(adapter):
    return "\n".join(p.read_text(encoding="utf-8")
                     for p in adapter.source.glob("*.py"))


def type_hint_missing(adapter):
    missing = 0
    for path in adapter.source.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if node.returns is None:
                missing += 1
            for arg in (*node.args.posonlyargs, *node.args.args,
                        *node.args.kwonlyargs):
                if arg.arg not in ("self", "cls") and arg.annotation is None:
                    missing += 1
    return missing


def check_models_errors(adapter):
    text = source_text(adapter)
    for name in ("AlreadyReturnedLoanError",):
        if name not in text:
            raise AssertionError(f"missing error class {name}")
    if "class Book" not in text or "class Loan" not in text:
        raise AssertionError("missing Book/Loan model")


def check_type_hints(adapter):
    missing = type_hint_missing(adapter)
    if missing:
        raise AssertionError(f"{missing} unannotated parameters/returns")


def check_schema_defaults(adapter):
    tables = table_map(adapter.db)
    connection = sqlite3.connect(adapter.db)
    try:
        for table in tables.values():
            sql = connection.execute(
                "SELECT sql FROM sqlite_master WHERE name=?", (table,)).fetchone()[0]
            if "AUTOINCREMENT" not in sql.upper():
                raise AssertionError(f"{table} does not autoincrement")
        if not lib.unique_index_for(connection, tables["book"], "isbn"):
            raise AssertionError("ISBN is not unique")
        if not lib.unique_index_for(connection, tables["member"], "email"):
            raise AssertionError("email is not unique")
        if not lib.foreign_key(connection, tables["book"], "author_id",
                               tables["author"], "id"):
            raise AssertionError("book author FK is not cascade")
        if not lib.foreign_key(connection, tables["loan"], "book_id",
                               tables["book"], "id"):
            raise AssertionError("loan book FK is not cascade")
    finally:
        connection.close()
    author = adapter.create_author("Defaults", 1900)
    book = adapter.create_book("Default Copies", "D-1", author)
    member = adapter.create_member("Default Member", "default@example.test")
    if adapter.get_book(book).available_copies != 1:
        raise AssertionError("available_copies default is not 1")
    record = adapter.get_member(member)
    if record.membership_date != date.today() or not record.is_active:
        raise AssertionError("member defaults are wrong")
    if adapter.get_author(author).id != author or adapter.get_book(book).id != book:
        raise AssertionError("IDs are not assigned")


def check_repository_crud(adapter):
    author = adapter.create_author("CRUD Author", 1900)
    book = adapter.create_book("CRUD Book", "CRUD-1", author, 2001, 2)
    member = adapter.create_member("CRUD Member", "crud@example.test")
    loan = adapter.create_loan(book, member, date.today(),
                               date.today() + timedelta(days=14))
    if adapter.get_author(author).name != "CRUD Author":
        raise AssertionError("author read failed")
    adapter.update("AuthorRepository" if adapter.kind == "esus" else "authors",
                   author, name="Renamed Author")
    if adapter.get_author(author).name != "Renamed Author":
        raise AssertionError("author update failed")
    adapter.update("BookRepository" if adapter.kind == "esus" else "books",
                   book, title="Renamed Book")
    if adapter.get_book(book).title != "Renamed Book":
        raise AssertionError("book update failed")
    adapter.update("MemberRepository" if adapter.kind == "esus" else "members",
                   member, name="Renamed Member")
    if adapter.get_member(member).name != "Renamed Member":
        raise AssertionError("member update failed")
    adapter.update("LoanRepository" if adapter.kind == "esus" else "loans",
                   loan, status="returned")
    if adapter.get_loan(loan).status != "returned":
        raise AssertionError("loan update failed")
    for repo, key in (("LoanRepository" if adapter.kind == "esus" else "loans", loan),
                      ("MemberRepository" if adapter.kind == "esus" else "members", member),
                      ("BookRepository" if adapter.kind == "esus" else "books", book),
                      ("AuthorRepository" if adapter.kind == "esus" else "authors", author)):
        adapter.delete(repo, key)
    # Read-after-delete either returns None or raises a not-found error.
    try:
        adapter.get_author(author)
    except Exception:
        pass


def check_search_and_filters(adapter):
    ada = adapter.create_author("Ada Lovelace", 1815)
    bob = adapter.create_author("Bob Writer", 1900)
    first = adapter.create_book("First Book", "FIND-1", ada, 1843, 1)
    zero = adapter.create_book("Zero Book", "FIND-2", ada, 1844, 0)
    third = adapter.create_book("Third Book", "FIND-3", bob, 1900, 1)
    if [b.id for b in adapter.search("LOVELACE")] != [first, zero]:
        raise AssertionError("author search failed")
    if [b.id for b in adapter.search("find-1")] != [first]:
        raise AssertionError("ISBN search failed")
    if adapter.search("missing-isbn"):
        raise AssertionError("empty search should be empty")
    if sorted(b.id for b in adapter.books_by_author(ada)) != [first, zero]:
        raise AssertionError("books by author failed")
    if sorted(b.id for b in adapter.available_books()) != [first, third]:
        raise AssertionError("available filter failed")
    live = adapter.create_member("Live", "live@example.test")
    dormant = adapter.create_member("Dormant", "dormant@example.test")
    adapter.update("MemberRepository" if adapter.kind == "esus" else "members",
                   dormant, is_active=False)
    if live not in [m.id for m in adapter.active_members()] \
            or dormant in [m.id for m in adapter.active_members()]:
        raise AssertionError("active members filter failed")
    if dormant not in [m.id for m in adapter.inactive_members()]:
        raise AssertionError("inactive members filter failed")


def check_borrow_return_overdue(adapter):
    author = adapter.create_author("Borrow Author", 1900)
    book = adapter.create_book("Borrow Book", "BORROW-1", author, 2000, 1)
    member = adapter.create_member("Borrow Member", "borrow@example.test")
    loan = adapter.borrow(member, book)
    if loan.due_date != loan.loan_date + timedelta(days=14):
        raise AssertionError("due date is not 14 days after loan date")
    if adapter.get_book(book).available_copies != 0:
        raise AssertionError("final copy was not decremented")
    if loan.id in [x.id for x in adapter.overdue_loans()]:
        raise AssertionError("a fresh loan is overdue")
    # Make it overdue in storage and check derivation.
    adapter.set_due(loan.id, date.today() - timedelta(days=1))
    if loan.id not in [x.id for x in adapter.overdue_loans()]:
        raise AssertionError("past-due loan is not overdue")
    tables = table_map(adapter.db)
    connection = sqlite3.connect(adapter.db)
    try:
        raw_status = connection.execute(
            f"SELECT status FROM {q(tables['loan'])} WHERE id=?",
            (loan.id,)).fetchone()[0]
    finally:
        connection.close()
    if str(raw_status).lower() != "active":
        raise AssertionError(f"stored status is {raw_status!r}, expected active")
    returned = adapter.return_loan(loan.id)
    if adapter.get_book(book).available_copies != 1:
        raise AssertionError("return did not restore the copy")
    record = adapter.get_loan(loan.id)
    if record.return_date is None or record.status != "returned":
        raise AssertionError("return did not set return_date/status")
    try:
        adapter.return_loan(loan.id)
        raise AssertionError("double return was accepted")
    except Exception as error:
        if "already" not in str(error).lower() and \
                "returned" not in type(error).__name__.lower():
            raise


def check_rollback(adapter):
    author = adapter.create_author("Rollback Author", 1900)
    book = adapter.create_book("Rollback Book", "ROLL-1", author, 2000, 1)
    member = adapter.create_member("Rollback Member", "rollback@example.test")
    target = (adapter.repos["BookRepository"] if adapter.kind == "esus"
              else adapter.service.books)
    with mock.patch.object(target, "update", side_effect=RuntimeError("inventory failed")):
        try:
            adapter.borrow(member, book)
            raise AssertionError("borrow did not fail")
        except RuntimeError:
            pass
    if adapter.get_book(book).available_copies != 1 or adapter.list_loans():
        raise AssertionError("failed borrow left partial writes")
    loan = adapter.borrow(member, book)
    with mock.patch.object(target, "update", side_effect=RuntimeError("inventory failed")):
        try:
            adapter.return_loan(loan.id)
            raise AssertionError("return did not fail")
        except RuntimeError:
            pass
    record = adapter.get_loan(loan.id)
    if record.return_date is not None or record.status != "active" \
            or adapter.get_book(book).available_copies != 0:
        raise AssertionError("failed return left partial writes")


def check_renew_history(adapter):
    author = adapter.create_author("History Author", 1900)
    book = adapter.create_book("History Book", "HIST-1", author)
    member = adapter.create_member("History Member", "history@example.test")
    loan = adapter.create_loan(book, member, date.today(),
                               date.today() + timedelta(days=14))
    adapter.renew(member)
    if adapter.get_member(member).is_active:
        raise AssertionError("renew did not toggle active off")
    adapter.renew(member)
    if not adapter.get_member(member).is_active:
        raise AssertionError("renew did not toggle active on")
    if loan not in [x.id for x in adapter.member_history(member)]:
        raise AssertionError("member history missing loan")
    if loan not in [x.id for x in adapter.book_history(book)]:
        raise AssertionError("book history missing loan")
    try:
        adapter.renew(999999)
        raise AssertionError("renew on missing member accepted")
    except Exception:
        pass


def check_cascade(adapter):
    author = adapter.create_author("Cascade Author", 1900)
    book = adapter.create_book("Cascade Book", "CASCADE-1", author)
    member = adapter.create_member("Cascade Member", "cascade@example.test")
    loan = adapter.create_loan(book, member, date.today(),
                               date.today() + timedelta(days=14))
    adapter.delete("AuthorRepository" if adapter.kind == "esus" else "authors",
                   author)
    for label, lookup in (("book", lambda: adapter.get_book(book)),
                          ("loan", lambda: adapter.get_loan(loan))):
        try:
            found = lookup()
        except Exception:
            continue
        if found is not None:
            raise AssertionError(f"author delete did not cascade to {label}")


def check_cli(adapter):
    directory = Path(tempfile.mkdtemp(prefix=f"cli-{adapter.kind}-"))
    db = directory / "cli.sqlite3"
    calls = [
        ["author", "add", "--name", "CLI Author", "--birth-year", "1950"],
        ["book", "add", "--title", "CLI Book", "--isbn", "CLI-1",
         "--author-id", "1", "--published-year", "2000", "--copies", "1"],
        ["member", "add", "--name", "CLI Member", "--email", "cli@example.test"],
        ["book", "list"],
        ["book", "list", "--available-only"],
        ["book", "search", "--query", "CLI"],
        ["member", "list", "--active-only"],
        ["borrow", "--member-id", "1", "--book-id", "1"],
        ["member", "history", "--member-id", "1"],
        ["overdue"],
        ["return", "--loan-id", "1"],
    ]
    for args in calls:
        result = adapter.cli(db, *args)
        if result.returncode != 0:
            raise AssertionError(
                f"CLI {args!r} failed: {result.stdout!r} {result.stderr!r}")
    tables = table_map(db)
    connection = sqlite3.connect(db)
    try:
        if connection.execute(f"SELECT count(*) FROM {q(tables['book'])}").fetchone()[0] != 1:
            raise AssertionError("CLI did not create the book")
        loan = connection.execute(
            f"SELECT return_date FROM {q(tables['loan'])} WHERE id=1").fetchone()[0]
        if loan is None:
            raise AssertionError("CLI return did not set return_date")
    finally:
        connection.close()


CHECKS = (
    ("models and errors", check_models_errors),
    ("type hints", check_type_hints),
    ("schema and defaults", check_schema_defaults),
    ("repository CRUD", check_repository_crud),
    ("search and filters", check_search_and_filters),
    ("borrow/return/overdue", check_borrow_return_overdue),
    ("transaction rollback", check_rollback),
    ("renew and history", check_renew_history),
    ("cascade deletes", check_cascade),
    ("CLI surface", check_cli),
)


def score(adapter_class, label):
    results = []
    for name, check in CHECKS:
        directory = Path(tempfile.mkdtemp(prefix=f"score-{label}-"))
        adapter = adapter_class(directory / "db.sqlite3")
        try:
            check(adapter)
        except Exception as error:  # noqa: BLE001
            results.append((name, False, str(error)[:300]))
        else:
            results.append((name, True, ""))
        finally:
            adapter.close()
    return results


def main():
    print("ESUS library")
    esus_results = score(EsusAdapter, "esus")
    print("GPT-6 library")
    gpt_results = score(GptAdapter, "gpt")
    for label, results in (("ESUS", esus_results), ("GPT-6", gpt_results)):
        print(f"\n=== {label}: {sum(1 for _, ok, _ in results if ok)}/{len(results)}")
        for name, ok, why in results:
            print(f"{'PASS' if ok else 'FAIL'}  {name}")
            if why:
                print(f"      {why}")


if __name__ == "__main__":
    main()
