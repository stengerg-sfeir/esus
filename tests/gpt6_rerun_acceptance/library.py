"""Acceptance checks for the 2026-11-13 GPT-6 Luna library output."""

from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from unittest import mock

from common import Suite, equal, fetchall, main, raises, require, run_python


def make_env(suite: Suite, name: str):
    suite.import_from(suite.out, "library_system")
    from library_system import (
        AuthorRepository, BookRepository, Database, LoanRepository,
        LibraryService, MemberRepository,
    )
    db = suite.db(name)
    database = Database(db)
    authors = AuthorRepository(database)
    books = BookRepository(database)
    members = MemberRepository(database)
    loans = LoanRepository(database)
    service = LibraryService(books, authors, members, loans)
    return database, authors, books, members, loans, service


def add_author(authors, name="Octavia Butler", year=1947):
    from library_system import Author
    return authors.create(Author(name=name, birth_year=year))


def add_book(books, author_id, title="Kindred", isbn="9780807083697", year=1979, copies=1):
    from library_system import Book
    return books.create(Book(title=title, isbn=isbn, author_id=author_id,
                             published_year=year, available_copies=copies))


def add_member(members, name="Sam Reader", email="sam@example.test"):
    from library_system import Member
    return members.create(Member(name=name, email=email))


def run(suite: Suite) -> int:
    @suite.check("schema has cascades, unique ISBN/email and copy checks")
    def schema(_: Suite) -> str:
        db = suite.db("schema.sqlite3")
        database, *_ = make_env(suite, "schema.sqlite3")
        database.close()
        tables = {row["name"]: row["sql"] for row in fetchall(
            db, "SELECT name, sql FROM sqlite_master WHERE type='table'")}
        require({"authors", "books", "members", "loans"} <= set(tables), "tables")
        text = " ".join(tables.values()).upper()
        require("ON DELETE CASCADE" in text, "cascade")
        require("UNIQUE" in text, "unique")
        require("AVAILABLE_COPIES >= 0" in text or "CHECK" in text, "copy check")
        return "cascades and checks"

    @suite.check("models default IDs to None and set copy/member defaults")
    def models(_: Suite) -> str:
        suite.import_from(suite.out, "library_system")
        from library_system import Author, Book, Loan, Member
        require(Book(title="T", isbn="I", author_id=1, published_year=2000).id is None, "Book.id")
        require(Book(title="T", isbn="I", author_id=1, published_year=2000).available_copies == 1,
                "copy default")
        require(Member(name="N", email="e@example.test").is_active is True, "active default")
        require(Member(name="N", email="e@example.test").membership_date == date.today(),
                "date default")
        require(Author(name="A", birth_year=1900).id is None, "Author.id")
        require(Loan(book_id=1, member_id=1, loan_date=date.today(),
                     due_date=date.today()).id is None, "Loan.id")
        return "typed defaults"

    @suite.check("author CRUD and books-by-author")
    def authors(_: Suite) -> str:
        database, author_repo, books, _, _, _ = make_env(suite, "authors.sqlite3")
        try:
            author = add_author(author_repo)
            equal(author_repo.get_by_id(author.id).name, "Octavia Butler", "get")
            book = add_book(books, author.id)
            equal([row.id for row in author_repo.find_books_by_author(author.id)], [book.id], "books")
            equal(author_repo.list_all()[0].name, "Octavia Butler", "list")
            require(author_repo.get_by_id(999) is None, "unknown author should be None")
            return "author repository"
        finally:
            database.close()

    @suite.check("book CRUD, zero copies and unique ISBN")
    def books(_: Suite) -> str:
        database, authors, book_repo, _, _, _ = make_env(suite, "books.sqlite3")
        try:
            author = add_author(authors)
            book = add_book(book_repo, author.id, copies=0)
            equal(book.available_copies, 0, "zero copies")
            raises(Exception, lambda: add_book(book_repo, author.id, title="Negative",
                                               isbn="NEG", copies=-1), "negative copies")
            raises(Exception, lambda: add_book(book_repo, author.id, title="Duplicate",
                                               isbn=book.isbn), "duplicate ISBN")
            book.title = "Updated"
            equal(book_repo.update(book).title, "Updated", "update")
            book_repo.delete(book.id)
            require(book_repo.get_by_id(book.id) is None, "deleted book still readable")
            return "book CRUD"
        finally:
            database.close()

    @suite.check("member defaults, unique email and active/inactive lists")
    def members(_: Suite) -> str:
        database, _, _, member_repo, _, _ = make_env(suite, "members.sqlite3")
        try:
            member = add_member(member_repo)
            equal(member.is_active, True, "active")
            equal(member.membership_date, date.today(), "date")
            raises(Exception, lambda: add_member(member_repo, email=member.email),
                   "duplicate email")
            equal([row.id for row in member_repo.find_active()], [member.id], "active list")
            member_repo.set_active(member.id, False)
            equal([row.id for row in member_repo.find_inactive()], [member.id], "inactive list")
            return "member repository"
        finally:
            database.close()

    @suite.check("borrow and return adjust copies and set due date")
    def borrow_return(_: Suite) -> str:
        database, authors, books, members, _, service = make_env(suite, "borrow.sqlite3")
        try:
            author = add_author(authors)
            book = add_book(books, author.id, copies=1)
            member = add_member(members)
            loan_date = date(2025, 1, 1)
            loan = service.borrow_book(member.id, book.id, loan_date)
            equal(loan.due_date, loan_date + timedelta(days=14), "due date")
            equal(books.get_by_id(book.id).available_copies, 0, "decrement")
            returned = service.return_book(loan.id, date(2025, 1, 20))
            equal(returned.status, "returned", "status")
            equal(returned.return_date, date(2025, 1, 20), "return date")
            equal(books.get_by_id(book.id).available_copies, 1, "increment")
            return "borrow/return"
        finally:
            database.close()

    @suite.check("borrow rejects unavailable books and inactive members")
    def borrow_guards(_: Suite) -> str:
        database, authors, books, members, _, service = make_env(suite, "guards.sqlite3")
        try:
            author = add_author(authors)
            book = add_book(books, author.id, copies=0)
            member = add_member(members)
            raises(Exception, lambda: service.borrow_book(member.id, book.id), "unavailable")
            books.set_available_copies(book.id, 1)
            member.is_active = False
            members.update(member)
            raises(Exception, lambda: service.borrow_book(member.id, book.id), "inactive")
            return "availability and active member"
        finally:
            database.close()

    @suite.check("overdue is derived and disappears after return")
    def overdue(_: Suite) -> str:
        database, authors, books, members, loans, service = make_env(suite, "overdue.sqlite3")
        try:
            author = add_author(authors)
            book = add_book(books, author.id, copies=1)
            member = add_member(members)
            loan = service.borrow_book(member.id, book.id, date(2024, 1, 1))
            equal([item.id for item in service.get_overdue_loans(date(2024, 1, 16))],
                  [loan.id], "overdue")
            equal(loans.get_by_id(loan.id).status, "active", "stored status")
            service.return_book(loan.id, date(2024, 2, 1))
            equal(service.get_overdue_loans(date(2024, 2, 2)), [], "returned")
            return "derived overdue"
        finally:
            database.close()

    @suite.check("search covers title, author and ISBN, deduplicated")
    def search(_: Suite) -> str:
        database, authors, books, _, _, service = make_env(suite, "search.sqlite3")
        try:
            author = add_author(authors)
            add_book(books, author.id, title="Kindred", isbn="9780807083697")
            equal(len(service.search_books("978080")), 1, "ISBN")
            equal(len(service.search_books("octavia")), 1, "author")
            equal(service.search_books("not-an-isbn"), [], "miss")
            unicode_author = add_author(authors, name="ÉMILE Zola", year=1840)
            add_book(books, unicode_author.id, title="Germinal", isbn="456")
            equal(len(service.search_books("émile")), 1, "unicode")
            return "search and dedupe"
        finally:
            database.close()

    @suite.check("deleting an author cascades to books and loans")
    def cascade(_: Suite) -> str:
        database, authors, books, members, loans, service = make_env(suite, "cascade.sqlite3")
        try:
            author = add_author(authors)
            book = add_book(books, author.id)
            member = add_member(members)
            loan = service.borrow_book(member.id, book.id)
            authors.delete(author.id)
            require(books.get_by_id(book.id) is None, "book not deleted")
            require(loans.get_by_id(loan.id) is None, "loan not deleted")
            return "cascade"
        finally:
            database.close()

    @suite.check("failed borrow rolls back inventory and loan")
    def rollback(_: Suite) -> str:
        database, authors, books, members, loans, service = make_env(suite, "rollback.sqlite3")
        try:
            author = add_author(authors)
            book = add_book(books, author.id)
            member = add_member(members)
            with mock.patch.object(loans, "create", side_effect=RuntimeError("insert failed")):
                raises(RuntimeError, lambda: service.borrow_book(member.id, book.id), "insert failure")
            equal(books.get_by_id(book.id).available_copies, 1, "copy restored")
            equal(loans.list_all(), [], "no loan")
            return "transaction rollback"
        finally:
            database.close()

    @suite.check("CLI drives author, book, member, borrow, return and search")
    def cli(_: Suite) -> str:
        db = suite.path("cli.sqlite3")
        base = ["-m", "library_system", "--database", str(db)]
        author = run_python(suite.out, base + [
            "author", "add", "--name", "Octavia Butler", "--birth-year", "1947",
        ])
        author_id = json.loads(author.stdout)["id"]
        book = run_python(suite.out, base + [
            "book", "add", "--title", "Kindred", "--isbn", "123",
            "--author-id", str(author_id), "--published-year", "1979",
        ])
        book_id = json.loads(book.stdout)["id"]
        member = run_python(suite.out, base + [
            "member", "add", "--name", "Sam Reader", "--email", "sam@example.test",
        ])
        member_id = json.loads(member.stdout)["id"]
        loan = run_python(suite.out, base + [
            "borrow", "--member-id", str(member_id), "--book-id", str(book_id),
        ])
        loan_id = json.loads(loan.stdout)["id"]
        returned = run_python(suite.out, base + ["return", "--loan-id", str(loan_id)])
        equal(json.loads(returned.stdout)["status"], "returned", "CLI return")
        search = run_python(suite.out, base + ["book", "search", "--query", "butler"])
        equal(len(json.loads(search.stdout)), 1, "CLI search")
        return "CLI lifecycle"

    return suite.run()


if __name__ == "__main__":
    raise SystemExit(main("library", sys.argv[1] if len(sys.argv) > 1 else None, run))
