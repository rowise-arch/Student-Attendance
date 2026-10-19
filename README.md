# RFID Student Attendance System (entrance logging)

Students tap their RFID card at the school entrance four times a day:

| Morning in | Morning out | Afternoon in | Afternoon out |
|---|---|---|---|
| arriving | leaving for lunch | back from lunch | going home |

A Python app saves each tap in **SQLite**, marks students **Late** when they arrive after the start time, and staff see everything on a web dashboard: today's taps live, a daily log, and a monthly attendance report per section.

The reader can be an Arduino Uno + RC522, an ACS ACR122U, or a keyboard-type USB reader.

```
[RC522 reader] → [Arduino Uno] —USB serial→ [Python app: serial bridge + Flask] → [attendance.db (SQLite)]
                       ↑ reply (beep/LED)                     ↓
                                                       Teacher dashboard (browser)
```

## Folder contents

| File | What it does |
|---|---|
| `arduino/rfid_attendance/rfid_attendance.ino` | Arduino sketch: reads the card, sends `UID:xxxx`, gives LED/buzzer/LCD feedback |
| `app.py` | Flask web dashboard (all pages and routes) |
| `database.py` | SQLite tables, the morning/afternoon tap rules and the reports |
| `capture.py` | Registration mode: taps on the Add/Edit student page fill in the card number |
| `serial_bridge.py` | Background thread that talks to the Arduino over the COM port |
| `pcsc_bridge.py` | Background thread that reads cards from an ACR122U (PC/SC) reader |
| `seed_demo.py` | Optional: fills the database with 3 sample sections, 24 students and 3 weeks of logs |
| `templates/`, `static/` | Dashboard pages, kiosk screen, styling and scripts (works offline, no internet needed) |
| `RFID_Attendance.bat` | Double-click to start everything on Windows |
| `attendance.db` | Created automatically on first run (this is the database) |

## 1. Hardware wiring

> ⚠️ The RC522 runs on **3.3V**. Connecting its VCC to 5V can damage it.

| RC522 pin | Arduino Uno |
|---|---|
| SDA (SS) | D10 |
| SCK | D13 |
| MOSI | D11 |
| MISO | D12 |
| RST | D9 |
| 3.3V | 3.3V |
| GND | GND |
| IRQ | not connected |

Feedback parts (optional but recommended):

| Part | Arduino Uno |
|---|---|
| Green LED (through a 220Ω resistor) | D5 |
| Red LED (through a 220Ω resistor) | D4 |
| Active buzzer (+) | D6 |
| 16x2 I2C LCD: GND / VCC / SDA / SCL | GND / 5V / A4 / A5 |

**LCD screen:** while waiting it shows *Tap your ID card* and the school name, e.g. *Corcuera NHS*. Until the dashboard connects, the second line reads *Waiting for PC..*. After a tap it shows the student's name and, for example, `IN 7:21 AM    OK`, `IN 7:45 AM  LATE` or `OUT 12:01 PM Bye`, for 2.5 seconds. The LCD's address (0x27 or 0x3F) is found automatically. If the backlight is on but no text shows, turn the small blue screw (potentiometer) on the back of the LCD to adjust the contrast. No LCD? Set `#define USE_LCD 0` in the sketch.

Feedback meaning: **1 beep + green** = logged in/out · **2 beeps + both LEDs** = repeat tap or already logged out · **3 beeps + red** = unregistered card or the PC app isn't running.

## 2. Upload the Arduino sketch

