"""
AARI Educational Suite — Data Center program database queries (dccourse).

Serves these app pages/features:
  - Login (student / admin auth)
  - Division track home, weekly modules, video library
  - Video player page (progress, resume position, instructions)
  - Graded assignment submit and assignments performance page
  - Admin grading queue and submission analytics dashboard
  - Cohort roster (About page with bios)
  - Messenger (general, division, direct channels)
  - Admin CRUD (cohorts, students, weeks, videos, passwords)

NOT YET SUPPORTED (no matching schema — do not invent columns):
  - Video streaming, presigned URLs, or MinIO object upload/download
    (miniokey strings are stored/returned as-is; object access is elsewhere)
  - Push notifications or read receipts on messages
  - Assignment due dates or late penalties
  - Multiple submission attempts per (student, video) — one row assumed
  - Platform-wide admin cross-cohort roster without explicit membership
  - Course/division CRUD (Course rows are seeded; no create/update course)

Database access: SQLAlchemy Core (raw SQL via text(), no ORM).
All queries run against the dccourse database.
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

DC_DATABASE = "dccourse"

_engine: Engine | None = None


def _get_engine() -> Engine:
    global _engine
    if _engine is None:
        user = os.getenv("MYSQL_USER", "root")
        password = quote_plus(os.getenv("MYSQL_PASSWORD", ""))
        host = os.getenv("MYSQL_HOST", "localhost")
        port = os.getenv("MYSQL_PORT", "3306")
        url = (
            f"mysql+pymysql://{user}:{password}@{host}:{port}"
            f"/{DC_DATABASE}?charset=utf8mb4"
        )
        _engine = create_engine(
            url,
            pool_pre_ping=True,
            future=True,
            connect_args={"charset": "utf8mb4"},
        )
    return _engine


@contextmanager
def _connection() -> Iterator[Connection]:
    with _get_engine().connect() as conn:
        yield conn


def _one(sql: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
    with _connection() as conn:
        row = conn.execute(text(sql), params or {}).mappings().first()
        return dict(row) if row else None


def _all(sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    with _connection() as conn:
        result = conn.execute(text(sql), params or {})
        return [dict(row) for row in result.mappings().all()]


def _run(sql: str, params: dict[str, Any] | None = None) -> int:
    with _connection() as conn:
        result = conn.execute(text(sql), params or {})
        conn.commit()
        return result.rowcount


def _insert(sql: str, params: dict[str, Any] | None = None) -> int:
    with _connection() as conn:
        result = conn.execute(text(sql), params or {})
        conn.commit()
        return int(result.lastrowid or 0)


# ---------------------------------------------------------------------------
# Integrity helpers
# ---------------------------------------------------------------------------


def student_division(studentid: int) -> int | None:
    """Return the student's division courseid, or None if not found."""
    row = _one(
        "SELECT courseid FROM student WHERE studentid = :studentid LIMIT 1",
        {"studentid": studentid},
    )
    return row["courseid"] if row else None


def verify_assignment_owner(assignmentid: int, studentid: int) -> bool:
    """Return True if the assignment belongs to the given student."""
    row = _one(
        """
        SELECT 1 AS ok
        FROM assignment
        WHERE assignmentid = :assignmentid AND studentid = :studentid
        LIMIT 1
        """,
        {"assignmentid": assignmentid, "studentid": studentid},
    )
    return row is not None


def is_channel_member(channelid: int, member_type: str, member_id: int) -> bool:
    """Return True if the polymorphic member belongs to the channel."""
    row = _one(
        """
        SELECT 1 AS ok
        FROM channel_member
        WHERE channelid = :channelid
          AND member_type = :member_type
          AND member_id = :member_id
        LIMIT 1
        """,
        {"channelid": channelid, "member_type": member_type, "member_id": member_id},
    )
    return row is not None


def _video_in_course(videoid: int, courseid: int) -> bool:
    row = _one(
        """
        SELECT 1 AS ok
        FROM video v
        JOIN Week w ON w.weekid = v.weekid
        WHERE v.videoid = :videoid AND w.courseid = :courseid
        LIMIT 1
        """,
        {"videoid": videoid, "courseid": courseid},
    )
    return row is not None


# ---------------------------------------------------------------------------
# Auth (password included for verification only)
# ---------------------------------------------------------------------------


def get_student_by_email(email: str) -> dict[str, Any] | None:
    """Return full student row including password hash for auth verification."""
    return _one(
        """
        SELECT studentid, fname, lname, email, password, courseid, cohortid, bio
        FROM student
        WHERE email = :email
        LIMIT 1
        """,
        {"email": email},
    )


def get_admin_by_email(email: str) -> dict[str, Any] | None:
    """Return full admin row including password hash for auth verification."""
    return _one(
        """
        SELECT adminid, fname, lname, email, password, cohortid
        FROM admin
        WHERE email = :email
        LIMIT 1
        """,
        {"email": email},
    )


def get_student_public(studentid: int) -> dict[str, Any] | None:
    """Return student profile without password."""
    return _one(
        """
        SELECT studentid, fname, lname, email, courseid, cohortid, bio
        FROM student
        WHERE studentid = :studentid
        LIMIT 1
        """,
        {"studentid": studentid},
    )


def get_admin_public(adminid: int) -> dict[str, Any] | None:
    """Return admin profile without password."""
    return _one(
        """
        SELECT adminid, fname, lname, email, cohortid
        FROM admin
        WHERE adminid = :adminid
        LIMIT 1
        """,
        {"adminid": adminid},
    )


def resolve_member_name(member_type: str, member_id: int) -> str | None:
    """
    Resolve a polymorphic (member_type, member_id) pair to a display name.

    Returns 'First Last' or None if the referenced row does not exist.
    """
    if member_type == "student":
        row = _one(
            """
            SELECT fname, lname FROM student
            WHERE studentid = :member_id LIMIT 1
            """,
            {"member_id": member_id},
        )
    elif member_type == "admin":
        row = _one(
            """
            SELECT fname, lname FROM admin
            WHERE adminid = :member_id LIMIT 1
            """,
            {"member_id": member_id},
        )
    else:
        return None
    if not row:
        return None
    return f"{row['fname']} {row['lname']}"


