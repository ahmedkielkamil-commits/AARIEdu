#!/usr/bin/env python3
"""
Copy the local bootcamp and highschool databases into a remote MySQL (e.g. Railway).

The source is the MySQL configured by MYSQL_* in .env. The target comes from
RAILWAY_MYSQL_URL (Railway's MYSQL_PUBLIC_URL), e.g.

  RAILWAY_MYSQL_URL='mysql://root:PASSWORD@sakura.proxy.rlwy.net:38784' \
    python push_to_railway.py --check

  RAILWAY_MYSQL_URL='...' python push_to_railway.py --replace --set-password

--check          only show what exists locally and remotely; changes nothing
--replace        drop the remote database first if it already exists (required
                 when the app has already created it on first boot)
--set-password   prompt for a new password and apply it to every account in the
                 copied databases, so the public site doesn't keep local passwords
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent / ".env")
except ImportError:
    pass

import bcrypt
import pymysql
import pymysql.cursors

DATABASES = ("bootcamp", "highschool")
BATCH_SIZE = 500


def local_kwargs() -> dict:
    return {
        "host": os.getenv("MYSQL_HOST", "localhost"),
        "port": int(os.getenv("MYSQL_PORT", "3306")),
        "user": os.getenv("MYSQL_USER", "root"),
        "password": os.getenv("MYSQL_PASSWORD", ""),
        "charset": "utf8mb4",
    }


def remote_kwargs() -> dict:
    url = os.getenv("RAILWAY_MYSQL_URL", "").strip()
    if not url:
        sys.exit(
            "Set RAILWAY_MYSQL_URL to the Railway MySQL public URL, e.g.\n"
            "  RAILWAY_MYSQL_URL='mysql://root:PASSWORD@sakura.proxy.rlwy.net:38784'"
        )
    parsed = urlparse(url)
    if parsed.scheme not in ("mysql", "mysql+pymysql") or not parsed.hostname:
        sys.exit("RAILWAY_MYSQL_URL must look like mysql://user:password@host:port")
    return {
        "host": parsed.hostname,
        "port": parsed.port or 3306,
        "user": unquote(parsed.username or "root"),
        "password": unquote(parsed.password or ""),
        "charset": "utf8mb4",
        "connect_timeout": 15,
    }


def database_names(conn) -> set[str]:
    with conn.cursor() as cur:
        cur.execute("SHOW DATABASES")
        return {row[0] for row in cur.fetchall()}


def table_counts(conn, database: str) -> dict[str, int]:
    counts = {}
    with conn.cursor() as cur:
        cur.execute(
            "SELECT TABLE_NAME FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA = %s AND TABLE_TYPE = 'BASE TABLE' ORDER BY TABLE_NAME",
            (database,),
        )
        for (table,) in cur.fetchall():
            cur.execute(f"SELECT COUNT(*) FROM `{database}`.`{table}`")
            counts[table] = cur.fetchone()[0]
    return counts


def copy_database(local, remote, database: str) -> None:
    with local.cursor(pymysql.cursors.SSCursor) as lcur, remote.cursor() as rcur:
        rcur.execute("SET FOREIGN_KEY_CHECKS = 0")
        rcur.execute(
            f"CREATE DATABASE `{database}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
        )
        rcur.execute(f"USE `{database}`")

        lcur.execute(f"USE `{database}`")
        lcur.execute("SHOW FULL TABLES WHERE Table_type = 'BASE TABLE'")
        tables = [row[0] for row in lcur.fetchall()]

        for table in tables:
            lcur.execute(f"SHOW CREATE TABLE `{table}`")
            rcur.execute(lcur.fetchall()[0][1])

        for table in tables:
            lcur.execute(f"SELECT * FROM `{table}`")
            columns = [d[0] for d in lcur.description]
            column_sql = ", ".join(f"`{c}`" for c in columns)
            placeholders = ", ".join(["%s"] * len(columns))
            insert = f"INSERT INTO `{table}` ({column_sql}) VALUES ({placeholders})"
            copied = 0
            while True:
                rows = lcur.fetchmany(BATCH_SIZE)
                if not rows:
                    break
                rcur.executemany(insert, rows)
                copied += len(rows)
            print(f"  {database}.{table}: {copied} row(s)")

        rcur.execute("SET FOREIGN_KEY_CHECKS = 1")
    remote.commit()


def set_passwords(remote, database: str, password_hash: str) -> None:
    with remote.cursor() as cur:
        cur.execute(
            "SELECT TABLE_NAME FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = %s AND COLUMN_NAME = 'password'",
            (database,),
        )
        for (table,) in cur.fetchall():
            cur.execute(f"UPDATE `{database}`.`{table}` SET password = %s", (password_hash,))
            print(f"  {database}.{table}: password reset for {cur.rowcount} account(s)")
    remote.commit()


def prompt_password() -> str:
    while True:
        first = getpass.getpass("New password for every account on Railway: ")
        if len(first) < 8:
            print("Use at least 8 characters.")
            continue
        if getpass.getpass("Repeat it: ") != first:
            print("Passwords didn't match.")
            continue
        return first


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="show local vs remote state only")
    parser.add_argument("--replace", action="store_true", help="drop existing remote databases first")
    parser.add_argument("--set-password", action="store_true", help="reset every account's password on the remote copy")
    args = parser.parse_args()

    target = remote_kwargs()
    local = pymysql.connect(**local_kwargs())
    remote = pymysql.connect(**target)
    print(f"Source: local MySQL at {local.host}:{local.port}")
    print(f"Target: {target['user']}@{target['host']}:{target['port']}\n")

    try:
        local_dbs = database_names(local)
        remote_dbs = database_names(remote)
        missing_local = [d for d in DATABASES if d not in local_dbs]
        if missing_local:
            sys.exit(f"Local MySQL is missing: {', '.join(missing_local)}")

        if args.check:
            for database in DATABASES:
                print(f"{database}:")
                print(f"  local : {table_counts(local, database)}")
                if database in remote_dbs:
                    print(f"  remote: {table_counts(remote, database)}")
                else:
                    print("  remote: (does not exist)")
            return

        existing = [d for d in DATABASES if d in remote_dbs]
        if existing and not args.replace:
            sys.exit(
                f"Remote already has: {', '.join(existing)}. "
                "Re-run with --replace to overwrite (this deletes the remote data)."
            )

        new_password_hash = None
        if args.set_password:
            new_password_hash = bcrypt.hashpw(
                prompt_password().encode("utf-8"), bcrypt.gensalt(rounds=12)
            ).decode("utf-8")

        if existing:
            answer = input(
                f"This will DELETE {', '.join(existing)} on {target['host']} and replace "
                "it with your local copy. Type 'yes' to continue: "
            )
            if answer.strip().lower() != "yes":
                sys.exit("Cancelled.")

        for database in DATABASES:
            print(f"\nCopying {database}...")
            with remote.cursor() as cur:
                cur.execute(f"DROP DATABASE IF EXISTS `{database}`")
            copy_database(local, remote, database)
            if new_password_hash:
                set_passwords(remote, database, new_password_hash)

        print("\nVerifying row counts...")
        ok = True
        for database in DATABASES:
            local_counts = table_counts(local, database)
            remote_counts = table_counts(remote, database)
            for table, count in local_counts.items():
                if remote_counts.get(table) != count:
                    ok = False
                    print(f"  MISMATCH {database}.{table}: local {count}, remote {remote_counts.get(table)}")
        print("  All tables match." if ok else "  Some tables did not match (see above).")
        if not new_password_hash:
            print("\nAccounts keep their local passwords. Re-run with --set-password to change them.")
    finally:
        local.close()
        remote.close()


if __name__ == "__main__":
    main()
