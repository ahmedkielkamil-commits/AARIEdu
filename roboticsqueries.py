"""
AARI Educational Suite — Robotics program database queries (robcourse).

Serves these app pages/features:
  - Login (student / teacher auth)
  - Student dashboard (enrolled courses, cross-course announcement feed)
  - Course home & syllabus
  - Weekly modules with per-day slides and exit tickets
  - Per-course announcements (read / teacher create-delete)
  - Exit ticket submit & edit (student, ungraded, one per day)
  - Teacher retention view (day/week responses, submission status — no grades)
  - Teacher admin (weeks CRUD, syllabus edit, roster enroll/unenroll, password reset)
  - Instructor profile — PARTIALLY SUPPORTED: fname, lname, email, courseid only

Database access: SQLAlchemy Core via db.py (raw SQL, no ORM).
"""

from __future__ import annotations

from typing import Any

from db import execute, execute_insert, fetch_all, fetch_one


# ---------------------------------------------------------------------------
# Integrity helpers
# ---------------------------------------------------------------------------


def is_student_enrolled(studentid: int, courseid: int) -> bool:
    """Return True if the student has a class enrollment row for the course."""
    row = fetch_one(
        """
        SELECT 1 AS ok
        FROM `class`
        WHERE studentid = :studentid AND courseid = :courseid
        LIMIT 1
        """,
        {"studentid": studentid, "courseid": courseid},
    )
    return row is not None


def day_and_class_same_course(dayid: int, classid: int) -> bool:
    """Return True when the day's week course matches the enrollment's course."""
    row = fetch_one(
        """
        SELECT 1 AS ok
        FROM `class` c
        JOIN `Week` w ON w.courseid = c.courseid
        JOIN `Day` d ON d.weekid = w.weekid
        WHERE c.classid = :classid AND d.dayid = :dayid
        LIMIT 1
        """,
        {"classid": classid, "dayid": dayid},
    )
    return row is not None


def week_and_class_same_course(weekid: int, classid: int) -> bool:
    """Return True when the week's course matches the enrollment's course."""
    row = fetch_one(
        """
        SELECT 1 AS ok
        FROM `class` c
        JOIN `Week` w ON w.courseid = c.courseid
        WHERE c.classid = :classid AND w.weekid = :weekid
        LIMIT 1
        """,
        {"classid": classid, "weekid": weekid},
    )
    return row is not None


def verify_ticket_belongs_to_class(ticketid: int, classid: int) -> bool:
    """Return True if the exit ticket belongs to the given enrollment row."""
    row = fetch_one(
        """
        SELECT 1 AS ok
        FROM exitTicket
        WHERE ticketid = :ticketid AND classid = :classid
        LIMIT 1
        """,
        {"ticketid": ticketid, "classid": classid},
    )
    return row is not None


def get_classid_for_student_course(studentid: int, courseid: int) -> int | None:
    """Return the classid for a (student, course) pair, or None if not enrolled."""
    row = fetch_one(
        """
        SELECT classid
        FROM `class`
        WHERE studentid = :studentid AND courseid = :courseid
        LIMIT 1
        """,
        {"studentid": studentid, "courseid": courseid},
    )
    return row["classid"] if row else None


# ---------------------------------------------------------------------------
# Auth (password included for verification only)
# ---------------------------------------------------------------------------


def get_student_by_email(email: str) -> dict[str, Any] | None:
    """Return full student row including password hash for auth verification."""
    return fetch_one(
        """
        SELECT studentid, fname, lname, email, password
        FROM students
        WHERE email = :email
        LIMIT 1
        """,
        {"email": email},
    )


def get_teacher_by_email(email: str) -> dict[str, Any] | None:
    """Return full teacher row including password hash for auth verification."""
    return fetch_one(
        """
        SELECT teacherid, fname, lname, email, password, courseid
        FROM teacher
        WHERE email = :email
        LIMIT 1
        """,
        {"email": email},
    )


def get_student_public(studentid: int) -> dict[str, Any] | None:
    """Return student profile without password."""
    return fetch_one(
        """
        SELECT studentid, fname, lname, email
        FROM students
        WHERE studentid = :studentid
        LIMIT 1
        """,
        {"studentid": studentid},
    )


def get_teacher_public(teacherid: int) -> dict[str, Any] | None:
    """Return teacher profile without password (name, email, courseid only)."""
    return fetch_one(
        """
        SELECT teacherid, fname, lname, email, courseid
        FROM teacher
        WHERE teacherid = :teacherid
        LIMIT 1
        """,
        {"teacherid": teacherid},
    )


