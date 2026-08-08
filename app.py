"""
AARI Educational Suite — Flask application (robotics + data center).
"""

from __future__ import annotations

import os
from datetime import datetime
from functools import wraps
from pathlib import Path

import bcrypt
from flask import (
    Flask,
    abort,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.utils import secure_filename

import dcqueries as dq
import roboticsqueries as rq

app = Flask(__name__, template_folder="Templates", static_folder="static")
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-change-me-in-production")

UPLOAD_DIR = Path(app.static_folder) / "uploads" / "exittickets"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "gif", "webp", "pdf"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def course_monogram(title: str) -> str:
    words = title.split()
    if len(words) >= 2:
        return (words[0][0] + words[1][0]).upper()
    return title[:2].upper() if title else "??"


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in to continue.", "error")
            return redirect(url_for("login", next=request.url))
        return view(*args, **kwargs)

    return wrapped


def dc_login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session or session.get("suite") != "dc":
            flash("Please log in to the data center program.", "error")
            return redirect(url_for("login", next=request.url))
        return view(*args, **kwargs)

    return wrapped


def dc_admin_required(view):
    @wraps(view)
    @dc_login_required
    def wrapped(*args, **kwargs):
        if session.get("user_type") != "admin":
            abort(403)
        admin = dq.get_admin_public(session["user_id"])
        if not admin or not admin.get("cohortid"):
            abort(403)
        return view(*args, **kwargs)

    return wrapped


def is_dc_suite() -> bool:
    return session.get("suite") == "dc"


def is_dc_admin() -> bool:
    return is_dc_suite() and session.get("user_type") == "admin"


def is_dc_student() -> bool:
    return is_dc_suite() and session.get("user_type") == "student"


def current_user():
    if "user_id" not in session:
        return None
    if session.get("suite") == "dc":
        if session.get("user_type") == "admin":
            return dq.get_admin_public(session["user_id"])
        return dq.get_student_public(session["user_id"])
    if session.get("user_type") == "student":
        return rq.get_student_public(session["user_id"])
    return rq.get_teacher_public(session["user_id"])


def is_instructor() -> bool:
    return session.get("user_type") == "teacher"


def can_access_course(courseid: int) -> bool:
    if "user_id" not in session:
        return False
    if session.get("user_type") == "teacher":
        teacher = rq.get_teacher_public(session["user_id"])
        return teacher is not None and teacher["courseid"] == courseid
    return rq.is_student_enrolled(session["user_id"], courseid)


def is_instructor_for(courseid: int) -> bool:
    return is_instructor() and can_access_course(courseid)


def rail_courses():
    """Courses shown in the left monogram rail."""
    if "user_id" not in session:
        return []
    if session.get("user_type") == "student":
        return rq.get_courses_for_student(session["user_id"])
    teacher = rq.get_teacher_public(session["user_id"])
    if not teacher:
        return []
    course = rq.get_course(teacher["courseid"])
    if not course:
        return []
    return [{"courseid": course["courseid"], "title": course["title"]}]


def student_progress(courseid: int, studentid: int) -> int:
    total_days = rq.count_days_for_course(courseid)
    if not total_days:
        return 0
    classid = rq.get_classid_for_student_course(studentid, courseid)
    if not classid:
        return 0
    submitted = rq.count_submitted_tickets_for_class(classid)
    return int(submitted / total_days * 100)


def course_context(courseid: int, active: str):
    if not can_access_course(courseid):
        abort(403)
    course = rq.get_course(courseid)
    if not course:
        abort(404)
    progress = 0
    if session.get("user_type") == "student":
        progress = student_progress(courseid, session["user_id"])
    return {
        "course": course,
        "courseid": courseid,
        "enrolled_courses": rail_courses(),
        "sidebar_active": active,
        "is_instructor": is_instructor_for(courseid),
        "progress_pct": progress,
        "monogram": course_monogram,
    }


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def save_attachment(file_storage) -> str | None:
    if not file_storage or not file_storage.filename:
        return None
    if not allowed_file(file_storage.filename):
        return None
    filename = secure_filename(file_storage.filename)
    dest = UPLOAD_DIR / filename
    base, ext = os.path.splitext(filename)
    counter = 1
    while dest.exists():
        filename = f"{base}_{counter}{ext}"
        dest = UPLOAD_DIR / filename
        counter += 1
    file_storage.save(dest)
    return f"exittickets/{filename}"


# ---------------------------------------------------------------------------
# Data Center helpers
# ---------------------------------------------------------------------------


def dc_member_type_and_id() -> tuple[str, int]:
    if is_dc_admin():
        return "admin", session["user_id"]
    return "student", session["user_id"]


def video_in_division(videoid: int, courseid: int) -> bool:
    video = dq.get_video(videoid)
    if not video:
        return False
    week = dq.get_week(video["weekid"])
    return week is not None and week["courseid"] == courseid


def dc_admin_with_cohort() -> tuple[dict, int]:
    """Return (admin row, cohortid) for a cohort-scoped DC admin, or abort 403."""
    if not is_dc_admin():
        abort(403)
    admin = dq.get_admin_public(session["user_id"])
    cohortid = admin.get("cohortid") if admin else None
    if not admin or not cohortid:
        abort(403)
    return admin, cohortid


def dc_admin_courseid() -> int:
    """Active division track for DC admin pages (query param or session, default 1)."""
    cid = request.args.get("courseid", type=int)
    if cid:
        session["dc_courseid"] = cid
        return cid
    return session.get("dc_courseid") or 1


def build_lesson_rail(
    studentid: int,
    courseid: int,
    current_videoid: int | None = None,
    *,
    include_assignments: bool = False,
) -> list[dict]:
    weeks = dq.get_weeks_for_course(courseid)
    videos = dq.get_videos_for_course(courseid)
    progress_rows = dq.get_progress_for_student(studentid)
    watched = {p["videoid"]: p["watched"] for p in progress_rows}
    assignments: dict[int, dict] = {}
    if include_assignments:
        for row in dq.get_assignments_for_student(studentid):
            assignments[row["videoid"]] = row
    by_week: dict[int, list] = {}
    for video in videos:
        entry = {
            **video,
            "watched": bool(watched.get(video["videoid"])),
            "current": video["videoid"] == current_videoid,
        }
        if include_assignments:
            entry["assignment"] = assignments.get(video["videoid"])
        by_week.setdefault(video["weekid"], []).append(entry)
    return [{"week": week, "videos": by_week.get(week["weekid"], [])} for week in weeks]


def build_lesson_rail_for_course(
    courseid: int,
    current_videoid: int | None = None,
    *,
    include_grading: bool = False,
    cohortid: int | None = None,
) -> list[dict]:
    """Lesson rail for admins browsing course content (no student progress required)."""
    weeks = dq.get_weeks_for_course(courseid)
    videos = dq.get_videos_for_course(courseid)
    grading: dict[int, dict] = {}
    if include_grading:
        for row in dq.get_submission_analytics(courseid, cohortid=cohortid)[
            "by_video"
        ]:
            grading[row["videoid"]] = row
    by_week: dict[int, list] = {}
    for video in videos:
        entry = {
            **video,
            "watched": False,
            "current": video["videoid"] == current_videoid,
        }
        if include_grading:
            stats = grading.get(video["videoid"], {})
            entry["submitted_count"] = stats.get("submitted_count", 0)
            entry["ungraded_count"] = stats.get("ungraded_count", 0)
        by_week.setdefault(video["weekid"], []).append(entry)
    return [{"week": week, "videos": by_week.get(week["weekid"], [])} for week in weeks]


def dc_student_context(active: str, student: dict, **extra) -> dict:
    course = dq.get_course(student["courseid"])
    cohort = dq.get_cohort(student["cohortid"])
    completion = dq.get_course_completion(student["studentid"])
    ctx = {
        "course": course,
        "courseid": student["courseid"],
        "cohort": cohort,
        "sidebar_active": active,
        "progress_pct": completion["completion_pct"],
        "completion": completion,
        "monogram": course_monogram,
        "all_courses": dq.get_all_courses(),
    }
    ctx.update(extra)
    return ctx


def dc_admin_context(active: str, admin: dict, **extra) -> dict:
    courseid = extra.pop("courseid", None) or dc_admin_courseid()
    session["dc_courseid"] = courseid
    course = dq.get_course(courseid)
    cohort = dq.get_cohort(admin["cohortid"])
    ctx = {
        "course": course,
        "courseid": courseid,
        "cohort": cohort,
        "sidebar_active": active,
        "progress_pct": 0,
        "monogram": course_monogram,
        "all_courses": dq.get_all_courses(),
    }
    ctx.update(extra)
    return ctx


def dc_page_context(active: str, **extra) -> dict:
    if is_dc_admin():
        admin = dq.get_admin_public(session["user_id"])
        if not admin:
            abort(403)
        return dc_admin_context(active, admin, **extra)
    student = dq.get_student_public(session["user_id"])
    if not student:
        abort(403)
    return dc_student_context(active, student, **extra)


def jitsi_room_name(student: dict | None, admin: dict | None) -> str:
    cohortid = None
    courseid = None
    if student:
        cohortid = student["cohortid"]
        courseid = student["courseid"]
    elif admin and admin.get("cohortid"):
        cohortid = admin["cohortid"]
    parts = ["aari-dc"]
    if cohortid:
        parts.append(f"cohort-{cohortid}")
    if courseid:
        parts.append(f"div-{courseid}")
    return "-".join(parts)


def can_access_dc_channel(channelid: int, member_type: str, member_id: int) -> bool:
    """Delegate to dcqueries — general is cohort-wide; division/DM require membership."""
    return dq.can_access_channel(channelid, member_type, member_id)


def flatten_messenger_channels(channel_groups: dict) -> list[dict]:
    """Flatten grouped messenger channels for lookup."""
    flat: list[dict] = []
    if channel_groups.get("general"):
        flat.append(channel_groups["general"])
    flat.extend(channel_groups.get("division") or [])
    flat.extend(channel_groups.get("direct") or [])
    return flat


@app.context_processor
def inject_globals():
    overlay = session.get("overlay_color", "maroon")
    user = current_user()
    display_name = ""
    if user:
        display_name = f"{user['fname']} {user['lname']}"
    return {
        "overlay_color": overlay,
        "current_user": user,
        "current_user_name": display_name,
        "is_logged_in": "user_id" in session,
        "user_is_instructor": is_instructor(),
        "user_is_dc_admin": is_dc_admin(),
    }


@app.template_filter("format_datetime")
def format_datetime(value):
    if not value:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%b %d, %Y · %I:%M %p")
    return str(value)


# ---------------------------------------------------------------------------
# Public routes
# ---------------------------------------------------------------------------


@app.route("/")
def landing():
    return render_template("landing.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        if not email or not password:
            flash("Email and password are required.", "error")
            return render_template("login.html")

        student = rq.get_student_by_email(email)
        if student and verify_password(password, student["password"]):
            session.clear()
            session["suite"] = "robotics"
            session["user_id"] = student["studentid"]
            session["user_type"] = "student"
            session["email"] = student["email"]
            dest = request.args.get("next") or url_for("student_home")
            return redirect(dest)

        teacher = rq.get_teacher_by_email(email)
        if teacher and verify_password(password, teacher["password"]):
            session.clear()
            session["suite"] = "robotics"
            session["user_id"] = teacher["teacherid"]
            session["user_type"] = "teacher"
            session["email"] = teacher["email"]
            session["teacher_courseid"] = teacher["courseid"]
            dest = request.args.get("next") or url_for(
                "course_home", courseid=teacher["courseid"]
            )
            return redirect(dest)

        dc_student = dq.get_student_by_email(email)
        if dc_student and verify_password(password, dc_student["password"]):
            session.clear()
            session["suite"] = "dc"
            session["user_id"] = dc_student["studentid"]
            session["user_type"] = "student"
            session["email"] = dc_student["email"]
            dest = request.args.get("next") or url_for("dc_home")
            return redirect(dest)

        dc_admin = dq.get_admin_by_email(email)
        if dc_admin and verify_password(password, dc_admin["password"]):
            if not dc_admin.get("cohortid"):
                flash("This admin account is not assigned to a cohort.", "error")
                return render_template("login.html")
            session.clear()
            session["suite"] = "dc"
            session["user_id"] = dc_admin["adminid"]
            session["user_type"] = "admin"
            session["email"] = dc_admin["email"]
            dest = request.args.get("next") or url_for("dc_home")
            return redirect(dest)

        flash("Invalid email or password.", "error")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("landing"))


@app.route("/datacenter")
def datacenter_entry():
    if session.get("suite") == "dc" and "user_id" in session:
        return redirect(url_for("dc_home"))
    return redirect(url_for("login", next=url_for("dc_home")))


@app.route("/account", methods=["GET", "POST"])
@login_required
def account():
    if request.method == "POST":
        action = request.form.get("action")
        if action == "overlay":
            choice = request.form.get("overlay_color", "maroon")
            if choice in ("maroon", "slate", "none"):
                session["overlay_color"] = choice
                flash("Display preference saved.", "success")
            return redirect(url_for("account"))

        if session.get("user_type") != "student":
            flash("Only students can edit profile here.", "error")
            return redirect(url_for("account"))

        fname = request.form.get("fname", "").strip()
        lname = request.form.get("lname", "").strip()
        email = request.form.get("email", "").strip()
        if not fname or not lname or not email:
            flash("All profile fields are required.", "error")
        else:
            updated = rq.update_student_profile(session["user_id"], fname, lname, email)
            if updated:
                session["email"] = email
                flash("Profile updated.", "success")
            else:
                flash("Could not update profile.", "error")
        return redirect(url_for("account"))

    user = current_user()
    return render_template("account.html", profile=user)


@app.route("/student/home")
@login_required
def student_home():
    if session.get("user_type") != "student":
        teacher = rq.get_teacher_public(session["user_id"])
        if teacher:
            return redirect(url_for("course_home", courseid=teacher["courseid"]))
        abort(403)
    courses = rq.get_courses_for_student(session["user_id"])
    if not courses:
        return render_template("student_no_courses.html", courses=[])
    return redirect(url_for("course_home", courseid=courses[0]["courseid"]))


# ---------------------------------------------------------------------------
# Course routes — robotics
# ---------------------------------------------------------------------------


@app.route("/course/<int:courseid>")
@login_required
def course_home(courseid):
    ctx = course_context(courseid, "home")
    ctx["announcements"] = rq.get_announcements_for_course(courseid)
    return render_template("course/home.html", **ctx)


@app.route("/course/<int:courseid>/syllabus", methods=["GET", "POST"])
@login_required
def course_syllabus(courseid):
    ctx = course_context(courseid, "syllabus")
    if request.method == "POST":
        if not ctx["is_instructor"]:
            abort(403)
        syllabus = request.form.get("syllabus", "").strip()
        if syllabus:
            rq.update_syllabus(courseid, syllabus)
            flash("Syllabus updated.", "success")
        return redirect(url_for("course_syllabus", courseid=courseid))
    ctx["syllabus_data"] = rq.get_syllabus(courseid)
    return render_template("course/syllabus.html", **ctx)


@app.route("/course/<int:courseid>/modules", methods=["GET", "POST"])
@login_required
def course_modules(courseid):
    ctx = course_context(courseid, "modules")
    if request.method == "POST" and ctx["is_instructor"]:
        action = request.form.get("action")
        if action == "create":
            title = request.form.get("title", "").strip()
            num = request.form.get("num", type=int)
            if title and num:
                rq.create_week(courseid, title, num)
                flash("Week created.", "success")
        elif action == "update":
            weekid = request.form.get("weekid", type=int)
            title = request.form.get("title", "").strip()
            num = request.form.get("num", type=int)
            if weekid and title and num:
                week = rq.get_week(weekid)
                if week and week["courseid"] == courseid:
                    rq.update_week(weekid, title, num)
                    flash("Week updated.", "success")
        elif action == "delete":
            weekid = request.form.get("weekid", type=int)
            if weekid:
                week = rq.get_week(weekid)
                if week and week["courseid"] == courseid:
                    if rq.delete_week(weekid):
                        flash("Week deleted.", "success")
                    else:
                        flash("Could not delete week.", "error")
        return redirect(url_for("course_modules", courseid=courseid))

    classid = None
    if session.get("user_type") == "student":
        classid = rq.get_classid_for_student_course(session["user_id"], courseid)
    ctx["weeks"] = rq.get_course_modules(courseid, classid=classid)
    return render_template("course/modules.html", **ctx)


@app.route("/course/<int:courseid>/week/<int:weekid>")
@login_required
def course_week(courseid, weekid):
    """Legacy URL — redirect to the first lecture day in the week."""
    week = rq.get_week(weekid)
    if not week or week["courseid"] != courseid:
        abort(404)
    days = rq.get_days_for_week(weekid)
    if not days:
        flash("This week has no lecture days yet.", "error")
        return redirect(url_for("course_modules", courseid=courseid))
    return redirect(url_for("course_day", courseid=courseid, dayid=days[0]["dayid"]))


@app.route("/course/<int:courseid>/day/<int:dayid>", methods=["GET", "POST"])
@login_required
def course_day(courseid, dayid):
    ctx = course_context(courseid, "modules")
    day = rq.get_day(dayid)
    if not day or day["courseid"] != courseid:
        abort(404)

    classid = None
    ticket = None
    if session.get("user_type") == "student":
        classid = rq.get_classid_for_student_course(session["user_id"], courseid)
        if classid:
            ticket = rq.get_student_ticket_for_day(classid, dayid)

    if request.method == "POST":
        action = request.form.get("action", "submit_ticket")
        if action == "update_assignment":
            if not ctx["is_instructor"]:
                abort(403)
            assignment = request.form.get("assignment", "").strip()
            if assignment:
                rq.update_day_assignment(dayid, assignment)
                flash("Exit ticket description updated.", "success")
            return redirect(url_for("course_day", courseid=courseid, dayid=dayid))

        if session.get("user_type") != "student" or not classid:
            abort(403)
        miniokey = save_attachment(request.files.get("attachment"))
        if ticket:
            if not rq.verify_ticket_belongs_to_class(ticket["ticketid"], classid):
                abort(403)
            if miniokey is None and ticket.get("miniokey"):
                miniokey = ticket["miniokey"]
            rq.update_exit_ticket(ticket["ticketid"], miniokey)
            flash("Exit ticket updated.", "success")
        else:
            result = rq.submit_exit_ticket(
                dayid, classid, session["user_id"], miniokey
            )
            if result:
                flash("Exit ticket submitted.", "success")
            else:
                flash("Could not submit — check that this day matches your enrollment.", "error")
        return redirect(url_for("course_day", courseid=courseid, dayid=dayid))

    ctx.update({"day": day, "classid": classid, "ticket": ticket})
    return render_template("course/day.html", **ctx)


@app.route("/course/<int:courseid>/week/<int:weekid>/tickets")
@login_required
def course_week_tickets(courseid, weekid):
    ctx = course_context(courseid, "modules")
    if not ctx["is_instructor"]:
        abort(403)
    week = rq.get_week(weekid)
    if not week or week["courseid"] != courseid:
        abort(404)
    ctx["week"] = week
    ctx["tickets"] = rq.get_tickets_for_week(weekid)
    ctx["day_status"] = rq.get_ticket_submission_status_for_week(courseid, weekid)
    return render_template("course/tickets.html", **ctx)


@app.route("/course/<int:courseid>/announcements", methods=["GET", "POST"])
@login_required
def course_announcements(courseid):
    ctx = course_context(courseid, "announcements")
    if request.method == "POST":
        if not ctx["is_instructor"]:
            abort(403)
        action = request.form.get("action")
        if action == "create":
            content = request.form.get("content", "").strip()
            if content:
                rq.create_announcement(courseid, content)
                flash("Announcement posted.", "success")
        elif action == "delete":
            announceid = request.form.get("announceid", type=int)
            if announceid:
                rq.delete_announcement(announceid)
                flash("Announcement deleted.", "success")
        return redirect(url_for("course_announcements", courseid=courseid))

    ctx["announcements"] = rq.get_announcements_for_course(courseid)
    return render_template("course/announcements.html", **ctx)


@app.route("/course/<int:courseid>/instructor")
@login_required
def course_instructor(courseid):
    ctx = course_context(courseid, "instructor")
    ctx["instructor"] = rq.get_teacher_for_course(courseid)
    return render_template("course/instructor.html", **ctx)


@app.route("/course/<int:courseid>/roster", methods=["GET", "POST"])
@login_required
def course_roster(courseid):
    ctx = course_context(courseid, "roster")
    if not ctx["is_instructor"]:
        abort(403)

    if request.method == "POST":
        action = request.form.get("action")
        if action == "enroll":
            studentid = request.form.get("studentid", type=int)
            if studentid:
                if rq.enroll_student(studentid, courseid):
                    flash("Student enrolled.", "success")
                else:
                    flash("Could not enroll (duplicate or invalid student).", "error")
        elif action == "unenroll":
            studentid = request.form.get("studentid", type=int)
            if studentid:
                rq.unenroll_student(studentid, courseid)
                flash("Student unenrolled.", "success")
        elif action == "reset_password":
            studentid = request.form.get("studentid", type=int)
            new_password = request.form.get("new_password", "")
            if studentid and new_password:
                new_hash = hash_password(new_password)
                if rq.reset_student_password(studentid, new_hash):
                    flash("Password reset.", "success")
                else:
                    flash("Could not reset password.", "error")
        elif action == "create":
            fname = request.form.get("fname", "").strip()
            lname = request.form.get("lname", "").strip()
            email = request.form.get("email", "").strip()
            password = request.form.get("password", "")
            if fname and lname and email and password:
                result = rq.create_student(
                    fname, lname, email, hash_password(password)
                )
                if result:
                    rq.enroll_student(result["studentid"], courseid)
                    flash("Student created and enrolled.", "success")
                else:
                    flash("Could not create student (duplicate email?).", "error")
        elif action == "delete":
            studentid = request.form.get("studentid", type=int)
            if studentid:
                rq.unenroll_student(studentid, courseid)
                if rq.delete_student(studentid):
                    flash("Student removed.", "success")
                else:
                    flash("Student unenrolled but account could not be deleted.", "error")
        return redirect(url_for("course_roster", courseid=courseid))

    ctx["roster"] = rq.get_students_in_course(courseid)
    return render_template("course/roster.html", **ctx)


# ---------------------------------------------------------------------------
# Data Center routes
# ---------------------------------------------------------------------------


@app.route("/dc/")
@app.route("/dc")
@dc_login_required
def dc_home():
    if is_dc_admin():
        dc_admin_with_cohort()
        courseid = dc_admin_courseid()
        videos = dq.get_videos_for_course(courseid)
        if videos:
            return redirect(url_for("dc_video", videoid=videos[0]["videoid"]))
        return redirect(url_for("dc_admin_weeks", courseid=courseid))
    student = dq.get_student_public(session["user_id"])
    if not student:
        abort(403)
    videos = dq.get_videos_for_course(student["courseid"])
    if videos:
        return redirect(url_for("dc_video", videoid=videos[0]["videoid"]))
    return redirect(url_for("dc_about"))


@app.route("/dc/about")
@dc_login_required
def dc_about():
    ctx = dc_page_context("about")
    return render_template("dc/about.html", **ctx)


@app.route("/dc/video/<int:videoid>", methods=["GET", "POST"])
@dc_login_required
def dc_video(videoid):
    video = dq.get_video(videoid)
    if not video:
        abort(404)
    week = dq.get_week(video["weekid"])
    if not week:
        abort(404)

    if is_dc_student():
        student = dq.get_student_public(session["user_id"])
        if not student or not video_in_division(videoid, student["courseid"]):
            abort(403)
        dq.get_or_create_progress(student["studentid"], videoid)

        if request.method == "POST":
            action = request.form.get("action")
            if action == "mark_watched":
                dq.mark_video_watched(student["studentid"], videoid)
                flash("Lesson marked complete.", "success")
            elif action == "submit_assignment":
                miniokey = request.form.get("miniokey", "").strip()
                if not miniokey:
                    flash("Submission key is required.", "error")
                elif dq.get_student_assignment_for_video(student["studentid"], videoid):
                    flash("You already submitted for this lesson.", "error")
                else:
                    result = dq.submit_assignment(videoid, student["studentid"], miniokey)
                    if result:
                        flash("Assignment submitted.", "success")
                    else:
                        flash("Could not submit assignment.", "error")
            return redirect(url_for("dc_video", videoid=videoid))

        progress = dq.get_or_create_progress(student["studentid"], videoid)
        assignment = dq.get_student_assignment_for_video(student["studentid"], videoid)
        ctx = dc_student_context(
            "content",
            student,
            video=video,
            week=week,
            progress=progress,
            assignment=assignment,
            lesson_rail=build_lesson_rail(
                student["studentid"], student["courseid"], videoid
            ),
        )
        return render_template("dc/video.html", **ctx)

    # Admin may view any video for grading context (cohort-scoped submission stats)
    admin, cohortid = dc_admin_with_cohort()
    ctx = dc_admin_context(
        "content",
        admin,
        courseid=week["courseid"],
        video=video,
        week=week,
        progress=None,
        assignment=None,
        lesson_rail=build_lesson_rail_for_course(
            week["courseid"], videoid, include_grading=True, cohortid=cohortid
        ),
    )
    return render_template("dc/video.html", **ctx)


@app.route("/dc/assignments")
@dc_login_required
def dc_assignments():
    if is_dc_admin():
        admin, cohortid = dc_admin_with_cohort()
        courseid = dc_admin_courseid()
        ctx = dc_admin_context(
            "assignments",
            admin,
            courseid=courseid,
            assignments=dq.get_assignments_for_course(courseid, cohortid=cohortid),
            admin_assignments_view=True,
        )
        return render_template("dc/assignments.html", **ctx)

    if not is_dc_student():
        abort(403)
    student = dq.get_student_public(session["user_id"])
    if not student:
        abort(403)
    ctx = dc_student_context(
        "assignments",
        student,
        assignments=dq.get_assignments_for_student(student["studentid"]),
    )
    return render_template("dc/assignments.html", **ctx)


@app.route("/dc/grades")
@dc_login_required
def dc_grades():
    if is_dc_admin():
        admin, cohortid = dc_admin_with_cohort()
        courseid = dc_admin_courseid()
        ctx = dc_admin_context(
            "grades",
            admin,
            courseid=courseid,
            lesson_rail=build_lesson_rail_for_course(
                courseid, include_grading=True, cohortid=cohortid
            ),
            admin_grades_view=True,
        )
        return render_template("dc/grades.html", **ctx)

    if not is_dc_student():
        abort(403)
    student = dq.get_student_public(session["user_id"])
    if not student:
        abort(403)
    ctx = dc_student_context(
        "grades",
        student,
        lesson_rail=build_lesson_rail(
            student["studentid"],
            student["courseid"],
            include_assignments=True,
        ),
    )
    return render_template("dc/grades.html", **ctx)


@app.route("/dc/progress")
@dc_login_required
def dc_progress():
    if is_dc_admin():
        admin, cohortid = dc_admin_with_cohort()
        courseid = dc_admin_courseid()
        students_progress = dq.get_students_progress_for_course(
            courseid, cohortid=cohortid
        )
        for row in students_progress:
            total = row["total_videos"] or 0
            watched = row["watched_videos"] or 0
            row["completion_pct"] = int(watched / total * 100) if total else 0
        ctx = dc_admin_context(
            "progress",
            admin,
            courseid=courseid,
            students_progress=students_progress,
            admin_progress_view=True,
        )
        return render_template("dc/progress.html", **ctx)

    if not is_dc_student():
        abort(403)
    student = dq.get_student_public(session["user_id"])
    if not student:
        abort(403)
    ctx = dc_student_context(
        "progress",
        student,
        completion=dq.get_course_completion(student["studentid"]),
        resume=dq.get_resume_point(student["studentid"]),
    )
    return render_template("dc/progress.html", **ctx)


@app.route("/dc/roster")
@dc_login_required
def dc_roster():
    user = current_user()
    if not user:
        abort(403)

    if is_dc_admin():
        admin, cohortid = dc_admin_with_cohort()
        ctx = dc_admin_context(
            "roster",
            admin,
            roster=dq.get_cohort_roster(cohortid),
        )
        return render_template("dc/roster.html", **ctx)

    cohortid = user.get("cohortid")
    if not cohortid:
        abort(403)
    ctx = dc_page_context("roster", roster=dq.get_cohort_roster(cohortid))
    return render_template("dc/roster.html", **ctx)


@app.route("/dc/messenger")
@app.route("/dc/messenger/<int:channelid>", methods=["GET", "POST"])
@dc_login_required
def dc_messenger(channelid=None):
    member_type, member_id = dc_member_type_and_id()
    channel_groups = dq.get_channels_for_member(member_type, member_id)
    all_channels = flatten_messenger_channels(channel_groups)
    active_channel = None
    messages = []
    channel_members = []
    cohort_contacts = dq.get_cohort_contacts(member_type, member_id)

    if channelid is not None:
        if not can_access_dc_channel(channelid, member_type, member_id):
            abort(403)
        active_channel = next(
            (ch for ch in all_channels if ch["channelid"] == channelid),
            None,
        )
        if active_channel is None:
            ch_row = dq.get_channel(channelid)
            if ch_row and can_access_dc_channel(channelid, member_type, member_id):
                ch_row["display_name"] = dq.channel_display_name(
                    channelid, member_type, member_id
                )
                active_channel = ch_row
            else:
                abort(403)

        if request.method == "POST":
            content = request.form.get("content", "").strip()
            if content:
                dq.post_message(channelid, member_type, member_id, content)
                flash("Message sent.", "success")
            return redirect(url_for("dc_messenger", channelid=channelid))

        messages = dq.get_messages_for_channel(channelid, limit=50)
        channel_members = dq.get_channel_members(channelid)

    user = current_user()
    student = user if is_dc_student() else None
    course = dq.get_course(student["courseid"]) if student else None
    if is_dc_admin() and course is None:
        course = dq.get_course(1)

    return render_template(
        "dc/messenger.html",
        channel_groups=channel_groups,
        active_channel=active_channel,
        messages=messages,
        channel_members=channel_members,
        cohort_contacts=cohort_contacts,
        member_type=member_type,
        member_id=member_id,
        course=course,
        monogram=course_monogram,
    )


@app.route("/dc/messenger/dm", methods=["POST"])
@dc_login_required
def dc_messenger_start_dm():
    member_type, member_id = dc_member_type_and_id()
    peer_type = request.form.get("peer_type", "").strip()
    peer_id = request.form.get("peer_id", type=int)
    if peer_type not in ("student", "admin") or not peer_id:
        flash("Select someone to message.", "error")
        return redirect(url_for("dc_messenger"))

    cohortid = dq.get_member_cohortid(member_type, member_id)
    if cohortid is None:
        flash("You must belong to a cohort to send direct messages.", "error")
        return redirect(url_for("dc_messenger"))

    peer_cohort = dq.get_member_cohortid(peer_type, peer_id)
    if peer_cohort != cohortid:
        abort(403)

    if peer_type == member_type and peer_id == member_id:
        flash("You cannot message yourself.", "error")
        return redirect(url_for("dc_messenger"))

    channel = dq.find_or_create_direct_channel(
        cohortid, member_type, member_id, peer_type, peer_id
    )
    if not channel:
        flash("Could not open direct message.", "error")
        return redirect(url_for("dc_messenger"))
    return redirect(url_for("dc_messenger", channelid=channel["channelid"]))


@app.route("/dc/messenger/<int:channelid>/delete", methods=["POST"])
@dc_admin_required
def dc_messenger_delete(channelid):
    member_type, member_id = dc_member_type_and_id()
    if not can_access_dc_channel(channelid, member_type, member_id):
        abort(403)
    messagesid = request.form.get("messagesid", type=int)
    if messagesid:
        dq.delete_message(messagesid)
        flash("Message deleted.", "success")
    return redirect(url_for("dc_messenger", channelid=channelid))


@app.route("/dc/calls")
@dc_login_required
def dc_calls():
    user = current_user()
    student = user if is_dc_student() else None
    admin = user if is_dc_admin() else None
    room = jitsi_room_name(student, admin)
    ctx = dc_page_context(
        "calls",
        jitsi_room=room,
        jitsi_url=f"https://meet.jit.si/{room}",
    )
    return render_template("dc/calls.html", **ctx)


@app.route("/dc/account", methods=["GET", "POST"])
@dc_login_required
def dc_account():
    if request.method == "POST":
        action = request.form.get("action")
        if action == "overlay":
            choice = request.form.get("overlay_color", "maroon")
            if choice in ("maroon", "slate", "none"):
                session["overlay_color"] = choice
                flash("Display preference saved.", "success")
            return redirect(url_for("dc_account"))

        if not is_dc_student():
            flash("Only students can edit profile here.", "error")
            return redirect(url_for("dc_account"))

        fname = request.form.get("fname", "").strip()
        lname = request.form.get("lname", "").strip()
        email = request.form.get("email", "").strip()
        bio = request.form.get("bio", "").strip() or None
        if not fname or not lname or not email:
            flash("Name and email are required.", "error")
        else:
            updated = dq.update_student_profile(
                session["user_id"], fname, lname, email, bio
            )
            if updated:
                session["email"] = email
                flash("Profile updated.", "success")
            else:
                flash("Could not update profile.", "error")
        return redirect(url_for("dc_account"))

    return render_template("dc/account.html", profile=current_user())


@app.route("/dc/admin/weeks", methods=["GET", "POST"])
@dc_admin_required
def dc_admin_weeks():
    admin = dq.get_admin_public(session["user_id"])
    courseid = (
        request.args.get("courseid", type=int)
        or request.form.get("courseid", type=int)
        or dc_admin_courseid()
    )

    if request.method == "POST":
        action = request.form.get("action")
        if action == "create_week":
            subject = request.form.get("subject", "").strip()
            num = request.form.get("num", type=int)
            description = request.form.get("description", "").strip()
            cid = request.form.get("courseid", type=int) or courseid
            if subject and num and description:
                dq.create_week(cid, subject, num, description)
                flash("Week created.", "success")
        elif action == "update_week":
            weekid = request.form.get("weekid", type=int)
            subject = request.form.get("subject", "").strip()
            num = request.form.get("num", type=int)
            description = request.form.get("description", "").strip()
            if weekid and subject and num and description:
                week = dq.get_week(weekid)
                if week:
                    dq.update_week(weekid, subject, num, description)
                    flash("Week updated.", "success")
        elif action == "delete_week":
            weekid = request.form.get("weekid", type=int)
            if weekid and dq.delete_week(weekid):
                flash("Week deleted.", "success")
            else:
                flash("Could not delete week.", "error")
        elif action == "create_video":
            weekid = request.form.get("weekid", type=int)
            day = request.form.get("day", type=int)
            title = request.form.get("title", "").strip()
            miniokey = request.form.get("miniokey", "").strip()
            script = request.form.get("script", "").strip()
            instructions = request.form.get("instructions", "").strip()
            reflection = request.form.get("reflection", "").strip()
            if weekid and day and title and miniokey and script and instructions and reflection:
                dq.create_video(weekid, day, title, miniokey, script, instructions, reflection)
                flash("Video created.", "success")
        elif action == "update_video":
            videoid = request.form.get("videoid", type=int)
            day = request.form.get("day", type=int)
            title = request.form.get("title", "").strip()
            miniokey = request.form.get("miniokey", "").strip()
            instructions = request.form.get("instructions", "").strip()
            reflection = request.form.get("reflection", "").strip()
            if videoid and day and title and miniokey and instructions and reflection:
                video = dq.get_video(videoid)
                if video:
                    dq.update_video(
                        videoid, day, title, miniokey, video["script"], instructions, reflection
                    )
                    flash("Video updated.", "success")
        elif action == "delete_video":
            videoid = request.form.get("videoid", type=int)
            if videoid and dq.delete_video(videoid):
                flash("Video deleted.", "success")
            else:
                flash("Could not delete video.", "error")
        return redirect(url_for("dc_admin_weeks", courseid=courseid))

    weeks = dq.get_weeks_for_course(courseid)
    all_videos = dq.get_videos_for_course(courseid)
    videos_by_week: dict[int, list] = {}
    for video in all_videos:
        videos_by_week.setdefault(video["weekid"], []).append(video)

    ctx = dc_admin_context(
        "admin_weeks",
        admin,
        courseid=courseid,
        weeks=weeks,
        videos_by_week=videos_by_week,
    )
    return render_template("dc/admin_weeks.html", **ctx)


@app.route("/dc/admin/grade/<int:videoid>", methods=["GET", "POST"])
@dc_admin_required
def dc_admin_grade_video(videoid):
    admin, cohortid = dc_admin_with_cohort()
    video = dq.get_video(videoid)
    if not video:
        abort(404)
    week = dq.get_week(video["weekid"])
    if not week:
        abort(404)

    if request.method == "POST":
        assignmentid = request.form.get("assignmentid", type=int)
        status = request.form.get("status", "").strip()
        feedback = request.form.get("feedback", "").strip() or None
        if assignmentid and status:
            assignment = dq.get_assignment(assignmentid)
            if assignment and dq.student_in_cohort(
                assignment["studentid"], cohortid
            ):
                result = dq.grade_assignment(assignmentid, status, feedback)
                if result:
                    flash("Grade saved.", "success")
                else:
                    flash("Could not save grade.", "error")
            else:
                flash("You can only grade students in your cohort.", "error")
        return redirect(url_for("dc_admin_grade_video", videoid=videoid))

    ctx = dc_admin_context(
        "admin_analytics",
        admin,
        courseid=week["courseid"],
        video=video,
        submissions=dq.get_submissions_for_video(videoid, cohortid=cohortid),
    )
    return render_template("dc/admin_grade.html", **ctx)


@app.route("/dc/admin/analytics")
@dc_admin_required
def dc_admin_analytics():
    admin, cohortid = dc_admin_with_cohort()
    courseid = request.args.get("courseid", type=int) or dc_admin_courseid()
    ctx = dc_admin_context(
        "admin_analytics",
        admin,
        courseid=courseid,
        analytics=dq.get_submission_analytics(courseid, cohortid=cohortid),
    )
    return render_template("dc/admin_analytics.html", **ctx)


@app.route("/dc/admin/students", methods=["GET", "POST"])
@dc_admin_required
def dc_admin_students():
    admin, cohortid = dc_admin_with_cohort()

    if request.method == "POST":
        action = request.form.get("action")
        if action == "create_student":
            fname = request.form.get("fname", "").strip()
            lname = request.form.get("lname", "").strip()
            email = request.form.get("email", "").strip()
            password = request.form.get("password", "")
            courseid = request.form.get("courseid", type=int)
            bio = request.form.get("bio", "").strip() or None
            if fname and lname and email and password and courseid:
                pw_hash = hash_password(password)
                result = dq.create_student(
                    fname, lname, email, pw_hash, courseid, cohortid, bio
                )
                if result:
                    flash("Student created.", "success")
                else:
                    flash("Could not create student (duplicate email?).", "error")
        elif action == "reset_password":
            studentid = request.form.get("studentid", type=int)
            new_password = request.form.get("new_password", "")
            if studentid and new_password:
                if dq.reset_student_password(
                    studentid, hash_password(new_password), cohortid=cohortid
                ):
                    flash("Password reset.", "success")
                else:
                    flash("Could not reset password.", "error")
        elif action == "delete_student":
            studentid = request.form.get("studentid", type=int)
            if studentid and dq.delete_student(studentid, cohortid=cohortid):
                flash("Student removed.", "success")
            else:
                flash("Could not remove student.", "error")
        return redirect(url_for("dc_admin_students"))

    ctx = dc_admin_context(
        "admin_students",
        admin,
        students=dq.get_all_students(cohortid=cohortid),
    )
    return render_template("dc/admin_students.html", **ctx)


if __name__ == "__main__":
    app.run(debug=True, port=int(os.getenv("PORT", "5000")))
