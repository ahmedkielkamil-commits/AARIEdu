"""
AARI Educational Suite — Flask application (robotics + data center).
"""

from __future__ import annotations

import os
from datetime import datetime
from functools import wraps
from urllib.parse import quote, urlencode, urlparse

import bcrypt
import requests
from flask import (
    Flask,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
    Response,
)
from werkzeug.middleware.proxy_fix import ProxyFix
import dcqueries as dq
import documents as lesson_documents
import miniIO
import roboticsqueries as rq
import streaming as video_streaming
import submissions as student_submissions
from db import mysql_config_hint
from documents import DocumentError
from streaming import StreamingAuthError
from submissions import SubmissionError

app = Flask(__name__, template_folder="Templates", static_folder="static")
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-change-me-in-production")
if os.getenv("BEHIND_PROXY", "").lower() in ("1", "true", "yes"):
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    app.config["SESSION_COOKIE_SECURE"] = True

_mysql_hint = mysql_config_hint()
if _mysql_hint:
    print(f"\n*** MySQL config: {_mysql_hint}\n")


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
            return redirect(url_for("dc_login", next=request.url))
        return view(*args, **kwargs)

    return wrapped


def dc_platform_admin_required(view):
    @wraps(view)
    @dc_login_required
    def wrapped(*args, **kwargs):
        if session.get("user_type") != "admin":
            abort(403)
        admin = dq.get_admin_public(session["user_id"])
        if not admin:
            abort(403)
        return view(*args, **kwargs)

    return wrapped


def dc_cohort_staff_required(view):
    """Cohort leaders and platform admins (grading, roster, cohort analytics)."""
    @wraps(view)
    @dc_login_required
    def wrapped(*args, **kwargs):
        if not is_dc_cohort_staff():
            abort(403)
        return view(*args, **kwargs)

    return wrapped


# Backward-compatible alias for course-content routes
dc_admin_required = dc_platform_admin_required


def is_dc_suite() -> bool:
    return session.get("suite") == "dc"


def is_dc_admin() -> bool:
    """Platform course admin (authoring, all tracks)."""
    return is_dc_suite() and session.get("user_type") == "admin"


def is_dc_leader() -> bool:
    return is_dc_suite() and session.get("user_type") == "leader"


def is_dc_cohort_staff() -> bool:
    return is_dc_admin() or is_dc_leader()


def is_dc_student() -> bool:
    return is_dc_suite() and session.get("user_type") == "student"


def dc_video_stream_url(videoid: int) -> str | None:
    """Presigned MinIO playback URL for the current DC user, or None if unavailable."""
    try:
        if is_dc_admin():
            return video_streaming.get_video_stream_url(
                videoid, None, is_admin=True
            )
        if is_dc_leader():
            return video_streaming.get_video_stream_url(
                videoid, None, is_staff=True
            )
        if is_dc_student():
            student = dq.get_student_public(session["user_id"])
            if student:
                return video_streaming.get_video_stream_url(videoid, student)
    except StreamingAuthError:
        return None
    except Exception:
        return None
    return None


def dc_can_read_document(videoid: int) -> bool:
    """Lesson PDFs follow the same access rules as lesson video playback."""
    if is_dc_admin() or is_dc_leader():
        return True
    if is_dc_student():
        student = dq.get_student_public(session["user_id"])
        return bool(student) and dq.student_can_access_video(
            student["studentid"], videoid
        )
    return False


def current_user():
    if "user_id" not in session:
        return None
    if session.get("suite") == "dc":
        if session.get("user_type") == "admin":
            return dq.get_admin_public(session["user_id"])
        if session.get("user_type") == "leader":
            return dq.get_leader_public(session["user_id"])
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
        return rq.get_teacher_public(session["user_id"]) is not None
    return rq.is_student_enrolled(session["user_id"], courseid)


def is_instructor_for(courseid: int) -> bool:
    return is_instructor() and can_access_course(courseid)


def rail_courses():
    """Courses shown in the left monogram rail."""
    if "user_id" not in session:
        return []
    if session.get("user_type") == "student":
        return rq.get_courses_for_student(session["user_id"])
    if not rq.get_teacher_public(session["user_id"]):
        return []
    return [
        {"courseid": c["courseid"], "title": c["title"]} for c in rq.get_all_courses()
    ]


def student_progress(courseid: int, studentid: int) -> int:
    total_days = rq.count_days_for_course(courseid)
    if not total_days:
        return 0
    classid = rq.get_classid_for_student_course(studentid, courseid)
    if not classid:
        return 0
    submitted = rq.count_submitted_tickets_for_class(classid)
    return int(submitted / total_days * 100)


def day_form_fields() -> tuple[dict | None, str | None]:
    """Lecture day fields from a Modules form as (fields, error message)."""
    num = request.form.get("num", type=int)
    title = request.form.get("title", "").strip()
    slidelink = request.form.get("slidelink", "").strip()
    if not num or not title:
        return None, "Day number and title are required."
    if slidelink and not slidelink.lower().startswith(("http://", "https://")):
        return None, "Slide link must start with http:// or https://."
    if len(slidelink) > 255:
        return None, "Slide link must be 255 characters or fewer."
    return {
        "num": num,
        "title": title[:255],
        "description": request.form.get("description", "").strip()[:255],
        "assignment": request.form.get("assignment", "").strip(),
        "slidelink": slidelink,
    }, None


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


def google_calendar_invite_url(admin: dict, student: dict | None = None) -> str:
    """Pre-filled Google Calendar event with the admin as a guest; the student picks the time and saves."""
    title = f"AARI Help Desk: 1:1 with {admin['fname']} {admin['lname']}"
    details = "1:1 help session booked from the AARI Help Desk."
    if student:
        title += f" ({student['fname']} {student['lname']})"
        details += f"\nStudent: {student['fname']} {student['lname']} <{student['email']}>"
    params = {
        "action": "TEMPLATE",
        "text": title,
        "details": details,
        "add": admin["email"],
    }
    return "https://calendar.google.com/calendar/render?" + urlencode(params, quote_via=quote)


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def redirect_to_submission(object_key: str | None, fallback_url: str):
    """Send the viewer to a presigned MinIO URL, or back with an error if the file is gone."""
    url = student_submissions.submission_url(object_key)
    if not url:
        flash("That file isn't available right now.", "error")
        return redirect(fallback_url)
    return redirect(url)


# ---------------------------------------------------------------------------
# Data Center helpers
# ---------------------------------------------------------------------------


def dc_member_type_and_id() -> tuple[str, int]:
    if is_dc_admin():
        return "admin", session["user_id"]
    if is_dc_leader():
        return "leader", session["user_id"]
    return "student", session["user_id"]


def dc_staff_cohortid() -> int | None:
    """Cohort scope for grading/analytics: leaders are fixed; admins may filter."""
    if is_dc_leader():
        student = dq.get_student_public(session["user_id"])
        return student.get("cohortid") if student else None
    if is_dc_admin():
        return request.args.get("cohortid", type=int) or request.form.get(
            "cohortid", type=int
        )
    return None


def dc_leader_with_cohort() -> tuple[dict, int]:
    """Return (leader row, cohortid) or abort."""
    if not is_dc_leader():
        abort(403)
    leader = dq.get_leader_public(session["user_id"])
    cohortid = leader.get("cohortid") if leader else None
    if not leader or not cohortid:
        abort(403)
    return leader, cohortid


def dc_admin_with_cohort() -> tuple[dict | None, int | None]:
    """Return (admin row, cohortid) for staff views; cohortid None = all cohorts."""
    if is_dc_admin():
        return dq.get_admin_public(session["user_id"]), dc_staff_cohortid()
    if is_dc_leader():
        student, cohortid = dc_leader_with_cohort()
        return student, cohortid
    abort(403)


def dc_admin_courseid() -> int:
    """Active division track for DC admin pages (query param or session, default 1)."""
    cid = request.args.get("courseid", type=int)
    if cid:
        session["dc_courseid"] = cid
        return cid
    return session.get("dc_courseid") or 1


