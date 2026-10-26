"""
MinIO object storage helpers for AARI Educational Suite.

Single shared client — import from here; do not create additional MinIO connections.
"""

from __future__ import annotations

import logging
import os
from datetime import timedelta
from functools import lru_cache
from io import BytesIO
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent / ".env")
except ImportError:
    pass

from minio import Minio
from minio.error import S3Error

logger = logging.getLogger(__name__)

_client: Minio | None = None


def get_client() -> Minio:
    """Return the process-wide MinIO client (lazy init)."""
    global _client
    if _client is None:
        endpoint = os.getenv("MINIO_ENDPOINT", "localhost:9000")
        access_key = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
        secret_key = os.getenv("MINIO_SECRET_KEY", "minioadmin")
        secure = os.getenv("MINIO_SECURE", "false").lower() in ("1", "true", "yes")
        _client = Minio(
            endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=secure,
        )
    return _client


def get_bucket() -> str:
    return os.getenv("MINIO_BUCKET", "aari-videos")


def ensure_bucket() -> None:
    """Create the bucket if it does not exist and allow browser playback (CORS)."""
    client = get_client()
    bucket = get_bucket()
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)
    _ensure_bucket_cors(client, bucket)


def _ensure_bucket_cors(client: Minio, bucket: str) -> None:
    """Allow lesson pages on Flask to load presigned video URLs from MinIO."""
    try:
        from minio.corsconfig import CorsConfig, Rule

        origins = os.getenv(
            "MINIO_CORS_ORIGINS",
            "http://localhost:5000,http://127.0.0.1:5000",
        ).split(",")
        origins = [origin.strip() for origin in origins if origin.strip()]
        if not origins:
            return

        client.set_bucket_cors(
            bucket,
            CorsConfig(
                [
                    Rule(
                        allowed_origins=origins,
                        allowed_methods=["GET", "HEAD"],
                        allowed_headers=["*"],
                        expose_headers=["Content-Length", "Content-Range", "Accept-Ranges"],
                    )
                ]
            ),
        )
    except Exception:
        pass


def upload_file(
    local_path: str | Path,
    object_key: str,
    *,
    content_type: str = "video/mp4",
) -> str:
    """
    Upload a local file to MinIO. Returns the object key.

    Raises S3Error or FileNotFoundError on failure.
    """
    path = Path(local_path)
    if not path.is_file():
        raise FileNotFoundError(f"Upload source not found: {path}")

    ensure_bucket()
    client = get_client()
    client.fput_object(
        get_bucket(),
        object_key,
        str(path),
        content_type=content_type,
    )
    return object_key


def upload_bytes(
    data: bytes,
    object_key: str,
    *,
    content_type: str = "application/octet-stream",
) -> str:
    """Upload an in-memory object to MinIO. Returns the object key."""
    ensure_bucket()
    client = get_client()
    client.put_object(
        get_bucket(),
        object_key,
        BytesIO(data),
        length=len(data),
        content_type=content_type,
    )
    return object_key


def download_file(object_key: str, local_path: str | Path) -> Path:
    """Download an object from MinIO to a local path. Returns the path."""
    path = Path(local_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    get_client().fget_object(get_bucket(), object_key, str(path))
    return path


def open_object(object_key: str):
    """Return a streaming response for an object; caller must close() and release_conn()."""
    return get_client().get_object(get_bucket(), object_key)


def presigned_get_url(object_key: str, *, expires_seconds: int = 3600) -> str:
    """Return a presigned GET URL for an object (playback / download)."""
    client = get_client()
    return client.presigned_get_object(
        get_bucket(),
        object_key,
        expires=timedelta(seconds=expires_seconds),
    )


def object_exists(object_key: str) -> bool:
    """Return True if the object exists in the bucket."""
    try:
        get_client().stat_object(get_bucket(), object_key)
        return True
    except S3Error:
        return False
    except Exception as err:
        logger.warning("MinIO unavailable while checking %s: %s", object_key, err)
        return False
