"""
Card registration mode.

While a teacher has the Add/Edit student page open, that page pings /api/capture
every second. During that time any card tapped on the reader (Arduino or ACR122U)
is handed to the form to fill in the RFID field, instead of recording attendance.
Closing the page (or switching to another tab) ends registration mode within a few seconds.
"""
import threading
import time
from datetime import datetime

ACTIVE_SECONDS = 3.0

_lock = threading.Lock()
_active_until = 0.0
_seq = 0
_last = None


def heartbeat():
    global _active_until
    with _lock:
        _active_until = time.time() + ACTIVE_SECONDS


def stop():
    global _active_until
    with _lock:
        _active_until = 0.0


def active():
    return time.time() < _active_until


def offer(uid):
    """Called by the reader bridges. Returns True if the tap was used for registration."""
    global _seq, _last
    with _lock:
        if time.time() >= _active_until:
            return False
        _seq += 1
        _last = {"seq": _seq, "uid": uid, "at": datetime.now().strftime("%H:%M:%S")}
        return True


def latest():
    with _lock:
        return dict(_last) if _last else None, _seq
