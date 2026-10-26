"""
Video upload, transcode (ffmpeg + RQ), and presigned playback URLs for DC course.

Upload/transcode: admin flow via RQ worker.
Playback: presigned MinIO URLs — byte delivery and HTTP range requests are handled
by MinIO and the reverse proxy, not Flask.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

import dcqueries as dq
import miniIO
import redis_conn as redis_jobs

logger = logging.getLogger(__name__)

TRANSCODE_QUEUE = "dc-transcode"
STATUS_KEY_PREFIX = "dc:transcode:"
# Fail fast when a job never leaves the queue (no worker). Active ffmpeg runs longer.
TRANSCODE_QUEUE_TIMEOUT_SECONDS = int(
    os.getenv(
        "TRANSCODE_QUEUE_TIMEOUT_SECONDS",
        os.getenv("TRANSCODE_TIMEOUT_SECONDS", "20"),
    )
)
TRANSCODE_JOB_TIMEOUT = int(os.getenv("TRANSCODE_JOB_TIMEOUT", "10800"))
# Chunked uploads keep each request small enough for hosting proxies (~100 MB caps).
UPLOAD_KEY_PREFIX = "dc:upload:"
UPLOAD_CHUNK_BYTES = int(os.getenv("VIDEO_UPLOAD_CHUNK_BYTES", str(16 * 1024 * 1024)))
UPLOAD_CHUNK_MAX_BYTES = 64 * 1024 * 1024
UPLOAD_MAX_BYTES = int(os.getenv("VIDEO_UPLOAD_MAX_BYTES", str(5 * 1024 * 1024 * 1024)))
UPLOAD_SESSION_TTL_SECONDS = 6 * 3600
PRESIGNED_EXPIRY_SECONDS = int(os.getenv("MINIO_PRESIGNED_EXPIRY", "3600"))
ALLOWED_UPLOAD_EXTENSIONS = frozenset(
    {"mp4", "mov", "mkv", "webm", "avi", "m4v", "mpeg", "mpg"}
)


def _transcode_tmp_dir() -> Path:
    configured = os.getenv("TRANSCODE_TMP_DIR")
    if configured:
        return Path(configured)
    return Path(tempfile.gettempdir()) / "aari-transcode"


TMP_DIR = _transcode_tmp_dir()


class StreamingAuthError(PermissionError):
    """Raised when a student is not allowed to stream a video."""


def _status_key(videoid: int) -> str:
    return f"{STATUS_KEY_PREFIX}{videoid}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _set_status(videoid: int, payload: dict[str, Any]) -> None:
    conn = redis_jobs.get_redis_connection()
    data = {**payload, "updated_at": _now_iso()}
    conn.set(_status_key(videoid), json.dumps(data), ex=86400 * 7)


def _parse_iso(ts: str) -> datetime | None:
    try:
        return datetime.fromisoformat(ts)
    except (TypeError, ValueError):
        return None


def _apply_queue_circuit_breaker(
    videoid: int, data: dict[str, Any], conn
) -> dict[str, Any]:
    """
    Fail only when a job sits in the RQ queue with no worker.

    Active ffmpeg jobs (RQ status ``started``) are allowed to run up to
    TRANSCODE_JOB_TIMEOUT — real transcoding often takes minutes.
    """
    if data.get("status") != "processing" or data.get("phase") != "queued":
        return data

    from rq import Worker

    if Worker.all(connection=conn):
        return data

    started = _parse_iso(data.get("started_at") or data.get("updated_at") or "")
    if not started:
        return data
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)

    elapsed = (datetime.now(timezone.utc) - started).total_seconds()
    if elapsed <= TRANSCODE_QUEUE_TIMEOUT_SECONDS:
        return data

    job_id = data.get("job_id")
    if job_id:
        try:
            from rq.job import Job

            job = Job.fetch(job_id, connection=conn)
            job.cancel()
        except Exception as err:
            logger.warning("Could not cancel timed-out job %s: %s", job_id, err)

    error = (
        f"No transcode worker picked up the job within "
        f"{TRANSCODE_QUEUE_TIMEOUT_SECONDS} seconds."
    )
    failed = {
        "status": "failed",
        "videoid": videoid,
        "error": error,
        "timed_out": True,
    }
    _set_status(videoid, failed)
    logger.warning("Queue circuit breaker opened for video %s", videoid)
    return {
        **failed,
        "updated_at": _now_iso(),
        "queue_timeout_seconds": TRANSCODE_QUEUE_TIMEOUT_SECONDS,
    }


def _enrich_processing_status(data: dict[str, Any], conn) -> dict[str, Any]:
    """Attach RQ job diagnostics when status is stuck on ``processing``."""
    job_id = data.get("job_id")
    if not job_id:
        return data

    from rq import Worker
    from rq.job import Job

    try:
        job = Job.fetch(job_id, connection=conn)
    except Exception:
        return data

    rq_status = job.get_status()
    data["rq_status"] = rq_status
    data.setdefault("queue_timeout_seconds", TRANSCODE_QUEUE_TIMEOUT_SECONDS)
    data.setdefault("job_timeout_seconds", TRANSCODE_JOB_TIMEOUT)

    if rq_status == "failed":
        data["status"] = "failed"
        data["error"] = (job.exc_info or "Transcode job failed").strip()[-500:]
        return data

    if rq_status == "started":
        data["phase"] = "running"
        return data

    if rq_status in ("queued", "deferred"):
        data["phase"] = "queued"
        workers = Worker.all(connection=conn)
        if not workers:
            data["hint"] = (
                "No transcode worker is running. Locally, start one with "
                "`rq worker --url redis://localhost:6379/0 dc-transcode`; in Docker/Railway "
                "it starts with the container, so check REDIS_URL and the deploy logs."
            )
        elif shutil.which("ffmpeg") is None:
            data["hint"] = "ffmpeg is not installed (macOS: brew install ffmpeg)."
        else:
            data["hint"] = "Waiting for worker (another job may be transcoding)…"

    return data


def get_transcode_status(videoid: int) -> dict[str, Any]:
    """
    Return processing state for admin UI: idle | processing | ready | failed.

    ``ready`` is also returned when the video has a miniokey and no active job.
    """
    conn = redis_jobs.get_redis_connection()
    raw = conn.get(_status_key(videoid))
    if raw:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        data = json.loads(raw)
        data.setdefault("queue_timeout_seconds", TRANSCODE_QUEUE_TIMEOUT_SECONDS)
        data.setdefault("job_timeout_seconds", TRANSCODE_JOB_TIMEOUT)
        if data.get("status") == "processing":
            data = _enrich_processing_status(data, conn)
            if data.get("status") == "processing":
                data = _apply_queue_circuit_breaker(videoid, data, conn)
        return data

    video = dq.get_video(videoid)
    if not video:
        return {
            "status": "unknown",
            "videoid": videoid,
            "queue_timeout_seconds": TRANSCODE_QUEUE_TIMEOUT_SECONDS,
        }
    if video.get("miniokey") and not str(video["miniokey"]).startswith("pending/"):
        return {
            "status": "ready",
            "videoid": videoid,
            "miniokey_set": True,
            "queue_timeout_seconds": TRANSCODE_QUEUE_TIMEOUT_SECONDS,
        }
    return {
        "status": "idle",
        "videoid": videoid,
        "queue_timeout_seconds": TRANSCODE_QUEUE_TIMEOUT_SECONDS,
    }


def _cancel_rq_job(job_id: str, conn) -> None:
    from rq.command import send_stop_job_command
    from rq.job import Job

    job = Job.fetch(job_id, connection=conn)
    rq_status = job.get_status()
    if rq_status == "started":
        send_stop_job_command(conn, job_id)
    job.cancel()

    if job.args and len(job.args) >= 2:
        source = Path(job.args[1])
        try:
            if source.is_file():
                source.unlink()
        except OSError as err:
            logger.warning("Could not remove upload temp file %s: %s", source, err)


def cancel_video_transcode(videoid: int) -> dict[str, Any]:
    """Stop a queued or running transcode job and mark status as cancelled."""
    conn = redis_jobs.get_redis_connection()
    raw = conn.get(_status_key(videoid))
    if not raw:
        return {**get_transcode_status(videoid), "cancelled": False}

    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    data = json.loads(raw)

    if data.get("status") != "processing":
        return {**get_transcode_status(videoid), "cancelled": False}

    job_id = data.get("job_id")
    if job_id:
        try:
            _cancel_rq_job(job_id, conn)
        except Exception as err:
            logger.warning("Could not cancel transcode job %s: %s", job_id, err)

    cancelled = {"status": "cancelled", "videoid": videoid}
    _set_status(videoid, cancelled)
    logger.info("Transcode cancelled for video %s", videoid)
    return {**cancelled, "cancelled": True}


def _object_key_for_video(videoid: int) -> str:
    return f"videos/dc/{videoid}.mp4"


def _upload_extension(filename: str | None) -> str:
    ext = Path(secure_filename(filename or "")).suffix.lstrip(".").lower()
    if ext not in ALLOWED_UPLOAD_EXTENSIONS:
        raise ValueError(
            f"Unsupported format '.{ext}'. "
            f"Allowed: {', '.join(sorted(ALLOWED_UPLOAD_EXTENSIONS))}"
        )
    return ext


def _save_upload_to_temp(upload: FileStorage) -> Path:
    if not upload or not upload.filename:
        raise ValueError("No video file provided.")

    ext = _upload_extension(upload.filename)
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    dest = TMP_DIR / f"upload-{uuid.uuid4().hex}.{ext}"
    upload.save(dest)
    return dest


def enqueue_video_upload(videoid: int, upload: FileStorage) -> dict[str, Any]:
    """
    Save an uploaded source file and enqueue background transcode.

    Returns immediately with status ``processing`` and the RQ job id.
    """
    if not dq.get_video(videoid):
        raise ValueError(f"Video {videoid} not found.")
    return _enqueue_transcode(videoid, _save_upload_to_temp(upload))


# ---------------------------------------------------------------------------
# Chunked upload: start -> chunk (repeated) -> finish, all in this container's TMP_DIR
# ---------------------------------------------------------------------------


def _upload_session_key(upload_id: str) -> str:
    return f"{UPLOAD_KEY_PREFIX}{upload_id}"


def _load_upload_session(upload_id: str, videoid: int) -> tuple[dict[str, Any], Path]:
    if not upload_id.isalnum():
        raise ValueError("Unknown upload.")
    raw = redis_jobs.get_redis_connection().get(_upload_session_key(upload_id))
    if not raw:
        raise ValueError("This upload expired or was cancelled. Start it again.")
    session = json.loads(raw)
    if session["videoid"] != videoid:
        raise ValueError("Upload does not belong to this lesson.")
    return session, Path(session["path"])


def _remove_stale_partial_uploads() -> None:
    cutoff = datetime.now(timezone.utc).timestamp() - UPLOAD_SESSION_TTL_SECONDS
    for path in TMP_DIR.glob("chunked-*.part"):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
        except OSError:
            pass


def start_chunked_upload(videoid: int, filename: str, total_size: int) -> dict[str, Any]:
    """Open an upload session and return its id plus the chunk size to use."""
    if not dq.get_video(videoid):
        raise ValueError(f"Video {videoid} not found.")
    ext = _upload_extension(filename)
    if total_size <= 0:
        raise ValueError("The video file is empty.")
    if total_size > UPLOAD_MAX_BYTES:
        raise ValueError(
            f"Video is too large (max {UPLOAD_MAX_BYTES // (1024 ** 3)} GB)."
        )

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    _remove_stale_partial_uploads()
    upload_id = uuid.uuid4().hex
    path = TMP_DIR / f"chunked-{upload_id}.{ext}.part"
    path.touch()
    redis_jobs.get_redis_connection().set(
        _upload_session_key(upload_id),
        json.dumps(
            {"videoid": videoid, "path": str(path), "ext": ext, "total_size": total_size}
        ),
        ex=UPLOAD_SESSION_TTL_SECONDS,
    )
    return {"upload_id": upload_id, "chunk_size": UPLOAD_CHUNK_BYTES}


def append_upload_chunk(
    videoid: int, upload_id: str, offset: int, stream, length: int | None
) -> dict[str, Any]:
    """
    Write one chunk at ``offset``. Re-sending a chunk (a retry) overwrites
    from that offset, so a dropped request can simply be sent again.
    """
    session, path = _load_upload_session(upload_id, videoid)
    if not length or length > UPLOAD_CHUNK_MAX_BYTES:
        raise ValueError("Chunk is missing or too large.")
    received = path.stat().st_size
    if offset > received:
        raise ValueError(f"Chunk out of order (have {received} bytes).")
    if offset + length > session["total_size"]:
        raise ValueError("Chunk goes past the end of the file.")

    with path.open("r+b") as out:
        out.truncate(offset)
        out.seek(offset)
        shutil.copyfileobj(stream, out, 1024 * 1024)
    received = path.stat().st_size
    if received != offset + length:
        raise ValueError("Chunk was cut off. Retry it.")

    redis_jobs.get_redis_connection().expire(
        _upload_session_key(upload_id), UPLOAD_SESSION_TTL_SECONDS
    )
    return {"received": received, "total_size": session["total_size"]}


def finish_chunked_upload(videoid: int, upload_id: str) -> dict[str, Any]:
    """Check the file is complete, then hand it to the transcode worker."""
    session, path = _load_upload_session(upload_id, videoid)
    received = path.stat().st_size if path.is_file() else 0
    if received != session["total_size"]:
        raise ValueError(
            f"Upload incomplete ({received} of {session['total_size']} bytes)."
        )
    source_path = path.with_name(f"upload-{upload_id}.{session['ext']}")
    path.rename(source_path)
    redis_jobs.get_redis_connection().delete(_upload_session_key(upload_id))
    return _enqueue_transcode(videoid, source_path)


def abort_chunked_upload(videoid: int, upload_id: str) -> None:
    try:
        _, path = _load_upload_session(upload_id, videoid)
    except ValueError:
        return
    redis_jobs.get_redis_connection().delete(_upload_session_key(upload_id))
    try:
        path.unlink(missing_ok=True)
    except OSError as err:
        logger.warning("Could not remove partial upload %s: %s", path, err)


def _enqueue_transcode(videoid: int, source_path: Path) -> dict[str, Any]:
    queue = redis_jobs.get_queue(TRANSCODE_QUEUE)
    job = queue.enqueue(
        transcode_video_job,
        videoid,
        str(source_path),
        job_timeout=TRANSCODE_JOB_TIMEOUT,
        result_ttl=86400,
        failure_ttl=86400,
    )

    started_at = _now_iso()
    _set_status(
        videoid,
        {
            "status": "processing",
            "job_id": job.id,
            "videoid": videoid,
            "started_at": started_at,
        },
    )

    return {
        "status": "processing",
        "job_id": job.id,
        "videoid": videoid,
        "phase": "queued",
        "queue_timeout_seconds": TRANSCODE_QUEUE_TIMEOUT_SECONDS,
    }


def transcode_video_job(videoid: int, source_path: str) -> None:
    """
    RQ worker: ffmpeg → MinIO upload → update video.miniokey via dcqueries.

    Cleans up temp files on success or failure. Logs errors and marks job failed
    without crashing the worker process.
    """
    source = Path(source_path)
    output_path = TMP_DIR / f"transcoded-{videoid}-{uuid.uuid4().hex}.mp4"
    object_key = _object_key_for_video(videoid)

    try:
        TMP_DIR.mkdir(parents=True, exist_ok=True)
        _run_ffmpeg(source, output_path)

        miniIO.upload_file(output_path, object_key, content_type="video/mp4")
        updated = dq.update_video_miniokey(videoid, object_key)
        if not updated:
            raise RuntimeError(f"Could not update miniokey for video {videoid}")

        _set_status(
            videoid,
            {
                "status": "ready",
                "videoid": videoid,
                "object_key": object_key,
            },
        )
        logger.info("Transcode complete for video %s → %s", videoid, object_key)

    except Exception as exc:
        logger.exception("Transcode failed for video %s: %s", videoid, exc)
        _set_status(
            videoid,
            {
                "status": "failed",
                "videoid": videoid,
                "error": str(exc),
            },
        )
    finally:
        for path in (source, output_path):
            try:
                if path.is_file():
                    path.unlink()
            except OSError as err:
                logger.warning("Could not remove temp file %s: %s", path, err)


def _run_ffmpeg(source: Path, output: Path) -> None:
    """
    Transcode to web-optimized MP4: H.264 ~720p, AAC, faststart (moov at front).

    Requires ffmpeg on PATH (apt-get install ffmpeg / brew install ffmpeg).
    """
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(source),
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-crf",
        "23",
        "-vf",
        "scale=-2:720",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-movflags",
        "+faststart",
        str(output),
    ]
    result = subprocess.run(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
        # Detach from the RQ worker's terminal so Ctrl+Z / job-control cannot
        # suspend ffmpeg while the worker waits forever.
        start_new_session=True,
    )
    if result.returncode != 0:
        stderr = (result.stderr or "").strip()[-2000:]
        raise RuntimeError(f"ffmpeg exited {result.returncode}: {stderr}")


def get_video_stream_url(
    videoid: int,
    requesting_student: dict[str, Any] | None,
    *,
    is_admin: bool = False,
    is_staff: bool = False,
) -> str | None:
    """
    Return a presigned MinIO URL for playback if authorized.

    Students must pass division + branch checks via dcqueries.
    Platform admins and cohort leaders may stream any uploaded video.
    """
    video = dq.get_video(videoid)
    if not video or not video.get("miniokey"):
        return None

    miniokey = video["miniokey"]
    if str(miniokey).startswith("pending/"):
        return None

    if is_admin or is_staff:
        pass
    elif requesting_student:
        if not dq.student_can_access_video(requesting_student["studentid"], videoid):
            raise StreamingAuthError("Not authorized to watch this video.")
    else:
        raise StreamingAuthError("Authentication required.")

    if not miniIO.object_exists(miniokey):
        logger.warning("Video %s miniokey missing in bucket: %s", videoid, miniokey)
        return None

    # Presigned URL only — MinIO + reverse proxy serve bytes and Range requests.
    return miniIO.presigned_get_url(
        miniokey,
        expires_seconds=PRESIGNED_EXPIRY_SECONDS,
    )
