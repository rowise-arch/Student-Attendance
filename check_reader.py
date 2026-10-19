"""
ACR122U troubleshooter. Double-click check_reader.bat (or run: python check_reader.py).
Checks each piece the dashboard needs and prints what to fix.
"""
import platform
import struct
import subprocess
import sys
import time

OK, BAD, INFO = "[ OK ]", "[FAIL]", "[ .. ]"


def run(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=20, shell=isinstance(cmd, str)).stdout
    except Exception as exc:
        return f"(could not run: {exc})"


print("=" * 64)
print(" ACR122U reader check")
print("=" * 64)

# 1. Python
bits = struct.calcsize("P") * 8
print(f"{INFO} Python {platform.python_version()} ({bits}-bit) at {sys.executable}")

# 2. Windows sees the device + driver
if sys.platform == "win32":
    out = run('powershell -NoProfile -Command "Get-PnpDevice -PresentOnly | Where-Object { $_.FriendlyName -match \'ACR122|ACS|Smart card reader|CCID\' } | Format-Table -AutoSize Status,Class,FriendlyName | Out-String -Width 200"')
    if out.strip():
        print(f"{INFO} Devices Windows sees:")
        print("       " + out.strip().replace("\n", "\n       "))
        if "Error" in out or "Unknown" in out:
            print(f"{BAD} A reader device shows an error status. Reinstall the ACR122U driver from acs.com.hk and replug it.")
    else:
        print(f"{BAD} Windows doesn't list an ACR122U / smart card reader. Replug it, try another USB port,")
        print("       and install the 'ACR122U PC/SC driver' from acs.com.hk.")

    # 3. Smart Card service
    svc = run("sc query SCardSvr")
    if "RUNNING" in svc:
        print(f"{OK} Windows Smart Card service is running")
    else:
        print(f"{BAD} Windows Smart Card service is NOT running.")
        print("       Fix: press Win+R, type services.msc, find 'Smart Card', set Startup type to Automatic, click Start.")
        print("       (Or in an Administrator command prompt: sc config SCardSvr start= auto  &  net start SCardSvr)")

# 4. pyscard
try:
    import smartcard
    from smartcard.System import readers
    print(f"{OK} pyscard is installed ({getattr(smartcard, '__version__', 'version unknown')})")
except Exception as exc:
    print(f"{BAD} pyscard is not installed or failed to load: {exc}")
    print(f"       Fix: \"{sys.executable}\" -m pip install pyscard")
    input("\nPress Enter to close...")
    sys.exit(1)

# 5. PC/SC readers
try:
    found = readers()
except Exception as exc:
    print(f"{BAD} Couldn't ask Windows for readers: {exc}")
    print("       This usually means the Smart Card service is stopped (see above).")
    input("\nPress Enter to close...")
    sys.exit(1)

if not found:
    print(f"{BAD} No PC/SC readers found. The driver isn't loaded or the reader isn't plugged in.")
    input("\nPress Enter to close...")
    sys.exit(1)

print(f"{OK} Readers found:")
for r in found:
    print(f"       - {r}")
reader = next((r for r in found if "ACR122" in str(r).upper() and "SAM" not in str(r).upper()), found[0])
print(f"{INFO} Using: {reader}")

# 6. Read a card
print(f"\n{INFO} Tap a card on the reader within 15 seconds...")
deadline = time.time() + 15
while time.time() < deadline:
    conn = reader.createConnection()
    try:
        conn.connect()
    except Exception:
        time.sleep(0.2)
        continue
    try:
        data, sw1, sw2 = conn.transmit([0xFF, 0xCA, 0x00, 0x00, 0x00])
        if sw1 == 0x90:
            uid = "".join(f"{b:02X}" for b in data)
            print(f"{OK} Card read! UID = {uid}")
            try:
                conn.transmit([0xFF, 0x00, 0x40, 0xA0, 0x04, 0x02, 0x01, 0x01, 0x01])
                print(f"{OK} Sent green blink + beep")
            except Exception as exc:
                print(f"{INFO} LED/beep command not accepted: {exc}")
        else:
            print(f"{BAD} Card found but UID command returned {sw1:02X} {sw2:02X}. Try a different card.")
    except Exception as exc:
        print(f"{BAD} Card read failed: {exc}")
    finally:
        try:
            conn.disconnect()
        except Exception:
            pass
    break
else:
    print(f"{BAD} No card detected. Hold the card flat on the reader's logo area.")

print("\nAll checks done. If everything says OK, restart the dashboard (close it and run RFID_Attendance.bat).")
input("Press Enter to close...")
