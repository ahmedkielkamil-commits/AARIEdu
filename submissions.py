"""
Student file submissions stored in MinIO.

Used by high school exit tickets and bootcamp assignments. Files are uploaded
under a random folder so names never collide, and are only ever handed out as
short-lived presigned URLs after the Flask route has checked who is asking.
"""

from __future__ import annotations

from uuid import uuid4

from werkzeug.utils import secure_filename

import miniIO

MAX_BYTES = 25 * 1024 * 1024
PRESIGNED_EXPIRY_SECONDS = 600

# Images and PDFs open in the browser; everything else downloads, so uploaded
# HTML/JS can never render as a page.
INLINE_TYPES = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "gif": "image/gif",
    "webp": "image/webp",
    "pdf": "application/pdf",
}
DOWNLOAD_EXTENSIONS = {
    "zip", "txt", "md", "csv", "json", "py", "js", "html", "css", "sql",
    "docx", "pptx", "xlsx",
}
ALLOWED_EXTENSIONS = set(INLINE_TYPES) | DOWNLOAD_EXTENSIONS
ACCEPT_ATTR = ",".join(f".{ext}" for ext in sorted(ALLOWED_EXTENSIONS))


class SubmissionError(Exception):
    """Raised with a student-facing message when a file cannot be stored."""


def store_submission(file_storage, prefix: str) -> str | None:
    """
    Upload a submitted file to MinIO under ``prefix`` and return its object key.

    Returns None when no file was chosen. Raises SubmissionError for bad
    types, empty or oversized files, or when MinIO is unreachable.
    """
    if not file_storage or not file_storage.filename:
        return None

    filename = secure_filename(file_storage.filename) or "upload"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_EXTENSIONS))
        raise SubmissionError(f"That file type isn't allowed. Allowed types: {allowed}.")

    data = file_storage.read()
    if not data:
        raise SubmissionError("That file is empty.")
    if len(data) > MAX_BYTES:
        raise SubmissionError(f"Files must be {MAX_BYTES // (1024 * 1024)} MB or smaller.")

    stem = filename[: -(len(ext) + 1)][:80] or "upload"
    object_key = f"{prefix}/{uuid4().hex}/{stem}.{ext}"
    try:
        miniIO.upload_bytes(
            data,
            object_key,
            content_type=INLINE_TYPES.get(ext, "application/octet-stream"),
        )
    except Exception as exc:
        raise SubmissionError("Could not save your file right now. Please try again.") from exc
    return object_key


def delete_submission(object_key: str | None) -> None:
    """Best-effort removal of a replaced file; a leftover object is harmless."""
    if not object_key:
        return
    try:
        miniIO.get_client().remove_object(miniIO.get_bucket(), object_key)
    except Exception:
        pass


def submission_url(object_key: str | None) -> str | None:
    """Presigned URL for a stored submission, or None if it is missing or MinIO is down."""
    if not object_key or not miniIO.object_exists(object_key):
        return None
    try:
        return miniIO.presigned_get_url(object_key, expires_seconds=PRESIGNED_EXPIRY_SECONDS)
    except Exception:
        return None


def display_name(object_key: str | None) -> str:
    """Original filename portion of an object key, for showing in the UI."""
    if not object_key:
        return ""
    return object_key.rsplit("/", 1)[-1]
