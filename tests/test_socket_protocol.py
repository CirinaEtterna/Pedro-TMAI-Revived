"""Protocol test of tmenv.socket against a fake AITool plugin built from Telemetry.as."""
import re
import socket as pysocket
import struct
import threading
import time
from pathlib import Path

from tmenv.socket import Socket

ROOT = Path(__file__).resolve().parents[1]
src = (ROOT / "public-op-aitool" / "Telemetry.as").read_text()
fields = re.findall(r"'(\"[a-z_0-9]+\":(?:\"[^\"]+\"|\[[^\]]+\]))'", src)
HEADER = ("{" + ",".join(fields) + "}").encode()
FORMAT = "<" + "".join(re.findall(r'"([?Iif])"', "".join(f.split(":", 1)[1] for f in fields)))


def fake_plugin(port, frames, received):
    s = pysocket.create_connection(("127.0.0.1", port))
    s.sendall(HEADER)
    for i in range(frames):
        values = []
        for code in FORMAT[1:]:
            values.append({"?": i % 2 == 0, "I": i, "i": -i, "f": i * 0.5}[code])
        payload = struct.pack(FORMAT, *values)
        # split frames at odd offsets to exercise partial recv
        s.sendall(payload[:7]); s.sendall(payload[7:200]); s.sendall(payload[200:])
        time.sleep(0.002)
    s.settimeout(1)
    try:
        received.append(s.recv(1024).decode())
    except OSError:
        pass
    time.sleep(0.3)
    s.close()


def run(port):
    sock = Socket(port=port)
    received = []
    t = threading.Thread(target=fake_plugin, args=(sock.port, 200, received))
    t.start()
    while not sock.connected:
        time.sleep(0.01)
    while not sock.telemetry or sock.telemetry["distance"] < 150 * 0.5:
        time.sleep(0.01)
    tel = sock.telemetry
    sock.send_command("LoadMap", "https://example/map.gbx")
    t.join()
    assert len(tel) == len(fields) + 1, len(tel)
    i = tel["landmark_index"]
    assert tel["racetime"] == -i and tel["distance"] == i * 0.5 and tel["position"] == [i * 0.5] * 3
    assert tel["finished"] == (i % 2 == 0) and tel["speed"] == i * 0.5
    assert received and received[0] == "LoadMap|https://example/map.gbx;", received
    sock.close()
    return sock.port, len(HEADER), struct.calcsize(FORMAT)


port, header, frame = run(0)
print(f"protocol OK: header {header} bytes, frame {frame} bytes, {len(fields)} fields")
# Recovery path: close and rebind the same fixed port twice in a row
for _ in range(2):
    run(20199)
print("fixed port close/rebind OK")