# ---------------------------------------------------------------------------
# Course / division structure
# ---------------------------------------------------------------------------


def get_course(courseid: int) -> dict[str, Any] | None:
    """Return a single division track (Course row), or None."""
    return _one(
        """
        SELECT courseid, name, description, teacher
        FROM Course
        WHERE courseid = :courseid
        LIMIT 1
        """,
        {"courseid": courseid},
    )


def get_all_courses() -> list[dict[str, Any]]:
    """Return all division tracks ordered by courseid."""
    return _all(
        """
        SELECT courseid, name, description, teacher
        FROM Course
        ORDER BY courseid
        """
    )


def get_weeks_for_course(courseid: int) -> list[dict[str, Any]]:
    """Return all weeks for a division, ordered by week number."""
    return _all(
        """
        SELECT weekid, courseid, subject, num, description
        FROM Week
        WHERE courseid = :courseid
        ORDER BY num
        """,
        {"courseid": courseid},
    )


def get_week(weekid: int) -> dict[str, Any] | None:
    """Return a single week row, or None."""
    return _one(
        """
        SELECT weekid, courseid, subject, num, description
        FROM Week
        WHERE weekid = :weekid
        LIMIT 1
        """,
        {"weekid": weekid},
    )


def get_videos_for_week(weekid: int) -> list[dict[str, Any]]:
    """Return all videos for a week, ordered by lecture day then videoid."""
    return _all(
        """
        SELECT videoid, weekid, day, title, miniokey, script, instructions, reflection
        FROM video
        WHERE weekid = :weekid
        ORDER BY day, videoid
        """,
        {"weekid": weekid},
    )


def get_video(videoid: int) -> dict[str, Any] | None:
    """Return a single video row including instructions, or None."""
    return _one(
        """
        SELECT videoid, weekid, day, title, miniokey, script, instructions, reflection
        FROM video
        WHERE videoid = :videoid
        LIMIT 1
        """,
        {"videoid": videoid},
    )


def get_videos_for_course(courseid: int) -> list[dict[str, Any]]:
    """Return all videos in a division via Week, ordered by week num then videoid."""
    return _all(
        """
        SELECT v.videoid, v.weekid, v.day, v.title, v.miniokey, v.script, v.instructions, v.reflection,
               w.num AS week_num, w.subject AS week_subject
        FROM video v
        JOIN Week w ON w.weekid = v.weekid
        WHERE w.courseid = :courseid
        ORDER BY w.num, v.day, v.videoid
        """,
        {"courseid": courseid},
    )


# ---------------------------------------------------------------------------
# About / cohort
# ---------------------------------------------------------------------------


def student_in_cohort(studentid: int, cohortid: int) -> bool:
    """Return True if the student belongs to the given cohort."""
    row = _one(
        """
        SELECT studentid FROM student
        WHERE studentid = :studentid AND cohortid = :cohortid
        LIMIT 1
        """,
        {"studentid": studentid, "cohortid": cohortid},
    )
    return row is not None


def get_cohort(cohortid: int) -> dict[str, Any] | None:
    """Return a cohort row, or None."""
    return _one(
        """
        SELECT cohortid, region, name
        FROM cohort
        WHERE cohortid = :cohortid
        LIMIT 1
        """,
        {"cohortid": cohortid},
    )


def get_all_students(
    cohortid: int | None = None,
    courseid: int | None = None,
) -> list[dict[str, Any]]:
    """List students for admin management, optionally filtered by cohort or division."""
    clauses = ["1=1"]
    params: dict[str, Any] = {}
    if cohortid is not None:
        clauses.append("s.cohortid = :cohortid")
        params["cohortid"] = cohortid
    if courseid is not None:
        clauses.append("s.courseid = :courseid")
        params["courseid"] = courseid
    where = " AND ".join(clauses)
    return _all(
        f"""
        SELECT s.studentid, s.fname, s.lname, s.email, s.bio,
               s.courseid, s.cohortid,
               c.name AS division_name,
               co.name AS cohort_name, co.region AS cohort_region
        FROM student s
        JOIN Course c ON c.courseid = s.courseid
        JOIN cohort co ON co.cohortid = s.cohortid
        WHERE {where}
        ORDER BY co.name, c.name, s.lname, s.fname
        """,
        params,
    )


def get_students_progress_for_course(
    courseid: int,
    cohortid: int | None = None,
) -> list[dict[str, Any]]:
    """Per-student watch progress for one division track (admin progress page)."""
    cohort_clause = "AND s.cohortid = :cohortid" if cohortid is not None else ""
    params: dict[str, Any] = {"courseid": courseid}
    if cohortid is not None:
        params["cohortid"] = cohortid
    return _all(
        f"""
        SELECT s.studentid, s.fname, s.lname, s.email,
               COUNT(DISTINCT v.videoid) AS total_videos,
               SUM(CASE WHEN p.watched THEN 1 ELSE 0 END) AS watched_videos
        FROM student s
        JOIN Week w ON w.courseid = s.courseid
        JOIN video v ON v.weekid = w.weekid
        LEFT JOIN progress p
            ON p.videoid = v.videoid AND p.studentid = s.studentid
        WHERE s.courseid = :courseid
          {cohort_clause}
        GROUP BY s.studentid, s.fname, s.lname, s.email
        ORDER BY s.lname, s.fname
        """,
        params,
    )


def get_cohort_roster(cohortid: int) -> list[dict[str, Any]]:
    """
    Return all students in a cohort with division name and bio (no passwords).

    Powers the roster / About page.
    """
    return _all(
        """
        SELECT s.studentid, s.fname, s.lname, s.email, s.bio,
               s.courseid, c.name AS division_name
        FROM student s
        JOIN Course c ON c.courseid = s.courseid
        WHERE s.cohortid = :cohortid
        ORDER BY c.name, s.lname, s.fname
        """,
        {"cohortid": cohortid},
    )


# ---------------------------------------------------------------------------
# Videos + progress
# ---------------------------------------------------------------------------


