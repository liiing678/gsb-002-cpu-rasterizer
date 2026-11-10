"""Public black-box checks; contains analytic probes, not a reference renderer."""
import argparse
import copy
import json
import math
from pathlib import Path
import struct
import subprocess
import sys
import tempfile

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
IDENTITY = [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def srgb(rgb):
    def encode(c):
        s = 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055
        return math.floor(255 * min(1, max(0, s)) + 0.5)
    return tuple(encode(c) for c in rgb)


def scene():
    return {
        "schema_version": 1, "width": 16, "height": 16,
        "clear_color": [0, 0, 0, 1],
        "camera": {"view": copy.deepcopy(IDENTITY), "projection": copy.deepcopy(IDENTITY)},
        "meshes": [], "materials": [], "instances": [],
    }


def add_shape(s, iid, positions, triangles, color, mode="OPAQUE", uvs=None, **material):
    key = str(iid)
    s["meshes"].append({"id": key, "positions": positions,
                        "uvs": uvs or [[0, 0] for _ in positions], "triangles": triangles})
    s["materials"].append({"id": key, "base_color": color, "alpha_mode": mode, **material})
    s["instances"].append({"id": iid, "mesh": key, "material": key,
                           "model": copy.deepcopy(IDENTITY)})


def rectangle(s, iid, depth, color, mode="OPAQUE", bounds=(2, 2, 14, 14), **material):
    left, top, right, bottom = bounds
    points = [(left, top), (right, top), (right, bottom), (left, bottom)]
    positions = [[2 * x / s["width"] - 1, 1 - 2 * y / s["height"], 2 * depth - 1]
                 for x, y in points]
    add_shape(s, iid, positions, [[0, 1, 2], [0, 2, 3]], color, mode,
              [[0, 0], [1, 0], [1, 1], [0, 1]], **material)


class Harness:
    def __init__(self, root, timeout):
        self.root, self.timeout, self.calls = root, timeout, 0

    def texture(self, name, width, height, pixels):
        path = self.root / name
        path.write_text(json.dumps({"width": width, "height": height, "pixels": pixels}),
                        encoding="utf-8")
        return path.name

    def call(self, label, s, samples=4, reject=False):
        self.calls += 1
        prefix = f"{self.calls:03d}_{label}"
        path, output = self.root / (prefix + ".json"), self.root / (prefix + "_out")
        path.write_text(json.dumps(s, allow_nan=False), encoding="utf-8")
        result = subprocess.run(
            [sys.executable, "-m", "renderer", "--scene", str(path), "--output", str(output),
             "--samples", str(samples)], cwd=ROOT, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=self.timeout,
        )
        message = (result.stdout + result.stderr).strip()
        if reject:
            require(result.returncode != 0, f"{label}: invalid input was accepted")
            require(bool(message), f"{label}: invalid input needs a readable diagnostic")
            return None
        require(result.returncode == 0,
                f"{label}: renderer exited {result.returncode}: {message[:1500]}")
        width, height = s["width"], s["height"]
        count = width * height
        with Image.open(output / "color.png") as img:
            require(img.format == "PNG" and img.mode == "RGB", f"{label}: expected RGB PNG")
            require(img.size == (width, height), f"{label}: wrong image dimensions")
            rgb = img.tobytes()
        depth_bytes, id_bytes = (output / "depth.f32").read_bytes(), (output / "ids.u32").read_bytes()
        require(len(depth_bytes) == count * 4, f"{label}: wrong depth.f32 size")
        require(len(id_bytes) == count * 4, f"{label}: wrong ids.u32 size")
        depths, ids = struct.unpack(f"<{count}f", depth_bytes), struct.unpack(f"<{count}I", id_bytes)
        require(all(math.isfinite(d) and 0 <= d <= 1 for d in depths), f"{label}: invalid depth")
        allowed = {0} | {instance["id"] for instance in s["instances"]}
        require(set(ids) <= allowed, f"{label}: unknown instance ID")
        require(all(i != 0 or abs(d - 1) <= 2e-6 for d, i in zip(depths, ids)),
                f"{label}: background must have depth=1")
        return {"label": label, "width": width, "rgb": rgb, "depth": depths, "ids": ids}


def probe(result, x, y, color, depth, iid):
    index = y * result["width"] + x
    rgb, expected = result["rgb"][index * 3:index * 3 + 3], srgb(color)
    where = f"{result['label']} at ({x},{y})"
    require(all(abs(a - b) <= 1 for a, b in zip(rgb, expected)),
            f"{where}: RGB {tuple(rgb)}, expected {expected}")
    require(abs(result["depth"][index] - depth) <= 2e-6,
            f"{where}: depth {result['depth'][index]}, expected {depth}")
    require(result["ids"][index] == iid, f"{where}: ID {result['ids'][index]}, expected {iid}")


def same(a, b):
    require(a["ids"] == b["ids"], f"{a['label']}: instance order changed IDs")
    require(all(abs(x - y) <= 2e-6 for x, y in zip(a["depth"], b["depth"])),
            f"{a['label']}: instance order changed depths")
    require(all(abs(x - y) <= 1 for x, y in zip(a["rgb"], b["rgb"])),
            f"{a['label']}: instance order changed colors")


def reversed_result(h, label, s, samples=4):
    changed = copy.deepcopy(s)
    changed["instances"].reverse()
    return h.call(label + "_reversed", changed, samples)


def analytic_checks(h):
    s = scene()
    rectangle(s, 7, 0.4, [0.25, 0.5, 0.75, 0])  # OPAQUE ignores zero alpha.
    for samples in (1, 4):
        result = h.call(f"opaque_{samples}", s, samples)
        probe(result, 8, 8, [0.25, 0.5, 0.75], 0.4, 7)
        probe(result, 0, 0, [0, 0, 0], 1, 0)

    s = scene()
    rectangle(s, 11, 0.5, [1, 0, 0, 0.5], "BLEND")
    for samples in (1, 4):
        result = h.call(f"shared_edge_{samples}", s, samples)
        # Samples exactly on the shared diagonal must belong to only one triangle.
        for xy in (4, 8, 11):
            probe(result, xy, xy, [0.5, 0, 0], 0.5, 11)
        probe(result, 4, 9, [0.5, 0, 0], 0.5, 11)

    s = scene()
    rectangle(s, 3, 0.5, [1, 1, 1, 1], bounds=(4.5, 2, 14, 14))
    result = h.call("partial_coverage", s, 4)
    # The two x=.75 samples are covered; the x=.25 samples are background.
    probe(result, 4, 8, [0.5, 0.5, 0.5], 0.5, 3)
    probe(result, 3, 8, [0, 0, 0], 1, 0)

    s = scene()
    rectangle(s, 80, 0.8, [0.2, 0.2, 0.2, 1])
    rectangle(s, 90, 0.9, [1, 1, 0, 1], "BLEND")  # Behind opaque.
    rectangle(s, 65, 0.65, [0, 0, 1, 0.25], "BLEND")
    rectangle(s, 50, 0.5, [0, 1, 0, 0.5], "BLEND")
    rectangle(s, 20, 0.2, [1, 0, 0, 0.5], "BLEND")
    rectangle(s, 10, 0.1, [0, 1, 1, 0], "BLEND")  # Must not be picked.
    rectangle(s, 1, 0.05, [1, 1, 1, 1])
    s["instances"][-1]["visible"] = False
    result = h.call("layers", s)
    probe(result, 8, 8, [0.5375, 0.2875, 0.1], 0.2, 20)
    same(result, reversed_result(h, "layers", s))

    s = scene()
    rectangle(s, 9, 0.4, [0, 1, 0, 0.5], "BLEND")
    rectangle(s, 3, 0.4, [1, 0, 0, 0.5], "BLEND")
    rectangle(s, 5, 0.4, [0, 0, 1, 1])
    result = h.call("equal_depth", s)
    # id3 is in front of opaque id5; id9 is behind it despite equal depth.
    probe(result, 8, 8, [0.5, 0, 0.5], 0.4, 3)
    same(result, reversed_result(h, "equal_depth", s))

    mask = h.texture("mask_probe.json", 2, 1, [[1, 0, 0, 0.8], [1, 0, 0, 1]])
    s = scene()
    rectangle(s, 70, 0.7, [0, 0, 1, 1])
    rectangle(s, 30, 0.3, [1, 1, 1, 0.5], "MASK", texture=mask)
    result = h.call("mask_threshold", s)
    probe(result, 4, 8, [0, 0, 1], 0.7, 70)  # 0.8 * 0.5 < default cutoff.
    probe(result, 10, 8, [1, 0, 0], 0.3, 30)  # 1 * 0.5 == cutoff.

    texture = h.texture("repeat_probe.json", 2, 2,
                        [[1, 0, 0, 1], [0, 1, 0, 1], [0, 0, 1, 1], [1, 1, 0, 1]])
    s = scene()
    rectangle(s, 4, 0.5, [1, 1, 1, 1], texture=texture)
    s["meshes"][0]["uvs"] = [[-0.25, -0.25]] * 4
    probe(h.call("negative_uv", s), 8, 8, [1, 1, 0], 0.5, 4)

    pixels = [[1, 0, 1, 1] for _ in range(16)]
    pixels[5] = [0.2, 0.4, 0.6, 1]
    texture = h.texture("perspective_probe.json", 4, 4, pixels)
    s = scene()
    s["camera"]["projection"] = [[1, 0, 0, 0], [0, 1, 0, 0],
                                  [0, 0, -11 / 9, -20 / 9], [0, 0, -1, 0]]
    # Projected screen vertices: (2,2),(14,2),(2,14), with w=1,4,4.
    add_shape(s, 15, [[-0.75, 0.75, -1], [3, 3, -4], [-3, -3, -4]], [[0, 1, 2]],
              [1, 1, 1, 1], uvs=[[0, 0], [4, 0], [0, 4]], texture=texture)
    # At (4.5,4.5): barycentrics=(7/12,5/24,5/24); UV=(10/33,10/33).
    # The expected depth is (5/24+5/24)*(5/6)=25/72, not perspective corrected again.
    probe(h.call("perspective_uv_depth", s, 1), 4, 4, [0.2, 0.4, 0.6], 25 / 72, 15)

    s = scene()
    add_shape(s, 16, [[-0.75, 0.75, -2], [0.75, 0.75, 0], [-0.75, -0.75, 0]],
              [[0, 1, 2]], [1, 0, 0, 1])
    result = h.call("near_clip", s, 1)
    probe(result, 4, 4, [0, 0, 0], 1, 0)
    probe(result, 8, 4, [1, 0, 0], 0.25, 16)

    s = scene()
    rectangle(s, 17, 1, [0, 1, 0, 1])
    probe(h.call("far_plane", s), 8, 8, [0, 1, 0], 1, 17)
    s["meshes"][0]["triangles"][0][0] = 999
    h.call("invalid_vertex_index", s, reject=True)
    print("PASS: analytic coverage, depth, texture, mask, transparency and rejection checks")


def supplied_checks(h):
    paths = sorted((ROOT / "scenes").glob("[0-9][0-9]_*.json"))
    require(len(paths) == 7, "Expected seven supplied scenes")
    for path in paths:
        s = json.loads(path.read_text(encoding="utf-8"))
        # Relocate textures alongside each temporary scene; no absolute-path extension is needed.
        for index, material in enumerate(s["materials"]):
            if "texture" in material:
                name = f"{path.stem}_texture_{index}.json"
                (h.root / name).write_bytes((path.parent / material["texture"]).resolve().read_bytes())
                material["texture"] = name
        result = h.call(path.stem, s, 4)
        same(result, reversed_result(h, path.stem, s, 4))
        if path.stem == "05_transparency":
            probe(result, 64, 64, [0.2875, 0.5375, 0.1], 0.496484375, 42)
            probe(result, 63, 64, [0.5375, 0.2875, 0.1], 0.496484375, 41)
        elif path.stem == "06_mask":
            probe(result, 52, 52, [0, 0, 1], 0.7, 51)
            probe(result, 52, 76, [0, 0, 1], 0.7, 51)
            probe(result, 76, 76, [0, 1, 0], 0.3, 52)
        elif path.stem == "07_empty":
            require(set(result["ids"]) == {0}, "07_empty: out-of-frustum geometry appeared")
            expected = bytes(srgb(s["clear_color"][:3])) * (s["width"] * s["height"])
            require(all(abs(a - b) <= 1 for a, b in zip(result["rgb"], expected)),
                    "07_empty: wrong background color")
        print(f"PASS: {path.name} output format, instance-order invariance and available probes")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=None,
                        help="Optional seconds per process; an operational timeout, not a speed requirement")
    args = parser.parse_args()
    try:
        with tempfile.TemporaryDirectory(prefix="render_checks_") as temporary:
            harness = Harness(Path(temporary), args.timeout)
            analytic_checks(harness)
            supplied_checks(harness)
            print(f"PASS: public checks completed ({harness.calls} renderer invocations)")
    except (AssertionError, OSError, ValueError, subprocess.TimeoutExpired) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
