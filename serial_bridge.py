"""
Serial bridge: runs in a background thread, reads "UID:XXXX" lines from the
Arduino over USB, records attendance in SQLite and replies so the Arduino can
beep / light the right LED.
"""
import threading
import time
import unicodedata
from datetime import datetime

import capture
import database as db

try:
    import serial
    from serial.tools import list_ports
except ImportError:          # pyserial not installed -> dashboard still works
    serial = None
    list_ports = None

BAUD_RATE = 9600

status = {
    "state": "disabled",     # disabled / connecting / connected / error
    "port": "",
    "message": "No serial port selected",
    "last_scan": None,
    "since": None,
}

_reconnect = threading.Event()
_started = False


def available_ports():
    if list_ports is None:
        return []
    return [{"device": p.device, "description": p.description} for p in list_ports.comports()]


def request_reconnect():
    """Call after the serial port setting changes."""
    _reconnect.set()


def _set(state, message, port=""):
    status.update(state=state, message=message, port=port,
                  since=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


def lcd_bytes(text: str) -> bytes:
    """Text for the 16x2 LCD. Its built-in character set has a lowercase ñ (code 0xEE),
    so "Peña" shows correctly; other accents are dropped (é -> e, Ñ -> N)."""
    out = bytearray()
    for ch in text:
        if ch == "ñ":
            out.append(0xEE)
        elif ord(ch) < 128:
            out.append(ord(ch))
        else:
            plain = unicodedata.normalize("NFKD", ch).encode("ascii", "ignore")
            out += plain or b"?"
    return bytes(out)


def _send_school(ser):
    """Tell the Arduino the school name for its LCD idle screen."""
    try:
        ser.write(lcd_bytes(f"SCHOOL|{db.lcd_school_name()}\n"))
    except Exception:
        pass


def _run():
    while True:
        _reconnect.clear()
        settings = db.get_settings()
        port = settings.get("serial_port", "").strip()

        if settings.get("reader_mode") in ("keyboard", "acr122u"):
            _set("disabled", "Arduino not in use")
            _reconnect.wait(5)
            continue

        if serial is None:
            _set("error", "pyserial is not installed (pip install pyserial)")
            _reconnect.wait(5)
            continue
        if not port:
            _set("disabled", "No serial port selected - choose one in Settings")
            _reconnect.wait(3)
            continue

        try:
            _set("connecting", f"Opening {port}...", port)
            with serial.Serial(port, BAUD_RATE, timeout=0.5) as ser:
                time.sleep(2)            # Uno resets when the port opens
                ser.reset_input_buffer()
                _set("connected", f"Reader connected on {port}", port)
                _send_school(ser)
                hello_at = time.time()

                while not _reconnect.is_set():
                    line = ser.readline().decode("ascii", errors="ignore").strip()
                    if line == "READY" or (not line and time.time() - hello_at > 60):
                        _send_school(ser)        # Arduino restarted, or a periodic refresh for the LCD
                        hello_at = time.time()
                    if not line.startswith("UID:"):
                        continue
                    uid = db.normalize_uid(line[4:])
                    if capture.offer(uid):           # teacher is registering a card
                        ser.write(f"REG|{uid}\n".encode("ascii"))
                        print(f"Card captured for registration: {uid}")
                        continue
                    result = db.process_scan(uid, source="reader")
                    ser.write(lcd_bytes(result["reply"] + "\n"))
                    status["last_scan"] = result
                    print(f"[{result['time']}] {result['uid']} -> {result['reply']}")
        except Exception as exc:     # unplugged, wrong port, port busy, ...
            _set("error", f"{port}: {exc}", port)
            _reconnect.wait(3)       # retry every few seconds


def start():
    global _started
    if _started:
        return
    _started = True
    threading.Thread(target=_run, name="serial-bridge", daemon=True).start()