def get_or_create_progress(studentid: int, videoid: int) -> dict[str, Any] | None:
    """Return the progress row for (student, video), creating one if missing."""
    row = _one(
        """
        SELECT studentid, videoid, watched, last_position, updated_at
        FROM progress
        WHERE studentid = :studentid AND videoid = :videoid
        LIMIT 1
        """,
        {"studentid": studentid, "videoid": videoid},
    )
    if row:
        return row

    _insert(
        """
        INSERT INTO progress (studentid, videoid, watched, last_position)
        VALUES (:studentid, :videoid, FALSE, 0)
        """,
        {"studentid": studentid, "videoid": videoid},
    )
    return _one(
        """
        SELECT studentid, videoid, watched, last_position, updated_at
        FROM progress
        WHERE studentid = :studentid AND videoid = :videoid
        LIMIT 1
        """,
        {"studentid": studentid, "videoid": videoid},
    )


def mark_video_watched(studentid: int, videoid: int) -> dict[str, Any] | None:
    """Set watched=true for (student, video). Creates progress row if needed."""
    get_or_create_progress(studentid, videoid)
    _run(
        """
        UPDATE progress
        SET watched = TRUE
        WHERE studentid = :studentid AND videoid = :videoid
        """,
        {"studentid": studentid, "videoid": videoid},
    )
    return _one(
        """
        SELECT studentid, videoid, watched, last_position, updated_at
        FROM progress
        WHERE studentid = :studentid AND videoid = :videoid
        LIMIT 1
        """,
        {"studentid": studentid, "videoid": videoid},
    )


def update_last_position(studentid: int, videoid: int, seconds: int) -> dict[str, Any] | None:
    """Update resume position in seconds for (student, video)."""
    get_or_create_progress(studentid, videoid)
    _run(
        """
        UPDATE progress
        SET last_position = :seconds
        WHERE studentid = :studentid AND videoid = :videoid
        """,
        {"studentid": studentid, "videoid": videoid, "seconds": seconds},
    )
    return _one(
        """
        SELECT studentid, videoid, watched, last_position, updated_at
        FROM progress
        WHERE studentid = :studentid AND videoid = :videoid
        LIMIT 1
        """,
        {"studentid": studentid, "videoid": videoid},
    )


def get_progress_for_student(studentid: int) -> list[dict[str, Any]]:
    """Return all progress rows for a student (Progress page)."""
    return _all(
        """
        SELECT p.studentid, p.videoid, p.watched, p.last_position, p.updated_at,
               v.title AS video_title, w.num AS week_num, v.day AS day_num, w.courseid
        FROM progress p
        JOIN video v ON v.videoid = p.videoid
        JOIN Week w ON w.weekid = v.weekid
        WHERE p.studentid = :studentid
        ORDER BY w.num, v.day, v.videoid
        """,
        {"studentid": studentid},
    )


def get_course_completion(studentid: int) -> dict[str, Any]:
    """
    Return watched vs total video counts and completion percentage for the
    student's division (courseid).
    """
    row = _one(
        """
        SELECT
            COUNT(v.videoid) AS total_videos,
            SUM(CASE WHEN p.watched = TRUE THEN 1 ELSE 0 END) AS watched_videos
        FROM student s
        JOIN Week w ON w.courseid = s.courseid
        JOIN video v ON v.weekid = w.weekid
        LEFT JOIN progress p
            ON p.videoid = v.videoid AND p.studentid = s.studentid
        WHERE s.studentid = :studentid
        GROUP BY s.studentid
        """,
        {"studentid": studentid},
    )
    if not row or row["total_videos"] == 0:
        return {
            "total_videos": 0,
            "watched_videos": 0,
            "completion_pct": 0,
        }
    total = int(row["total_videos"])
    watched = int(row["watched_videos"] or 0)
    return {
        "total_videos": total,
        "watched_videos": watched,
        "completion_pct": int(watched / total * 100),
    }


def get_resume_point(studentid: int) -> dict[str, Any] | None:
    """
    Return the most recently updated in-progress video for 'pick up where you left off'.

    Prefers unwatched videos with last_position > 0; falls back to latest progress row.
    """
    row = _one(
        """
        SELECT p.studentid, p.videoid, p.watched, p.last_position, p.updated_at,
               v.title AS video_title, v.miniokey, w.num AS week_num, v.day AS day_num, w.courseid
        FROM progress p
        JOIN video v ON v.videoid = p.videoid
        JOIN Week w ON w.weekid = v.weekid
        JOIN student s ON s.studentid = p.studentid AND w.courseid = s.courseid
        WHERE p.studentid = :studentid
          AND p.watched = FALSE
          AND p.last_position > 0
        ORDER BY p.updated_at DESC
        LIMIT 1
        """,
        {"studentid": studentid},
    )
    if row:
        return row
    return _one(
        """
        SELECT p.studentid, p.videoid, p.watched, p.last_position, p.updated_at,
               v.title AS video_title, v.miniokey, w.num AS week_num, v.day AS day_num, w.courseid
        FROM progress p
        JOIN video v ON v.videoid = p.videoid
        JOIN Week w ON w.weekid = v.weekid
        JOIN student s ON s.studentid = p.studentid AND w.courseid = s.courseid
        WHERE p.studentid = :studentid
        ORDER BY p.updated_at DESC
        LIMIT 1
        """,
        {"studentid": studentid},
    )


# ---------------------------------------------------------------------------
# Assignments — student (graded)
# ---------------------------------------------------------------------------


def submit_assignment(
    videoid: int,
    studentid: int,
    miniokey: str,
) -> dict[str, Any] | None:
    """
    Insert a graded assignment submission (status defaults to 'submitted').

    Returns None if the student already has a submission for this video, or if
    the video is not in the student's division track.
    """
    courseid = student_division(studentid)
    if courseid is None or not _video_in_course(videoid, courseid):
        return None
    if get_student_assignment_for_video(studentid, videoid) is not None:
        return None

    assignmentid = _insert(
        """
        INSERT INTO assignment (videoid, studentid, miniokey)
        VALUES (:videoid, :studentid, :miniokey)
        """,
        {"videoid": videoid, "studentid": studentid, "miniokey": miniokey},
    )
    return get_assignment(assignmentid)


