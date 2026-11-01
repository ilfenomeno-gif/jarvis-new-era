"""Builds a tiny valid .glb (two named nodes) so viewer tests need no network or assets."""
import json
import struct


def make_glb(path) -> None:
    positions = struct.pack("<9f", 0, 0, 0, 1, 0, 0, 0, 1, 0)
    gltf = {
        "asset": {"version": "2.0"},
        "scene": 0,
        "scenes": [{"nodes": [0, 1]}],
        "nodes": [
            {"name": "part_a", "mesh": 0, "translation": [-1, 0, 0]},
            {"name": "part_b", "mesh": 0, "translation": [1, 0, 0]},
        ],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}}]}],
        "accessors": [{
            "bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3",
            "min": [0, 0, 0], "max": [1, 1, 0],
        }],
        "bufferViews": [{"buffer": 0, "byteLength": len(positions)}],
        "buffers": [{"byteLength": len(positions)}],
    }
    js = json.dumps(gltf).encode()
    js += b" " * (-len(js) % 4)
    total = 12 + 8 + len(js) + 8 + len(positions)
    blob = struct.pack("<III", 0x46546C67, 2, total)
    blob += struct.pack("<II", len(js), 0x4E4F534A) + js
    blob += struct.pack("<II", len(positions), 0x004E4942) + positions
    with open(path, "wb") as f:
        f.write(blob)