def resolve_next_video(studentid: int, courseid: int) -> dict | None:
    """Return the lesson the student should watch next (resume or first unwatched)."""
    unlocked = dq.get_week_gate(studentid)["unlocked"]
    videos = [
        v for v in dq.get_videos_for_student(studentid) if v["weekid"] in unlocked
    ]
    unlocked_videoids = {v["videoid"] for v in videos}

    resume = dq.get_resume_point(studentid)
    if resume and not resume.get("watched") and resume["videoid"] in unlocked_videoids:
        return resume

    if not videos:
        return None

    progress_rows = dq.get_progress_for_student(studentid)
    watched = {p["videoid"]: p["watched"] for p in progress_rows}
    for video in videos:
        if not watched.get(video["videoid"]):
            return {
                "videoid": video["videoid"],
                "video_title": video["title"],
                "week_num": video["week_num"],
                "day_num": video["day"],
                "watched": False,
                "last_position": 0,
            }

    last = videos[-1]
    return {
        "videoid": last["videoid"],
        "video_title": last["title"],
        "week_num": last["week_num"],
        "day_num": last["day"],
        "watched": True,
        "last_position": 0,
    }

@app.route("/api/speak", methods=["POST"])
def api_speak():
    data = request.get_json()
    text = data.get("text", "").strip()
    if text == "":
        return jsonify({"error": "No text"}), 400

    key = os.environ.get("Eleven_Labs_Key", "").strip()
    voice_id = os.environ.get("Voice_Id", "").strip()
    if key == "" or voice_id == "":
        return jsonify({"error": "Missing Eleven_Labs_Key or Voice_Id"}), 500

    try:
        resp = requests.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
            params={"output_format": "mp3_44100_128"},
            headers={
                "xi-api-key": key,
                "Content-Type": "application/json",
                "Accept": "audio/mpeg",
            },
            json={"text": text, "model_id": "eleven_multilingual_v2"},
            timeout=60,
        )
    except requests.RequestException as exc:
        return jsonify({"error": f"Could not reach ElevenLabs: {exc.__class__.__name__}"}), 500

    if resp.status_code != 200:
        detail = ""
        try:
            body = resp.json().get("detail")
            detail = body.get("message", "") if isinstance(body, dict) else str(body or "")
        except ValueError:
            pass
        message = f"ElevenLabs speech failed ({resp.status_code})"
        return jsonify({"error": f"{message}: {detail}" if detail else message}), 500

    if not resp.content or not resp.headers.get("Content-Type", "").startswith("audio/"):
        return jsonify({"error": "ElevenLabs returned no audio"}), 500

    return Response(resp.content, mimetype="audio/mpeg")

def build_week_path(lesson_rail: list[dict], next_videoid: int | None) -> list[dict]:
    """Summarize week completion for the dashboard learning path."""
    path: list[dict] = []
    for group in lesson_rail:
        videos = group["videos"]
        all_watched = bool(videos) and all(v["watched"] for v in videos)
        is_current = next_videoid is not None and any(
            v["videoid"] == next_videoid for v in videos
        )
        path.append(
            {
                "week": group["week"],
                "all_watched": all_watched,
                "is_current": is_current,
                "locked": group.get("locked", False),
            }
        )
    return path


def build_lesson_rail(
    studentid: int,
    courseid: int,
    current_videoid: int | None = None,
    *,
    include_assignments: bool = False,
) -> list[dict]:
    weeks = dq.get_weeks_for_student(studentid)
    videos = dq.get_videos_for_student(studentid)
    unlocked = dq.get_week_gate(studentid)["unlocked"]
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
    rail = []
    previous = None
    for week in weeks:
        rail.append(
            {
                "week": week,
                "videos": by_week.get(week["weekid"], []),
                "locked": week["weekid"] not in unlocked,
                "previous_week": previous,
            }
        )
        previous = week
    return rail


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
    cohort = dq.get_cohort(student["cohortid"]) if student.get("cohortid") else None
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
        "orchestration_branch": student.get("orchestration_branch"),
        "student_is_college": bool(student.get("college")),
    }
    ctx.update(extra)
    return ctx


def dc_leader_context(active: str, leader: dict, **extra) -> dict:
    courseid = extra.pop("courseid", None) or dc_admin_courseid()
    session["dc_courseid"] = courseid
    course = dq.get_course(courseid)
    cohort = dq.get_cohort(leader["cohortid"])
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


def dc_admin_context(active: str, admin: dict, **extra) -> dict:
    courseid = extra.pop("courseid", None) or dc_admin_courseid()
    session["dc_courseid"] = courseid
    course = dq.get_course(courseid)
    cohortid = extra.get("cohortid") or dc_staff_cohortid()
    cohort = dq.get_cohort(cohortid) if cohortid else None
    ctx = {
        "course": course,
        "courseid": courseid,
        "cohort": cohort,
        "sidebar_active": active,
        "progress_pct": 0,
        "monogram": course_monogram,
        "all_courses": dq.get_all_courses(),
        "all_cohorts": dq.get_all_cohorts(),
    }
    ctx.update(extra)
    return ctx


def dc_page_context(active: str, **extra) -> dict:
    if is_dc_admin():
        admin = dq.get_admin_public(session["user_id"])
        if not admin:
            abort(403)
        return dc_admin_context(active, admin, **extra)
    if is_dc_leader():
        leader = dq.get_leader_public(session["user_id"])
        if not leader:
            abort(403)
        return dc_leader_context(active, leader, **extra)
    student = dq.get_student_public(session["user_id"])
    if not student:
        abort(403)
    return dc_student_context(active, student, **extra)


def jitsi_room_name(
    student: dict | None,
    admin: dict | None,
    leader: dict | None = None,
) -> str:
    cohortid = None
    courseid = None
    if student:
        cohortid = student["cohortid"]
        courseid = student["courseid"]
    elif leader:
        cohortid = leader["cohortid"]
        courseid = session.get("dc_courseid") or 1
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
        "user_is_dc_leader": is_dc_leader(),
        "user_is_dc_cohort_staff": is_dc_cohort_staff(),
        "submission_accept": student_submissions.ACCEPT_ATTR,
    }


@app.template_filter("format_datetime")
def format_datetime(value):
    if not value:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%b %d, %Y · %I:%M %p")
    return str(value)


@app.template_filter("attachment_name")
def attachment_name(object_key: str | None) -> str:
    return student_submissions.display_name(object_key)


@app.template_filter("branch_label")
def branch_label(branch: str | None) -> str:
    """Human-readable orchestration branch name."""
    if branch == "software":
        return "Software branch"
    if branch == "hardware":
        return "Hardware branch"
    return ""


# ---------------------------------------------------------------------------
# Public routes
# ---------------------------------------------------------------------------


@app.route("/")
def landing():
    return render_template("landing.html")


def suite_for_path(url: str | None) -> str | None:
    """Which program a URL belongs to ("dc" or "robotics"), or None for shared pages."""
    if not url:
        return None
    path = urlparse(url).path
    if path == "/dc" or path.startswith("/dc/") or path.startswith("/api/"):
        return "dc"
    if path.startswith(("/course/", "/teacher/", "/student/")):
        return "robotics"
    return None


# (suite, user_type, lookup, id column, default landing endpoint), tried in order per login page
LOGIN_ACCOUNTS = {
    "robotics": [
        ("robotics", "student", rq.get_student_by_email, "studentid", "student_home"),
        ("robotics", "teacher", rq.get_teacher_by_email, "teacherid", "teacher_home"),
    ],
    "dc": [
        ("dc", "student", dq.get_student_by_email, "studentid", "dc_home"),
        ("dc", "leader", dq.get_leader_by_email, "leaderid", "dc_home"),
        ("dc", "admin", dq.get_admin_by_email, "adminid", "dc_home"),
    ],
}


def _password_unset(account: dict) -> bool:
    """True when the account has no password yet (first-login setup)."""
    pw = account.get("password")
    return pw is None or pw == ""


def _set_account_password(suite: str, user_type: str, user_id: int, pw_hash: str) -> bool:
    """Persist a new password on first login (bootcamp or high school)."""
    if suite == "dc":
        if user_type == "admin":
            return bool(dq.set_admin_password(user_id, pw_hash))
        if user_type == "student":
            return dq.set_student_password(user_id, pw_hash)
        if user_type == "leader":
            return dq.set_leader_password(user_id, pw_hash)
    elif suite == "robotics":
        if user_type == "student":
            return rq.reset_student_password(user_id, pw_hash)
        if user_type == "teacher":
            return rq.set_teacher_password(user_id, pw_hash)
    return False


def _finish_login(
    suite: str,
    user_type: str,
    user_id: int,
    email: str,
    landing: str,
    next_url: str | None,
):
    session.clear()
    session["suite"] = suite
    session["user_id"] = user_id
    session["user_type"] = user_type
    session["email"] = email
    if next_url and suite_for_path(next_url) in (None, suite):
        return redirect(next_url)
    return redirect(url_for(landing))