def get_assignment(assignmentid: int) -> dict[str, Any] | None:
    """Return a single assignment row, or None."""
    return _one(
        """
        SELECT assignmentid, videoid, studentid, miniokey, status, feedback, submitted_at
        FROM assignment
        WHERE assignmentid = :assignmentid
        LIMIT 1
        """,
        {"assignmentid": assignmentid},
    )


def get_student_assignment_for_video(
    studentid: int,
    videoid: int,
) -> dict[str, Any] | None:
    """Return the student's existing submission for a video, or None."""
    return _one(
        """
        SELECT assignmentid, videoid, studentid, miniokey, status, feedback, submitted_at
        FROM assignment
        WHERE studentid = :studentid AND videoid = :videoid
        LIMIT 1
        """,
        {"studentid": studentid, "videoid": videoid},
    )


def get_assignments_for_course(
    courseid: int,
    cohortid: int | None = None,
) -> list[dict[str, Any]]:
    """Return submissions in a division track, optionally limited to one cohort."""
    cohort_clause = "AND s.cohortid = :cohortid" if cohortid is not None else ""
    params: dict[str, Any] = {"courseid": courseid}
    if cohortid is not None:
        params["cohortid"] = cohortid
    return _all(
        f"""
        SELECT a.assignmentid, a.videoid, a.studentid, a.miniokey,
               a.status, a.feedback, a.submitted_at,
               v.title AS video_title, w.num AS week_num, v.day AS day_num, w.subject AS week_subject,
               s.fname, s.lname, s.email
        FROM assignment a
        JOIN video v ON v.videoid = a.videoid
        JOIN Week w ON w.weekid = v.weekid
        JOIN student s ON s.studentid = a.studentid
        WHERE w.courseid = :courseid
          {cohort_clause}
        ORDER BY a.submitted_at DESC
        """,
        params,
    )


def get_assignments_for_student(studentid: int) -> list[dict[str, Any]]:
    """
    Return all submissions for a student with video title, status, and feedback.

    Powers the Assignments / performance reviews page.
    """
    return _all(
        """
        SELECT a.assignmentid, a.videoid, a.studentid, a.miniokey,
               a.status, a.feedback, a.submitted_at,
               v.title AS video_title, w.num AS week_num, v.day AS day_num, w.subject AS week_subject
        FROM assignment a
        JOIN video v ON v.videoid = a.videoid
        JOIN Week w ON w.weekid = v.weekid
        WHERE a.studentid = :studentid
        ORDER BY a.submitted_at DESC
        """,
        {"studentid": studentid},
    )


# ---------------------------------------------------------------------------
# Assignments — admin grading
# ---------------------------------------------------------------------------


def get_submissions_for_video(
    videoid: int,
    cohortid: int | None = None,
) -> list[dict[str, Any]]:
    """Return student submissions for one video (grading queue), optionally by cohort."""
    cohort_clause = "AND s.cohortid = :cohortid" if cohortid is not None else ""
    params: dict[str, Any] = {"videoid": videoid}
    if cohortid is not None:
        params["cohortid"] = cohortid
    return _all(
        f"""
        SELECT a.assignmentid, a.videoid, a.studentid, a.miniokey,
               a.status, a.feedback, a.submitted_at,
               s.fname, s.lname, s.email
        FROM assignment a
        JOIN student s ON s.studentid = a.studentid
        WHERE a.videoid = :videoid
          {cohort_clause}
        ORDER BY a.submitted_at
        """,
        params,
    )


def grade_assignment(
    assignmentid: int,
    status: str,
    feedback: str | None,
) -> dict[str, Any] | None:
    """
    Set assignment status to 'satisfactory' or 'unsatisfactory' with feedback.

    Returns None if assignmentid not found or status is invalid.
    """
    if status not in ("satisfactory", "unsatisfactory"):
        return None
    rows = _run(
        """
        UPDATE assignment
        SET status = :status, feedback = :feedback
        WHERE assignmentid = :assignmentid
        """,
        {"assignmentid": assignmentid, "status": status, "feedback": feedback},
    )
    if rows == 0:
        return None
    return get_assignment(assignmentid)


def get_submission_analytics(
    courseid: int,
    cohortid: int | None = None,
) -> dict[str, Any]:
    """
    Admin dashboard data: per-video submission counts and students falling behind.

    When cohortid is set, counts and behind-list are limited to that cohort.
    """
    cohort_assignment_join = ""
    cohort_filter = ""
    params: dict[str, Any] = {"courseid": courseid}
    if cohortid is not None:
        cohort_assignment_join = """
        LEFT JOIN (
            SELECT a.*
            FROM assignment a
            JOIN student s ON s.studentid = a.studentid
            WHERE s.cohortid = :cohortid
        ) a ON a.videoid = v.videoid
        """
        cohort_filter = "AND s.cohortid = :cohortid"
        params["cohortid"] = cohortid
    else:
        cohort_assignment_join = "LEFT JOIN assignment a ON a.videoid = v.videoid"

    by_video = _all(
        f"""
        SELECT v.videoid, v.title AS video_title, w.num AS week_num, v.day AS day_num,
               COUNT(a.assignmentid) AS submitted_count,
               SUM(CASE WHEN a.status IN ('satisfactory', 'unsatisfactory') THEN 1 ELSE 0 END) AS graded_count,
               SUM(CASE WHEN a.status = 'submitted' THEN 1 ELSE 0 END) AS ungraded_count
        FROM video v
        JOIN Week w ON w.weekid = v.weekid
        {cohort_assignment_join}
        WHERE w.courseid = :courseid
        GROUP BY v.videoid, v.title, w.num, v.day
        ORDER BY w.num, v.day, v.videoid
        """,
        params,
    )

    students_behind = _all(
        f"""
        SELECT s.studentid, s.fname, s.lname, v.videoid, v.title AS video_title,
               w.num AS week_num, v.day AS day_num
        FROM student s
        JOIN Week w ON w.courseid = s.courseid
        JOIN video v ON v.weekid = w.weekid
        LEFT JOIN assignment a
            ON a.videoid = v.videoid AND a.studentid = s.studentid
        WHERE s.courseid = :courseid
          {cohort_filter}
          AND a.assignmentid IS NULL
        ORDER BY s.lname, s.fname, w.num
        """,
        params,
    )

    return {"by_video": by_video, "students_behind": students_behind}


