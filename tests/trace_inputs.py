"""Send the test key sequence to Trackmania while tracing telemetry (racetime, inputs) at 20 Hz."""
import threading
import time

from tmenv.socket import Socket
from tmenv.win32 import TmWindow, find_game_windows, send_keys

sock = Socket(port=20131)
print("listening on 20131 ...")
while not sock.connected:
    time.sleep(0.1)
while not sock.telemetry:
    time.sleep(0.1)
print("telemetry flowing")
win = TmWindow(find_game_windows()[0])
print("focus:", win.focus(), "| foreground:", win.is_foreground())

rows, stop = [], False


def sampler():
    while not stop:
        t = sock.telemetry
        rows.append((time.time(), t["racetime"], t["accelerate"], t["brake"], round(t["steer"], 2), round(t["speed"], 1), t["ui_sequence"]))
        time.sleep(0.05)


threading.Thread(target=sampler, daemon=True).start()
t0 = time.time()
events = []


def at(sec, label, fn):
    while time.time() - t0 < sec:
        time.sleep(0.005)
    fn()
    events.append((time.time(), label))


at(0.5, "Delete tap", lambda: (send_keys("Delete"), time.sleep(0.03), send_keys("Delete", up=True)))
at(3.0, "Up down", lambda: send_keys("Up"))
at(4.5, "Up up", lambda: send_keys("Up", up=True))
at(5.0, "Down down", lambda: send_keys("Down"))
at(5.6, "Down up", lambda: send_keys("Down", up=True))
at(6.0, "Left down", lambda: send_keys("Left"))
at(6.6, "Left up", lambda: send_keys("Left", up=True))
at(7.0, "Right down", lambda: send_keys("Right"))
at(7.6, "Right up", lambda: send_keys("Right", up=True))
at(8.0, "Delete tap", lambda: (send_keys("Delete"), time.sleep(0.03), send_keys("Delete", up=True)))
time.sleep(1.5)
stop = True
print("foreground at end:", win.is_foreground())
print(f"{'t':>5} {'racetime':>8} {'accel':>5} {'brake':>5} {'steer':>5} {'speed':>6} ui")
ei, prev = 0, None
for ts, *vals in rows:
    while ei < len(events) and events[ei][0] <= ts:
        print(f"{events[ei][0] - t0:5.2f} >>> {events[ei][1]}")
        ei += 1
    key = tuple(vals[1:5]) + (vals[5],)
    if key != prev or int((ts - t0) * 20) % 10 == 0:
        print(f"{ts - t0:5.2f} {vals[0]:8d} {vals[1]:5.1f} {str(vals[2]):>5} {vals[3]:5.2f} {vals[4]:6.1f} {vals[5]}")
    prev = key
sock.close()