def handle_login(program: str):
    """Shared login form; each program's page only checks that program's accounts."""
    next_url = request.args.get("next")

    def render_login(**extra):
        return render_template("login.html", program=program, **extra)

    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")
        first_time = request.form.get("first_time") == "on"

        if not email:
            flash("Email is required.", "error")
            return render_login(first_time=first_time)

        if first_time:
            if len(password) < 8:
                flash("Use a password of at least 8 characters.", "error")
                return render_login(email=email, first_time=True)
            if password != confirm:
                flash("Passwords did not match.", "error")
                return render_login(email=email, first_time=True)

            for suite, user_type, lookup, id_col, landing in LOGIN_ACCOUNTS[program]:
                account = lookup(email)
                if not account:
                    continue
                if not _password_unset(account):
                    flash(
                        "This account already has a password. "
                        "Uncheck “first time” and sign in normally.",
                        "error",
                    )
                    return render_login(email=email, first_time=False)
                pw_hash = hash_password(password)
                if not _set_account_password(suite, user_type, account[id_col], pw_hash):
                    flash("Could not save your password. Contact an administrator.", "error")
                    return render_login(email=email, first_time=True)
                flash("Password saved. You're signed in.", "success")
                return _finish_login(
                    suite, user_type, account[id_col], account["email"], landing, next_url
                )

            flash("No invited account found for that email.", "error")
            return render_login(email=email, first_time=True)

        if not password:
            flash("Email and password are required.", "error")
            return render_login(email=email)

        for suite, user_type, lookup, id_col, landing in LOGIN_ACCOUNTS[program]:
            account = lookup(email)
            if not account:
                continue
            if _password_unset(account):
                flash(
                    "Check “First time logging in” to choose a password, "
                    "or sign in with Microsoft.",
                    "error",
                )
                return render_login(email=email, first_time=True)
            if verify_password(password, account["password"]):
                return _finish_login(
                    suite, user_type, account[id_col], account["email"], landing, next_url
                )

        flash("Invalid email or password.", "error")
        return render_login(email=email)

    return render_login()


@app.route("/login", methods=["GET", "POST"])
def login():
    return handle_login("robotics")


@app.route("/dc/login", methods=["GET", "POST"])
def dc_login():
    return handle_login("dc")


# ---------------------------------------------------------------------------
# Microsoft Entra ID (high school + bootcamp)
# ---------------------------------------------------------------------------

_MS_RESERVED_SCOPES = frozenset({"openid", "profile", "offline_access"})
_MS_PROGRAM_ROLES = {
    "robotics": frozenset({"student", "teacher"}),
    "dc": frozenset({"student", "leader", "admin"}),
}


def _env_first(*names: str) -> str:
    """Return the first non-empty environment value among the given names."""
    for name in names:
        value = (os.getenv(name) or "").strip()
        if value:
            return value
    return ""


def _ms_authority(raw: str) -> str:
    """
    Normalize an Entra authority / authorize URL to what MSAL expects, e.g.
    https://login.microsoftonline.com/common
    """
    raw = raw.strip().rstrip("/")
    if not raw:
        return ""
    for marker in ("/oauth2/", "/v2.0"):
        idx = raw.find(marker)
        if idx != -1:
            return raw[:idx].rstrip("/")
    return raw


def _ms_config() -> dict[str, str] | None:
    """
    Return Entra settings from the environment, or None if incomplete.

    Primary names (from the Entra app registration):
      Client_id, Value (client secret string), Redirect_url, auth_url
    MS_* names are accepted as fallbacks.
    Secret_id is the Azure secret identifier, not the secret itself — ignored.
    """
    client_id = _env_first("Client_id", "MS_CLIENT_ID")
    # Azure portal labels the secret string "Value"; Secret_id is only an id.
    client_secret = _env_first("Value", "MS_CLIENT_SECRET")
    redirect_uri = _env_first("Redirect_url", "MS_REDIRECT_URI")
    authority = _ms_authority(_env_first("auth_url", "MS_AUTHORITY"))
    if not (client_id and client_secret and redirect_uri and authority):
        return None
    return {
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "authority": authority,
    }


def _ms_scopes() -> list[str]:
    # "authorization" may hold space-separated scopes; otherwise default.
    raw = _env_first("authorization", "MS_SCOPES") or "User.Read email"
    if raw.lower().startswith("http"):
        # Full authorize URL was pasted into authorization — not scopes.
        raw = "User.Read email"
    return [s for s in raw.split() if s and s not in _MS_RESERVED_SCOPES]


def _msal_app(config: dict[str, str]):
    import msal

    return msal.ConfidentialClientApplication(
        config["client_id"],
        authority=config["authority"],
        client_credential=config["client_secret"],
    )


def _ms_login_endpoint(program: str) -> str:
    return "dc_login" if program == "dc" else "login"


def _ms_lookup_account(program: str, role: str, email: str):
    """
    Look up an allowlisted account for Microsoft sign-in.

    Returns (account_row, id_column, landing_endpoint) or (None, None, None).
    """
    if program == "robotics":
        if role == "student":
            account = rq.get_student_by_email(email)
            return (account, "studentid", "student_home") if account else (None, None, None)
        if role == "teacher":
            account = rq.get_teacher_by_email(email)
            return (account, "teacherid", "teacher_home") if account else (None, None, None)
    elif program == "dc":
        if role == "student":
            account = dq.get_student_by_email(email)
            return (account, "studentid", "dc_home") if account else (None, None, None)
        if role == "leader":
            account = dq.get_leader_by_email(email)
            return (account, "leaderid", "dc_home") if account else (None, None, None)
        if role == "admin":
            account = dq.get_admin_by_email(email)
            return (account, "adminid", "dc_home") if account else (None, None, None)
    return None, None, None


@app.route("/auth/microsoft/login")
def microsoft_login():
    """Start the Entra authorization-code flow for a high school or bootcamp role."""
    program = (request.args.get("program") or "robotics").strip()
    role = (request.args.get("role") or "").strip()
    allowed = _MS_PROGRAM_ROLES.get(program)
    if not allowed or role not in allowed:
        abort(400)

    login_endpoint = _ms_login_endpoint(program)
    config = _ms_config()
    if not config:
        missing = [
            label
            for label, ok in (
                ("Client_id", _env_first("Client_id", "MS_CLIENT_ID")),
                ("Value", _env_first("Value", "MS_CLIENT_SECRET")),
                ("Redirect_url", _env_first("Redirect_url", "MS_REDIRECT_URI")),
                ("auth_url", _env_first("auth_url", "MS_AUTHORITY")),
            )
            if not ok
        ]
        flash(
            "Microsoft sign-in is not configured. "
            f"Add these to .env and restart Flask: {', '.join(missing) or 'Client_id, Value, Redirect_url, auth_url'}.",
            "error",
        )
        return redirect(url_for(login_endpoint))

    flow = _msal_app(config).initiate_auth_code_flow(
        _ms_scopes(),
        redirect_uri=config["redirect_uri"],
    )
    session["ms_auth_flow"] = flow
    session["ms_auth_role"] = role
    session["ms_auth_program"] = program
    return redirect(flow["auth_uri"])


