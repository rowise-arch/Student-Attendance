"""
Fills the database with sample sections, students and three weeks of entrance logs
(morning in/out, afternoon in/out) so the dashboard has something to show.

    python seed_demo.py

Delete attendance.db to start over with an empty database.
"""
import random
from datetime import date, datetime, timedelta

import database as db

SECTIONS = [("Grade 10", "Rizal"), ("Grade 10", "Bonifacio"), ("Grade 9", "Mabini")]
FIRST = ["Juan", "Maria", "Jose", "Ana", "Mark", "Angela", "Paolo", "Kristine", "Miguel", "Bea",
         "Carlo", "Jasmine", "Rafael", "Nicole", "Gabriel", "Sofia", "Daniel", "Patricia", "Luis", "Camille"]
LAST = ["Dela Cruz", "Santos", "Reyes", "Garcia", "Bautista", "Mendoza", "Villanueva", "Ramos", "Torres", "Aquino",
        "Flores", "Castillo", "Navarro", "Lopez", "Domingo", "Morales", "Cruz", "Rivera", "Ramirez", "Salazar"]
STUDENTS_PER_SECTION = 8


def t(base, minutes):
    return (datetime.strptime(base, "%H:%M") + timedelta(minutes=minutes)).strftime("%H:%M:%S")


def main():
    db.init_db()
    random.seed(7)
    s = db.get_settings()
    start = date.today() - timedelta(days=21)
    with db.connect() as conn:
        for grade, name in SECTIONS:
            conn.execute("INSERT OR IGNORE INTO sections(name, grade_level) VALUES (?, ?)", (name, grade))
        sec = {r["name"]: r["id"] for r in conn.execute("SELECT id, name FROM sections")}
        n = 0
        for _, name in SECTIONS:
            for _ in range(STUDENTS_PER_SECTION):
                n += 1
                conn.execute(
                    """INSERT OR IGNORE INTO students(student_no, first_name, last_name, section_id, rfid_uid, created_at)
                       VALUES (?,?,?,?,?,?)""",
                    (f"2024-{n:04d}", FIRST[(n - 1) % len(FIRST)], LAST[(n * 7) % len(LAST)], sec[name],
                     f"DE{n:02X}{random.randint(0, 0xFFFF):04X}", start.isoformat()))

        students = conn.execute("SELECT id FROM students").fetchall()
        d = start
        while d < date.today():
            if db.is_school_day(d, s):
                for st in students:
                    roll = random.random()
                    if roll < 0.06:
                        continue                                       # absent all day
                    row = {"am_in": None, "am_out": None, "pm_in": None, "pm_out": None,
                           "am_status": None, "pm_status": None, "remarks": ""}
                    if roll < 0.08:
                        row.update(am_status="EXCUSED", pm_status="EXCUSED", remarks="Medical certificate")
                    else:
                        if roll > 0.12:                               # came in the morning
                            late = random.random() < 0.15
                            row["am_in"] = t(s["am_start"], random.randint(1, 25) if late else -random.randint(0, 35))
                            row["am_status"] = "LATE" if late else "PRESENT"
                            row["am_out"] = t(s["am_end"], random.randint(0, 10))
                        if roll < 0.12 or random.random() > 0.05:     # came in the afternoon
                            late = random.random() < 0.08
                            row["pm_in"] = t(s["pm_start"], random.randint(1, 15) if late else -random.randint(0, 25))
                            row["pm_status"] = "LATE" if late else "PRESENT"
                            row["pm_out"] = t(s["pm_end"], random.randint(0, 20))
                    conn.execute(
                        """INSERT OR IGNORE INTO daily_logs(student_id, date, am_in, am_out, pm_in, pm_out,
                                                            am_status, pm_status, remarks)
                           VALUES (?,?,?,?,?,?,?,?,?)""",
                        (st["id"], d.isoformat(), row["am_in"], row["am_out"], row["pm_in"], row["pm_out"],
                         row["am_status"], row["pm_status"], row["remarks"]))
            d += timedelta(days=1)
    print("Demo data added: 3 sections, 24 students, 3 weeks of morning/afternoon logs.")


if __name__ == "__main__":
    main()
