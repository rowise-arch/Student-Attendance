"""
RFID Student Attendance - Entrance logging dashboard (Flask + SQLite)

Run:   python app.py      then open http://127.0.0.1:5000
First login: admin / admin123   (change it in Settings)

Students tap their card at the entrance four times a day:
Morning in, Morning out (lunch), Afternoon in, Afternoon out.
"""
import base64
import calendar
import csv
import io
import os
import secrets
import sqlite3
import time
from datetime import date, datetime, timedelta
from functools import wraps

from flask import (Flask, Response, abort, flash, jsonify, redirect, render_template,
                   request, send_from_directory, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

import capture
import database as db
import pcsc_bridge
import serial_bridge

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024      # photos and CSV files
PHOTO_DIR = os.path.join(db.BASE_DIR, "photos")
BRANDING_DIR = os.path.join(db.BASE_DIR, "branding")
PAGE_SIZE = 50


def _secret_key():
    path = os.path.join(db.BASE_DIR, ".secret_key")
    if not os.path.exists(path):
        with open(path, "w") as f:
            f.write(secrets.token_hex(32))
    with open(path) as f:
        return f.read().strip()


app.secret_key = _secret_key()


# ---------------------------------------------------------------- helpers
def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if "teacher_id" not in session:
            if request.path.startswith("/api/"):
                return jsonify(error="login required"), 401
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapper


def parse_date(value, default):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return default


def parse_time(value):
    v = (value or "").strip()
    if not v:
        return None
    try:
        return datetime.strptime(v[:5], "%H:%M").strftime("%H:%M:00")
    except ValueError:
        return None


def sections():
    with db.connect() as conn:
        return conn.execute(
            """SELECT sec.id, sec.name, sec.grade_level, sec.adviser, COUNT(s.id) AS students,
                      CASE WHEN sec.grade_level <> '' THEN sec.grade_level || ' ' ELSE '' END || sec.name AS label
               FROM sections sec LEFT JOIN students s ON s.section_id = sec.id
               GROUP BY sec.id ORDER BY sec.grade_level, sec.name"""
        ).fetchall()


def reader_status():
    mode = db.get_settings()["reader_mode"]
    if mode == "keyboard":
        return {"state": "keyboard", "message": "USB keyboard-type reader", "port": "", "mode": mode}
    src = pcsc_bridge.status if mode == "acr122u" else serial_bridge.status
    return dict(src, mode=mode)


def reader_label(status):
    mode, state = status["mode"], status["state"]
    if mode == "keyboard":
        return "Keyboard reader mode"
    if mode == "acr122u":
        return "ACR122U connected" if state == "connected" else "ACR122U not found"
    if state == "connected":
        return "Arduino reader connected"
    return "Keyboard reader only" if mode == "both" else "Reader offline"


@app.context_processor
def inject_globals():
    settings = db.get_settings()
    status = reader_status()
    return {"settings": settings, "reader": status, "reader_label": reader_label(status),
            "teacher_name": session.get("teacher_name"), "today": date.today()}


@app.template_filter("time12")
def time12(value):
    return db.fmt_time(value) if value else "—"


@app.template_filter("nicedate")
def nicedate(value):
    try:
        d = value if isinstance(value, date) else datetime.strptime(value, "%Y-%m-%d").date()
        return d.strftime("%a, %b %d, %Y")
    except (TypeError, ValueError):
        return value


def csv_response(rows, filename):
    buf = io.StringIO()
    csv.writer(buf).writerows(rows)
    # utf-8-sig so Excel opens names with ñ correctly
    return Response(buf.getvalue().encode("utf-8-sig"), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={filename}"})


# ---------------------------------------------------------------- student photos
def save_photo(student_id, data_url):
    """Save a JPEG sent by the browser (already cropped to a square). Returns the file name."""
    header, _, b64 = (data_url or "").partition(",")
    if not header.startswith("data:image/jpeg;base64"):
        return None
    try:
        raw = base64.b64decode(b64, validate=True)
    except ValueError:
        return None
    if len(raw) > 3_000_000 or raw[:3] != b"\xff\xd8\xff":          # must really be a JPEG
        return None
    os.makedirs(PHOTO_DIR, exist_ok=True)
    name = f"{student_id}_{int(time.time())}.jpg"            # new name each time, so browsers don't show an old copy
    with open(os.path.join(PHOTO_DIR, name), "wb") as f:
        f.write(raw)
    return name


def delete_photo(name):
    if name:
        try:
            os.remove(os.path.join(PHOTO_DIR, os.path.basename(name)))
        except OSError:
            pass


@app.route("/photos/<path:name>")
def photo(name):
    if "teacher_id" not in session:
        abort(403)
    return send_from_directory(PHOTO_DIR, os.path.basename(name), max_age=86400)


@app.route("/branding/<path:name>")
def branding(name):
    return send_from_directory(BRANDING_DIR, os.path.basename(name), max_age=86400)


def save_logo(file):
    """School logo: PNG, JPG or WebP up to 2 MB (no SVG: it can carry scripts)."""
    data = file.read()
    kinds = {b"\x89PNG": "png", b"\xff\xd8\xff": "jpg", b"RIFF": "webp"}
    ext = next((e for sig, e in kinds.items() if data.startswith(sig)), None)
    if not ext or len(data) > 2_000_000:
        return None
    os.makedirs(BRANDING_DIR, exist_ok=True)
    name = f"logo_{int(time.time())}.{ext}"
    with open(os.path.join(BRANDING_DIR, name), "wb") as f:
        f.write(data)
    return name


# ---------------------------------------------------------------- auth
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        with db.connect() as conn:
            t = conn.execute("SELECT * FROM teachers WHERE username = ?",
                             (request.form.get("username", "").strip(),)).fetchone()
        if t and check_password_hash(t["password_hash"], request.form.get("password", "")):
            session.clear()
            session["teacher_id"] = t["id"]
            session["teacher_name"] = t["full_name"]
            nxt = request.args.get("next", "")
            return redirect(nxt if nxt.startswith("/") else url_for("dashboard"))
        flash("Wrong username or password.", "error")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ---------------------------------------------------------------- today
@app.route("/")
@login_required
def dashboard():
    section_id = request.args.get("section", type=int)
    with db.connect() as conn:
        student_count = conn.execute("SELECT COUNT(*) FROM students").fetchone()[0]
    s = db.get_settings()
    am_late, pm_late = db.late_times(s)
    return render_template("dashboard.html", sections=sections(), section_id=section_id,
                           student_count=student_count, school_day=db.is_school_day(date.today(), s),
                           no_class_day=db.is_no_class_day(date.today(), s), am_late=am_late, pm_late=pm_late)


@app.route("/api/today")
@login_required
def api_today():
    section_id = request.args.get("section", type=int)
    today = date.today()
    counts, missing = db.today_summary(section_id)
    with db.connect() as conn:
        params = [today.isoformat()] + ([section_id] if section_id else [])
        feed = conn.execute(
            f"""SELECT l.id, l.scanned_at, l.result, l.uid, l.source,
                       s.first_name || ' ' || s.last_name AS name, s.student_no, s.photo,
                       COALESCE(sec.name, '') AS section
                FROM scan_log l
                LEFT JOIN students s ON s.id = l.student_id
                LEFT JOIN sections sec ON sec.id = s.section_id
                WHERE substr(l.scanned_at, 1, 10) = ? {'AND s.section_id = ?' if section_id else ''}
                ORDER BY l.id DESC LIMIT 25""", params).fetchall()
    return jsonify(counts=counts, missing=missing, feed=[dict(r) for r in feed], week=db.week_chart(section_id),
                   reader=reader_status(), reader_label=reader_label(reader_status()),
                   unknown=db.last_unknown_uid(), today=today.isoformat(),
                   now=datetime.now().strftime("%I:%M:%S %p").lstrip("0"))


@app.route("/api/find")
@login_required
def api_find():
    return jsonify(results=db.find_students(request.args.get("q", "")))


@app.route("/today/no-classes", methods=["POST"])
@login_required
def today_no_classes():
    on = request.form.get("on") == "1"
    db.set_no_class_day(date.today(), on)
    flash("Today is marked as a day with no classes. It won't count in reports." if on
          else "Today counts as a school day again.", "success")
    return redirect(url_for("dashboard"))


# ---------------------------------------------------------------- daily log
def _log_args():
    today = date.today()
    start = parse_date(request.args.get("from"), today)
    end = parse_date(request.args.get("to"), today)
    if end < start:
        start, end = end, start
    if (end - start).days > 186:
        start = end - timedelta(days=186)
    return dict(start=start, end=end, section_id=request.args.get("section", type=int),
                search=request.args.get("q", "").strip(), status=request.args.get("status", ""))


@app.route("/attendance")
@login_required
def attendance():
    a = _log_args()
    rows = db.log_report(**a)
    counts = {k: sum(1 for r in rows if r["status"] == k) for k in ("PRESENT", "LATE", "HALF", "EXCUSED", "ABSENT")}
    pages = max(1, -(-len(rows) // PAGE_SIZE))
    page = min(max(1, request.args.get("page", 1, type=int)), pages)
    with db.connect() as conn:
        all_students = conn.execute(
            "SELECT id, student_no, last_name || ', ' || first_name AS name FROM students ORDER BY last_name").fetchall()
    args = {k: v for k, v in request.args.items() if k != "page"}
    return render_template("attendance.html", rows=rows[(page - 1) * PAGE_SIZE: page * PAGE_SIZE], total=len(rows),
                           page=page, pages=pages, page_size=PAGE_SIZE, counts=counts, sections=sections(),
                           all_students=all_students, args=args, **a)


@app.route("/attendance/export.csv")
@login_required
def attendance_export():
    a = _log_args()
    rows = db.log_report(**a)
    out = [["Date", "Student No", "Name", "Section", "Morning In", "Morning Out", "Afternoon In", "Afternoon Out",
            "Morning", "Afternoon", "Day", "Remarks"]]
    for r in rows:
        out.append([r["date"], r["student_no"], r["name"], r["section"],
                    db.fmt_time(r["am_in"]) if r["am_in"] else "", db.fmt_time(r["am_out"]) if r["am_out"] else "",
                    db.fmt_time(r["pm_in"]) if r["pm_in"] else "", db.fmt_time(r["pm_out"]) if r["pm_out"] else "",
                    r["am_status"].title(), r["pm_status"].title(), r["status"].title(), r["remarks"]])
    return csv_response(out, f"attendance_{a['start']}_to_{a['end']}.csv")


@app.route("/attendance/save", methods=["POST"])
@login_required
def attendance_save():
    f = request.form
    student_id = f.get("student_id", type=int)
    day = parse_date(f.get("date"), None)
    if not student_id or not day:
        flash("Choose a student and a date.", "error")
        return redirect(request.referrer or url_for("attendance"))
    db.save_log(student_id, day, parse_time(f.get("am_in")), parse_time(f.get("am_out")),
                parse_time(f.get("pm_in")), parse_time(f.get("pm_out")),
                f.get("am_status"), f.get("pm_status"), f.get("remarks", "").strip())
    flash("Attendance saved.", "success")
    return redirect(request.referrer or url_for("attendance"))


# ---------------------------------------------------------------- monthly report
def _month_args():
    today = date.today()
    try:
        y, m = (int(x) for x in request.args.get("month", "").split("-"))
        date(y, m, 1)
    except ValueError:
        y, m = today.year, today.month
    return request.args.get("section", type=int), y, m


@app.route("/reports")
@login_required
def reports():
    section_id, y, m = _month_args()
    days, rows = db.month_report(section_id, y, m)
    prev = (date(y, m, 1) - timedelta(days=1)).strftime("%Y-%m")
    nxt = (date(y, m, 28) + timedelta(days=5)).strftime("%Y-%m")
    sec = next((x for x in sections() if x["id"] == section_id), None)
    return render_template("reports.html", sections=sections(), section_id=section_id, sec=sec, year=y, month=m,
                           month_name=f"{calendar.month_name[m]} {y}", days=days, rows=rows,
                           prev=prev, nxt=nxt if date(y, m, 1) <= date.today().replace(day=1) - timedelta(days=1) else None)


@app.route("/reports/export.csv")
@login_required
def reports_export():
    section_id, y, m = _month_args()
    days, rows = db.month_report(section_id, y, m)
    label = next((s["label"] for s in sections() if s["id"] == section_id), "All sections")
    out = [[f"Monthly attendance - {label} - {calendar.month_name[m]} {y}"],
           ["P = present, L = late, H = half day, E = excused, A = absent"], [],
           ["Student No", "Name"] + [d.strftime("%d %a") for d in days]
           + ["Present", "Late", "Half day", "Excused", "Absent", "Days absent", "Attendance %"]]
    for r in rows:
        st = r["student"]
        out.append([st["student_no"], f"{st['last_name']}, {st['first_name']}"]
                   + [c["code"] if c else "" for c in r["cells"]]
                   + [r["counts"]["P"], r["counts"]["L"], r["counts"]["H"], r["counts"]["E"], r["counts"]["A"],
                      r["absences"], "" if r["rate"] is None else r["rate"]])
    safe = "".join(ch if ch.isalnum() else "_" for ch in label).strip("_")
    return csv_response(out, f"attendance_{safe}_{y}-{m:02d}.csv")


# ---------------------------------------------------------------- kiosk (student-facing screen)
@app.route("/kiosk")
@login_required
def kiosk():
    return render_template("kiosk.html")


@app.route("/api/kiosk")
@login_required
def api_kiosk():
    after = request.args.get("after", type=int)
    sql = """SELECT l.id, l.scanned_at, l.result, l.uid, s.first_name, s.last_name, s.photo,
                    d.am_in, d.am_out, d.pm_in, d.pm_out, d.am_status, d.pm_status
             FROM scan_log l
             LEFT JOIN students s ON s.id = l.student_id
             LEFT JOIN daily_logs d ON d.student_id = l.student_id AND d.date = substr(l.scanned_at, 1, 10)
             {where} ORDER BY l.id DESC LIMIT {limit}"""
    with db.connect() as conn:
        last = conn.execute("SELECT COALESCE(MAX(id), 0) FROM scan_log").fetchone()[0]
        recent = conn.execute(sql.format(
            where="WHERE substr(l.scanned_at, 1, 10) = ? AND l.result IN ('AM_IN','AM_OUT','PM_IN','PM_OUT')", limit=6),
            (date.today().isoformat(),)).fetchall()
        new = conn.execute(sql.format(where="WHERE l.id > ?", limit=5), (after,)).fetchall() \
            if after is not None else []
    now = datetime.now()
    s = db.get_settings()
    return jsonify(last_id=last, new=[dict(r) for r in reversed(new)], recent=[dict(r) for r in recent],
                   period=db.current_period(now, s), reader=reader_status()["state"], reader_mode=s["reader_mode"],
                   now=now.strftime("%I:%M").lstrip("0"), ampm=now.strftime("%p"),
                   date=now.strftime("%A, %B %d, %Y").replace(" 0", " "))


@app.route("/api/stream")
@login_required
def api_stream():
    """Server-Sent Events: sends "scan" the instant a card is saved, so screens don't wait for their next poll."""
    def events():
        seen = db.scan_version()
        yield "retry: 2000\n\n"
        while True:
            now = db.wait_for_scan(seen, timeout=15)
            if now != seen:
                seen = now
                yield f"event: scan\ndata: {now}\n\n"
            else:
                yield ": ping\n\n"      # keeps the connection alive and notices closed tabs
    return Response(events(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---------------------------------------------------------------- students
@app.route("/students")
@login_required
def students():
    q = request.args.get("q", "").strip()
    section_id = request.args.get("section", type=int)
    missing = request.args.get("missing", "")
    where, params = [], []
    if q:
        where.append("(s.first_name || ' ' || s.last_name LIKE ? OR s.student_no LIKE ? OR s.rfid_uid LIKE ?)")
        params += [f"%{q}%"] * 3
    if section_id:
        where.append("s.section_id = ?")
        params.append(section_id)
    if missing == "card":
        where.append("(s.rfid_uid IS NULL OR s.rfid_uid = '')")
    elif missing == "photo":
        where.append("(s.photo IS NULL OR s.photo = '')")
    with db.connect() as conn:
        prog = conn.execute(
            f"""SELECT COUNT(*) AS total,
                       SUM(CASE WHEN rfid_uid IS NOT NULL AND rfid_uid <> '' THEN 1 ELSE 0 END) AS cards,
                       SUM(CASE WHEN photo IS NOT NULL AND photo <> '' THEN 1 ELSE 0 END) AS photos
                FROM students {'WHERE section_id = ?' if section_id else ''}""",
            (section_id,) if section_id else ()).fetchone()
        rows = conn.execute(
            f"""SELECT s.*, CASE WHEN sec.grade_level <> '' THEN sec.grade_level || ' ' ELSE '' END || sec.name AS section
                FROM students s LEFT JOIN sections sec ON sec.id = s.section_id
                {'WHERE ' + ' AND '.join(where) if where else ''}
                ORDER BY s.last_name, s.first_name""", params).fetchall()
    return render_template("students.html", students=rows, sections=sections(), q=q, section_id=section_id,
                           missing=missing, prog=prog)


@app.route("/students/new", methods=["GET", "POST"])
@app.route("/students/<int:student_id>/edit", methods=["GET", "POST"])
@login_required
def student_form(student_id=None):
    student = None
    if student_id:
        with db.connect() as conn:
            student = conn.execute("SELECT * FROM students WHERE id = ?", (student_id,)).fetchone()
        if student is None:
            flash("Student not found.", "error")
            return redirect(url_for("students"))

    errors = {}
    if request.method == "POST":
        f = request.form
        data = (f.get("student_no", "").strip(), f.get("first_name", "").strip(),
                f.get("last_name", "").strip(), f.get("section_id", type=int) or None,
                db.normalize_uid(f.get("rfid_uid", "")) or None)
        for key, value, label in (("student_no", data[0], "Student number"),
                                  ("first_name", data[1], "First name"),
                                  ("last_name", data[2], "Last name")):
            if not value:
                errors[key] = f"{label} is required."
        if not errors:
            try:
                with db.write_lock, db.connect() as conn:
                    if student_id:
                        conn.execute("""UPDATE students SET student_no=?, first_name=?, last_name=?,
                                        section_id=?, rfid_uid=? WHERE id=?""", data + (student_id,))
                        sid = student_id
                    else:
                        sid = conn.execute("""INSERT INTO students(student_no, first_name, last_name,
                                        section_id, rfid_uid) VALUES (?,?,?,?,?)""", data).lastrowid
                _update_photo(sid, f)
                flash(f"Saved {data[1]} {data[2]}.", "success")
                return redirect(url_for("students"))
            except sqlite3.IntegrityError as e:
                if "rfid_uid" in str(e):
                    with db.connect() as conn:
                        owner = conn.execute("SELECT first_name || ' ' || last_name FROM students WHERE rfid_uid = ?",
                                             (data[4],)).fetchone()
                    errors["rfid_uid"] = (f"This card already belongs to {owner[0]}. Tap a different card, "
                                          "or remove it from that student first.") if owner else \
                        "This card is already assigned to another student."
                else:
                    errors["student_no"] = f"Student number {data[0]} already exists. Check for a duplicate entry."
        student = f.to_dict() | {"section_id": f.get("section_id", type=int),
                                 "photo": student["photo"] if student_id and student else None}

    return render_template("student_form.html", student=student, sections=sections(),
                           editing=bool(student_id), student_id=student_id, errors=errors,
                           pending_photo=request.form.get("photo_data", "") if errors else "",
                           remove_photo=request.form.get("photo_remove") == "1" if errors else False), \
        (422 if errors else 200)


def _update_photo(student_id, form):
    with db.connect() as conn:
        old = conn.execute("SELECT photo FROM students WHERE id = ?", (student_id,)).fetchone()["photo"]
    new = old
    if form.get("photo_remove") == "1":
        new = None
    elif form.get("photo_data"):
        saved = save_photo(student_id, form["photo_data"])
        if saved:
            new = saved
        else:
            flash("The photo couldn't be saved. Try another picture.", "error")
    if new != old:
        with db.write_lock, db.connect() as conn:
            conn.execute("UPDATE students SET photo = ? WHERE id = ?", (new, student_id))
        delete_photo(old)


@app.route("/students/<int:student_id>/delete", methods=["POST"])
@login_required
def student_delete(student_id):
    with db.write_lock, db.connect() as conn:
        row = conn.execute("SELECT first_name || ' ' || last_name, photo FROM students WHERE id = ?",
                           (student_id,)).fetchone()
        conn.execute("DELETE FROM students WHERE id = ?", (student_id,))
    if row:
        delete_photo(row[1])
    flash(f"Deleted {row[0] if row else 'student'} and their attendance records.", "success")
    return redirect(url_for("students"))


@app.route("/students/<int:student_id>")
@login_required
def student_profile(student_id):
    with db.connect() as conn:
        s = conn.execute(
            """SELECT s.*, CASE WHEN sec.grade_level <> '' THEN sec.grade_level || ' ' ELSE '' END || sec.name AS section
               FROM students s LEFT JOIN sections sec ON sec.id = s.section_id WHERE s.id = ?""",
            (student_id,)).fetchone()
    if s is None:
        return redirect(url_for("students"))
    today = date.today()
    start = parse_date(request.args.get("from"), today - timedelta(days=30))
    rows = [r for r in db.log_report(start, today, search=s["student_no"]) if r["student_id"] == student_id]
    counts = {k: sum(1 for r in rows if r["status"] == k) for k in ("PRESENT", "LATE", "HALF", "EXCUSED", "ABSENT")}
    done = [r for r in rows if not (r["date"] == today.isoformat() and r["pm_status"] == "PENDING")]
    attended = sum(1 for r in done if r["status"] in ("PRESENT", "LATE")) + 0.5 * sum(1 for r in done if r["status"] == "HALF")
    rate = round(100 * attended / len(done)) if done else None
    return render_template("student_profile.html", s=s, rows=rows, counts=counts, rate=rate, start=start)


IMPORT_COLUMNS = ["student_no", "first_name", "last_name", "grade_level", "section", "rfid_uid"]


@app.route("/students/export.csv")
@login_required
def students_export():
    with db.connect() as conn:
        rows = conn.execute(
            """SELECT s.student_no, s.first_name, s.last_name, COALESCE(sec.grade_level, ''),
                      COALESCE(sec.name, ''), COALESCE(s.rfid_uid, '')
               FROM students s LEFT JOIN sections sec ON sec.id = s.section_id
               ORDER BY sec.grade_level, sec.name, s.last_name""").fetchall()
    return csv_response([IMPORT_COLUMNS] + [list(r) for r in rows], "students.csv")


@app.route("/students/import", methods=["GET", "POST"])
@login_required
def students_import():
    """Bring in a class list made in Excel (saved as CSV)."""
    if request.method == "POST":
        file = request.files.get("file")
        if not file or not file.filename:
            flash("Choose a CSV file first.", "error")
            return redirect(url_for("students_import"))
        text = file.read().decode("utf-8-sig", errors="replace")
        reader = csv.DictReader(io.StringIO(text))
        headers = [h.strip().lower().replace(" ", "_") for h in (reader.fieldnames or [])]
        missing = [c for c in ("student_no", "first_name", "last_name") if c not in headers]
        if missing:
            flash(f"The file is missing these columns: {', '.join(missing)}.", "error")
            return redirect(url_for("students_import"))
        added = updated = skipped = 0
        problems = []
        with db.write_lock, db.connect() as conn:
            for n, raw in enumerate(reader, start=2):
                row = {h: (raw.get(orig) or "").strip() for h, orig in zip(headers, reader.fieldnames)}
                if not (row.get("student_no") and row.get("first_name") and row.get("last_name")):
                    skipped += 1
                    continue
                section_id = None
                if row.get("section"):
                    conn.execute("INSERT OR IGNORE INTO sections(name, grade_level) VALUES (?, ?)",
                                 (row["section"], row.get("grade_level", "")))
                    section_id = conn.execute("SELECT id FROM sections WHERE name = ?", (row["section"],)).fetchone()[0]
                uid = db.normalize_uid(row.get("rfid_uid", "")) or None
                existing = conn.execute("SELECT id FROM students WHERE student_no = ?", (row["student_no"],)).fetchone()
                try:
                    if existing:
                        conn.execute("""UPDATE students SET first_name=?, last_name=?, section_id=COALESCE(?, section_id),
                                        rfid_uid=COALESCE(?, rfid_uid) WHERE id=?""",
                                     (row["first_name"], row["last_name"], section_id, uid, existing["id"]))
                        updated += 1
                    else:
                        conn.execute("""INSERT INTO students(student_no, first_name, last_name, section_id, rfid_uid)
                                        VALUES (?,?,?,?,?)""",
                                     (row["student_no"], row["first_name"], row["last_name"], section_id, uid))
                        added += 1
                except sqlite3.IntegrityError:
                    problems.append(f"line {n} ({row['student_no']}): card {uid} is already used by another student")
        msg = f"Import done: {added} added, {updated} updated" + (f", {skipped} incomplete rows skipped" if skipped else "")
        flash(msg + ".", "success")
        for p in problems[:5]:
            flash("Not imported: " + p, "error")
        return redirect(url_for("students"))
    return render_template("student_import.html", columns=IMPORT_COLUMNS)


@app.route("/api/capture", methods=["GET", "DELETE"])
@login_required
def api_capture():
    """Registration mode for the student form: keeps it on and returns the last card tapped."""
    if request.method == "DELETE":
        capture.stop()
        return jsonify(active=False)
    capture.heartbeat()
    last, seq = capture.latest()
    owner = None
    if last:
        with db.connect() as conn:
            row = conn.execute("SELECT id, first_name || ' ' || last_name AS name FROM students WHERE rfid_uid = ?",
                               (last["uid"],)).fetchone()
        owner = dict(row) if row else None
    return jsonify(active=True, seq=seq, last=last, owner=owner,
                   reader=reader_status()["state"], reader_label=reader_label(reader_status()))


@app.route("/api/last-unknown")
@login_required
def api_last_unknown():
    return jsonify(db.last_unknown_uid() or {})


# ---------------------------------------------------------------- sections
@app.route("/sections", methods=["GET", "POST"])
@login_required
def sections_page():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        grade = request.form.get("grade_level", "").strip()
        if name:
            try:
                with db.write_lock, db.connect() as conn:
                    conn.execute("INSERT INTO sections(name, grade_level, adviser) VALUES (?, ?, ?)",
                                 (name, grade, request.form.get("adviser", "").strip()))
                flash(f"Added section {(grade + ' ') if grade else ''}{name}.", "success")
            except sqlite3.IntegrityError:
                flash("That section already exists.", "error")
        return redirect(url_for("sections_page"))
    return render_template("sections.html", sections=sections())


@app.route("/sections/<int:section_id>/rename", methods=["POST"])
@login_required
def section_rename(section_id):
    name = request.form.get("name", "").strip()
    if name:
        try:
            with db.write_lock, db.connect() as conn:
                conn.execute("UPDATE sections SET name = ?, grade_level = ?, adviser = ? WHERE id = ?",
                             (name, request.form.get("grade_level", "").strip(),
                              request.form.get("adviser", "").strip(), section_id))
            flash("Section saved.", "success")
        except sqlite3.IntegrityError:
            flash("That section name is already used.", "error")
    return redirect(url_for("sections_page"))


@app.route("/sections/<int:section_id>/delete", methods=["POST"])
@login_required
def section_delete(section_id):
    with db.write_lock, db.connect() as conn:
        conn.execute("DELETE FROM sections WHERE id = ?", (section_id,))
    flash("Section deleted. Its students are now unassigned.", "success")
    return redirect(url_for("sections_page"))


# ---------------------------------------------------------------- settings
def _valid_hm(v, default):
    try:
        return datetime.strptime((v or "")[:5], "%H:%M").strftime("%H:%M")
    except ValueError:
        return default


@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings_page():
    if request.method == "POST":
        f = request.form
        action = f.get("action")
        if action == "general":
            old = db.get_settings()
            port = f.get("serial_port_manual", "").strip() or f.get("serial_port", "")
            mode = f.get("reader_mode", "serial")
            if mode not in ("serial", "acr122u", "keyboard", "both"):
                mode = "serial"
            times = {k: _valid_hm(f.get(k), old[k]) for k in ("am_start", "am_end", "pm_start", "pm_end")}
            if not (times["am_start"] < times["am_end"] <= times["pm_start"] < times["pm_end"]):
                flash("School hours must go in order: morning start < morning end ≤ afternoon start < afternoon end.",
                      "error")
                return redirect(url_for("settings_page"))
            db.save_settings({
                **times,
                "grace_minutes": max(0, f.get("grace_minutes", 0, type=int)),
                "min_gap_minutes": max(0, f.get("min_gap_minutes", 3, type=int)),
                "count_weekends": "1" if f.get("count_weekends") else "0",
                "serial_port": port,
                "reader_mode": mode,
            })
            if port != old["serial_port"] or mode != old["reader_mode"]:
                serial_bridge.request_reconnect()
                pcsc_bridge.request_reconnect()
            flash("Settings saved.", "success")
        elif action == "school":
            db.save_settings({
                "school_name": f.get("school_name", "").strip() or db.DEFAULT_SETTINGS["school_name"],
                "school_id": f.get("school_id", "").strip(),
                "school_year": f.get("school_year", "").strip(),
                "school_address": f.get("school_address", "").strip(),
                "principal_name": f.get("principal_name", "").strip(),
            })
            logo = request.files.get("logo")
            old_logo = db.get_settings()["school_logo"]
            if f.get("logo_remove") == "1" and old_logo:
                db.save_settings({"school_logo": ""})
                try:
                    os.remove(os.path.join(BRANDING_DIR, os.path.basename(old_logo)))
                except OSError:
                    pass
            elif logo and logo.filename:
                name = save_logo(logo)
                if name:
                    db.save_settings({"school_logo": name})
                    if old_logo:
                        try:
                            os.remove(os.path.join(BRANDING_DIR, os.path.basename(old_logo)))
                        except OSError:
                            pass
                else:
                    flash("The logo must be a PNG, JPG or WebP image under 2 MB.", "error")
                    return redirect(url_for("settings_page"))
            flash("School details saved.", "success")
        elif action == "holiday_add":
            d = parse_date(f.get("date"), None)
            if d:
                db.set_no_class_day(d, True)
                flash(f"{d.strftime('%b %d, %Y')} added as a no-class day.", "success")
        elif action == "holiday_remove":
            d = parse_date(f.get("date"), None)
            if d:
                db.set_no_class_day(d, False)
                flash(f"{d.strftime('%b %d, %Y')} is a school day again.", "success")
        elif action == "reconnect":
            serial_bridge.request_reconnect()
            pcsc_bridge.request_reconnect()
            flash("Reconnecting to the reader...", "success")
        elif action == "password":
            with db.connect() as conn:
                t = conn.execute("SELECT * FROM teachers WHERE id = ?", (session["teacher_id"],)).fetchone()
            new = f.get("new_password", "")
            if not check_password_hash(t["password_hash"], f.get("current_password", "")):
                flash("Current password is wrong.", "error")
            elif len(new) < 6:
                flash("New password must be at least 6 characters.", "error")
            else:
                with db.write_lock, db.connect() as conn:
                    conn.execute("UPDATE teachers SET password_hash = ? WHERE id = ?",
                                 (generate_password_hash(new), t["id"]))
                flash("Password changed.", "success")
        elif action == "add_teacher":
            u, n, p = f.get("username", "").strip(), f.get("full_name", "").strip(), f.get("password", "")
            if not (u and n and len(p) >= 6):
                flash("Fill in all account fields (password at least 6 characters).", "error")
            else:
                try:
                    with db.write_lock, db.connect() as conn:
                        conn.execute("INSERT INTO teachers(username, full_name, password_hash) VALUES (?,?,?)",
                                     (u, n, generate_password_hash(p)))
                    flash(f"Added account {u}.", "success")
                except sqlite3.IntegrityError:
                    flash("That username is taken.", "error")
        elif action == "delete_teacher":
            tid = f.get("teacher_id", type=int)
            if tid == session["teacher_id"]:
                flash("You can't delete your own account.", "error")
            else:
                with db.write_lock, db.connect() as conn:
                    conn.execute("DELETE FROM teachers WHERE id = ?", (tid,))
                flash("Account deleted.", "success")
        elif action == "simulate":
            uid = f.get("uid", "")
            if db.normalize_uid(uid):
                r = db.process_scan(uid, source="simulator")
                flash(f"Simulated tap {r['uid']} → {r['label']}{' · ' + r['name'] if r['name'] else ''}", "success")
            else:
                flash("Enter a card UID (hex, e.g. 04A1B2C3).", "error")
        return redirect(url_for("settings_page"))

    with db.connect() as conn:
        cards = conn.execute("""SELECT rfid_uid, first_name || ' ' || last_name AS name FROM students
                                WHERE rfid_uid IS NOT NULL ORDER BY last_name""").fetchall()
        teachers = conn.execute("SELECT id, username, full_name FROM teachers ORDER BY id").fetchall()
    holidays = sorted(d for d in db.get_settings()["no_class_dates"].split(",") if d)
    return render_template("settings.html", ports=serial_bridge.available_ports(),
                           pcsc_readers=pcsc_bridge.available_readers(),
                           pyscard_ok=pcsc_bridge.list_readers is not None, cards=cards,
                           teachers=teachers, me=session["teacher_id"], holidays=holidays,
                           lunch_split=db.lunch_split(), late=db.late_times())


@app.route("/api/scan", methods=["POST"])
@login_required
def api_scan():
    """Card read by a USB keyboard-type reader (the browser captures the typed number)."""
    data = request.get_json(silent=True) or request.form
    uid = db.normalize_uid(str(data.get("uid", "")))
    if len(uid) < 4:
        return jsonify(error="That doesn't look like a card number."), 400
    return jsonify(db.process_scan(uid, source="keyboard"))


@app.route("/api/reader")
@login_required
def api_reader():
    return jsonify(reader_status())


if __name__ == "__main__":
    db.init_db()
    serial_bridge.start()
    pcsc_bridge.start()
    import threading, webbrowser
    if "--no-browser" not in os.sys.argv:
        threading.Timer(1.5, lambda: webbrowser.open("http://127.0.0.1:5000")).start()
    print("\n  Dashboard running at http://127.0.0.1:5000  (login: admin / admin123)\n")
    # debug must stay off: the reloader would start a second copy that fights over the COM port
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)