def get_teacher_for_course(courseid: int) -> dict[str, Any] | None:
    """Return the instructor for a course (no password), or None."""
    return fetch_one(
        """
        SELECT teacherid, fname, lname, email, courseid
        FROM teacher
        WHERE courseid = :courseid
        LIMIT 1
        """,
        {"courseid": courseid},
    )


def update_student_profile(
    studentid: int,
    fname: str,
    lname: str,
    email: str,
) -> dict[str, Any] | None:
    """Update a student's basic profile fields. Return updated row, or None."""
    rows = execute(
        """
        UPDATE students
        SET fname = :fname, lname = :lname, email = :email
        WHERE studentid = :studentid
        """,
        {"fname": fname, "lname": lname, "email": email, "studentid": studentid},
    )
    if rows == 0:
        return None
    return get_student_public(studentid)


# ---------------------------------------------------------------------------
# Course / home
# ---------------------------------------------------------------------------


def get_all_courses() -> list[dict[str, Any]]:
    """Return all courses ordered by courseid."""
    return fetch_all(
        """
        SELECT courseid, title, syllabus
        FROM Course
        ORDER BY courseid
        """
    )


def get_course(courseid: int) -> dict[str, Any] | None:
    """Return a single course by id, or None."""
    return fetch_one(
        """
        SELECT courseid, title, syllabus
        FROM Course
        WHERE courseid = :courseid
        LIMIT 1
        """,
        {"courseid": courseid},
    )


def get_courses_for_student(studentid: int) -> list[dict[str, Any]]:
    """Return courses the student is enrolled in, with classid for each."""
    return fetch_all(
        """
        SELECT c.courseid, c.title, c.syllabus, cl.classid
        FROM `class` cl
        JOIN Course c ON c.courseid = cl.courseid
        WHERE cl.studentid = :studentid
        ORDER BY c.courseid
        """,
        {"studentid": studentid},
    )


def get_students_in_course(courseid: int) -> list[dict[str, Any]]:
    """Return course roster (no passwords), ordered by last name."""
    return fetch_all(
        """
        SELECT s.studentid, s.fname, s.lname, s.email, cl.classid
        FROM `class` cl
        JOIN students s ON s.studentid = cl.studentid
        WHERE cl.courseid = :courseid
        ORDER BY s.lname, s.fname
        """,
        {"courseid": courseid},
    )


# ---------------------------------------------------------------------------
# Syllabus / modules (weeks + days)
# ---------------------------------------------------------------------------


def get_syllabus(courseid: int) -> dict[str, Any] | None:
    """Return courseid, title, and syllabus text, or None."""
    return fetch_one(
        """
        SELECT courseid, title, syllabus
        FROM Course
        WHERE courseid = :courseid
        LIMIT 1
        """,
        {"courseid": courseid},
    )


def get_weeks_for_course(courseid: int) -> list[dict[str, Any]]:
    """Return all weeks for a course ordered by week number."""
    return fetch_all(
        """
        SELECT weekid, courseid, title, num
        FROM `Week`
        WHERE courseid = :courseid
        ORDER BY num
        """,
        {"courseid": courseid},
    )


def get_week(weekid: int) -> dict[str, Any] | None:
    """Return a single week row, or None."""
    return fetch_one(
        """
        SELECT weekid, courseid, title, num
        FROM `Week`
        WHERE weekid = :weekid
        LIMIT 1
        """,
        {"weekid": weekid},
    )


def get_days_for_week(weekid: int) -> list[dict[str, Any]]:
    """Return lecture days for a week ordered by day number."""
    return fetch_all(
        """
        SELECT dayid, weekid, num, title, description, assignment, slidelink
        FROM `Day`
        WHERE weekid = :weekid
        ORDER BY num
        """,
        {"weekid": weekid},
    )


def get_day(dayid: int) -> dict[str, Any] | None:
    """Return a single day row with its parent week courseid, or None."""
    return fetch_one(
        """
        SELECT d.dayid, d.weekid, d.num, d.title, d.description, d.assignment, d.slidelink,
               w.courseid, w.title AS week_title, w.num AS week_num
        FROM `Day` d
        JOIN `Week` w ON w.weekid = d.weekid
        WHERE d.dayid = :dayid
        LIMIT 1
        """,
        {"dayid": dayid},
    )


def count_days_for_course(courseid: int) -> int:
    """Return total lecture days published for a course."""
    row = fetch_one(
        """
        SELECT COUNT(*) AS n
        FROM `Day` d
        JOIN `Week` w ON w.weekid = d.weekid
        WHERE w.courseid = :courseid
        """,
        {"courseid": courseid},
    )
    return int(row["n"]) if row else 0


