"""Independent acceptance checks for the direct GPT-6 Luna library output.

The delivered package imports on Python 3.14 but not on Python 3.12 because
``BookRepository.list`` shadows the builtin during annotation evaluation.  Run
this suite with 3.14 to exercise the behavior; ``compat.py`` records the 3.12
import failure.
"""

from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

from common import (
    Suite, clean_error, equal, fetchall, main, raises, require, run_cli,
)


def make_service(suite: Suite, db: Path):
    suite.import_from(suite.out / "src", "library_system")
    from library_system.database import Database
    from library_system.services import LibraryService
    return LibraryService(Database(db))


def add_author(service, name="Octavia Butler", year=1947):
    from library_system.models import Author
    return service.add_author(Author(name=name, birth_year=year))


def add_book(service, author_id, title="Kindred", isbn="9780807083697",
             year=1979, copies=1):
    from library_system.models import Book
    return service.add_book(Book(title=title, isbn=isbn, author_id=author_id,
                                 published_year=year, available_copies=copies))


def add_member(service, name="Sam Reader", email="sam@example.test"):
    from library_system.models import Member
    return service.add_member(Member(name=name, email=email))


def cli(suite: Suite, db: Path, *args: str, expected: int = 0):
    return run_cli(
        suite.out,
        ["-m", "library_system", "--database", str(db), *args],
        expected=expected,
        env={"PYTHONPATH": str(suite.out / "src")},
    )