# ---------------------------------------------------------------------------
# Messenger
# ---------------------------------------------------------------------------


def get_channels_for_cohort(cohortid: int) -> list[dict[str, Any]]:
    """Return general and division channels for a cohort (excludes direct DMs)."""
    return _all(
        """
        SELECT channelid, cohortid, type, name
        FROM channel
        WHERE cohortid = :cohortid AND type IN ('general', 'division')
        ORDER BY FIELD(type, 'general', 'division'), name
        """,
        {"cohortid": cohortid},
    )


def get_member_cohortid(member_type: str, member_id: int) -> int | None:
    """Return the cohortid for a student or cohort-scoped admin, or None."""
    if member_type == "student":
        row = _one(
            "SELECT cohortid FROM student WHERE studentid = :member_id LIMIT 1",
            {"member_id": member_id},
        )
    elif member_type == "admin":
        row = _one(
            "SELECT cohortid FROM admin WHERE adminid = :member_id LIMIT 1",
            {"member_id": member_id},
        )
    else:
        return None
    return row["cohortid"] if row else None


def get_channel(channelid: int) -> dict[str, Any] | None:
    """Return a single channel row, or None."""
    return _one(
        """
        SELECT channelid, cohortid, type, name
        FROM channel
        WHERE channelid = :channelid
        LIMIT 1
        """,
        {"channelid": channelid},
    )


def _get_channel(channelid: int) -> dict[str, Any] | None:
    return get_channel(channelid)


def channel_display_name(
    channelid: int,
    member_type: str,
    member_id: int,
) -> str:
    """Return a human label for a channel in the messenger sidebar."""
    channel = get_channel(channelid)
    if not channel:
        return "Channel"
    if channel["type"] == "general":
        return "General"
    if channel["type"] == "direct":
        return _direct_channel_peer_name(channelid, member_type, member_id) or "Direct message"
    return channel["name"] or "Channel"


def can_access_channel(channelid: int, member_type: str, member_id: int) -> bool:
    """
    Authorize channel access.

    - general: any student or cohort admin in the same cohort (whole-cohort chat)
    - division / direct: explicit channel_member row required
    """
    channel = _get_channel(channelid)
    if not channel:
        return False
    if is_channel_member(channelid, member_type, member_id):
        return True
    if channel["type"] == "general":
        member_cohort = get_member_cohortid(member_type, member_id)
        return member_cohort is not None and member_cohort == channel["cohortid"]
    return False


def _direct_channel_peer_name(
    channelid: int,
    member_type: str,
    member_id: int,
) -> str | None:
    """Return the display name of the other participant in a direct channel."""
    rows = _all(
        """
        SELECT cm.member_type, cm.member_id,
               CASE
                   WHEN cm.member_type = 'student' THEN CONCAT(s.fname, ' ', s.lname)
                   WHEN cm.member_type = 'admin' THEN CONCAT(a.fname, ' ', a.lname)
               END AS member_name
        FROM channel_member cm
        LEFT JOIN student s
            ON cm.member_type = 'student' AND cm.member_id = s.studentid
        LEFT JOIN admin a
            ON cm.member_type = 'admin' AND cm.member_id = a.adminid
        WHERE cm.channelid = :channelid
        """,
        {"channelid": channelid},
    )
    for row in rows:
        if row["member_type"] != member_type or row["member_id"] != member_id:
            return row.get("member_name")
    return None


def find_direct_channel(
    cohortid: int,
    member_a_type: str,
    member_a_id: int,
    member_b_type: str,
    member_b_id: int,
) -> dict[str, Any] | None:
    """Return an existing direct channel between two members, or None."""
    row = _one(
        """
        SELECT c.channelid, c.cohortid, c.type, c.name
        FROM channel c
        JOIN channel_member ma
            ON ma.channelid = c.channelid
           AND ma.member_type = :a_type AND ma.member_id = :a_id
        JOIN channel_member mb
            ON mb.channelid = c.channelid
           AND mb.member_type = :b_type AND mb.member_id = :b_id
        WHERE c.cohortid = :cohortid AND c.type = 'direct'
        LIMIT 1
        """,
        {
            "cohortid": cohortid,
            "a_type": member_a_type,
            "a_id": member_a_id,
            "b_type": member_b_type,
            "b_id": member_b_id,
        },
    )
    return row


def find_or_create_direct_channel(
    cohortid: int,
    member_a_type: str,
    member_a_id: int,
    member_b_type: str,
    member_b_id: int,
) -> dict[str, Any] | None:
    """Find an existing DM channel or create one. Caller validates (type, id) pairs."""
    existing = find_direct_channel(
        cohortid, member_a_type, member_a_id, member_b_type, member_b_id
    )
    if existing:
        return existing
    return create_direct_channel(
        cohortid, member_a_type, member_a_id, member_b_type, member_b_id
    )


def get_cohort_contacts(
    member_type: str,
    member_id: int,
) -> list[dict[str, Any]]:
    """
    Return cohort members the user can start a direct message with (excludes self).

    Includes students and cohort-scoped admins in the same cohort.
    """
    cohortid = get_member_cohortid(member_type, member_id)
    if cohortid is None:
        return []
    contacts: list[dict[str, Any]] = []
    for row in _all(
        """
        SELECT 'student' AS member_type, studentid AS member_id,
               fname, lname, email, c.name AS division_name
        FROM student s
        JOIN Course c ON c.courseid = s.courseid
        WHERE s.cohortid = :cohortid
        ORDER BY lname, fname
        """,
        {"cohortid": cohortid},
    ):
        if member_type == "student" and row["member_id"] == member_id:
            continue
        contacts.append(
            {
                "member_type": "student",
                "member_id": row["member_id"],
                "name": f"{row['fname']} {row['lname']}",
                "email": row["email"],
                "division_name": row["division_name"],
            }
        )
    for row in _all(
        """
        SELECT 'admin' AS member_type, adminid AS member_id, fname, lname, email
        FROM admin
        WHERE cohortid = :cohortid
        ORDER BY lname, fname
        """,
        {"cohortid": cohortid},
    ):
        if member_type == "admin" and row["member_id"] == member_id:
            continue
        contacts.append(
            {
                "member_type": "admin",
                "member_id": row["member_id"],
                "name": f"{row['fname']} {row['lname']}",
                "email": row["email"],
                "division_name": "Admin",
            }
        )
    return contacts