def count_submitted_tickets_for_class(classid: int) -> int:
    """Return how many day exit tickets this enrollment has submitted."""
    row = fetch_one(
        """
        SELECT COUNT(*) AS n
        FROM exitTicket
        WHERE classid = :classid
        """,
        {"classid": classid},
    )
    return int(row["n"]) if row else 0


def get_submitted_day_ids_for_class(classid: int) -> set[int]:
    """Return dayids that already have an exit ticket for this enrollment."""
    rows = fetch_all(
        """
        SELECT dayid
        FROM exitTicket
        WHERE classid = :classid
        """,
        {"classid": classid},
    )
    return {row["dayid"] for row in rows}


def get_course_modules(
    courseid: int,
    classid: int | None = None,
) -> list[dict[str, Any]]:
    """
    Return weeks with nested days for the modules page.

    When classid is provided, each day includes submitted=True/False for that student.
    """
    weeks = get_weeks_for_course(courseid)
    submitted: set[int] = set()
    if classid is not None:
        submitted = get_submitted_day_ids_for_class(classid)

    result: list[dict[str, Any]] = []
    for week in weeks:
        days = get_days_for_week(week["weekid"])
        day_rows = []
        for day in days:
            entry = dict(day)
            if classid is not None:
                entry["submitted"] = day["dayid"] in submitted
            day_rows.append(entry)
        result.append({**week, "days": day_rows})
    return result


# ---------------------------------------------------------------------------
# Announcements
# ---------------------------------------------------------------------------


def get_announcements_for_course(courseid: int) -> list[dict[str, Any]]:
    """Return announcements for one course, newest first."""
    return fetch_all(
        """
        SELECT announceid, courseid, content, created_at
        FROM announcement
        WHERE courseid = :courseid
        ORDER BY created_at DESC
        """,
        {"courseid": courseid},
    )


def get_announcements_for_student(studentid: int) -> list[dict[str, Any]]:
    """Return announcements across all enrolled courses, newest first."""
    return fetch_all(
        """
        SELECT a.announceid, a.courseid, a.content, a.created_at, c.title AS course_title
        FROM announcement a
        JOIN `class` cl ON cl.courseid = a.courseid
        JOIN Course c ON c.courseid = a.courseid
        WHERE cl.studentid = :studentid
        ORDER BY a.created_at DESC
        """,
        {"studentid": studentid},
    )


def create_announcement(courseid: int, content: str) -> dict[str, Any] | None:
    """Insert an announcement; created_at defaults in DB. Return the new row."""
    announceid = execute_insert(
        """
        INSERT INTO announcement (courseid, content)
        VALUES (:courseid, :content)
        """,
        {"courseid": courseid, "content": content},
    )
    return fetch_one(
        """
        SELECT announceid, courseid, content, created_at
        FROM announcement
        WHERE announceid = :announceid
        LIMIT 1
        """,
        {"announceid": announceid},
    )


def delete_announcement(announceid: int) -> bool:
    """Delete an announcement. Return True if a row was removed."""
    return (
        execute(
            "DELETE FROM announcement WHERE announceid = :announceid",
            {"announceid": announceid},
        )
        > 0
    )


# ---------------------------------------------------------------------------
# Exit tickets — student
# ---------------------------------------------------------------------------


def submit_exit_ticket(
    dayid: int,
    classid: int,
    studentid: int,
    miniokey: str | None = None,
) -> dict[str, Any] | None:
    """
    Insert a new exit ticket for a day/enrollment pair.

    Returns None if day and class are not the same course, or if a ticket
    already exists for this (classid, dayid).
    """
    if not day_and_class_same_course(dayid, classid):
        return None
    if get_student_ticket_for_day(classid, dayid) is not None:
        return None

    ticketid = execute_insert(
        """
        INSERT INTO exitTicket (dayid, classid, studentid, miniokey)
        VALUES (:dayid, :classid, :studentid, :miniokey)
        """,
        {
            "dayid": dayid,
            "classid": classid,
            "studentid": studentid,
            "miniokey": miniokey,
        },
    )
    return get_exit_ticket(ticketid)


def update_exit_ticket(
    ticketid: int,
    miniokey: str | None = None,
) -> dict[str, Any] | None:
    """Update an existing exit ticket attachment. Return updated row, or None if not found."""
    rows = execute(
        """
        UPDATE exitTicket
        SET miniokey = :miniokey
        WHERE ticketid = :ticketid
        """,
        {"miniokey": miniokey, "ticketid": ticketid},
    )
    if rows == 0:
        return None
    return get_exit_ticket(ticketid)


