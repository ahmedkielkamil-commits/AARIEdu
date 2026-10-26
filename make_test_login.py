#!/usr/bin/env python3
"""
Insert (or update) test accounts with real bcrypt passwords for local dev.

Usage:
  python make_test_login.py --suite robotics   # highschool student
  python make_test_login.py --suite dc         # bootcamp student + admin

Login password comes from TEST_PASSWORD in .env (default: 123123).

Requires: pip install bcrypt SQLAlchemy PyMySQL python-dotenv
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / ".env")
except ImportError:
    pass

try:
    import bcrypt
except ImportError:
    print("Missing dependency: pip install bcrypt", file=sys.stderr)
    sys.exit(1)

from sqlalchemy.exc import SQLAlchemyError

from db import execute, execute_insert, fetch_all, fetch_one, get_connection


DEFAULT_TEST_PASSWORD = "123123"


def get_test_password() -> str:
    return os.getenv("TEST_PASSWORD", DEFAULT_TEST_PASSWORD)


ROBOTICS = {
    "database": "highschool",
    "accounts": [
        {
            "role": "student",
            "table": "students",
            "id_col": "studentid",
            "email": "test.user@student.aari.org",
            "fname": "Test",
            "lname": "User",
            "extra_insert": None,
            "extra_on_create": "enroll_robotics",
        },
    ],
}

DC = {
    "database": "bootcamp",
    "accounts": [
        {
            "role": "student",
            "table": "student",
            "id_col": "studentid",
            "email": "test.student@aari.org",
            "fname": "Test",
            "lname": "Student",
            "extra_insert": {"courseid": 1, "cohortid": 1},
            "extra_on_create": None,
        },
        {
            "role": "leader",
            "table": "leader",
            "id_col": "leaderid",
            "email": "test.leader@aari.org",
            "fname": "Test",
            "lname": "Leader",
            "extra_insert": {"cohortid": 1},
            "extra_on_create": None,
        },
        {
            "role": "admin",
            "table": "admin",
            "id_col": "adminid",
            "email": "test.admin@aari.org",
            "fname": "Test",
            "lname": "Admin",
            "extra_insert": {},
            "extra_on_create": None,
        },
    ],
}

SUITES = {"robotics": ROBOTICS, "dc": DC}


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def upsert_account(database: str, password_hash: str, account: dict) -> int:
    table = account["table"]
    email = account["email"]
    id_col = account["id_col"]

    existing = fetch_one(
        f"SELECT {id_col} AS id FROM `{table}` WHERE email = :email LIMIT 1",
        {"email": email},
        database=database,
    )

    if existing:
        account_id = existing["id"]
        execute(
            f"""
            UPDATE `{table}`
            SET fname = :fname, lname = :lname, password = :password
            WHERE {id_col} = :account_id
            """,
            {
                "fname": account["fname"],
                "lname": account["lname"],
                "password": password_hash,
                "account_id": account_id,
            },
            database=database,
        )
        print(f"Updated existing test {account['role']} ({id_col}={account_id}).")
        return account_id

    extra = account.get("extra_insert") or {}

    # One leader per cohort — reuse the slot if seed data already assigned someone.
    if table == "leader" and extra.get("cohortid") is not None:
        cohort_leader = fetch_one(
            """
            SELECT leaderid AS id FROM leader
            WHERE cohortid = :cohortid LIMIT 1
            """,
            {"cohortid": extra["cohortid"]},
            database=database,
        )
        if cohort_leader:
            account_id = cohort_leader["id"]
            execute(
                """
                UPDATE leader
                SET fname = :fname, lname = :lname, email = :email, password = :password
                WHERE leaderid = :account_id
                """,
                {
                    "fname": account["fname"],
                    "lname": account["lname"],
                    "email": email,
                    "password": password_hash,
                    "account_id": account_id,
                },
                database=database,
            )
            print(
                f"Updated cohort {extra['cohortid']} leader as test {account['role']} "
                f"(leaderid={account_id})."
            )
            return account_id

    if table == "student":
        account_id = execute_insert(
            """
            INSERT INTO student (fname, lname, email, password, courseid, cohortid)
            VALUES (:fname, :lname, :email, :password, :courseid, :cohortid)
            """,
            {
                "fname": account["fname"],
                "lname": account["lname"],
                "email": email,
                "password": password_hash,
                "courseid": extra["courseid"],
                "cohortid": extra["cohortid"],
            },
            database=database,
        )
    elif table == "leader":
        account_id = execute_insert(
            """
            INSERT INTO leader (fname, lname, email, password, cohortid)
            VALUES (:fname, :lname, :email, :password, :cohortid)
            """,
            {
                "fname": account["fname"],
                "lname": account["lname"],
                "email": email,
                "password": password_hash,
                "cohortid": extra["cohortid"],
            },
            database=database,
        )
    elif table == "admin":
        account_id = execute_insert(
            """
            INSERT INTO admin (fname, lname, email, password)
            VALUES (:fname, :lname, :email, :password)
            """,
            {
                "fname": account["fname"],
                "lname": account["lname"],
                "email": email,
                "password": password_hash,
            },
            database=database,
        )
    else:
        account_id = execute_insert(
            f"""
            INSERT INTO `{table}` (fname, lname, email, password)
            VALUES (:fname, :lname, :email, :password)
            """,
            {
                "fname": account["fname"],
                "lname": account["lname"],
                "email": email,
                "password": password_hash,
            },
            database=database,
        )

    print(f"Inserted new test {account['role']} ({id_col}={account_id}).")

    if account.get("extra_on_create") == "enroll_robotics":
        courses = fetch_all("SELECT courseid FROM Course", database=database)
        for course in courses:
            execute_insert(
                "INSERT INTO class (studentid, courseid) VALUES (:studentid, :courseid)",
                {"studentid": account_id, "courseid": course["courseid"]},
                database=database,
            )
        print(f"Enrolled test student in {len(courses)} high school course(s).")

    return account_id


def reset_all_passwords(database: str, password_hash: str, suite: str) -> None:
    """Re-hash every student/teacher (or student/admin) password for local dev logins."""
    if suite == "robotics":
        tables = ("students", "teacher")
    else:
        tables = ("student", "leader", "admin")

    for table in tables:
        count = execute(
            f"UPDATE `{table}` SET password = :password",
            {"password": password_hash},
            database=database,
        )
        print(f"Reset password for {count} row(s) in `{table}`.")


def main() -> None:
    test_password = get_test_password()

    parser = argparse.ArgumentParser(
        description="Create test login accounts using TEST_PASSWORD from .env."
    )
    parser.add_argument(
        "--suite",
        choices=("robotics", "dc"),
        default="robotics",
        help="Which AARI program database to seed (default: robotics)",
    )
    parser.add_argument(
        "--database",
        default=None,
        help="Override database name (default: highschool or bootcamp by suite)",
    )
    parser.add_argument(
        "--reset-all",
        action="store_true",
        help="Bcrypt-hash TEST_PASSWORD for ALL users in the suite DB (fixes seed data)",
    )
    args = parser.parse_args()

    suite = SUITES[args.suite]
    database = args.database or suite["database"]
    password_hash = hash_password(test_password)

    try:
        with get_connection(database):
            pass
    except SQLAlchemyError as exc:
        user = os.getenv("MYSQL_USER", "root")
        host = os.getenv("MYSQL_HOST", "localhost")
        port = os.getenv("MYSQL_PORT", "3306")
        has_pw = bool(os.getenv("MYSQL_PASSWORD", ""))
        print(f"Database connection failed: {exc}", file=sys.stderr)
        print(
            f"\nTried: user={user!r} host={host} port={port} "
            f"database={database!r} (password {'set' if has_pw else 'empty'})",
            file=sys.stderr,
        )
        print(
            "Set MYSQL_PASSWORD in a .env file to the same password you use in MySQL Workbench.",
            file=sys.stderr,
        )
        sys.exit(1)

    for account in suite["accounts"]:
        upsert_account(database, password_hash, account)

    if args.reset_all:
        reset_all_passwords(database, password_hash, args.suite)
        print()
        print(f"All {args.suite} users can now log in with password: {test_password}")

    print()
    print(f"Test logins ({database}):")
    for account in suite["accounts"]:
        print(f"  {account['role']:8}  email: {account['email']}  password: {test_password}")


if __name__ == "__main__":
    main()
