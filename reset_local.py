#!/usr/bin/env python3
"""
Wipe MinIO and reload both schemas, bootcamp.sql and highschool.sql (local dev only).

Usage:
  python reset_local.py --yes

Requires MinIO running (docker compose up -d) and MYSQL_* in .env.
After reload, hashes TEST_PASSWORD for every account in both databases so logins work.
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

import pymysql
from pymysql.constants import CLIENT
from sqlalchemy.exc import SQLAlchemyError

import miniIO
from make_test_login import (
    get_test_password,
    hash_password,
    reset_all_passwords,
    upsert_account,
    SUITES,
)

ROOT = Path(__file__).resolve().parent
DC_SQL = ROOT / "bootcamp.sql"
ROBOTICS_SQL = ROOT / "highschool.sql"


def mysql_kwargs() -> dict:
    return {
        "host": os.getenv("MYSQL_HOST", "localhost"),
        "port": int(os.getenv("MYSQL_PORT", "3306")),
        "user": os.getenv("MYSQL_USER", "root"),
        "password": os.getenv("MYSQL_PASSWORD", ""),
        "charset": "utf8mb4",
        "autocommit": False,
        "client_flag": CLIENT.MULTI_STATEMENTS,
    }


def flush_minio() -> None:
    client = miniIO.get_client()
    buckets = list(client.list_buckets())
    if not buckets:
        print("MinIO: no buckets to remove.")
        return

    for bucket in buckets:
        name = bucket.name
        removed = 0
        for obj in client.list_objects(name, recursive=True):
            client.remove_object(name, obj.object_name)
            removed += 1
        client.remove_bucket(name)
        print(f"MinIO: removed bucket {name!r} ({removed} object(s)).")


def flush_redis_caches() -> None:
    try:
        import redis_conn as redis_jobs

        conn = redis_jobs.get_redis_connection()
        keys = list(conn.scan_iter("dc:pdfdoc:*")) + list(conn.scan_iter("dc:transcode:*"))
        if keys:
            conn.delete(*keys)
        print(f"Redis: cleared {len(keys)} DC cache/job key(s).")
    except Exception as err:
        print(f"Redis: skipped ({err}).")


def run_sql_file(sql_path: Path) -> None:
    if not sql_path.is_file():
        raise FileNotFoundError(sql_path)

    sql = sql_path.read_text(encoding="utf-8")
    conn = pymysql.connect(**mysql_kwargs())
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            while cur.nextset():
                pass
        conn.commit()
        print(f"MySQL: applied {sql_path.name}")
    finally:
        conn.close()


def drop_database(name: str) -> None:
    conn = pymysql.connect(**mysql_kwargs())
    try:
        with conn.cursor() as cur:
            cur.execute(f"DROP DATABASE IF EXISTS `{name}`")
        conn.commit()
        print(f"MySQL: dropped `{name}`")
    finally:
        conn.close()


def seed_passwords(suite_key: str) -> None:
    suite = SUITES[suite_key]
    database = suite["database"]
    password = get_test_password()
    password_hash = hash_password(password)
    for account in suite["accounts"]:
        upsert_account(database, password_hash, account)
    reset_all_passwords(database, password_hash, suite_key)
    print(f"MySQL: {database} logins use password {password}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Flush MinIO and reload bootcamp.sql and highschool.sql (destroys all data)."
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Required. Confirm you want to wipe MinIO and reload both schemas.",
    )
    args = parser.parse_args()

    if not args.yes:
        print(
            "Refusing to run without --yes. This deletes all MinIO objects and rebuilds "
            "the bootcamp and highschool databases from bootcamp.sql and highschool.sql.",
            file=sys.stderr,
        )
        sys.exit(2)

    try:
        flush_minio()
    except Exception as err:
        print(f"MinIO flush failed: {err}", file=sys.stderr)
        print("Is Docker Desktop running? Try: docker compose up -d", file=sys.stderr)
        sys.exit(1)

    flush_redis_caches()

    try:
        drop_database("bootcamp")
        run_sql_file(DC_SQL)
        seed_passwords("dc")
        drop_database("highschool")
        run_sql_file(ROBOTICS_SQL)
        seed_passwords("robotics")
    except SQLAlchemyError as err:
        print(f"MySQL failed: {err}", file=sys.stderr)
        sys.exit(1)
    except Exception as err:
        print(f"Schema reload failed: {err}", file=sys.stderr)
        sys.exit(1)

    print()
    print("Reset complete. Restart Flask if it is already running.")


if __name__ == "__main__":
    main()