def get_channels_for_member(member_type: str, member_id: int) -> dict[str, Any]:
    """
    Return messenger channels grouped for the sidebar.

    - general: whole-cohort chat (same cohortid)
    - division: track group chat(s) — student's division; admins see all cohort divisions
    - direct: 1:1 channels with resolved peer display names
    """
    cohortid = get_member_cohortid(member_type, member_id)
    result: dict[str, Any] = {"general": None, "division": [], "direct": []}
    if cohortid is None:
        member_channels = _all(
            """
            SELECT c.channelid, c.cohortid, c.type, c.name
            FROM channel_member cm
            JOIN channel c ON c.channelid = cm.channelid
            WHERE cm.member_type = :member_type AND cm.member_id = :member_id
            ORDER BY c.type, c.name
            """,
            {"member_type": member_type, "member_id": member_id},
        )
        for ch in member_channels:
            if ch["type"] == "direct":
                ch["display_name"] = _direct_channel_peer_name(
                    ch["channelid"], member_type, member_id
                ) or "Direct message"
                result["direct"].append(ch)
        return result

    general = _one(
        """
        SELECT channelid, cohortid, type, name
        FROM channel
        WHERE cohortid = :cohortid AND type = 'general'
        LIMIT 1
        """,
        {"cohortid": cohortid},
    )
    if general:
        general["display_name"] = "General"
        result["general"] = general

    if member_type == "student":
        row = _one(
            "SELECT courseid FROM student WHERE studentid = :member_id LIMIT 1",
            {"member_id": member_id},
        )
        if row:
            div = _one(
                """
                SELECT ch.channelid, ch.cohortid, ch.type, ch.name
                FROM channel ch
                JOIN Course co ON co.name = ch.name
                WHERE ch.cohortid = :cohortid
                  AND ch.type = 'division'
                  AND co.courseid = :courseid
                LIMIT 1
                """,
                {"cohortid": cohortid, "courseid": row["courseid"]},
            )
            if div:
                div["display_name"] = div["name"]
                result["division"].append(div)
    else:
        divisions = _all(
            """
            SELECT c.channelid, c.cohortid, c.type, c.name
            FROM channel c
            WHERE c.cohortid = :cohortid AND c.type = 'division'
            ORDER BY c.name
            """,
            {"cohortid": cohortid},
        )
        for div in divisions:
            div["display_name"] = div["name"]
            result["division"].append(div)

    direct_rows = _all(
        """
        SELECT c.channelid, c.cohortid, c.type, c.name
        FROM channel_member cm
        JOIN channel c ON c.channelid = cm.channelid
        WHERE cm.member_type = :member_type
          AND cm.member_id = :member_id
          AND c.type = 'direct'
        ORDER BY c.channelid DESC
        """,
        {"member_type": member_type, "member_id": member_id},
    )
    for ch in direct_rows:
        ch["display_name"] = (
            _direct_channel_peer_name(ch["channelid"], member_type, member_id)
            or "Direct message"
        )
        result["direct"].append(ch)

    return result


def get_messages_for_channel(
    channelid: int,
    limit: int = 50,
    before_id: int | None = None,
) -> list[dict[str, Any]]:
    """
    Return messages for a channel, newest first, with resolved sender display names.

    Pass before_id for pagination (returns messages with messagesid < before_id).
    """
    params: dict[str, Any] = {
        "channelid": channelid,
        "limit": limit,
        "before_id": before_id if before_id is not None else 0,
        "use_before": 1 if before_id is not None else 0,
    }
    return _all(
        """
        SELECT m.messagesid, m.channelid, m.sender_type, m.sender_id,
               m.content, m.sendtime,
               CASE
                   WHEN m.sender_type = 'student' THEN CONCAT(s.fname, ' ', s.lname)
                   WHEN m.sender_type = 'admin' THEN CONCAT(a.fname, ' ', a.lname)
               END AS sender_name
        FROM messages m
        LEFT JOIN student s
            ON m.sender_type = 'student' AND m.sender_id = s.studentid
        LEFT JOIN admin a
            ON m.sender_type = 'admin' AND m.sender_id = a.adminid
        WHERE m.channelid = :channelid
          AND (:use_before = 0 OR m.messagesid < :before_id)
        ORDER BY m.messagesid DESC
        LIMIT :limit
        """,
        params,
    )


def post_message(
    channelid: int,
    sender_type: str,
    sender_id: int,
    content: str,
) -> dict[str, Any] | None:
    """
    Insert a chat message.

    The caller must ensure (sender_type, sender_id) references a real student
    or admin row, and that the sender is authorized to post in the channel.
    """
    if sender_type not in ("student", "admin"):
        return None
    messagesid = _insert(
        """
        INSERT INTO messages (channelid, sender_type, sender_id, content)
        VALUES (:channelid, :sender_type, :sender_id, :content)
        """,
        {
            "channelid": channelid,
            "sender_type": sender_type,
            "sender_id": sender_id,
            "content": content,
        },
    )
    rows = get_messages_for_channel(channelid, limit=1)
    for row in rows:
        if row["messagesid"] == messagesid:
            return row
    return _one(
        """
        SELECT m.messagesid, m.channelid, m.sender_type, m.sender_id,
               m.content, m.sendtime,
               :sender_name AS sender_name
        FROM messages m
        WHERE m.messagesid = :messagesid
        LIMIT 1
        """,
        {
            "messagesid": messagesid,
            "sender_name": resolve_member_name(sender_type, sender_id),
        },
    )


