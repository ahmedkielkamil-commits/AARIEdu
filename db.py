"""
Shared SQLAlchemy Core database access (no ORM).

Reads MYSQL_* from environment / .env. Uses PyMySQL driver.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import quote_plus

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / ".env")
except ImportError:
    pass

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine

_engines: dict[str, Engine] = {}


_PLACEHOLDER_PASSWORDS = frozenset({"", "your_mysql_password", "password", "changeme"})


def mysql_config_hint() -> str | None:
    """Return a user-facing hint when MySQL env looks misconfigured."""
    password = os.getenv("MYSQL_PASSWORD", "")
    if password in _PLACEHOLDER_PASSWORDS:
        return (
            "MYSQL_PASSWORD in .env is still a placeholder. "
            "Set it to the same password you use in MySQL Workbench, then restart Flask."
        )
    return None


def build_database_url(database: str) -> str:
    user = os.getenv("MYSQL_USER", "root")
    password = quote_plus(os.getenv("MYSQL_PASSWORD", ""))
    host = os.getenv("MYSQL_HOST", "localhost")
    port = os.getenv("MYSQL_PORT", "3306")
    return f"mysql+pymysql://{user}:{password}@{host}:{port}/{database}?charset=utf8mb4"


def get_engine(database: str | None = None) -> Engine:
    db = database or os.getenv("MYSQL_DATABASE", "robcourse")
    if db not in _engines:
        _engines[db] = create_engine(
            build_database_url(db),
            pool_pre_ping=True,
            future=True,
            connect_args={"charset": "utf8mb4"},
        )
    return _engines[db]


@contextmanager
def get_connection(database: str | None = None) -> Iterator[Connection]:
    engine = get_engine(database)
    with engine.connect() as conn:
        yield conn


def _as_dict(row) -> dict[str, Any] | None:
    if row is None:
        return None
    return dict(row)


def fetch_one(
    sql: str,
    params: dict[str, Any] | None = None,
    *,
    database: str | None = None,
) -> dict[str, Any] | None:
    with get_connection(database) as conn:
        result = conn.execute(text(sql), params or {})
        return _as_dict(result.mappings().first())


def fetch_all(
    sql: str,
    params: dict[str, Any] | None = None,
    *,
    database: str | None = None,
) -> list[dict[str, Any]]:
    with get_connection(database) as conn:
        result = conn.execute(text(sql), params or {})
        return [dict(row) for row in result.mappings().all()]


def execute(
    sql: str,
    params: dict[str, Any] | None = None,
    *,
    database: str | None = None,
) -> int:
    """Run a write statement; return affected row count."""
    with get_connection(database) as conn:
        result = conn.execute(text(sql), params or {})
        conn.commit()
        return result.rowcount


def execute_insert(
    sql: str,
    params: dict[str, Any] | None = None,
    *,
    database: str | None = None,
) -> int:
    """Run an INSERT; return lastrowid."""
    with get_connection(database) as conn:
        result = conn.execute(text(sql), params or {})
        conn.commit()
        return int(result.lastrowid or 0)