@app.route("/auth/callback")
def microsoft_callback():
    """Finish the Entra flow, allowlist by program/role, then mirror a password login session."""
    role = session.pop("ms_auth_role", None)
    program = session.pop("ms_auth_program", None) or "robotics"
    flow = session.pop("ms_auth_flow", None)
    login_endpoint = _ms_login_endpoint(program)

    def fail(message: str = "Microsoft sign-in failed. Please try again."):
        flash(message, "error")
        return redirect(url_for(login_endpoint))

    allowed = _MS_PROGRAM_ROLES.get(program, frozenset())
    if role not in allowed or not flow:
        return fail(
            "Microsoft sign-in session expired. Click Sign in with Microsoft again."
        )

    config = _ms_config()
    if not config:
        return fail("Microsoft sign-in is not configured.")

    try:
        result = _msal_app(config).acquire_token_by_auth_code_flow(flow, dict(request.args))
    except ValueError as exc:
        print(f"Microsoft auth code flow error: {exc.__class__.__name__}")
        return fail("Microsoft sign-in could not be completed. Please try again.")

    if "error" in result:
        # Log description for local debugging; never flash tokens or raw secrets.
        print(
            "Microsoft token error:",
            result.get("error"),
            result.get("error_description", "")[:200],
        )
        return fail("Microsoft sign-in was rejected. Please try again.")

    claims = result.get("id_token_claims") or {}
    tid = claims.get("tid")
    # Personal Microsoft accounts always have tid; oid can fall back to sub.
    oid = claims.get("oid") or claims.get("sub")
    if not tid or not oid:
        print("Microsoft claims missing tid/oid; keys:", sorted(claims.keys()))
        return fail("Microsoft sign-in did not return a usable account id.")

    email = (claims.get("email") or claims.get("preferred_username") or "").strip().lower()
    if not email:
        print("Microsoft claims missing email; keys:", sorted(claims.keys()))
        return fail("Microsoft sign-in did not return an email address.")

    # Entra only proves identity. Access requires that email already exist in the
    # matching program DB for the role they clicked. Passwords are not checked.
    account, id_col, landing = _ms_lookup_account(program, role, email)
    if not account:
        session.clear()
        flash(
            f"No {role} account exists for {email}. "
            "Ask an instructor to add that email first.",
            "error",
        )
        return redirect(url_for(login_endpoint))

    # user_id must stay the DB primary key — the rest of the app looks up rows by it.
    # Microsoft's stable id is stored separately as ms_user_id (tid:oid).
    suite = "dc" if program == "dc" else "robotics"
    # Entra counts as a completed first login (no password required).
    if suite == "dc" and role == "admin":
        dq.mark_admin_signed_in(account[id_col])
    session.clear()
    session["suite"] = suite
    session["user_id"] = account[id_col]
    session["user_type"] = role
    session["role"] = role
    session["email"] = account["email"]
    session["auth_provider"] = "microsoft"
    session["ms_user_id"] = f"{tid}:{oid}"
    return redirect(url_for(landing))


@app.route("/logout")
def logout():
    # Clear the app session only. Do not send users through Microsoft's
    # account-picker / "you signed out" pages — those rarely redirect back
    # unless a front-channel logout URI is registered in Entra.
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("landing"))


@app.route("/datacenter")
def datacenter_entry():
    if session.get("suite") == "dc" and "user_id" in session:
        return redirect(url_for("dc_home"))
    return redirect(url_for("dc_login"))


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
        if is_instructor():
            return redirect(url_for("teacher_home"))
        abort(403)
    courses = rq.get_courses_for_student(session["user_id"])
    if not courses:
        return render_template("student_no_courses.html", courses=[])
    return redirect(url_for("course_home", courseid=courses[0]["courseid"]))


@app.route("/teacher/courses", methods=["GET", "POST"])
@login_required
def teacher_home():
    """Teacher dashboard: every high school course, plus a form to create one."""
    if session.get("suite") == "dc" or not is_instructor():
        abort(403)
    teacher = rq.get_teacher_public(session["user_id"])
    if not teacher:
        abort(403)

    if request.method == "POST" and request.form.get("action") == "create_teacher":
        fname = request.form.get("fname", "").strip()
        lname = request.form.get("lname", "").strip()
        email = request.form.get("email", "").strip().lower()
        if not (fname and lname and email):
            flash("First name, last name, and email are required.", "error")
        elif rq.create_teacher(fname, lname, email, None):
            flash(
                f"Invited {fname} {lname}. They can sign in with Microsoft, "
                "or set a password on first login.",
                "success",
            )
        else:
            flash("Could not add teacher: that email is already in use.", "error")
        return redirect(url_for("teacher_home"))

    if request.method == "POST":
        title = request.form.get("title", "").strip()[:255]
        syllabus = request.form.get("syllabus", "").strip()
        if not title:
            flash("Course title is required.", "error")
            return redirect(url_for("teacher_home"))
        course = rq.create_course(title, syllabus)
        if not course:
            flash("Could not create course.", "error")
            return redirect(url_for("teacher_home"))
        flash(f"Created {course['title']}. Add weeks and days under Modules.", "success")
        return redirect(url_for("course_modules", courseid=course["courseid"]))

    return render_template(
        "teacher_home.html",
        teacher=teacher,
        courses=rq.get_course_summaries(),
        teachers=rq.get_all_teachers(),
    )


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
        title = request.form.get("title", "").strip()[:255]
        syllabus = request.form.get("syllabus", "").strip()
        if not title:
            flash("Course title is required.", "error")
        else:
            rq.update_course_title(courseid, title)
            rq.update_syllabus(courseid, syllabus)
            flash("Course details updated.", "success")
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
        elif action in ("create_day", "update_day"):
            fields, error = day_form_fields()
            if error:
                flash(error, "error")
            elif action == "create_day":
                week = rq.get_week(request.form.get("weekid", type=int) or 0)
                if week and week["courseid"] == courseid:
                    rq.create_day(week["weekid"], **fields)
                    flash("Day added.", "success")
            else:
                day = rq.get_day(request.form.get("dayid", type=int) or 0)
                if day and day["courseid"] == courseid:
                    rq.update_day(day["dayid"], **fields)
                    flash("Day updated.", "success")
        elif action == "delete_day":
            day = rq.get_day(request.form.get("dayid", type=int) or 0)
            if day and day["courseid"] == courseid:
                if rq.delete_day(day["dayid"]):
                    flash("Day deleted.", "success")
                else:
                    flash("Could not delete day.", "error")
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
        try:
            miniokey = student_submissions.store_submission(
                request.files.get("attachment"),
                f"exittickets/course-{courseid}/day-{dayid}/student-{session['user_id']}",
            )
        except SubmissionError as exc:
            flash(str(exc), "error")
            return redirect(url_for("course_day", courseid=courseid, dayid=dayid))
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
    if ctx["is_instructor"]:
        ctx["day_rows"] = rq.get_ticket_submission_status_for_day(courseid, dayid)
    return render_template("course/day.html", **ctx)


@app.route("/course/<int:courseid>/tickets")
@login_required
def course_tickets(courseid):
    ctx = course_context(courseid, "tickets")
    if not ctx["is_instructor"]:
        abort(403)
    ctx["weeks"] = rq.get_ticket_overview_for_course(courseid)
    ctx["roster_size"] = len(rq.get_students_in_course(courseid))
    return render_template("course/tickets_overview.html", **ctx)


@app.route("/course/<int:courseid>/week/<int:weekid>/tickets")
@login_required
def course_week_tickets(courseid, weekid):
    ctx = course_context(courseid, "tickets")
    if not ctx["is_instructor"]:
        abort(403)
    week = rq.get_week(weekid)
    if not week or week["courseid"] != courseid:
        abort(404)
    ctx["week"] = week
    ctx["tickets"] = rq.get_tickets_for_week(weekid)
    ctx["day_status"] = rq.get_ticket_submission_status_for_week(courseid, weekid)
    return render_template("course/tickets.html", **ctx)


@app.route("/course/<int:courseid>/ticket/<int:ticketid>/attachment")
@login_required
def course_ticket_attachment(courseid, ticketid):
    """Open an exit ticket attachment: the course's instructor or the student who submitted it."""
    if session.get("suite") == "dc" or not can_access_course(courseid):
        abort(403)
    ticket = rq.get_exit_ticket(ticketid)
    if not ticket or not ticket.get("miniokey"):
        abort(404)
    day = rq.get_day(ticket["dayid"])
    if not day or day["courseid"] != courseid:
        abort(404)
    is_owner = (
        session.get("user_type") == "student"
        and ticket["studentid"] == session["user_id"]
    )
    if not is_owner and not is_instructor_for(courseid):
        abort(403)
    return redirect_to_submission(
        ticket["miniokey"],
        url_for("course_day", courseid=courseid, dayid=ticket["dayid"]),
    )


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
    ctx["instructors"] = rq.get_all_teachers()
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
        elif action == "create":
            fname = request.form.get("fname", "").strip()
            lname = request.form.get("lname", "").strip()
            email = request.form.get("email", "").strip()
            if fname and lname and email:
                result = rq.create_student(fname, lname, email, None)
                if result:
                    rq.enroll_student(result["studentid"], courseid)
                    flash(
                        "Student invited and enrolled. They can sign in with Microsoft, "
                        "or set a password on first login.",
                        "success",
                    )
                else:
                    flash("Could not create student (duplicate email?).", "error")
            else:
                flash("First name, last name, and email are required.", "error")
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