def delete_message(messagesid: int) -> bool:
    """Delete a message by id. Return True if a row was removed."""
    return _run(
        "DELETE FROM messages WHERE messagesid = :messagesid",
        {"messagesid": messagesid},
    ) > 0


def get_channel_members(channelid: int) -> list[dict[str, Any]]:
    """
    Return members for the member list sidebar.

    General channels list everyone in the cohort. Division and direct channels
    use explicit channel_member rows.
    """
    channel = _get_channel(channelid)
    if not channel:
        return []

    if channel["type"] == "general":
        cohortid = channel["cohortid"]
        members: list[dict[str, Any]] = []
        for row in _all(
            """
            SELECT 'student' AS member_type, s.studentid AS member_id,
                   CONCAT(s.fname, ' ', s.lname) AS member_name,
                   s.email, c.name AS division_name
            FROM student s
            JOIN Course c ON c.courseid = s.courseid
            WHERE s.cohortid = :cohortid
            ORDER BY s.lname, s.fname
            """,
            {"cohortid": cohortid},
        ):
            members.append(dict(row))
        for row in _all(
            """
            SELECT 'admin' AS member_type, adminid AS member_id,
                   CONCAT(fname, ' ', lname) AS member_name,
                   email, 'Admin' AS division_name
            FROM admin
            WHERE cohortid = :cohortid
            ORDER BY lname, fname
            """,
            {"cohortid": cohortid},
        ):
            members.append(dict(row))
        return members

    return _all(
        """
        SELECT cm.channelid, cm.member_type, cm.member_id,
               CASE
                   WHEN cm.member_type = 'student' THEN CONCAT(s.fname, ' ', s.lname)
                   WHEN cm.member_type = 'admin' THEN CONCAT(a.fname, ' ', a.lname)
               END AS member_name,
               CASE
                   WHEN cm.member_type = 'student' THEN s.email
                   WHEN cm.member_type = 'admin' THEN a.email
               END AS email,
               CASE
                   WHEN cm.member_type = 'student' THEN co.name
                   ELSE 'Admin'
               END AS division_name
        FROM channel_member cm
        LEFT JOIN student s
            ON cm.member_type = 'student' AND cm.member_id = s.studentid
        LEFT JOIN admin a
            ON cm.member_type = 'admin' AND cm.member_id = a.adminid
        LEFT JOIN Course co ON co.courseid = s.courseid
        WHERE cm.channelid = :channelid
        ORDER BY cm.member_type, member_name
        """,
        {"channelid": channelid},
    )


def create_direct_channel(
    cohortid: int,
    member_a_type: str,
    member_a_id: int,
    member_b_type: str,
    member_b_id: int,
) -> dict[str, Any] | None:
    """
    Create a direct-message channel (name NULL) and add both members.

    The caller must ensure both (type, id) pairs reference real rows.
    """
    if member_a_type not in ("student", "admin") or member_b_type not in ("student", "admin"):
        return None

    channelid = _insert(
        """
        INSERT INTO channel (cohortid, type, name)
        VALUES (:cohortid, 'direct', NULL)
        """,
        {"cohortid": cohortid},
    )
    for member_type, member_id in (
        (member_a_type, member_a_id),
        (member_b_type, member_b_id),
    ):
        _insert(
            """
            INSERT INTO channel_member (channelid, member_type, member_id)
            VALUES (:channelid, :member_type, :member_id)
            """,
            {"channelid": channelid, "member_type": member_type, "member_id": member_id},
        )
    return _one(
        """
        SELECT channelid, cohortid, type, name
        FROM channel
        WHERE channelid = :channelid
        LIMIT 1
        """,
        {"channelid": channelid},
    )


# ---------------------------------------------------------------------------
# Admin CRUD
# ---------------------------------------------------------------------------


def get_all_cohorts() -> list[dict[str, Any]]:
    """Return all cohorts ordered by cohortid."""
    return _all(
        """
        SELECT cohortid, region, name
        FROM cohort
        ORDER BY cohortid
        """
    )


def create_cohort(region: str, name: str) -> dict[str, Any] | None:
    """Insert a cohort and seed its general + division channels."""
    cohortid = _insert(
        """
        INSERT INTO cohort (region, name)
        VALUES (:region, :name)
        """,
        {"region": region, "name": name},
    )
    _insert(
        """
        INSERT INTO channel (cohortid, type, name)
        VALUES (:cohortid, 'general', 'General')
        """,
        {"cohortid": cohortid},
    )
    courses = get_all_courses()
    for course in courses:
        _insert(
            """
            INSERT INTO channel (cohortid, type, name)
            VALUES (:cohortid, 'division', :name)
            """,
            {"cohortid": cohortid, "name": course["name"]},
        )
    return get_cohort(cohortid)


def _general_channel_for_cohort(cohortid: int) -> int | None:
    row = _one(
        """
        SELECT channelid FROM channel
        WHERE cohortid = :cohortid AND type = 'general'
        LIMIT 1
        """,
        {"cohortid": cohortid},
    )
    return row["channelid"] if row else None


def _division_channel_for_student(cohortid: int, courseid: int) -> int | None:
    row = _one(
        """
        SELECT ch.channelid
        FROM channel ch
        JOIN Course co ON co.name = ch.name
        WHERE ch.cohortid = :cohortid
          AND ch.type = 'division'
          AND co.courseid = :courseid
        LIMIT 1
        """,
        {"cohortid": cohortid, "courseid": courseid},
    )
    return row["channelid"] if row else None


