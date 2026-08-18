"""
Redis connection helpers for RQ background jobs.

Named redis_conn.py (not redis.py) to avoid shadowing the PyPI `redis` package.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent / ".env")
except ImportError:
    pass

import redis as redis_lib
from rq import Queue


def get_redis_url() -> str:
    return os.getenv("REDIS_URL", "redis://localhost:6379/0")


@lru_cache(maxsize=1)
def get_redis_connection():
    """Return a shared Redis connection for RQ."""
    return redis_lib.from_url(get_redis_url())


def get_queue(name: str = "dc-transcode") -> Queue:
    """Return an RQ queue backed by the shared Redis connection."""
    return Queue(name, connection=get_redis_connection())