def get_exit_ticket(ticketid: int) -> dict[str, Any] | None:
    """Return a single exit ticket row, or None."""
    return fetch_one(
        """
        SELECT ticketid, dayid, classid, studentid, miniokey, response
        FROM exitTicket
        WHERE ticketid = :ticketid
        LIMIT 1
        """,
        {"ticketid": ticketid},
    )


def get_student_ticket_for_day(classid: int, dayid: int) -> dict[str, Any] | None:
    """Return the student's existing ticket for a day, or None."""
    return fetch_one(
        """
        SELECT ticketid, dayid, classid, studentid, miniokey, response
        FROM exitTicket
        WHERE classid = :classid AND dayid = :dayid
        LIMIT 1
        """,
        {"classid": classid, "dayid": dayid},
    )


# ---------------------------------------------------------------------------
# Exit tickets — teacher retention (ungraded, no feedback)
# ---------------------------------------------------------------------------


def get_tickets_for_day(dayid: int) -> list[dict[str, Any]]:
    """Return all exit-ticket responses for one lecture day with student names."""
    return fetch_all(
        """
        SELECT et.ticketid, et.dayid, et.classid, et.studentid, et.miniokey, et.response,
               s.fname, s.lname, s.email
        FROM exitTicket et
        JOIN students s ON s.studentid = et.studentid
        WHERE et.dayid = :dayid
        ORDER BY s.lname, s.fname
        """,
        {"dayid": dayid},
    )


def get_tickets_for_week(weekid: int) -> list[dict[str, Any]]:
    """Return all exit-ticket responses for a week (all days), with day labels."""
    return fetch_all(
        """
        SELECT et.ticketid, et.dayid, et.classid, et.studentid, et.miniokey, et.response,
               s.fname, s.lname, s.email,
               d.num AS day_num, d.title AS day_title
        FROM exitTicket et
        JOIN `Day` d ON d.dayid = et.dayid
        JOIN students s ON s.studentid = et.studentid
        WHERE d.weekid = :weekid
        ORDER BY d.num, s.lname, s.fname
        """,
        {"weekid": weekid},
    )


def get_ticket_submission_status_for_day(
    courseid: int,
    dayid: int,
) -> list[dict[str, Any]]:
    """Per enrolled student: submitted or not for one lecture day."""
    day = get_day(dayid)
    if day is None or day["courseid"] != courseid:
        return []

    return fetch_all(
        """
        SELECT s.studentid, s.fname, s.lname, s.email, cl.classid,
               CASE WHEN et.ticketid IS NOT NULL THEN 1 ELSE 0 END AS submitted,
               et.ticketid
        FROM `class` cl
        JOIN students s ON s.studentid = cl.studentid
        LEFT JOIN exitTicket et
            ON et.classid = cl.classid AND et.dayid = :dayid
        WHERE cl.courseid = :courseid
        ORDER BY s.lname, s.fname
        """,
        {"dayid": dayid, "courseid": courseid},
    )


def get_ticket_submission_status_for_week(
    courseid: int,
    weekid: int,
) -> list[dict[str, Any]]:
    """
    For each day in the week, return roster submission status.

    Structure: [{day, rows: [{student, submitted, ...}]}]
    """
    week = get_week(weekid)
    if week is None or week["courseid"] != courseid:
        return []

    days = get_days_for_week(weekid)
    roster = fetch_all(
        """
        SELECT s.studentid, s.fname, s.lname, s.email, cl.classid
        FROM `class` cl
        JOIN students s ON s.studentid = cl.studentid
        WHERE cl.courseid = :courseid
        ORDER BY s.lname, s.fname
        """,
        {"courseid": courseid},
    )

    tickets = fetch_all(
        """
        SELECT et.classid, et.dayid, et.ticketid
        FROM exitTicket et
        JOIN `Day` d ON d.dayid = et.dayid
        WHERE d.weekid = :weekid
        """,
        {"weekid": weekid},
    )
    by_day_class: dict[tuple[int, int], int] = {
        (t["dayid"], t["classid"]): t["ticketid"] for t in tickets
    }

    result = []
    for day in days:
        rows = []
        for student in roster:
            ticketid = by_day_class.get((day["dayid"], student["classid"]))
            rows.append(
                {
                    **student,
                    "submitted": ticketid is not None,
                    "ticketid": ticketid,
                }
            )
        result.append({"day": day, "rows": rows})
    return result


# ---------------------------------------------------------------------------
# Teacher CRUD
# ---------------------------------------------------------------------------