1. Install the [Arduino IDE](https://www.arduino.cc/en/software).
2. **Tools → Manage Libraries**, install **MFRC522** (by GithubCommunity) and **LiquidCrystal I2C** (by Frank de Brabander). The LCD is turned on in the sketch (`#define USE_LCD 1`).
3. Open `arduino/rfid_attendance/rfid_attendance.ino`, select **Board: Arduino Uno** and the right **Port**, then click Upload.
4. Optional check: open the Serial Monitor (9600 baud) and tap a card. You should see `UID:XXXXXXXX`. **Close the Serial Monitor afterwards.** Only one program can use the COM port at a time.

## 3. Run the dashboard

1. Install **Python 3.10 or newer** from python.org. During setup, tick **"Add python.exe to PATH"**.
2. Double-click **`RFID_Attendance.bat`**. The first run installs Flask and pyserial, then the dashboard opens at <http://127.0.0.1:5000>.
3. Sign in with **admin / admin123**, then change the password in **Settings**.
4. In **Settings → RFID reader**, choose the Arduino's COM port (e.g. `COM3 — USB Serial Device`) and click Save. The sidebar dot turns green when the reader is connected.

(Manual start: `pip install -r requirements.txt`, then `python app.py`.)

## 3a. Using an ACS ACR122U reader instead (no Arduino needed)

The ACR122U plugs straight into the PC by USB and reads the same 13.56 MHz cards as the RC522. The card numbers match too, so cards registered with the Arduino keep working.

1. Plug in the ACR122U. Windows usually installs a driver by itself. If the reader isn't detected, install the **ACR122U PC/SC driver** from the ACS website (acs.com.hk).
2. Run `RFID_Attendance.bat`. It also installs **pyscard**, the Python package that talks to the reader.
3. In **Settings → Reader type**, choose **ACS ACR122U** and click Save. The sidebar should show **ACR122U connected**.
4. Students tap their card. The reader beeps **once** (green blink) when logged in/out, **twice** for a repeat tap or if already logged out, and **three times** (red blink) for an unregistered card. It works in the background; no window needs to be active.

To register a card, open **Add student** (or Edit student) and tap the card. The card number fills in by itself, and no attendance is recorded.

## 3b. Using a USB keyboard-type reader instead (optional)

Plug-in readers that "type" the card number (they show up as a keyboard) work without the Arduino.

1. Plug the reader into the PC. Open Notepad and tap a card: you should see a number appear, followed by a new line.
2. In **Settings → Reader type**, choose **Keyboard-type reader** and click Save.
3. Use **Test the keyboard reader** on the Settings page to check that it's detected.
4. Keep the **Dashboard** or **Kiosk screen** window active (clicked on) while students tap. The reader types into whichever window is active. The kiosk shows a yellow "Click here" bar if it loses focus.

How it tells a reader from a person: the reader types the whole number in a few milliseconds, so slow typing on the keyboard is ignored. On the **Add student** page, tapping a card just fills in the card number; no attendance is recorded.

> Cards are not interchangeable between readers. Most keyboard-type readers are 125 kHz and read different cards than the RC522 (13.56 MHz), and the number format differs too. Register each student's card using the reader you'll actually use.

## 4. Setting up (once)

1. **Settings → School**: upload the school logo (PNG/JPG/WebP) and fill in the school name, School ID, school year, address and principal. They appear on the sidebar, login page, kiosk screen and the printed monthly report.
1. **Settings → School hours**: set when the morning and afternoon start and end (default 7:30–12:00 and 1:00–5:00), plus an optional grace period before a tap counts as late.
2. **Sections**: add each year level and section, e.g. *Grade 10* · *Rizal*, plus the class adviser (printed as "Prepared by" on the report).
3. **Students**: add them one by one, or **Import CSV** a whole list (columns: `student_no, first_name, last_name, grade_level, section, rfid_uid`). To link a card, open **Add student** or **Edit student** and tap the card. The number fills in by itself, and no attendance is recorded.
   **Photo:** on the same page, click **Take photo** to use the PC's webcam, or **Upload** a picture. It's cropped to a square automatically. The photo shows on the student list, on the live taps, and big on the kiosk screen, so the guard can check that the card belongs to the student. Photos are saved in the `photos` folder; back it up together with `attendance.db`.
4. Optional: open the **Kiosk screen** on a monitor at the entrance and click **Full screen**. Each tap shows the student's name, e.g. "Good morning, Juan! Morning in 7:21 AM · On time".

## 5. Every day

Nothing to set up. Keep the app running (`RFID_Attendance.bat`) and students tap in and out.

* **Today**: separate Morning and Afternoon panels (in, late, logged out, missing), live taps with photos, and a 7-day chart. Click **Absent / Not in yet** to see exactly who is missing, then open or print the list. Use **Find a student** to check where someone is right now (inside since…, logged out, not arrived). Filter by section.
* **Daily log**: every student's four times per day, with Present / Late / Half day / Excused / Absent. Filter by date, section, status or name. Shows 50 rows per page; students still inside get an **Inside now** chip. Click **Edit** (or **Manual entry**) for a forgotten card, an excused absence or a wrong tap. **Export CSV** opens in Excel.
* **Monthly report**: choose a section and month to get the attendance sheet, with one column per school day (P / L / H / E / A) plus totals, days absent and an attendance rate. Export or print it. The printout is an official form: school logo and details, section, month, school year, legend, and signature lines for the adviser and principal (use landscape).
* **Holidays / suspensions**: on **Today**, click **Mark today as no classes** (an **Undo** button appears right away), or add dates in **Settings → No-class days**. Those days don't count in reports.
* Click a student's name to see their history and attendance rate.
* **Students** shows how many have a card and a photo; click **Show … without a card/photo** to finish setup quickly.
* **Kiosk**: taps appear on the kiosk and on Today the instant the card is read (the server pushes them, no waiting). The kiosk can play a tone that matches the result: rising = logged in, falling = logged out, two soft notes = already recorded, low buzz = unknown card. Sound is on by default for keyboard-type readers and off for the ACR122U/Arduino (they beep themselves); switch it with the **Sound** button. Click the kiosk once after opening it so the browser allows sound. Press **Esc** to go back to the dashboard.

**Tips:** click any table header to sort. Deleting a section, an account or a no-class day happens at once with an **Undo** button for 7 seconds. Deleting a student (which also removes their attendance history) still needs the button **pressed and held** for 1.5 seconds.

## Tap rules

| When the student taps | Recorded as |
|---|---|
| First tap in the morning | **Morning in** (Late if after the morning start + grace) |
| Next tap in the morning | **Morning out** |
| First tap after the middle of lunch (or the first tap of the day during lunch) | **Afternoon in** (Late if after the afternoon start + grace) |
| A student still "in" from the morning who taps during lunch | **Morning out** (left late for lunch) |
| Next tap in the afternoon | **Afternoon out** |
| Tapping again within 3 minutes | Ignored (repeat tap) |
| After logging out | Ignored ("already logged out") |

**Day status:** Present = morning and afternoon · Late = present but late in either half · Half day = only morning or only afternoon · Excused = marked by staff · Absent = no taps. In the monthly report, a half day counts as half a day absent.

## Testing without the Arduino

* `python seed_demo.py` adds 3 sections, 24 students and 3 weeks of morning/afternoon logs.
* **Settings → Test without the Arduino** simulates a card tap using any UID.
* To start fresh, stop the app and delete `attendance.db`.

## Database tables (for your capstone documentation)

| Table | Key columns |
|---|---|
| `teachers` | id, username, full_name, password_hash |
| `sections` | id, name, grade_level |
| `students` | id, student_no, first_name, last_name, section_id → sections, rfid_uid (unique) |
| `daily_logs` | id, student_id → students, date, am_in, am_out, pm_in, pm_out, am_status, pm_status, remarks · one row per student per day |
| `scan_log` | id, uid, student_id, scanned_at, result (AM_IN / AM_OUT / PM_IN / PM_OUT / DUP / DONE / UNKNOWN), source |
| `settings` | key, value (school hours, grace period, holidays, reader) |

You can open `attendance.db` with [DB Browser for SQLite](https://sqlitebrowser.org/) to show the tables during your defense.

## Troubleshooting

| Problem | Fix |
|---|---|
| Reader shows offline / "Access is denied" | Close the Arduino IDE Serial Monitor (or any other program using the port), then click **Reconnect reader** |
| COM port isn't listed | Replug the USB cable and refresh Settings. Check Device Manager → Ports |
| 3 beeps on every tap | The PC app isn't running, the wrong port is selected, or the card isn't registered |
| Morning taps counted as afternoon (or the reverse) | Check **Settings → School hours**. Taps switch to "afternoon" at the middle of lunch break |
| "ACR122U not found" | Replug the reader, install the ACS driver, and check that the Windows **Smart Card** service is running (services.msc) |
| "Camera access was blocked" | Click the camera icon in the browser's address bar, choose **Allow**, and try again. Close other apps using the webcam (Zoom, Camera) |
| "pyscard is not installed" | Run `pip install pyscard` in the project folder, then restart the app |
| Reader never detects cards | Check that the RC522 gets **3.3V** and that the SPI pins match the table above |
| `python` not recognized | Reinstall Python and tick "Add python.exe to PATH" |
