"""
ACR122U bridge: reads cards from an ACS ACR122U (or any PC/SC NFC reader) through
Windows' smart-card service, records attendance, then blinks the reader's LED and
beeps so the student knows what happened.

  1 short beep + green blink   = logged in / out
  2 beeps + red & green blink  = repeat tap, or already logged out
  3 beeps + red blink          = card not registered

Needs:  pip install pyscard
The card UID is read with the standard "Get UID" command (FF CA 00 00 00), so it is
the same hex string the Arduino + RC522 sketch produces for the same card.
"""
import threading
import time
from datetime import datetime

import capture
import database as db

try:
    from smartcard.System import readers as list_readers
    from smartcard.Exceptions import NoCardException, CardConnectionException, SmartcardException
except Exception:                 # pyscard missing -> dashboard still works
    list_readers = None
    NoCardException = CardConnectionException = SmartcardException = Exception

GET_UID = [0xFF, 0xCA, 0x00, 0x00, 0x00]
BUZZER_OFF_ON_DETECT = [0xFF, 0x00, 0x52, 0x00, 0x00]   # we beep ourselves, with a meaning

# FF 00 40 <LED state> 04 <T1> <T2> <repeat> <buzzer>; T1/T2 in units of 100 ms, buzzer 01 = beep during T1
FEEDBACK = {
    "ok":    [0xFF, 0x00, 0x40, 0xA0, 0x04, 0x02, 0x01, 0x01, 0x01],   # green blink, 1 beep
    "warn":  [0xFF, 0x00, 0x40, 0xF0, 0x04, 0x01, 0x01, 0x02, 0x01],   # red+green blink, 2 beeps
    "error": [0xFF, 0x00, 0x40, 0x50, 0x04, 0x01, 0x01, 0x03, 0x01],   # red blink, 3 beeps
}
RESULT_FEEDBACK = {"AM_IN": "ok", "AM_OUT": "ok", "PM_IN": "ok", "PM_OUT": "ok",
                   "DUP": "warn", "DONE": "warn", "UNKNOWN": "error"}

POLL_SECONDS = 0.2

status = {
    "state": "disabled",       # disabled / connecting / connected / error
    "port": "",                # reader name
    "message": "ACR122U not in use",
    "last_scan": None,
    "since": None,
}

_reconnect = threading.Event()
_started = False


def available_readers():
    if list_readers is None:
        return []
    try:
        return [str(r) for r in list_readers()]
    except Exception:
        return []


def request_reconnect():
    _reconnect.set()


def _set(state, message, reader=""):
    if status["state"] != state or status["message"] != message:
        status.update(state=state, message=message, port=reader,
                      since=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


def _pick_reader():
    found = list_readers()
    if not found:
        return None
    for r in found:                       # prefer the ACR122U, skip its SAM slot if listed
        name = str(r).upper()
        if "ACR122" in name and "SAM" not in name:
            return r
    return found[0]


def _uid_hex(data):
    return "".join(f"{b:02X}" for b in data)


def _feedback(conn, kind):
    try:
        conn.transmit(FEEDBACK[kind])
    except Exception:
        pass                              # LEDs are a nice-to-have; never fail a scan over them


def _run():
    present_uid = None                    # card currently sitting on the reader
    buzzer_configured_for = None

    while True:
        if db.get_settings().get("reader_mode") != "acr122u":
            _set("disabled", "ACR122U not in use")
            present_uid = None
            _reconnect.wait(3)
            _reconnect.clear()
            continue
        if list_readers is None:
            _set("error", "pyscard is not installed. Run: pip install pyscard")
            _reconnect.wait(5)
            _reconnect.clear()
            continue

        try:
            reader = _pick_reader()
        except Exception as exc:          # smart-card service stopped, etc.
            reader = None
            _set("error", f"Smart card service not available: {exc}")
        if reader is None:
            if status["state"] != "error" or "service" not in status["message"]:
                _set("error", "ACR122U not found. Plug it in (and install the ACS driver if Windows asks).")
            present_uid = None
            buzzer_configured_for = None
            _reconnect.wait(2)
            _reconnect.clear()
            continue

        name = str(reader)
        _set("connected", f"Reader ready: {name}", name)

        conn = reader.createConnection()
        try:
            conn.connect()
        except (NoCardException, CardConnectionException, SmartcardException):
            present_uid = None            # no card on the reader
            time.sleep(POLL_SECONDS)
            continue
        except Exception:
            present_uid = None
            time.sleep(POLL_SECONDS)
            continue

        try:
            data, sw1, sw2 = conn.transmit(GET_UID)
            if sw1 != 0x90 or not data:
                _feedback(conn, "error")
                present_uid = None
            else:
                uid = _uid_hex(data)
                if uid != present_uid:    # new tap (not the same card still lying there)
                    present_uid = uid
                    if buzzer_configured_for != name:
                        try:
                            conn.transmit(BUZZER_OFF_ON_DETECT)
                        except Exception:
                            pass
                        buzzer_configured_for = name
                    if capture.offer(uid):       # teacher is registering a card
                        print(f"Card captured for registration: {uid}")
                        _feedback(conn, "ok")
                    else:
                        result = db.process_scan(uid, source="acr122u")
                        status["last_scan"] = result
                        print(f"[{result['time']}] {uid} -> {result['reply']}")
                        _feedback(conn, RESULT_FEEDBACK.get(result["result"], "error"))
        except Exception as exc:
            print("ACR122U read error:", exc)
        finally:
            try:
                conn.disconnect()
            except Exception:
                pass
        time.sleep(POLL_SECONDS)


def start():
    global _started
    if _started:
        return
    _started = True
    threading.Thread(target=_run, name="acr122u-bridge", daemon=True).start()