@app.route("/dc/", methods=["GET", "POST"])
@app.route("/dc", methods=["GET", "POST"])
@dc_login_required
def dc_home():
    if is_dc_admin():
        admin = dq.get_admin_public(session["user_id"])
        if not admin:
            abort(403)
        courseid = request.args.get("courseid", type=int) or dc_admin_courseid()
        session["dc_courseid"] = courseid
        cross_cohort = dq.get_cross_cohort_engagement()
        weeks = dq.get_weeks_for_course(courseid)
        videos = dq.get_videos_for_course(courseid)
        total_ungraded = sum(int(row.get("ungraded_count") or 0) for row in cross_cohort)
        ctx = dc_admin_context(
            "home",
            admin,
            courseid=courseid,
            week_path=[{"week": week} for week in weeks],
            video_count=len(videos),
            cross_cohort=cross_cohort,
            total_ungraded=total_ungraded,
        )
        return render_template("dc/admin_home.html", **ctx)

    if is_dc_leader():
        leader, cohortid = dc_leader_with_cohort()
        courseid = request.args.get("courseid", type=int) or dc_admin_courseid()
        session["dc_courseid"] = courseid
        analytics = dq.get_submission_analytics(courseid, cohortid=cohortid)
        weeks = dq.get_weeks_for_course(courseid)
        videos = dq.get_videos_for_course(courseid)
        total_ungraded = sum(
            int(row.get("ungraded_count") or 0) for row in analytics["by_video"]
        )
        ungraded_queue = [
            row
            for row in analytics["by_video"]
            if int(row.get("ungraded_count") or 0) > 0
        ][:5]
        ctx = dc_leader_context(
            "home",
            leader,
            courseid=courseid,
            week_path=[{"week": week} for week in weeks],
            video_count=len(videos),
            student_count=dq.count_cohort_learners(cohortid),
            total_ungraded=total_ungraded,
            ungraded_queue=ungraded_queue,
            recent_messages=dq.get_recent_messages_for_member(
                "leader", leader["leaderid"], limit=3
            ),
        )
        return render_template("dc/leader_home.html", **ctx)

    if not is_dc_student():
        abort(403)
    student = dq.get_student_public(session["user_id"])
    if not student:
        abort(403)

    if request.method == "POST":
        action = request.form.get("action", "bio")
        if action == "branch":
            branch = request.form.get("orchestration_branch", "").strip()
            if branch in ("software", "hardware"):
                updated = dq.set_orchestration_branch(student["studentid"], branch)
                if updated:
                    flash(f"You're on the {branch} branch.", "success")
                    student = updated
                else:
                    flash("Could not save branch choice.", "error")
            else:
                flash("Choose software or hardware.", "error")
            return redirect(url_for("dc_home"))

        bio = request.form.get("bio", "").strip() or None
        updated = dq.update_student_profile(
            student["studentid"],
            student["fname"],
            student["lname"],
            student["email"],
            bio,
        )
        if updated:
            flash("Bio updated.", "success")
            student = updated
        else:
            flash("Could not update bio.", "error")
        return redirect(url_for("dc_home"))

    needs_branch = dq.student_needs_branch_choice(student["studentid"])

    next_video = resolve_next_video(student["studentid"], student["courseid"])
    lesson_rail = build_lesson_rail(
        student["studentid"],
        student["courseid"],
        next_video["videoid"] if next_video else None,
    )
    ctx = dc_student_context(
        "home",
        student,
        next_video=next_video,
        week_path=build_week_path(
            lesson_rail, next_video["videoid"] if next_video else None
        ),
        recent_messages=dq.get_recent_messages_for_member(
            "student", student["studentid"], limit=3
        ),
        profile=student,
        needs_branch_choice=needs_branch,
        week_gate=dq.get_week_gate(student["studentid"]),
    )
    return render_template("dc/home.html", **ctx)


@app.route("/dc/content")
@dc_login_required
def dc_content():
    """Open the next lesson, or a module overview when the track has no lessons yet."""
    if is_dc_admin() or is_dc_leader():
        courseid = dc_admin_courseid()
        videos = dq.get_videos_for_course(courseid)
        if videos:
            return redirect(url_for("dc_video", videoid=videos[0]["videoid"]))
        ctx = dc_page_context(
            "content",
            courseid=courseid,
            lesson_rail=build_lesson_rail_for_course(courseid),
        )
        return render_template("dc/content.html", **ctx)
    if not is_dc_student():
        abort(403)
    student = dq.get_student_public(session["user_id"])
    if not student:
        abort(403)
    next_video = resolve_next_video(student["studentid"], student["courseid"])
    if next_video:
        return redirect(url_for("dc_video", videoid=next_video["videoid"]))
    ctx = dc_student_context(
        "content",
        student,
        lesson_rail=build_lesson_rail(student["studentid"], student["courseid"]),
    )
    return render_template("dc/content.html", **ctx)


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
        if not student or not dq.video_in_student_path(student["studentid"], videoid):
            abort(403)
        if week["weekid"] not in dq.get_week_gate(student["studentid"])["unlocked"]:
            flash(
                f"Week {week['num']} is locked. Get every assignment in the week "
                "before it marked satisfactory to unlock it.",
                "error",
            )
            return redirect(url_for("dc_content"))
        dq.get_or_create_progress(student["studentid"], videoid)

        if request.method == "POST":
            action = request.form.get("action")
            if action == "mark_watched":
                dq.mark_video_watched(student["studentid"], videoid)
                flash("Lesson marked complete.", "success")
            elif action == "submit_assignment":
                existing = dq.get_student_assignment_for_video(student["studentid"], videoid)
                if existing and existing["status"] != "unsatisfactory":
                    flash("You already submitted for this lesson.", "error")
                else:
                    try:
                        miniokey = student_submissions.store_submission(
                            request.files.get("submission"),
                            f"assignments/video-{videoid}/student-{student['studentid']}",
                        )
                    except SubmissionError as exc:
                        miniokey = None
                        flash(str(exc), "error")
                    else:
                        if not miniokey:
                            flash("Choose a file to submit.", "error")
                        elif existing:
                            if dq.resubmit_assignment(
                                existing["assignmentid"], student["studentid"], miniokey
                            ):
                                student_submissions.delete_submission(existing["miniokey"])
                                flash("Resubmitted — your new file is awaiting review.", "success")
                            else:
                                student_submissions.delete_submission(miniokey)
                                flash("Could not resubmit assignment.", "error")
                        elif dq.submit_assignment(videoid, student["studentid"], miniokey):
                            flash("Assignment submitted.", "success")
                        else:
                            student_submissions.delete_submission(miniokey)
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
            stream_url=None if video.get("pdfkey") else dc_video_stream_url(videoid),
            lesson_rail=build_lesson_rail(
                student["studentid"], student["courseid"], videoid
            ),
        )
        return render_template("dc/video.html", **ctx)

    if is_dc_leader():
        leader, cohortid = dc_leader_with_cohort()
        ctx = dc_leader_context(
            "content",
            leader,
            courseid=week["courseid"],
            video=video,
            week=week,
            progress=None,
            assignment=None,
            stream_url=None if video.get("pdfkey") else dc_video_stream_url(videoid),
            lesson_rail=build_lesson_rail_for_course(
                week["courseid"], videoid, include_grading=True, cohortid=cohortid
            ),
        )
        return render_template("dc/video.html", **ctx)

    # Platform admin preview for grading context
    admin = dq.get_admin_public(session["user_id"])
    if not admin:
        abort(403)
    ctx = dc_admin_context(
        "content",
        admin,
        courseid=week["courseid"],
        video=video,
        week=week,
        progress=None,
        assignment=None,
        stream_url=None if video.get("pdfkey") else dc_video_stream_url(videoid),
        lesson_rail=build_lesson_rail_for_course(
            week["courseid"], videoid, include_grading=True, cohortid=None
        ),
    )
    return render_template("dc/video.html", **ctx)


@app.route("/dc/assignment/<int:assignmentid>/file")
@dc_login_required
def dc_assignment_file(assignmentid):
    """Open a submitted assignment file: its student, or staff allowed to grade it."""
    assignment = dq.get_assignment(assignmentid)
    if not assignment:
        abort(404)
    if is_dc_student():
        if assignment["studentid"] != session["user_id"]:
            abort(403)
    elif is_dc_cohort_staff():
        _, cohortid = dc_admin_with_cohort()
        if cohortid is not None and not dq.student_in_cohort(
            assignment["studentid"], cohortid
        ):
            abort(403)
    else:
        abort(403)
    return redirect_to_submission(
        assignment["miniokey"],
        url_for("dc_video", videoid=assignment["videoid"]),
    )


