"""Capture raw AITool telemetry bytes and work out the real frame layout (size, byte order, alignment)."""
import re
import socket
import struct
import time
from pathlib import Path

src = Path(r"D:\TMAI\public-op-aitool\Telemetry.as").read_text()
fields = re.findall(r"'(\"[a-z_0-9]+\":(?:\"[^\"]+\"|\[[^\]]+\]))'", src)
names = [f.split(":", 1)[0].strip('"') for f in fields]
fmts = [re.findall(r'"([?Iif])"', f.split(":", 1)[1]) for f in fields]
flat = "".join("".join(x) for x in fmts)
size = struct.calcsize("<" + flat)
print(f"expected frame {size} bytes, {len(names)} fields")

s = socket.socket()
s.bind(("127.0.0.1", 20131))
s.listen()
print("listening on 20131 ...")
conn, _ = s.accept()
hdr = b""
while not hdr.endswith(b"}"):
    hdr += conn.recv(1)
print(f"header {len(hdr)} bytes, starts {hdr[:40]!r}")
data, t = b"", time.time()
while len(data) < 60000 and time.time() - t < 15:
    data += conn.recv(65536)
conn.close()
s.close()
print(f"got {len(data)} bytes in {time.time() - t:.2f}s")

scores = []
for P in range(200, 500):
    n = min(len(data) - P, 20000)
    scores.append((sum(data[i] == data[i + P] for i in range(n)) / n, P))
scores.sort(reverse=True)
print("most likely frame sizes (similarity, bytes):", [(round(a, 3), p) for a, p in scores[:6]])
P = scores[0][1]


def decode(buf, order):
    vals = struct.unpack(order + flat, buf[:size])
    out, i = {}, 0
    for nm, f in zip(names, fmts):
        if len(f) > 1:
            out[nm] = [round(v, 3) for v in vals[i:i + len(f)]]
            i += len(f)
        else:
            out[nm] = round(vals[i], 3) if isinstance(vals[i], float) else vals[i]
            i += 1
    return out


keys = ["finished", "ui_sequence", "landmark_index", "racetime", "position", "velocity", "forward", "speed",
        "accelerate", "brake", "gear", "rpm", "front_speed", "fl_wheel_contact_material", "rr_wheel_contact_material"]
for order, label in (("<", "little endian"), (">", "big endian")):
    for k in (0, 1):
        d = decode(data[k * P:], order)
        print(f"{label} frame {k}:", {n: d[n] for n in keys})
print(f"\nfirst frame hex ({P} bytes):")
for i in range(0, P, 16):
    print(f"{i:4d}: {data[i:i + 16].hex(' ')}")