def run(suite: Suite) -> int:
    @suite.check("schema has cascades, unique ISBN/email and non-negative copies")
    def schema(_: Suite) -> str:
        db = suite.db("schema.sqlite3")
        make_service(suite, db)
        tables = {row["name"]: row["sql"] for row in fetchall(
            db, "SELECT name, sql FROM sqlite_master WHERE type='table'")}
        require({"authors", "books", "members", "loans"} <= set(tables), "missing tables")
        text = " ".join(tables.values()).upper()
        require("ON DELETE CASCADE" in text, "missing cascade")
        require("UNIQUE" in text, "missing unique constraint")
        require("AVAILABLE_COPIES >= 0" in text or "CHECK" in text, "missing copy check")
        return "cascades and unique constraints"

    @suite.check("model IDs default to None and copies default to one")
    def models(_: Suite) -> str:
        suite.import_from(suite.out / "src", "library_system")
        from library_system.models import Author, Book, Loan, Member
        require(Book(title="T", isbn="I", author_id=1, published_year=2000).id is None,
                "Book.id not optional")
        require(Book(title="T", isbn="I", author_id=1, published_year=2000).available_copies == 1,
                "Book copies default")
        require(Member(name="N", email="e@example.test").is_active is True,
                "Member active default")
        require(Member(name="N", email="e@example.test").membership_date == date.today(),
                "Member date default")
        require(Author(name="A", birth_year=1900).id is None, "Author.id not optional")
        require(Loan(book_id=1, member_id=1, loan_date=date.today(),
                     due_date=date.today()).id is None, "Loan.id not optional")
        return "typed defaults"

    @suite.check("author CRUD and books-by-author")
    def authors(_: Suite) -> str:
        db = suite.db("authors.sqlite3")
        service = make_service(suite, db)
        author = add_author(service)
        equal(service.authors.get(author.id).name, "Octavia Butler", "author get")
        book = add_book(service, author.id)
        equal([row.id for row in service.authors.find_books_by_author(author.id)],
              [book.id], "books by author")
        equal(service.authors.list()[0].name, "Octavia Butler", "author list")
        raises(Exception, lambda: service.authors.get(999), "unknown author")
        return "author repository"

    @suite.check("book CRUD, zero copies and unique ISBN")
    def books(_: Suite) -> str:
        db = suite.db("books.sqlite3")
        service = make_service(suite, db)
        author = add_author(service)
        book = add_book(service, author.id, copies=0)
        equal(book.available_copies, 0, "zero copies")
        raises(Exception, lambda: add_book(service, author.id, title="Negative",
                                           isbn="NEG", copies=-1), "negative copies")
        raises(Exception, lambda: add_book(service, author.id, title="Duplicate",
                                           isbn=book.isbn), "duplicate ISBN")
        book.title = "Updated"
        updated = service.books.update(book)
        equal(updated.title, "Updated", "book update")
        service.books.delete(book.id)
        raises(Exception, lambda: service.books.get(book.id), "deleted book")
        return "book CRUD"

    @suite.check("member defaults, unique email and active/inactive lists")
    def members(_: Suite) -> str:
        db = suite.db("members.sqlite3")
        service = make_service(suite, db)
        member = add_member(service)
        equal((member.is_active, member.membership_date), (True, date.today()),
              "member defaults")
        raises(Exception, lambda: add_member(service, email=member.email), "duplicate email")
        service.members.update(member.__class__(id=member.id, name=member.name,
                                                email=member.email,
                                                membership_date=member.membership_date,
                                                is_active=False))
        equal([row.id for row in service.members.list(active_only=True)], [], "active list")
        equal([row.id for row in service.members.list(inactive_only=True)], [member.id],
              "inactive list")
        return "member CRUD and filters"

    @suite.check("borrowing decrements one copy and sets a 14-day due date")
    def borrow(_: Suite) -> str:
        db = suite.db("borrow.sqlite3")
        service = make_service(suite, db)
        author = add_author(service)
        book = add_book(service, author.id, copies=2)
        member = add_member(service)
        loan = service.borrow_book(member.id, book.id)
        equal(loan.due_date, loan.loan_date + timedelta(days=14), "due date")
        equal(service.books.get(book.id).available_copies, 1, "decrement")
        service.borrow_book(member.id, book.id)
        equal(service.books.get(book.id).available_copies, 0, "final copy")
        raises(Exception, lambda: service.borrow_book(member.id, book.id),
               "no available copy")
        return "borrow and zero inventory"

    @suite.check("inactive members cannot borrow")
    def inactive_member(_: Suite) -> str:
        db = suite.db("inactive.sqlite3")
        service = make_service(suite, db)
        author = add_author(service)
        book = add_book(service, author.id)
        member = add_member(service)
        service.renew_membership(member.id)
        raises(Exception, lambda: service.borrow_book(member.id, book.id),
               "inactive borrow")
        service.renew_membership(member.id)
        service.borrow_book(member.id, book.id)
        return "membership toggle"

    @suite.check("return restores one copy and rejects a second return")
    def returns(_: Suite) -> str:
        db = suite.db("return.sqlite3")
        service = make_service(suite, db)
        author = add_author(service)
        book = add_book(service, author.id)
        member = add_member(service)
        loan = service.borrow_book(member.id, book.id)
        returned = service.return_book(loan.id)
        equal((returned.return_date, returned.status), (date.today(), "returned"),
              "return fields")
        equal(service.books.get(book.id).available_copies, 1, "restored copy")
        raises(Exception, lambda: service.return_book(loan.id), "second return")
        equal(service.books.get(book.id).available_copies, 1, "no extra copy")
        return "return semantics"

    @suite.check("overdue is derived and leaves stored status active")
    def overdue(_: Suite) -> str:
        db = suite.db("overdue.sqlite3")
        service = make_service(suite, db)
        author = add_author(service)
        book = add_book(service, author.id)
        member = add_member(service)
        loan = service.borrow_book(member.id, book.id)
        service.database.connection.execute(
            "UPDATE loans SET due_date=? WHERE id=?",
            ((date.today() - timedelta(days=1)).isoformat(), loan.id),
        )
        overdue = service.get_overdue_loans()
        equal([row.id for row in overdue], [loan.id], "overdue list")
        equal(overdue[0].status, "overdue", "derived status")
        equal(service.loans.get(loan.id).status, "active", "stored status")
        service.return_book(loan.id)
        equal(service.books.get(book.id).available_copies, 1, "late return")
        return "derived overdue"

    @suite.check("search covers title, author and ISBN without duplicates")
    def search(_: Suite) -> str:
        db = suite.db("search.sqlite3")
        service = make_service(suite, db)
        author = add_author(service, name="Ursula Le Guin")
        first = add_book(service, author.id, title="A Wizard of Earthsea",
                         isbn="9780547773742")
        add_book(service, author.id, title="The Dispossessed", isbn="9780060512750")
        equal([row.id for row in service.search_books("EARTHSEA")], [first.id],
              "title search")
        equal([row.id for row in service.search_books("le guin")],
              [first.id, first.id + 1], "author search")
        equal([row.id for row in service.search_books("080708")], [], "ISBN miss")
        equal([row.id for row in service.search_books("054777")], [first.id],
              "ISBN hit")
        return "case-insensitive search"

    @suite.check("book list filters by author and availability")
    def list_filters(_: Suite) -> str:
        db = suite.db("list.sqlite3")
        service = make_service(suite, db)
        author = add_author(service)
        first = add_book(service, author.id, title="A", isbn="A")
        second = add_book(service, author.id, title="B", isbn="B")
        other_author = add_author(service, name="Other", year=1950)
        third = add_book(service, other_author.id, title="C", isbn="C")
        service.books.set_available_copies(second.id, 0)
        service.books.set_available_copies(third.id, 0)
        equal([row.id for row in service.books.list(author_id=author.id)],
              [first.id, second.id], "author filter")
        equal([row.id for row in service.books.list(available_only=True)],
              [first.id], "availability filter")
        return "book filters"

    @suite.check("borrow rolls back when inventory write fails")
    def borrow_rollback(_: Suite) -> str:
        db = suite.db("borrow-rollback.sqlite3")
        service = make_service(suite, db)
        author = add_author(service)
        book = add_book(service, author.id)
        member = add_member(service)
        with mock.patch.object(service.books, "adjust_available_copies",
                               side_effect=RuntimeError("write failed")):
            raises(RuntimeError, lambda: service.borrow_book(member.id, book.id),
                   "borrow failure")
        equal(service.books.get(book.id).available_copies, 1, "copy unchanged")
        equal(service.loans.list(), [], "no loan")
        return "borrow transaction"

    @suite.check("return rolls back when inventory write fails")
    def return_rollback(_: Suite) -> str:
        db = suite.db("return-rollback.sqlite3")
        service = make_service(suite, db)
        author = add_author(service)
        book = add_book(service, author.id)
        member = add_member(service)
        loan = service.borrow_book(member.id, book.id)
        with mock.patch.object(service.books, "adjust_available_copies",
                               side_effect=RuntimeError("write failed")):
            raises(RuntimeError, lambda: service.return_book(loan.id), "return failure")
        equal(service.books.get(book.id).available_copies, 0, "copy unchanged")
        equal(service.loans.get(loan.id).status, "active", "status unchanged")
        return "return transaction"

    @suite.check("author deletion cascades to books and loans")
    def cascade(_: Suite) -> str:
        db = suite.db("cascade.sqlite3")
        service = make_service(suite, db)
        author = add_author(service)
        book = add_book(service, author.id)
        member = add_member(service)
        service.borrow_book(member.id, book.id)
        service.authors.delete(author.id)
        equal(service.books.list(), [], "books deleted")
        equal(service.loans.list(), [], "loans deleted")
        return "cascade"

    @suite.check("data persists across Database instances")
    def persistence(_: Suite) -> str:
        db = suite.db("persist.sqlite3")
        service = make_service(suite, db)
        author = add_author(service)
        book = add_book(service, author.id)
        add_member(service)
        service.borrow_book(1, book.id)
        service2 = make_service(suite, db)
        equal(service2.books.get(book.id).available_copies, 0, "persisted stock")
        equal(len(service2.loans.list()), 1, "persisted loan")
        return "SQLite persistence"

    @suite.check("CLI runs the requested lifecycle")
    def cli_lifecycle(_: Suite) -> str:
        db = suite.db("cli.sqlite3")
        author = cli(suite, db, "author", "add", "--name", "N. K. Jemisin",
                     "--birth-year", "1972")
        require("Added author 1" in author.stdout, f"author CLI: {author.stdout!r}")
        book = cli(suite, db, "book", "add", "--title", "The Fifth Season",
                   "--isbn", "9780316229296", "--author-id", "1",
                   "--published-year", "2015")
        require("Added book 1" in book.stdout, f"book CLI: {book.stdout!r}")
        member = cli(suite, db, "member", "add", "--name", "Reader",
                     "--email", "r@example.test")
        require("Added member 1" in member.stdout, f"member CLI: {member.stdout!r}")
        borrowed = cli(suite, db, "borrow", "--member-id", "1", "--book-id", "1")
        require("Created loan" in borrowed.stdout, f"borrow CLI: {borrowed.stdout!r}")
        history = cli(suite, db, "member", "history", "--member-id", "1")
        require("book 1" in history.stdout, f"history CLI: {history.stdout!r}")
        returned = cli(suite, db, "return", "--loan-id", "1")
        require("Returned" in returned.stdout, f"return CLI: {returned.stdout!r}")
        overdue = cli(suite, db, "overdue")
        require("No overdue loans" in overdue.stdout, f"overdue CLI: {overdue.stdout!r}")
        return "CLI lifecycle"

    @suite.check("CLI validation errors are clean")
    def cli_errors(_: Suite) -> str:
        db = suite.db("cli-error.sqlite3")
        result = cli(suite, db, "borrow", "--member-id", "99", "--book-id", "99",
                     expected=1)
        clean_error(result, "missing loan member/book")
        return "clean click error"

    @suite.check("member history and book history expose persisted loans")
    def histories(_: Suite) -> str:
        db = suite.db("history.sqlite3")
        service = make_service(suite, db)
        author = add_author(service)
        book = add_book(service, author.id)
        member = add_member(service)
        loan = service.borrow_book(member.id, book.id)
        equal([row.id for row in service.loans.find_member_history(member.id)], [loan.id],
              "member history")
        equal([row.id for row in service.loans.find_book_history(book.id)], [loan.id],
              "book history")
        equal([row.id for row in service.loans.find_active_loans()], [loan.id],
              "active loans")
        return "loan histories"

    return suite.run()


if __name__ == "__main__":
    raise SystemExit(main("library", sys.argv[1] if len(sys.argv) > 1 else None, run))