def create_student(
    fname: str,
    lname: str,
    email: str,
    password_hash: str,
    courseid: int,
    cohortid: int,
    bio: str | None = None,
) -> dict[str, Any] | None:
    """
    Create a student with an already-bcrypt-hashed password.

    Adds them to the cohort general channel and their division channel.
    Returns None if email is duplicate.
    """
    existing = _one(
        "SELECT studentid FROM student WHERE email = :email LIMIT 1",
        {"email": email},
    )
    if existing:
        return None

    studentid = _insert(
        """
        INSERT INTO student (fname, lname, email, password, courseid, cohortid, bio)
        VALUES (:fname, :lname, :email, :password, :courseid, :cohortid, :bio)
        """,
        {
            "fname": fname,
            "lname": lname,
            "email": email,
            "password": password_hash,
            "courseid": courseid,
            "cohortid": cohortid,
            "bio": bio,
        },
    )

    general_id = _general_channel_for_cohort(cohortid)
    division_id = _division_channel_for_student(cohortid, courseid)
    for channelid in (general_id, division_id):
        if channelid is not None:
            enroll_student_in_channel(channelid, studentid)

    return get_student_public(studentid)


def enroll_student_in_channel(channelid: int, studentid: int) -> bool:
    """
    Add a student to a channel. Returns False if already a member.

    Caller must ensure studentid references a real student row.
    """
    if is_channel_member(channelid, "student", studentid):
        return False
    _insert(
        """
        INSERT INTO channel_member (channelid, member_type, member_id)
        VALUES (:channelid, 'student', :member_id)
        """,
        {"channelid": channelid, "member_id": studentid},
    )
    return True


def remove_member(channelid: int, member_type: str, member_id: int) -> bool:
    """Remove a polymorphic member from a channel."""
    return (
        _run(
            """
            DELETE FROM channel_member
            WHERE channelid = :channelid
              AND member_type = :member_type
              AND member_id = :member_id
            """,
            {"channelid": channelid, "member_type": member_type, "member_id": member_id},
        )
        > 0
    )


def update_student_profile(
    studentid: int,
    fname: str,
    lname: str,
    email: str,
    bio: str | None = None,
) -> dict[str, Any] | None:
    """Update a student's profile fields (no password). Returns public row or None."""
    rows = _run(
        """
        UPDATE student
        SET fname = :fname, lname = :lname, email = :email, bio = :bio
        WHERE studentid = :studentid
        """,
        {
            "studentid": studentid,
            "fname": fname,
            "lname": lname,
            "email": email,
            "bio": bio,
        },
    )
    if rows == 0:
        return None
    return get_student_public(studentid)


def delete_student(studentid: int, cohortid: int | None = None) -> bool:
    """Remove a student and their assignments, progress, and channel memberships."""
    if cohortid is not None and not student_in_cohort(studentid, cohortid):
        return False
    if not get_student_public(studentid):
        return False
    _run("DELETE FROM assignment WHERE studentid = :studentid", {"studentid": studentid})
    _run("DELETE FROM progress WHERE studentid = :studentid", {"studentid": studentid})
    _run(
        """
        DELETE FROM channel_member
        WHERE member_type = 'student' AND member_id = :studentid
        """,
        {"studentid": studentid},
    )
    _run(
        """
        DELETE FROM messages
        WHERE sender_type = 'student' AND sender_id = :studentid
        """,
        {"studentid": studentid},
    )
    return (
        _run("DELETE FROM student WHERE studentid = :studentid", {"studentid": studentid})
        > 0
    )


def reset_student_password(
    studentid: int,
    new_hash: str,
    cohortid: int | None = None,
) -> bool:
    """
    Store an already-bcrypt-hashed password for a student.

    This function does not hash plaintext — hashing belongs in the auth layer.
    """
    if cohortid is not None and not student_in_cohort(studentid, cohortid):
        return False
    return (
        _run(
            """
            UPDATE student SET password = :password
            WHERE studentid = :studentid
            """,
            {"password": new_hash, "studentid": studentid},
        )
        > 0
    )


def create_week(
    courseid: int,
    subject: str,
    num: int,
    description: str,
) -> dict[str, Any] | None:
    """Insert a week module for a division track."""
    weekid = _insert(
        """
        INSERT INTO Week (courseid, subject, num, description)
        VALUES (:courseid, :subject, :num, :description)
        """,
        {"courseid": courseid, "subject": subject, "num": num, "description": description},
    )
    return get_week(weekid)


def update_week(
    weekid: int,
    subject: str,
    num: int,
    description: str,
) -> dict[str, Any] | None:
    """Update a week module."""
    rows = _run(
        """
        UPDATE Week
        SET subject = :subject, num = :num, description = :description
        WHERE weekid = :weekid
        """,
        {"weekid": weekid, "subject": subject, "num": num, "description": description},
    )
    if rows == 0:
        return None
    return get_week(weekid)


def delete_week(weekid: int) -> bool:
    """Delete a week. Fails if videos or dependent rows reference it."""
    return _run("DELETE FROM Week WHERE weekid = :weekid", {"weekid": weekid}) > 0


def create_video(
    weekid: int,
    day: int,
    title: str,
    miniokey: str,
    script: str,
    instructions: str,
    reflection: str,
) -> dict[str, Any] | None:
    """Insert a video for a week on a specific lecture day (1–3)."""
    videoid = _insert(
        """
        INSERT INTO video (weekid, day, title, miniokey, script, instructions, reflection)
        VALUES (:weekid, :day, :title, :miniokey, :script, :instructions, :reflection)
        """,
        {
            "weekid": weekid,
            "day": day,
            "title": title,
            "miniokey": miniokey,
            "script": script,
            "instructions": instructions,
            "reflection": reflection,
        },
    )
    return get_video(videoid)


def update_video(
    videoid: int,
    day: int,
    title: str,
    miniokey: str,
    script: str,
    instructions: str,
    reflection: str,
) -> dict[str, Any] | None:
    """Update a video row."""
    rows = _run(
        """
        UPDATE video
        SET day = :day, title = :title, miniokey = :miniokey,
            script = :script, instructions = :instructions, reflection = :reflection
        WHERE videoid = :videoid
        """,
        {
            "videoid": videoid,
            "day": day,
            "title": title,
            "miniokey": miniokey,
            "script": script,
            "instructions": instructions,
            "reflection": reflection,
        },
    )
    if rows == 0:
        return None
    return get_video(videoid)


def delete_video(videoid: int) -> bool:
    """Delete a video. Fails if assignments or progress reference it."""
    return _run("DELETE FROM video WHERE videoid = :videoid", {"videoid": videoid}) > 0