def create_week(courseid: int, title: str, num: int) -> dict[str, Any] | None:
    """Insert a week module. Return the new row."""
    weekid = execute_insert(
        """
        INSERT INTO `Week` (courseid, title, num)
        VALUES (:courseid, :title, :num)
        """,
        {"courseid": courseid, "title": title, "num": num},
    )
    return get_week(weekid)


def update_week(weekid: int, title: str, num: int) -> dict[str, Any] | None:
    """Update a week module. Return updated row, or None if not found."""
    rows = execute(
        """
        UPDATE `Week`
        SET title = :title, num = :num
        WHERE weekid = :weekid
        """,
        {"title": title, "num": num, "weekid": weekid},
    )
    if rows == 0:
        return None
    return get_week(weekid)


def delete_week(weekid: int) -> bool:
    """Delete a week and its days/tickets. Return True if the week was removed."""
    days = get_days_for_week(weekid)
    for day in days:
        execute(
            "DELETE FROM exitTicket WHERE dayid = :dayid",
            {"dayid": day["dayid"]},
        )
        execute("DELETE FROM `Day` WHERE dayid = :dayid", {"dayid": day["dayid"]})
    return execute("DELETE FROM `Week` WHERE weekid = :weekid", {"weekid": weekid}) > 0


def update_day_assignment(dayid: int, assignment: str) -> dict[str, Any] | None:
    """Update the exit-ticket description for a lecture day."""
    rows = execute(
        """
        UPDATE `Day`
        SET assignment = :assignment
        WHERE dayid = :dayid
        """,
        {"assignment": assignment, "dayid": dayid},
    )
    if rows == 0:
        return None
    return get_day(dayid)


def update_syllabus(courseid: int, syllabus: str) -> dict[str, Any] | None:
    """Update course syllabus text. Return updated course row, or None."""
    rows = execute(
        """
        UPDATE Course
        SET syllabus = :syllabus
        WHERE courseid = :courseid
        """,
        {"syllabus": syllabus, "courseid": courseid},
    )
    if rows == 0:
        return None
    return get_course(courseid)


def create_student(
    fname: str,
    lname: str,
    email: str,
    password_hash: str,
) -> dict[str, Any] | None:
    """Create a student account. Returns None if email is already taken."""
    existing = fetch_one(
        "SELECT studentid FROM students WHERE email = :email LIMIT 1",
        {"email": email},
    )
    if existing:
        return None
    studentid = execute_insert(
        """
        INSERT INTO students (fname, lname, email, password)
        VALUES (:fname, :lname, :email, :password)
        """,
        {
            "fname": fname,
            "lname": lname,
            "email": email,
            "password": password_hash,
        },
    )
    return get_student_public(studentid)


def delete_student(studentid: int) -> bool:
    """Delete a student, their enrollments, and exit tickets."""
    if not get_student_public(studentid):
        return False
    execute(
        """
        DELETE et FROM exitTicket et
        JOIN `class` cl ON cl.classid = et.classid
        WHERE cl.studentid = :studentid
        """,
        {"studentid": studentid},
    )
    execute("DELETE FROM `class` WHERE studentid = :studentid", {"studentid": studentid})
    return (
        execute("DELETE FROM students WHERE studentid = :studentid", {"studentid": studentid})
        > 0
    )


def enroll_student(studentid: int, courseid: int) -> dict[str, Any] | None:
    """Enroll a student in a course. Return the class row, or None if duplicate."""
    existing = fetch_one(
        """
        SELECT classid
        FROM `class`
        WHERE studentid = :studentid AND courseid = :courseid
        LIMIT 1
        """,
        {"studentid": studentid, "courseid": courseid},
    )
    if existing is not None:
        return None

    classid = execute_insert(
        """
        INSERT INTO `class` (studentid, courseid)
        VALUES (:studentid, :courseid)
        """,
        {"studentid": studentid, "courseid": courseid},
    )
    return fetch_one(
        """
        SELECT classid, studentid, courseid
        FROM `class`
        WHERE classid = :classid
        LIMIT 1
        """,
        {"classid": classid},
    )


def unenroll_student(studentid: int, courseid: int) -> bool:
    """Remove enrollment. Return True if a class row was deleted."""
    return (
        execute(
            """
            DELETE FROM `class`
            WHERE studentid = :studentid AND courseid = :courseid
            """,
            {"studentid": studentid, "courseid": courseid},
        )
        > 0
    )


def reset_student_password(studentid: int, new_hash: str) -> bool:
    """Store an already-bcrypt-hashed password for a student."""
    return (
        execute(
            """
            UPDATE students
            SET password = :password
            WHERE studentid = :studentid
            """,
            {"password": new_hash, "studentid": studentid},
        )
        > 0
    )
