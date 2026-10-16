"""Prepare GbxToJson for Windows from the Linux single-file .NET bundle shipped with tmenv.

The bundle (`gbx-to-json/GbxToJson`) contains platform-independent managed assemblies (GbxToJson,
GBX.NET 1.x, GBX.NET.LZO, Newtonsoft.Json, ...). They run unchanged on a Windows .NET runtime, so instead of
redistributing them they are extracted here on first use into `gbx-to-json/win/`.

Usage: python extract_bundle.py [bundle] [out_dir]
"""
import json
import struct
import zlib
from pathlib import Path

BUNDLE_SIGNATURE = bytes([
    0x8B, 0x12, 0x02, 0xB9, 0x6A, 0x61, 0x20, 0x38, 0x72, 0x7B, 0x93, 0x02, 0x14, 0xD7, 0xA0, 0x32,
    0x13, 0xF5, 0xB9, 0xE6, 0xEF, 0xAE, 0x33, 0x18, 0xEE, 0x3B, 0x2D, 0xCE, 0x24, 0xB3, 0x6A, 0xAE,
])
HERE = Path(__file__).resolve().parent
# Runs on any .NET >= 7 runtime (the bundle targets net7.0, which is out of support)
RUNTIME_CONFIG = {"runtimeOptions": {"tfm": "net7.0", "rollForward": "Major",
                                     "framework": {"name": "Microsoft.NETCore.App", "version": "7.0.0"}}}


class _Reader:
    def __init__(self, data, pos):
        self.data, self.pos = data, pos

    def unpack(self, fmt):
        values = struct.unpack_from("<" + fmt, self.data, self.pos)
        self.pos += struct.calcsize("<" + fmt)
        return values if len(values) > 1 else values[0]

    def string(self):
        length, shift = 0, 0
        while True:  # 7-bit encoded length prefix (BinaryWriter.Write(string))
            b = self.data[self.pos]
            self.pos += 1
            length |= (b & 0x7F) << shift
            if not b & 0x80:
                break
            shift += 7
        s = self.data[self.pos:self.pos + length].decode("utf-8")
        self.pos += length
        return s


def bundle_files(bundle_path):
    "Yield (relative path, file type, bytes) for every file of a .NET single-file bundle."
    data = Path(bundle_path).read_bytes()
    sig = data.find(BUNDLE_SIGNATURE)
    if sig < 8:
        raise ValueError(f"{bundle_path} is not a .NET single-file bundle")
    (header_offset,) = struct.unpack_from("<q", data, sig - 8)
    r = _Reader(data, header_offset)
    major, _minor, count = r.unpack("IIi")
    r.string()  # bundle id
    if major >= 2:
        r.unpack("qqqqQ")  # deps.json / runtimeconfig.json locations + flags
    for _ in range(count):
        offset, size, compressed_size = r.unpack("qqq") if major >= 6 else (*r.unpack("qq"), 0)
        file_type = r.unpack("B")
        rel_path = r.string()
        raw = data[offset:offset + (compressed_size or size)]
        if compressed_size:
            raw = zlib.decompress(raw) if raw[:2] == b"\x78\x9c" else zlib.decompress(raw, -15)
        yield rel_path, file_type, raw


def extract(bundle=HERE / "GbxToJson", out_dir=HERE / "win"):
    "Extract the application assemblies (not the bundled Linux runtime) and write a portable runtimeconfig."
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    names = []
    deps = None
    files = {rel: (kind, raw) for rel, kind, raw in bundle_files(bundle)}
    for rel, (kind, raw) in files.items():
        if rel.endswith(".deps.json"):
            deps = json.loads(raw)
    # Keep the assemblies the app references (deps.json "runtime" entries outside Microsoft.NETCore.App)
    wanted = {"GbxToJson.dll", "GbxToJson.deps.json"}
    for lib in (deps or {}).get("targets", {}).values():
        for name, info in lib.items():
            if not name.startswith(("Microsoft.NETCore.App", "runtimepack.")):
                wanted.update(Path(p).name for p in info.get("runtime", {}))
    for rel, (kind, raw) in files.items():
        if Path(rel).name in wanted:
            (out_dir / Path(rel).name).write_bytes(raw)
            names.append(Path(rel).name)
    (out_dir / "GbxToJson.runtimeconfig.json").write_text(json.dumps(RUNTIME_CONFIG, indent=2), encoding="utf-8")
    return sorted(names)


if __name__ == "__main__":
    import sys

    print("\n".join(extract(*sys.argv[1:3])))