@app.route("/dc/assignments")
@dc_login_required
def dc_assignments():
    if is_dc_cohort_staff():
        staff, cohortid = dc_admin_with_cohort()
        courseid = dc_admin_courseid()
        if is_dc_leader():
            ctx = dc_leader_context(
                "assignments",
                staff,
                courseid=courseid,
                assignments=dq.get_assignments_for_course(courseid, cohortid=cohortid),
                admin_assignments_view=True,
            )
        else:
            ctx = dc_admin_context(
                "assignments",
                staff,
                courseid=courseid,
                cohortid=cohortid,
                assignments=dq.get_assignments_for_course(
                    courseid, cohortid=cohortid
                ),
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
    if is_dc_cohort_staff():
        staff, cohortid = dc_admin_with_cohort()
        courseid = dc_admin_courseid()
        if is_dc_leader():
            ctx = dc_leader_context(
                "grades",
                staff,
                courseid=courseid,
                lesson_rail=build_lesson_rail_for_course(
                    courseid, include_grading=True, cohortid=cohortid
                ),
                admin_grades_view=True,
            )
        else:
            ctx = dc_admin_context(
                "grades",
                staff,
                courseid=courseid,
                cohortid=cohortid,
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
    if is_dc_cohort_staff():
        staff, cohortid = dc_admin_with_cohort()
        courseid = dc_admin_courseid()
        students_progress = dq.get_students_progress_for_course(
            courseid, cohortid=cohortid
        )
        for row in students_progress:
            total = row["total_videos"] or 0
            watched = row["watched_videos"] or 0
            row["completion_pct"] = int(watched / total * 100) if total else 0
        if is_dc_leader():
            ctx = dc_leader_context(
                "progress",
                staff,
                courseid=courseid,
                students_progress=students_progress,
                admin_progress_view=True,
            )
        else:
            ctx = dc_admin_context(
                "progress",
                staff,
                courseid=courseid,
                cohortid=cohortid,
                students_progress=students_progress,
                admin_progress_view=True,
            )
        return render_template("dc/progress.html", **ctx)

    if not is_dc_student():
        abort(403)
    student = dq.get_student_public(session["user_id"])
    if not student:
        abort(403)
    resume = dq.get_resume_point(student["studentid"])
    if resume and not dq.student_can_access_video(student["studentid"], resume["videoid"]):
        resume = None
    ctx = dc_student_context(
        "progress",
        student,
        completion=dq.get_course_completion(student["studentid"]),
        resume=resume,
    )
    return render_template("dc/progress.html", **ctx)


@app.route("/dc/roster")
@dc_login_required
def dc_roster():
    user = current_user()
    if not user:
        abort(403)

    if is_dc_cohort_staff():
        staff, cohortid = dc_admin_with_cohort()
        if is_dc_leader():
            ctx = dc_leader_context(
                "roster",
                staff,
                roster=dq.get_cohort_roster(cohortid),
                cohort_leader=dq.get_leader_for_cohort(cohortid),
            )
        else:
            ctx = dc_admin_context(
                "roster",
                staff,
                roster_by_cohort=dq.get_roster_by_cohort(),
            )
        return render_template("dc/roster.html", **ctx)

    cohortid = user.get("cohortid")
    if not cohortid:
        ctx = dc_page_context("roster", roster=[], no_cohort_student=True)
        return render_template("dc/roster.html", **ctx)
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
    if peer_type not in ("student", "leader", "admin") or not peer_id:
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
@dc_cohort_staff_required
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
    leader = user if is_dc_leader() else None
    room = jitsi_room_name(student, admin, leader)
    ctx = dc_page_context(
        "calls",
        jitsi_room=room,
        jitsi_url=f"https://meet.jit.si/{room}",
    )
    return render_template("dc/calls.html", **ctx)


@app.route("/dc/helpdesk")
@dc_login_required
def dc_helpdesk():
    """List Help Desk contacts: admins (student) or student threads (admin)."""
    if is_dc_leader():
        abort(403)
    if is_dc_admin():
        ctx = dc_page_context(
            "helpdesk",
            students=dq.list_helpdesk_students_for_admin(session["user_id"]),
        )
        return render_template("dc/helpdesk.html", **ctx)
    if not is_dc_student():
        abort(403)
    student = dq.get_student_public(session["user_id"])
    admins = dq.list_helpdesk_admins()
    for a in admins:
        a["booking_url"] = google_calendar_invite_url(a, student)
    ctx = dc_page_context("helpdesk", admins=admins)
    return render_template("dc/helpdesk.html", **ctx)


@app.route("/dc/helpdesk/<int:peer_id>", methods=["GET", "POST"])
@dc_login_required
def dc_helpdesk_thread(peer_id):
    """Fetch or send on the 1:1 Help Desk thread with this admin (student) or student (admin)."""
    if is_dc_leader():
        abort(403)

    if is_dc_student():
        studentid = session["user_id"]
        admin = dq.get_admin_public(peer_id)
        if not admin:
            abort(404)
        if request.method == "POST":
            content = request.form.get("content", "").strip()
            if content:
                dq.post_help_message(studentid, peer_id, "student", content)
                flash("Message sent.", "success")
            return redirect(url_for("dc_helpdesk_thread", peer_id=peer_id))
        ctx = dc_page_context(
            "helpdesk",
            messages=dq.get_help_thread(studentid, peer_id),
            peer_name=f"{admin['fname']} {admin['lname']}",
            booking_url=google_calendar_invite_url(
                admin, dq.get_student_public(studentid)
            ),
            member_type="student",
        )
        return render_template("dc/helpdesk_thread.html", **ctx)

    if is_dc_admin():
        student = dq.get_student_public(peer_id)
        if not student:
            abort(404)
        if request.method == "POST":
            content = request.form.get("content", "").strip()
            if content:
                dq.post_help_message(peer_id, session["user_id"], "admin", content)
                flash("Message sent.", "success")
            return redirect(url_for("dc_helpdesk_thread", peer_id=peer_id))
        ctx = dc_page_context(
            "helpdesk",
            messages=dq.get_help_thread(peer_id, session["user_id"]),
            peer_name=f"{student['fname']} {student['lname']}",
            booking_url=None,
            member_type="admin",
        )
        return render_template("dc/helpdesk_thread.html", **ctx)

    abort(403)


def _help_message_json(row: dict) -> dict:
    return {
        "id": row["help_messageid"],
        "studentid": row["studentid"],
        "adminid": row["adminid"],
        "sender_type": row["sender_type"],
        "sender_name": row.get("sender_name"),
        "content": row["content"],
        "sendtime": row["sendtime"].isoformat() if row.get("sendtime") else None,
    }


@app.route("/api/helpdesk/admins")
@dc_login_required
def api_helpdesk_admins():
    if not is_dc_student():
        abort(403)
    student = dq.get_student_public(session["user_id"])
    return jsonify([
        {
            "adminid": a["adminid"],
            "name": f"{a['fname']} {a['lname']}",
            "bookingUrl": google_calendar_invite_url(a, student),
        }
        for a in dq.list_helpdesk_admins()
    ])


@app.route("/api/helpdesk/<int:adminid>/messages", methods=["GET", "POST"])
@dc_login_required
def api_helpdesk_messages(adminid):
    if not is_dc_student():
        abort(403)
    if not dq.get_admin_public(adminid):
        abort(404)
    studentid = session["user_id"]
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        content = (data.get("content") or "").strip()
        if not content:
            return jsonify({"error": "Message text is required."}), 400
        row = dq.post_help_message(studentid, adminid, "student", content)
        if not row:
            return jsonify({"error": "Could not send message."}), 400
        return jsonify(_help_message_json(row)), 201
    return jsonify([_help_message_json(m) for m in dq.get_help_thread(studentid, adminid)])


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

        if not is_dc_student() and not is_dc_leader():
            flash("Only students and cohort leaders can edit profile here.", "error")
            return redirect(url_for("dc_account"))

        fname = request.form.get("fname", "").strip()
        lname = request.form.get("lname", "").strip()
        email = request.form.get("email", "").strip()
        bio = request.form.get("bio", "").strip() or None
        if not fname or not lname or not email:
            flash("Name and email are required.", "error")
        elif is_dc_leader():
            updated = dq.update_leader_profile(
                session["user_id"], fname, lname, email, bio
            )
            if updated:
                session["email"] = email
                flash("Profile updated.", "success")
            else:
                flash("Could not update profile.", "error")
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
            upload = request.files.get("video_file")
            has_upload = upload and upload.filename
            pdf_upload = request.files.get("pdf_file")
            has_pdf = pdf_upload and pdf_upload.filename
            if not miniokey and (has_upload or has_pdf):
                miniokey = "pending/processing"
            if weekid and day and title:
                video = dq.create_video(
                    weekid, day, title, miniokey, script, instructions, reflection
                )
                if video and has_upload:
                    try:
                        video_streaming.enqueue_video_upload(video["videoid"], upload)
                        flash("Video added; transcoding started.", "success")
                    except ValueError as exc:
                        flash(f"Video created but upload failed: {exc}", "error")
                elif video:
                    flash("Video created.", "success")
                if video and has_pdf:
                    try:
                        lesson_documents.store_lesson_pdf(video["videoid"], pdf_upload)
                        flash("Lesson PDF uploaded.", "success")
                    except DocumentError as exc:
                        flash(f"Video created but PDF upload failed: {exc}", "error")
        elif action == "update_video":
            videoid = request.form.get("videoid", type=int)
            day = request.form.get("day", type=int)
            title = request.form.get("title", "").strip()
            miniokey = request.form.get("miniokey", "").strip()
            instructions = request.form.get("instructions", "").strip()
            reflection = request.form.get("reflection", "").strip()
            if videoid and day and title:
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


@app.route("/dc/admin/video/<int:videoid>/upload", methods=["POST"])
@dc_admin_required
def dc_admin_video_upload(videoid):
    """Accept a source video file and enqueue background transcode (admin only)."""
    upload = request.files.get("video")
    try:
        result = video_streaming.enqueue_video_upload(videoid, upload)
        return jsonify(result), 202
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@app.route("/dc/admin/video/<int:videoid>/upload/start", methods=["POST"])
@dc_admin_required
def dc_admin_video_upload_start(videoid):
    """Open a chunked upload session for a large source video (admin only)."""
    data = request.get_json(silent=True) or {}
    try:
        result = video_streaming.start_chunked_upload(
            videoid, str(data.get("filename") or ""), int(data.get("size") or 0)
        )
    except (TypeError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify(result), 201


@app.route("/dc/admin/video/<int:videoid>/upload/<upload_id>/chunk", methods=["POST"])
@dc_admin_required
def dc_admin_video_upload_chunk(videoid, upload_id):
    """Append one raw chunk of the source video at ?offset= (admin only)."""
    offset = request.args.get("offset", type=int)
    if offset is None or offset < 0:
        return jsonify({"error": "offset is required"}), 400
    try:
        result = video_streaming.append_upload_chunk(
            videoid, upload_id, offset, request.stream, request.content_length
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify(result)


@app.route("/dc/admin/video/<int:videoid>/upload/<upload_id>/finish", methods=["POST"])
@dc_admin_required
def dc_admin_video_upload_finish(videoid, upload_id):
    """Close a chunked upload and enqueue the transcode (admin only)."""
    try:
        result = video_streaming.finish_chunked_upload(videoid, upload_id)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify(result), 202


@app.route("/dc/admin/video/<int:videoid>/upload/<upload_id>/abort", methods=["POST"])
@dc_admin_required
def dc_admin_video_upload_abort(videoid, upload_id):
    """Discard a partially uploaded video (admin only)."""
    video_streaming.abort_chunked_upload(videoid, upload_id)
    return jsonify({"aborted": True})


@app.route("/dc/admin/video/<int:videoid>/transcode-status")
@dc_admin_required
def dc_admin_video_transcode_status(videoid):
    """Return processing / ready / failed status for admin UI polling."""
    if not dq.get_video(videoid):
        abort(404)
    return jsonify(video_streaming.get_transcode_status(videoid))


@app.route("/dc/admin/video/<int:videoid>/cancel-transcode", methods=["POST"])
@dc_admin_required
def dc_admin_video_cancel_transcode(videoid):
    """Cancel a queued or in-progress transcode job (admin only)."""
    if not dq.get_video(videoid):
        abort(404)
    return jsonify(video_streaming.cancel_video_transcode(videoid))


@app.route("/dc/admin/video/<int:videoid>/upload-pdf", methods=["POST"])
@dc_admin_required
def dc_admin_video_upload_pdf(videoid):
    """Accept a source PDF and store it in MinIO alongside lesson video (admin only)."""
    upload = request.files.get("pdf")
    try:
        result = lesson_documents.store_lesson_pdf(videoid, upload)
        return jsonify(result), 201
    except DocumentError as exc:
        return jsonify({"error": str(exc)}), 400


@app.route("/dc/admin/video/<int:videoid>/pdf-status")
@dc_admin_required
def dc_admin_video_pdf_status(videoid):
    """Report whether a lesson currently has a stored PDF (admin UI polling)."""
    video = dq.get_video(videoid)
    if not video:
        abort(404)
    pdfkey = video.get("pdfkey")
    return jsonify(
        {
            "status": "stored" if pdfkey else "idle",
            "videoid": videoid,
            "pdfkey": pdfkey,
        }
    )


@app.route("/dc/admin/video/<int:videoid>/remove-pdf", methods=["POST"])
@dc_admin_required
def dc_admin_video_remove_pdf(videoid):
    """Detach a lesson PDF so the video player takes over again (admin only)."""
    try:
        return jsonify(lesson_documents.delete_lesson_pdf(videoid))
    except DocumentError as exc:
        return jsonify({"error": str(exc)}), 400


@app.route("/dc/admin/video/<int:videoid>/upload-instructions-pdf", methods=["POST"])
@dc_admin_required
def dc_admin_video_upload_instructions(videoid):
    """Store the assignment instructions PDF shown at the end of a lesson (admin only)."""
    try:
        result = lesson_documents.store_instructions_pdf(videoid, request.files.get("pdf"))
        return jsonify(result), 201
    except DocumentError as exc:
        return jsonify({"error": str(exc)}), 400


@app.route("/dc/admin/video/<int:videoid>/instructions-pdf-status")
@dc_admin_required
def dc_admin_video_instructions_status(videoid):
    video = dq.get_video(videoid)
    if not video:
        abort(404)
    key = video.get("instructionskey")
    return jsonify({"status": "stored" if key else "idle", "videoid": videoid, "pdfkey": key})


@app.route("/dc/admin/video/<int:videoid>/remove-instructions-pdf", methods=["POST"])
@dc_admin_required
def dc_admin_video_remove_instructions(videoid):
    try:
        return jsonify(lesson_documents.delete_instructions_pdf(videoid))
    except DocumentError as exc:
        return jsonify({"error": str(exc)}), 400


@app.route("/dc/video/<int:videoid>/instructions.pdf")
@dc_login_required
def dc_video_instructions_pdf(videoid):
    """Serve a lesson's assignment instructions PDF inline, under lesson access rules."""
    video = dq.get_video(videoid)
    if not video or not video.get("instructionskey"):
        abort(404)
    if not dc_can_read_document(videoid):
        abort(403)
    try:
        obj = miniIO.open_object(video["instructionskey"])
    except Exception:
        abort(404)

    def close_object():
        obj.close()
        obj.release_conn()

    filename = f"lesson-{videoid}-assignment-instructions.pdf"
    response = Response(obj.stream(64 * 1024), mimetype="application/pdf")
    response.headers["Content-Disposition"] = f'inline; filename="{filename}"'
    response.headers["Cache-Control"] = "private, no-store"
    if obj.headers.get("Content-Length"):
        response.headers["Content-Length"] = obj.headers["Content-Length"]
    response.call_on_close(close_object)
    return response


@app.route("/api/extract_pdf", methods=["POST"])
@dc_login_required
def api_extract_pdf():
    """
    Extract a stored lesson PDF into display HTML plus TTS-ready text.

    Images are served from MinIO, never inlined; ``chunks`` is the image-free
    text pre-split to sizes ElevenLabs can synthesize in one request.
    """
    data = request.get_json(silent=True) or {}
    videoid = data.get("videoid")
    try:
        videoid = int(videoid)
    except (TypeError, ValueError):
        return jsonify({"error": "videoid is required"}), 400

    if not dq.get_video(videoid):
        abort(404)
    if not dc_can_read_document(videoid):
        abort(403)

    try:
        document = lesson_documents.get_document(
            videoid, refresh=bool(data.get("refresh")) and is_dc_admin()
        )
    except DocumentError as exc:
        return jsonify({"error": str(exc)}), 404

    return jsonify(document)


@app.route("/dc/video/<int:videoid>/stream")
@dc_login_required
def dc_video_stream(videoid):
    """
    Return a presigned MinIO URL for authorized playback.

    Never exposes the raw miniokey — only the time-limited URL.
    """
    if is_dc_admin():
        url = video_streaming.get_video_stream_url(
            videoid, None, is_admin=True
        )
    elif is_dc_leader():
        url = video_streaming.get_video_stream_url(
            videoid, None, is_staff=True
        )
    elif is_dc_student():
        student = dq.get_student_public(session["user_id"])
        if not student:
            abort(403)
        try:
            url = video_streaming.get_video_stream_url(videoid, student)
        except StreamingAuthError:
            abort(403)
    else:
        abort(403)

    if not url:
        return jsonify({"error": "Video not available for streaming."}), 404

    return jsonify(
        {
            "url": url,
            "expires_in": video_streaming.PRESIGNED_EXPIRY_SECONDS,
        }
    )


@app.route("/dc/admin/grade/<int:videoid>", methods=["GET", "POST"])
@dc_cohort_staff_required
def dc_admin_grade_video(videoid):
    staff, cohortid = dc_admin_with_cohort()
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
            if assignment:
                if cohortid is not None and not dq.student_in_cohort(
                    assignment["studentid"], cohortid
                ):
                    flash("You can only grade students in your cohort.", "error")
                else:
                    result = dq.grade_assignment(assignmentid, status, feedback)
                    if result:
                        flash("Grade saved.", "success")
                    else:
                        flash("Could not save grade.", "error")
            else:
                flash("Assignment not found.", "error")
        return redirect(url_for("dc_admin_grade_video", videoid=videoid))

    if is_dc_leader():
        ctx = dc_leader_context(
            "admin_analytics",
            staff,
            courseid=week["courseid"],
            video=video,
            submissions=dq.get_submissions_for_video(videoid, cohortid=cohortid),
        )
    else:
        ctx = dc_admin_context(
            "admin_analytics",
            staff,
            courseid=week["courseid"],
            cohortid=cohortid,
            video=video,
            submissions=dq.get_submissions_for_video(videoid, cohortid=cohortid),
        )
    return render_template("dc/admin_grade.html", **ctx)


@app.route("/dc/admin/analytics")
@dc_cohort_staff_required
def dc_admin_analytics():
    staff, cohortid = dc_admin_with_cohort()
    courseid = request.args.get("courseid", type=int) or dc_admin_courseid()
    if is_dc_admin():
        cohortid = request.args.get("cohortid", type=int)
    analytics = dq.get_submission_analytics(courseid, cohortid=cohortid)
    if is_dc_leader():
        ctx = dc_leader_context(
            "admin_analytics",
            staff,
            courseid=courseid,
            analytics=analytics,
        )
    else:
        ctx = dc_admin_context(
            "admin_analytics",
            staff,
            courseid=courseid,
            cohortid=cohortid,
            analytics=analytics,
            cross_cohort=dq.get_cross_cohort_engagement(),
        )
    return render_template("dc/admin_analytics.html", **ctx)


@app.route("/dc/admin/admins", methods=["GET", "POST"])
@dc_platform_admin_required
def dc_admin_admins():
    """Invite platform admins by email (password left unset until first login)."""
    admin = dq.get_admin_public(session["user_id"])
    if not admin:
        abort(403)

    if request.method == "POST":
        action = request.form.get("action")
        if action == "create_admin":
            fname = request.form.get("fname", "").strip()
            lname = request.form.get("lname", "").strip()
            email = request.form.get("email", "").strip()
            if not fname or not lname or not email:
                flash("First name, last name, and email are required.", "error")
            else:
                created = dq.create_admin(fname, lname, email, password_hash=None)
                if created:
                    flash(
                        f"Admin invited: {created['email']}. "
                        "They can sign in with Microsoft, or with that email to choose a password.",
                        "success",
                    )
                else:
                    flash("Could not add admin (email already in use?).", "error")
        return redirect(url_for("dc_admin_admins"))

    ctx = dc_admin_context("admin_admins", admin, admins=dq.get_all_admins())
    return render_template("dc/admin_admins.html", **ctx)


@app.route("/dc/admin/students", methods=["GET", "POST"])
@dc_cohort_staff_required
def dc_admin_students():
    staff, cohortid = dc_admin_with_cohort()
    # Platform admins can switch to the college students who have no cohort.
    no_cohort = is_dc_admin() and request.args.get("cohortid") == "none"
    if is_dc_admin() and cohortid is None and not no_cohort:
        cohortid = request.args.get("cohortid", type=int) or (
            dq.get_all_cohorts()[0]["cohortid"] if dq.get_all_cohorts() else None
        )

    if request.method == "POST":
        action = request.form.get("action")
        if action == "create_student":
            fname = request.form.get("fname", "").strip()
            lname = request.form.get("lname", "").strip()
            email = request.form.get("email", "").strip()
            courseid = request.form.get("courseid", type=int)
            bio = request.form.get("bio", "").strip() or None
            orch_branch = request.form.get("orchestration_branch", "").strip() or None
            college = no_cohort or request.form.get("college") == "on"
            if fname and lname and email and courseid:
                result = dq.create_student(
                    fname,
                    lname,
                    email,
                    None,
                    courseid,
                    None if no_cohort else cohortid,
                    bio,
                    orchestration_branch=orch_branch,
                    college=college,
                )
                if result:
                    flash(
                        ("College student invited." if college else "Student invited.")
                        + " They can sign in with Microsoft, or with that email to choose a password.",
                        "success",
                    )
                else:
                    flash("Could not create student (duplicate email?).", "error")
            else:
                flash("First name, last name, email, and division are required.", "error")
        elif action == "delete_student":
            studentid = request.form.get("studentid", type=int)
            if studentid and dq.delete_student(studentid, cohortid=cohortid):
                flash("Student removed.", "success")
            else:
                flash("Could not remove student.", "error")
        return redirect(url_for("dc_admin_students", cohortid="none" if no_cohort else cohortid))

    if is_dc_leader():
        ctx = dc_leader_context(
            "admin_students",
            staff,
            students=dq.get_all_students(cohortid=cohortid),
        )
    else:
        ctx = dc_admin_context(
            "admin_students",
            staff,
            cohortid=None if no_cohort else cohortid,
            no_cohort_view=no_cohort,
            students=dq.get_all_students(cohortid=cohortid, without_cohort=no_cohort),
        )
    return render_template("dc/admin_students.html", **ctx)


@app.route("/dc/admin/cohorts", methods=["GET", "POST"])
@dc_platform_admin_required
def dc_admin_cohorts():
    admin = dq.get_admin_public(session["user_id"])
    if not admin:
        abort(403)

    if request.method == "POST":
        action = request.form.get("action")
        if action == "create_cohort":
            region = request.form.get("region", "").strip()
            name = request.form.get("name", "").strip()
            leader_fname = request.form.get("leader_fname", "").strip()
            leader_lname = request.form.get("leader_lname", "").strip()
            leader_email = request.form.get("leader_email", "").strip()
            leader_bio = request.form.get("leader_bio", "").strip() or None
            if not region or not name:
                flash("Cohort name and region are required.", "error")
            else:
                result = dq.create_cohort_with_leader(
                    region,
                    name,
                    leader_fname or None,
                    leader_lname or None,
                    leader_email or None,
                    None,
                    leader_bio,
                )
                if result:
                    if leader_email and not result.get("leader"):
                        flash(
                            "Cohort created, but leader was not assigned "
                            "(duplicate email or cohort already has a leader).",
                            "error",
                        )
                    else:
                        flash("Cohort created.", "success")
                else:
                    flash("Could not create cohort.", "error")
        elif action == "assign_leader":
            cohortid = request.form.get("cohortid", type=int)
            leader_fname = request.form.get("leader_fname", "").strip()
            leader_lname = request.form.get("leader_lname", "").strip()
            leader_email = request.form.get("leader_email", "").strip()
            leader_bio = request.form.get("leader_bio", "").strip() or None
            if cohortid and leader_fname and leader_lname and leader_email:
                result = dq.create_leader(
                    leader_fname,
                    leader_lname,
                    leader_email,
                    None,
                    cohortid,
                    leader_bio,
                )
                if result:
                    flash(
                        "Cohort leader invited. They can sign in with Microsoft, "
                        "or set a password on first login.",
                        "success",
                    )
                else:
                    flash(
                        "Could not assign leader (duplicate email or cohort "
                        "already has one).",
                        "error",
                    )
            else:
                flash("Leader first name, last name, and email are required.", "error")
        return redirect(url_for("dc_admin_cohorts"))

    ctx = dc_admin_context(
        "admin_cohorts",
        admin,
        cohorts=dq.get_cohorts_with_leaders(),
    )
    return render_template("dc/admin_cohorts.html", **ctx)


if __name__ == "__main__":
    app.run(debug=True, port=int(os.getenv("PORT") or os.getenv("FLASK_PORT") or "3000"))
