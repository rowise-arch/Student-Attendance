"""
Database layer for the RFID Student Attendance system (SQLite).

Used at the school ENTRANCE. Every school day each student has four logs:
    Morning in  ->  Morning out  ->  Afternoon in  ->  Afternoon out

Tables
  teachers    - dashboard accounts
  sections    - year level + section, e.g. Grade 10 - Rizal
  students    - student info, section, RFID card UID and photo (saved in the photos/ folder)
  daily_logs  - one row per student per day: am_in, am_out, pm_in, pm_out,
                am_status / pm_status (PRESENT, LATE, EXCUSED; empty = absent)
  scan_log    - every card tap, including unknown cards
  settings    - school hours, late times, reader settings ...
(Tables from earlier versions, like classes/sessions, are left untouched and unused.)
"""
import os
import sqlite3
import threading
from datetime import datetime, date, timedelta

from werkzeug.security import generate_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("ATTENDANCE_DB", os.path.join(BASE_DIR, "attendance.db"))

# One lock so the reader threads and web requests never write at the same time
write_lock = threading.Lock()

# Open kiosk and dashboard screens wait on this so a tap shows up the moment it is saved,
# at the same time as the reader's beep (see /api/stream in app.py).
_scan_cond = threading.Condition()
_scan_version = 0


def notify_scan():
    global _scan_version
    with _scan_cond:
        _scan_version += 1
        _scan_cond.notify_all()


def wait_for_scan(seen: int, timeout: float = 15.0) -> int:
    """Block until a tap newer than `seen` is saved (or timeout). Returns the current version."""
    with _scan_cond:
        _scan_cond.wait_for(lambda: _scan_version != seen, timeout=timeout)
        return _scan_version


def scan_version() -> int:
    return _scan_version

DEFAULT_SETTINGS = {
    "school_name": "Corcuera National High School",
    "am_start": "07:30",            # morning classes start; Morning in after this = LATE
    "am_end": "12:00",              # morning dismissal; Morning out before this = left early
    "pm_start": "13:00",            # afternoon classes start; Afternoon in after this = LATE
    "pm_end": "17:00",              # afternoon dismissal; Afternoon out before this = left early
    "grace_minutes": "0",           # extra minutes before a tap counts as late
    "min_gap_minutes": "3",         # taps closer together than this are treated as a double tap
    "count_weekends": "0",          # 1 = Saturdays/Sundays are school days
    "no_class_dates": "",           # comma-separated YYYY-MM-DD holidays (not counted)
    "school_id": "",                # DepEd school ID, shown on printed reports
    "school_year": "",              # e.g. 2026-2027
    "school_address": "",
    "principal_name": "",           # "Noted by" on printed reports
    "school_logo": "",              # file name in the branding/ folder
    "sound_preset": "classic",      # kiosk sounds: classic / chime / bell / arcade / soft
    "sound_in": "",                 # uploaded audio files (in the sounds/ folder) that replace
    "sound_late": "",               #   the preset for one kind of tap; empty = use the preset
    "sound_out": "",
    "sound_warn": "",
    "sound_error": "",
    "serial_port": "",
    "reader_mode": "serial",        # serial = Arduino + RC522, acr122u = ACS ACR122U, keyboard = keyboard-type reader
}

