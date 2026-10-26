#!/usr/bin/env python3
"""
First-boot database setup for deployments (non-destructive).

Loads bootcamp.sql and highschool.sql only for databases that do not exist yet,
then sets every seeded account's password to TEST_PASSWORD. Existing databases
only receive additive schema updates (migrate_existing), so this is safe to run
on every container start.
Use reset_local.py --yes instead when you want to wipe and reload everything.
"""

from __future__ import annotations

import sys
import time

import pymysql

from make_test_login import (
    SUITES,
    get_test_password,
    hash_password,
    reset_all_passwords,
    upsert_account,
)
from reset_local import DC_SQL, ROBOTICS_SQL, mysql_kwargs, run_sql_file

DATABASES = (("bootcamp", DC_SQL, "dc"), ("highschool", ROBOTICS_SQL, "robotics"))
CONNECT_ATTEMPTS = 15
CONNECT_DELAY_SECONDS = 4


def existing_databases() -> set[str]:
    for attempt in range(1, CONNECT_ATTEMPTS + 1):
        try:
            conn = pymysql.connect(**mysql_kwargs())
            break
        except pymysql.err.OperationalError as err:
            if attempt == CONNECT_ATTEMPTS:
                raise
            print(f"MySQL not reachable yet ({err.args[0]}); retrying...", file=sys.stderr)
            time.sleep(CONNECT_DELAY_SECONDS)
    try:
        with conn.cursor() as cur:
            cur.execute("SHOW DATABASES")
            return {row[0] for row in cur.fetchall()}
    finally:
        conn.close()


def seed_passwords(suite_key: str) -> None:
    """Like reset_local.seed_passwords, but never writes the password to the logs."""
    suite = SUITES[suite_key]
    password_hash = hash_password(get_test_password())
    for account in suite["accounts"]:
        upsert_account(suite["database"], password_hash, account)
    reset_all_passwords(suite["database"], password_hash, suite_key)
    print(f"MySQL: {suite['database']} seed logins use TEST_PASSWORD")


def migrate_existing() -> None:
    """Bring databases created from an older schema up to date (additive, idempotent)."""
    conn = pymysql.connect(**mysql_kwargs())
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COLUMN_NAME, IS_NULLABLE FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA = 'bootcamp' AND TABLE_NAME = 'student'"
            )
            columns = dict(cur.fetchall())
            if "college" not in columns and columns:
                cur.execute(
                    "ALTER TABLE bootcamp.student "
                    "ADD COLUMN `college` BOOLEAN NOT NULL DEFAULT FALSE AFTER `courseid`"
                )
                print("MySQL: added bootcamp.student.college")
            if columns and columns.get("cohortid") == "NO":
                cur.execute("ALTER TABLE bootcamp.student MODIFY `cohortid` BIGINT UNSIGNED NULL")
                print("MySQL: bootcamp.student.cohortid is now optional")
            cur.execute(
                "SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = 'bootcamp' "
                "AND TABLE_NAME = 'content' AND COLUMN_NAME = 'instructionskey'"
            )
            if not cur.fetchone():
                cur.execute(
                    "ALTER TABLE bootcamp.content "
                    "ADD COLUMN `instructionskey` VARCHAR(255) NULL AFTER `pdfkey`"
                )
                print("MySQL: added bootcamp.content.instructionskey")
            cur.execute(
                "SELECT IS_NULLABLE FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA = 'bootcamp' AND TABLE_NAME = 'admin' "
                "AND COLUMN_NAME = 'password'"
            )
            admin_pw = cur.fetchone()
            if admin_pw and admin_pw[0] == "NO":
                cur.execute(
                    "ALTER TABLE bootcamp.admin MODIFY `password` VARCHAR(255) NULL"
                )
                print("MySQL: bootcamp.admin.password is now optional (first-login setup)")
            cur.execute(
                "SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = 'bootcamp' "
                "AND TABLE_NAME = 'admin' AND COLUMN_NAME = 'signed_in_at'"
            )
            if not cur.fetchone():
                cur.execute(
                    "ALTER TABLE bootcamp.admin "
                    "ADD COLUMN `signed_in_at` DATETIME NULL AFTER `password`"
                )
                print("MySQL: added bootcamp.admin.signed_in_at")
            cur.execute(
                "SELECT IS_NULLABLE FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA = 'bootcamp' AND TABLE_NAME = 'student' "
                "AND COLUMN_NAME = 'password'"
            )
            student_pw = cur.fetchone()
            if student_pw and student_pw[0] == "NO":
                cur.execute(
                    "ALTER TABLE bootcamp.student MODIFY `password` VARCHAR(255) NULL"
                )
                print("MySQL: bootcamp.student.password is now optional (first-login setup)")
            cur.execute(
                "SELECT IS_NULLABLE FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA = 'bootcamp' AND TABLE_NAME = 'leader' "
                "AND COLUMN_NAME = 'password'"
            )
            leader_pw = cur.fetchone()
            if leader_pw and leader_pw[0] == "NO":
                cur.execute(
                    "ALTER TABLE bootcamp.leader MODIFY `password` VARCHAR(255) NULL"
                )
                print("MySQL: bootcamp.leader.password is now optional (first-login setup)")

            # High school: invite-by-email, password set on first login
            for table in ("students", "teacher"):
                cur.execute(
                    "SELECT IS_NULLABLE FROM information_schema.COLUMNS "
                    "WHERE TABLE_SCHEMA = 'highschool' AND TABLE_NAME = %s "
                    "AND COLUMN_NAME = 'password'",
                    (table,),
                )
                row = cur.fetchone()
                if row and row[0] == "NO":
                    cur.execute(
                        f"ALTER TABLE highschool.`{table}` MODIFY `password` VARCHAR(255) NULL"
                    )
                    print(f"MySQL: highschool.{table}.password is now optional (first-login setup)")
        conn.commit()
    finally:
        conn.close()


def main() -> None:
    present = existing_databases()
    for name, sql_path, suite_key in DATABASES:
        if name in present:
            print(f"MySQL: `{name}` already exists, leaving it alone.")
            continue
        run_sql_file(sql_path)
        seed_passwords(suite_key)
    migrate_existing()


if __name__ == "__main__":
    main()