STATUSES = ("PRESENT", "LATE", "EXCUSED", "ABSENT")
EVENT_LABEL = {"AM_IN": "Morning in", "AM_OUT": "Morning out", "PM_IN": "Afternoon in", "PM_OUT": "Afternoon out",
               "DUP": "Repeat tap", "DONE": "Already out", "UNKNOWN": "Unknown card"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS teachers (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE,
    full_name     TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    created_at    TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS sections (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    grade_level TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS students (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    student_no TEXT NOT NULL UNIQUE,
    first_name TEXT NOT NULL,
    last_name  TEXT NOT NULL,
    section_id INTEGER REFERENCES sections(id) ON DELETE SET NULL,
    rfid_uid   TEXT UNIQUE,
    photo      TEXT,                           -- file name in the photos/ folder
    created_at TEXT NOT NULL DEFAULT (date('now','localtime'))
);

CREATE TABLE IF NOT EXISTS daily_logs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    date       TEXT NOT NULL,                  -- YYYY-MM-DD
    am_in      TEXT,                           -- HH:MM:SS
    am_out     TEXT,
    pm_in      TEXT,
    pm_out     TEXT,
    am_status  TEXT,                           -- PRESENT / LATE / EXCUSED (NULL = absent)
    pm_status  TEXT,
    remarks    TEXT NOT NULL DEFAULT '',
    UNIQUE (student_id, date)
);

CREATE TABLE IF NOT EXISTS scan_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    uid        TEXT NOT NULL,
    student_id INTEGER REFERENCES students(id) ON DELETE SET NULL,
    scanned_at TEXT NOT NULL,                  -- YYYY-MM-DD HH:MM:SS
    result     TEXT NOT NULL,                  -- AM_IN / AM_OUT / PM_IN / PM_OUT / DUP / DONE / UNKNOWN
    source     TEXT NOT NULL DEFAULT 'reader'
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_logs_date     ON daily_logs(date);
CREATE INDEX IF NOT EXISTS idx_scan_log_time ON scan_log(scanned_at);
"""

MIGRATIONS = [
    ("sections", "grade_level", "ALTER TABLE sections ADD COLUMN grade_level TEXT NOT NULL DEFAULT ''"),
    ("students", "photo", "ALTER TABLE students ADD COLUMN photo TEXT"),
    ("sections", "adviser", "ALTER TABLE sections ADD COLUMN adviser TEXT NOT NULL DEFAULT ''"),
]


def connect():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    with connect() as conn:
        conn.executescript(SCHEMA)
        for table, column, sql in MIGRATIONS:
            if column not in [r["name"] for r in conn.execute(f"PRAGMA table_info({table})")]:
                conn.execute(sql)
        for key, value in DEFAULT_SETTINGS.items():
            conn.execute("INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (key, value))
        # databases created before the school was named still say "My School"
        conn.execute("UPDATE settings SET value = ? WHERE key = 'school_name' AND value IN ('My School', '')",
                     (DEFAULT_SETTINGS["school_name"],))
        # Bring over records from the first version (one time in / time out per day)
        old = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='attendance'").fetchone()
        if old and conn.execute("SELECT COUNT(*) FROM daily_logs").fetchone()[0] == 0:
            cols = [r["name"] for r in conn.execute("PRAGMA table_info(attendance)")]
            if {"student_id", "date", "time_in", "time_out", "status"} <= set(cols):
                conn.execute(
                    """INSERT OR IGNORE INTO daily_logs(student_id, date, am_in, pm_out, am_status, pm_status, remarks)
                       SELECT a.student_id, a.date, a.time_in, a.time_out, a.status,
                              CASE WHEN a.time_out IS NOT NULL OR a.status = 'EXCUSED' THEN
                                   CASE WHEN a.status = 'EXCUSED' THEN 'EXCUSED' ELSE 'PRESENT' END END,
                              COALESCE(a.remarks, '')
                       FROM attendance a JOIN students s ON s.id = a.student_id""")
        if conn.execute("SELECT COUNT(*) FROM teachers").fetchone()[0] == 0:
            conn.execute(
                "INSERT INTO teachers(username, full_name, password_hash) VALUES (?, ?, ?)",
                ("admin", "Administrator", generate_password_hash("admin123")),
            )


# ---------------------------------------------------------------- settings
def get_settings():
    with connect() as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
    data = dict(DEFAULT_SETTINGS)
    data.update({r["key"]: r["value"] for r in rows if r["key"] in DEFAULT_SETTINGS})
    return data


def save_settings(values: dict):
    with write_lock, connect() as conn:
        for key, value in values.items():
            conn.execute(
                "INSERT INTO settings(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, str(value)),
            )


def _add_minutes(hhmm, minutes):
    t = datetime.strptime(hhmm[:5], "%H:%M") + timedelta(minutes=minutes)
    return t.strftime("%H:%M")


def late_times(settings=None):
    """(morning late after, afternoon late after) as HH:MM, grace included."""
    s = settings or get_settings()
    g = int(s.get("grace_minutes") or 0)
    return _add_minutes(s["am_start"], g), _add_minutes(s["pm_start"], g)


def lunch_split(settings=None):
    """Taps before this time belong to the morning, after it to the afternoon (midpoint of lunch)."""
    s = settings or get_settings()
    a = datetime.strptime(s["am_end"], "%H:%M")
    b = datetime.strptime(s["pm_start"], "%H:%M")
    return (a + (b - a) / 2).strftime("%H:%M") if b > a else s["pm_start"]


def current_period(now: datetime = None, settings=None):
    """'before' / 'morning' / 'lunch' / 'afternoon' / 'after' for the Today page."""
    s = settings or get_settings()
    t = (now or datetime.now()).strftime("%H:%M")
    if t < _add_minutes(s["am_start"], -90):
        return "before"
    if t < s["am_end"]:
        return "morning"
    if t < s["pm_start"]:
        return "lunch"
    if t < s["pm_end"]:
        return "afternoon"
    return "after"


def fmt_time(hhmm):
    if not hhmm:
        return "—"
    t = datetime.strptime(hhmm[:5], "%H:%M")
    return f"{t.hour % 12 or 12}:{t.minute:02d} {'AM' if t.hour < 12 else 'PM'}"


# ---------------------------------------------------------------- school days
def is_no_class_day(d: date, settings=None):
    s = settings or get_settings()
    return d.isoformat() in s["no_class_dates"].split(",")


def is_school_day(d: date, settings=None):
    s = settings or get_settings()
    if is_no_class_day(d, s):
        return False
    return s["count_weekends"] == "1" or d.weekday() < 5


def set_no_class_day(d: date, on: bool):
    days = {x for x in get_settings()["no_class_dates"].split(",") if x}
    (days.add if on else days.discard)(d.isoformat())
    save_settings({"no_class_dates": ",".join(sorted(days))})


def school_days(start: date, end: date, settings=None):
    s = settings or get_settings()
    d = start
    while d <= end:
        if is_school_day(d, s):
            yield d
        d += timedelta(days=1)


# ---------------------------------------------------------------- scanning
def normalize_uid(uid: str) -> str:
    return "".join(ch for ch in uid.upper() if ch in "0123456789ABCDEF")


def _minutes_between(t1, t2):
    a = datetime.strptime(t1, "%H:%M:%S")
    b = datetime.strptime(t2, "%H:%M:%S")
    return (b - a).total_seconds() / 60


def process_scan(uid: str, source: str = "reader", now: datetime = None):
    """
    Called for every card tap at the entrance.

    Morning (before the middle of lunch break):
        1st tap -> MORNING IN   (LATE if after the morning start + grace)
        2nd tap -> MORNING OUT
    Afternoon:
        a student still "in" from the morning who taps before the afternoon start
               -> MORNING OUT  (left for lunch late)
        next tap -> AFTERNOON IN  (LATE if after the afternoon start + grace)
        next tap -> AFTERNOON OUT
    Taps within a few minutes of the previous one are ignored (DUP).
    Returns a dict, including the reply line for the Arduino.
    """
    uid = normalize_uid(uid)
    now = now or datetime.now()
    today, clock, hm = now.strftime("%Y-%m-%d"), now.strftime("%H:%M:%S"), now.strftime("%H:%M")
    s = get_settings()
    am_late, pm_late = late_times(s)
    gap = float(s["min_gap_minutes"] or 0)
    event, status, name = None, None, None

    with write_lock, connect() as conn:
        student = conn.execute(
            "SELECT id, first_name, last_name FROM students WHERE rfid_uid = ?", (uid,)).fetchone()
        if student is None:
            event = "UNKNOWN"
        else:
            name = f"{student['first_name']} {student['last_name']}"
            conn.execute("INSERT OR IGNORE INTO daily_logs(student_id, date) VALUES (?, ?)", (student["id"], today))
            log = conn.execute("SELECT * FROM daily_logs WHERE student_id = ? AND date = ?",
                               (student["id"], today)).fetchone()
            last = max([t for t in (log["am_in"], log["am_out"], log["pm_in"], log["pm_out"]) if t], default=None)
            if last and _minutes_between(last, clock) < gap:
                event = "DUP"
            elif hm < lunch_split(s) and not (not log["am_in"] and hm >= s["am_end"]):
                # (someone arriving for the first time during lunch is coming for the afternoon)
                if not log["am_in"]:
                    status = "LATE" if hm > am_late else "PRESENT"
                    if log["am_status"] == "EXCUSED":
                        status = "EXCUSED"
                    conn.execute("UPDATE daily_logs SET am_in = ?, am_status = ? WHERE id = ?", (clock, status, log["id"]))
                    event = "AM_IN"
                elif not log["am_out"]:
                    conn.execute("UPDATE daily_logs SET am_out = ? WHERE id = ?", (clock, log["id"]))
                    event, status = "AM_OUT", log["am_status"]
                else:
                    event, status = "DONE", log["am_status"]
            else:
                if log["am_in"] and not log["am_out"] and not log["pm_in"] and hm < s["pm_start"]:
                    conn.execute("UPDATE daily_logs SET am_out = ? WHERE id = ?", (clock, log["id"]))
                    event, status = "AM_OUT", log["am_status"]
                elif not log["pm_in"]:
                    status = "LATE" if hm > pm_late else "PRESENT"
                    if log["pm_status"] == "EXCUSED":
                        status = "EXCUSED"
                    conn.execute("UPDATE daily_logs SET pm_in = ?, pm_status = ? WHERE id = ?", (clock, status, log["id"]))
                    event = "PM_IN"
                elif not log["pm_out"]:
                    conn.execute("UPDATE daily_logs SET pm_out = ? WHERE id = ?", (clock, log["id"]))
                    event, status = "PM_OUT", log["pm_status"]
                else:
                    event, status = "DONE", log["pm_status"]

        conn.execute(
            "INSERT INTO scan_log(uid, student_id, scanned_at, result, source) VALUES (?, ?, ?, ?, ?)",
            (uid, student["id"] if student else None, f"{today} {clock}", event, source))
    notify_scan()   # wake up open kiosk / dashboard screens right away

    # Arduino reply (the sketch understands IN / OUT / DUP / DONE / UNKNOWN).
    # The last field is the tap time for the LCD, e.g. "7:21 AM"; older sketches ignore it.
    hh, mm = int(clock[:2]), clock[3:5]
    lcd = lcd_name(student["first_name"], student["last_name"]) if student else ""
    at = f"{hh % 12 or 12}:{mm} {'AM' if hh < 12 else 'PM'}"
    if event in ("AM_IN", "PM_IN"):
        reply = f"IN|{lcd}|{status}|{at}"
    elif event in ("AM_OUT", "PM_OUT"):
        reply = f"OUT|{lcd}|{at}"
    elif event in ("DUP", "DONE"):
        reply = f"{event}|{lcd}"
    else:
        reply = "UNKNOWN"
    return {"uid": uid, "result": event, "label": EVENT_LABEL[event], "name": name, "status": status,
            "time": clock, "reply": reply}


def lcd_name(first: str, last: str) -> str:
    """Student name that fits one 16-character LCD line: "Maria Cristina Dela Cruz" -> "Maria Dela Cruz"."""
    first, last = first.strip(), last.strip()
    given = first.split()[0] if first else ""
    for option in (f"{first} {last}", f"{given} {last}", f"{given} {last[:1]}."):
        if len(option.strip()) <= 16:
            return option.strip()
    return given[:16]


def lcd_school_name(name: str = None) -> str:
    """School name shortened to fit a 16-character LCD line, e.g. "Corcuera NHS"."""
    name = (name or get_settings()["school_name"]).strip()
    for long, short in (("National High School", "NHS"), ("High School", "HS"),
                        ("Elementary School", "ES"), ("Integrated School", "IS"), ("National", "Nat'l")):
        if len(name) <= 16:
            break
        name = name.replace(long, short)
    return name[:16]


def last_unknown_uid():
    """Most recent unknown card that still isn't registered."""
    with connect() as conn:
        row = conn.execute(
            """SELECT uid, scanned_at FROM scan_log
               WHERE result = 'UNKNOWN'
                 AND uid NOT IN (SELECT rfid_uid FROM students WHERE rfid_uid IS NOT NULL)
               ORDER BY id DESC LIMIT 1"""
        ).fetchone()
    return dict(row) if row else None


# ---------------------------------------------------------------- manual entry
def save_log(student_id, day: date, am_in=None, am_out=None, pm_in=None, pm_out=None,
             am_status=None, pm_status=None, remarks=""):
    """Teacher adds or corrects a day (forgot card, excused, wrong tap). ABSENT -> stored as empty."""
    def st(v):
        return v if v in ("PRESENT", "LATE", "EXCUSED") else None
    with write_lock, connect() as conn:
        conn.execute(
            """INSERT INTO daily_logs(student_id, date, am_in, am_out, pm_in, pm_out, am_status, pm_status, remarks)
               VALUES (?,?,?,?,?,?,?,?,?)
               ON CONFLICT(student_id, date) DO UPDATE SET am_in=excluded.am_in, am_out=excluded.am_out,
                 pm_in=excluded.pm_in, pm_out=excluded.pm_out, am_status=excluded.am_status,
                 pm_status=excluded.pm_status, remarks=excluded.remarks""",
            (student_id, day.isoformat(), am_in, am_out, pm_in, pm_out, st(am_status), st(pm_status), remarks or ""))


# ---------------------------------------------------------------- reports
def day_code(am, pm, pm_pending=False):
    """
    One letter for a school day:
      P = present all day   L = present but late (morning or afternoon)
      H = half day (only morning or only afternoon)   E = excused   A = absent
    """
    here = {"PRESENT", "LATE"}
    am_here, pm_here = am in here, pm in here
    if pm_pending:                       # today, afternoon not finished: judge by the morning
        if am_here:
            return "L" if am == "LATE" else "P"
        return "E" if am == "EXCUSED" else "A"
    if am_here and pm_here:
        return "L" if "LATE" in (am, pm) else "P"
    if am_here or pm_here:
        return "H"
    if "EXCUSED" in (am, pm):
        return "E"
    return "A"


DAY_STATUS = {"P": "PRESENT", "L": "LATE", "H": "HALF", "E": "EXCUSED", "A": "ABSENT"}


def _students(section_id=None, search=""):
    where, params = [], []
    if section_id:
        where.append("s.section_id = ?")
        params.append(section_id)
    if search:
        where.append("(s.first_name || ' ' || s.last_name LIKE ? OR s.last_name || ', ' || s.first_name LIKE ? "
                     "OR s.student_no LIKE ?)")
        params += [f"%{search}%"] * 3
    with connect() as conn:
        return conn.execute(
            f"""SELECT s.id, s.student_no, s.first_name, s.last_name, s.created_at, s.section_id, s.photo,
                       COALESCE(CASE WHEN sec.grade_level <> '' THEN sec.grade_level || ' ' ELSE '' END || sec.name, '—') AS section
                FROM students s LEFT JOIN sections sec ON sec.id = s.section_id
                {('WHERE ' + ' AND '.join(where)) if where else ''}
                ORDER BY sec.grade_level, sec.name, s.last_name, s.first_name""", params).fetchall()


def log_report(start: date, end: date, section_id=None, search="", status=""):
    """One row per student per school day, including days they never tapped (absent)."""
    s = get_settings()
    now = datetime.now()
    end = min(end, now.date())
    students = _students(section_id, search)
    with connect() as conn:
        logs = conn.execute("SELECT * FROM daily_logs WHERE date BETWEEN ? AND ?",
                            (start.isoformat(), end.isoformat())).fetchall()
    by_key = {(r["student_id"], r["date"]): r for r in logs}
    rows = []
    for d in sorted(school_days(start, end, s), reverse=True):
        ds = d.isoformat()
        pending = d == now.date() and now.strftime("%H:%M") < s["pm_end"]
        for st in students:
            if ds < st["created_at"]:
                continue
            lg = by_key.get((st["id"], ds))
            am, pm = (lg["am_status"], lg["pm_status"]) if lg else (None, None)
            code = day_code(am, pm, pending and not (lg and lg["pm_in"]))
            day_status = DAY_STATUS[code]
            if status and day_status != status:
                continue
            rows.append({
                "date": ds, "student_id": st["id"], "student_no": st["student_no"],
                "name": f"{st['last_name']}, {st['first_name']}", "section": st["section"], "photo": st["photo"],
                "inside": bool(lg and d == now.date() and ((lg["am_in"] and not lg["am_out"]) or (lg["pm_in"] and not lg["pm_out"]))),
                "am_in": lg["am_in"] if lg else None, "am_out": lg["am_out"] if lg else None,
                "pm_in": lg["pm_in"] if lg else None, "pm_out": lg["pm_out"] if lg else None,
                "am_status": am or "ABSENT", "pm_status": pm or ("PENDING" if pending else "ABSENT"),
                "code": code, "status": day_status, "remarks": lg["remarks"] if lg else "",
            })
    return rows


def where_now(log, now: datetime = None, settings=None):
    """Where a student is right now, from today's log: (code, text)."""
    s = settings or get_settings()
    now = now or datetime.now()
    if not log or not any(log[k] for k in ("am_in", "am_out", "pm_in", "pm_out")):
        if log and "EXCUSED" in (log["am_status"], log["pm_status"]):
            return "excused", "Excused today"
        return "absent", "Not arrived" if now.strftime("%H:%M") < s["pm_end"] else "Absent today"
    if log["pm_out"]:
        return "out", f"Went home at {fmt_time(log['pm_out'])}"
    if log["pm_in"]:
        return "in", f"Inside since {fmt_time(log['pm_in'])} (afternoon)"
    if log["am_out"]:
        return "out", f"Out since {fmt_time(log['am_out'])} (lunch)" if now.strftime("%H:%M") < s["pm_end"] \
            else f"Left at {fmt_time(log['am_out'])}, didn't return"
    return "in", f"Inside since {fmt_time(log['am_in'])}"


def find_students(q, limit=8, now: datetime = None):
    """Search by name, student no. or card and say where each match is right now."""
    q = (q or "").strip()
    if len(q) < 2:
        return []
    now = now or datetime.now()
    s = get_settings()
    with connect() as conn:
        rows = conn.execute(
            """SELECT s.id, s.student_no, s.first_name, s.last_name, s.photo, s.rfid_uid,
                      COALESCE(CASE WHEN sec.grade_level <> '' THEN sec.grade_level || ' ' ELSE '' END || sec.name, '') AS section,
                      d.am_in, d.am_out, d.pm_in, d.pm_out, d.am_status, d.pm_status
               FROM students s LEFT JOIN sections sec ON sec.id = s.section_id
               LEFT JOIN daily_logs d ON d.student_id = s.id AND d.date = ?
               WHERE s.first_name || ' ' || s.last_name LIKE ? OR s.last_name || ', ' || s.first_name LIKE ?
                  OR s.student_no LIKE ? OR s.rfid_uid = ?
               ORDER BY s.last_name, s.first_name LIMIT ?""",
            (now.date().isoformat(), f"%{q}%", f"%{q}%", f"%{q}%", normalize_uid(q), limit)).fetchall()
    out = []
    for r in rows:
        code, text = where_now(r, now, s)
        out.append({**dict(r), "where": code, "where_text": text})
    return out


def today_summary(section_id=None, now: datetime = None):
    """Counts for the Today page, per half day, plus who is missing."""
    now = now or datetime.now()
    s = get_settings()
    students = _students(section_id)
    with connect() as conn:
        logs = {r["student_id"]: r for r in conn.execute("SELECT * FROM daily_logs WHERE date = ?",
                                                          (now.date().isoformat(),))}
    here = ("PRESENT", "LATE")
    hm = now.strftime("%H:%M")
    period = current_period(now, s)
    c = {"TOTAL": len(students), "PERIOD": period, "INSIDE": 0,
         "AM": {"IN": 0, "LATE": 0, "OUT": 0, "EXCUSED": 0, "MISSING": 0, "started": hm >= _add_minutes(s["am_start"], -60)},
         "PM": {"IN": 0, "LATE": 0, "OUT": 0, "EXCUSED": 0, "MISSING": 0, "started": hm >= lunch_split(s)}}
    missing = {"AM": [], "PM": []}
    for st in students:
        lg = logs.get(st["id"])
        for half, key_in, key_out, key_st in (("AM", "am_in", "am_out", "am_status"), ("PM", "pm_in", "pm_out", "pm_status")):
            status = lg[key_st] if lg else None
            if status in here:
                c[half]["IN"] += 1
                c[half]["LATE"] += status == "LATE"
            elif status == "EXCUSED":
                c[half]["EXCUSED"] += 1
            else:
                c[half]["MISSING"] += 1
                missing[half].append({"id": st["id"], "name": f"{st['last_name']}, {st['first_name']}",
                                      "student_no": st["student_no"], "section": st["section"], "photo": st["photo"],
                                      "note": "Came in the afternoon" if half == "AM" and lg and lg["pm_in"] else ""})
            if lg and lg[key_out]:
                c[half]["OUT"] += 1
        if lg and ((lg["am_in"] and not lg["am_out"]) or (lg["pm_in"] and not lg["pm_out"])):
            c["INSIDE"] += 1
    return c, missing


def month_report(section_id, year: int, month: int):
    """Monthly attendance sheet for a section: one column per school day, P/L/H/E/A per student."""
    s = get_settings()
    first = date(year, month, 1)
    last = (date(year + (month == 12), (month % 12) + 1, 1) - timedelta(days=1))
    now = datetime.now()
    end = min(last, now.date())
    if end == now.date() and now.strftime("%H:%M") < s["pm_end"]:
        end = end - timedelta(days=1)                # today isn't finished yet
    days = list(school_days(first, end, s)) if end >= first else []
    students = _students(section_id)
    with connect() as conn:
        logs = conn.execute("SELECT * FROM daily_logs WHERE date BETWEEN ? AND ?",
                            (first.isoformat(), last.isoformat())).fetchall()
    by_key = {(r["student_id"], r["date"]): r for r in logs}
    rows = []
    for st in students:
        cells, counts = [], {"P": 0, "L": 0, "H": 0, "E": 0, "A": 0}
        counted = 0
        for d in days:
            ds = d.isoformat()
            if ds < st["created_at"]:
                cells.append(None)
                continue
            lg = by_key.get((st["id"], ds))
            code = day_code(lg["am_status"] if lg else None, lg["pm_status"] if lg else None)
            counts[code] += 1
            counted += 1
            cells.append({"code": code, "log": dict(lg) if lg else None})
        attended = counts["P"] + counts["L"] + 0.5 * counts["H"]
        absences = counts["A"] + 0.5 * counts["H"]
        rate = round(100 * attended / counted) if counted else None
        rows.append({"student": dict(st), "cells": cells, "counts": counts, "attended": attended,
                     "absences": absences, "rate": rate})
    return days, rows


def week_chart(section_id=None, days=7):
    """Present / late / half day / absent counts for the last few finished school days."""
    s = get_settings()
    out, d = [], date.today()
    now = datetime.now()
    if now.strftime("%H:%M") < s["pm_end"]:
        d -= timedelta(days=1)
    tries = 0
    while len(out) < days and tries < 40:
        tries += 1
        if is_school_day(d, s):
            rows = log_report(d, d, section_id)
            c = {k: 0 for k in DAY_STATUS.values()}
            for r in rows:
                c[r["status"]] += 1
            out.append({"date": d.strftime("%b %d").replace(" 0", " "), **c})
        d -= timedelta(days=1)
    return list(reversed(out))


def student_month(student_id, year, month):
    with connect() as conn:
        st = conn.execute("SELECT section_id FROM students WHERE id = ?", (student_id,)).fetchone()
    if not st:
        return [], {}
    days, rows = month_report(st["section_id"], year, month)
    row = next((r for r in rows if r["student"]["id"] == student_id), None)
    return days, row


if __name__ == "__main__":
    init_db()
    print("Database ready at", DB_PATH)
