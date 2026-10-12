"""Bounded, offline whole-rectangle atlas repacking with serialized equivalence.

MaxRects splitting/short-side placement adapts the GPL-3.0 project tool
fantasy-gauntlet-mod-tools/wf_battle_atlas_repack.py. Codecs and Flatomo replay
come from the already distributed bridge/core. No game store is read or written.
This proves local artifact equivalence, never native/game acceptance.
"""
from __future__ import annotations

import bisect
import copy
import hashlib
import io
import json
import math
import re
import zlib
from dataclasses import dataclass
from pathlib import PurePosixPath

from PIL import Image, ImageChops, ImageDraw
from bridge import AMF3Reader, encode_amf3, flatomo

PNG = b"\x89PNG\r\n\x1a\n"
FAKE_PNG = b"\x89png\r\n\x1a\n"
ATLAS_SUFFIX = ".atlas.amf3.deflate"
DEFAULT_OPTIONS = {"enabled": False, "max_ticks": 20000, "max_depth": 32,
                   "max_rects": 4096, "max_pixels": 64000000, "max_commands": 500000}
HARD_LIMITS = {"max_ticks": 100000, "max_depth": 40, "max_rects": 16000,
               "max_pixels": 128000000, "max_commands": 2000000}
MAX_AMF_BYTES = 16000000
MAX_FILES = 16000
MAX_PACK_FREE = 2048
MAX_BUNDLE_RECTS = 2048
MAX_PACK_WORK = 8000000


class AtlasOptimizationError(ValueError):
    """Invalid configuration/input; bundle-specific failures are receipts."""


def validate_options(options=None):
    """Return normalized options, preserving unknown extensions without mutation."""
    if options is None:
        options = {}
    if not isinstance(options, dict):
        raise AtlasOptimizationError("atlasOptimization must be an object")
    result = copy.deepcopy(options)
    for key, default in DEFAULT_OPTIONS.items():
        value = result.setdefault(key, default)
        if key == "enabled":
            if not isinstance(value, bool):
                raise AtlasOptimizationError("enabled must be boolean")
        elif isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= HARD_LIMITS[key]:
            raise AtlasOptimizationError(f"{key} must be an integer in 1..{HARD_LIMITS[key]}")
    return result


def _amf(raw, require_reencodable=False):
    decoder = zlib.decompressobj(-15)
    value = decoder.decompress(raw, MAX_AMF_BYTES + 1)
    if len(value) > MAX_AMF_BYTES or decoder.unconsumed_tail or not decoder.eof or decoder.unused_data:
        raise AtlasOptimizationError("AMF deflate size/trailing-data limit")
    reader = AMF3Reader(value)
    result = reader.read_value()
    if reader.pos != len(value):
        raise AtlasOptimizationError("AMF trailing data")
    if require_reencodable and encode_amf3(result) != value:
        # The small bridge reader intentionally collapses undefined/null and
        # typed/sealed/associative encodings. They cannot be safely rewritten.
        raise AtlasOptimizationError("unsupported noncanonical atlas AMF encoding")
    return result


def _amf_bytes(value):
    compressor = zlib.compressobj(9, zlib.DEFLATED, -15)
    return compressor.compress(encode_amf3(value)) + compressor.flush()


def _image(raw, limit):
    if raw[:8] not in (PNG, FAKE_PNG):
        raise AtlasOptimizationError("not a supported PNG")
    with Image.open(io.BytesIO(PNG + raw[8:])) as image:
        if image.format != "PNG" or getattr(image, "n_frames", 1) != 1:
            raise AtlasOptimizationError("not a single-frame PNG")
        if image.width * image.height > limit:
            raise AtlasOptimizationError("pixel budget exceeded")
        return image.convert("RGBA")


def _png_bytes(image, header):
    output = io.BytesIO()
    image.save(output, format="PNG", compress_level=9)
    return header + output.getvalue()[8:]


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _sha(value):
    return hashlib.sha256(value).hexdigest()


def _logical_root(file_root):
    # compile_project wraps native logical paths for export; this is packaging,
    # not an atlas collection/layer inference. Other wrappers are unsupported.
    if file_root.startswith("compiled/common/"):
        return file_root[len("compiled/common/"):]
    if file_root.startswith("compiled/"):
        raise AtlasOptimizationError("unsupported compiled namespace wrapper")
    return file_root


def _int(value, label, low=0, high=0xffffffff):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or int(value) != value or not low <= value <= high:
        raise AtlasOptimizationError(f"invalid integer {label}")
    return int(value)


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    w: int
    h: int


def _intersects(a, b):
    return a.x < b.x + b.w and b.x < a.x + a.w and a.y < b.y + b.h and b.y < a.y + a.h


def _contains(a, b):
    return a.x <= b.x and a.y <= b.y and a.x + a.w >= b.x + b.w and a.y + a.h >= b.y + b.h


def _rect(record):
    if not isinstance(record, dict):
        raise AtlasOptimizationError("atlas record is not an object")
    return Rect(*(_int(record.get(k), k, 1 if k in ("w", "h") else 0) for k in ("x", "y", "w", "h")))


def _validate_atlas(image, records, options, root):
    if not isinstance(records, list) or not records:
        raise AtlasOptimizationError("atlas must be a nonempty record array")
    if len(records) > min(options["max_rects"], MAX_BUNDLE_RECTS):
        raise AtlasOptimizationError("rectangle budget exceeded")
    names, regions = set(), []
    for record in records:
        region = _rect(record)
        name = record.get("n")
        if not isinstance(name, str) or not name.startswith(root + "/") or name in names:
            raise AtlasOptimizationError("missing/duplicate/foreign logical atlas name")
        names.add(name)
        _canonical(record)  # Reject nonfinite/unsupported/cyclic metadata before copying.
        if region.x + region.w > image.width or region.y + region.h > image.height:
            raise AtlasOptimizationError("atlas rectangle outside sheet")
        if region not in regions:
            if any(_intersects(region, other) for other in regions):
                raise AtlasOptimizationError("overlapping nonidentical source rectangles")
            regions.append(region)
    covered = Image.new("L", image.size)
    draw = ImageDraw.Draw(covered)
    for r in regions:
        draw.rectangle((r.x, r.y, r.x + r.w - 1, r.y + r.h - 1), fill=255)
    if ImageChops.multiply(image.getchannel("A"), ImageChops.invert(covered)).getbbox():
        raise AtlasOptimizationError("opaque pixels outside declared atlas rectangles")
    return regions


def _split(free, used):
    if not _intersects(free, used):
        return [free]
    result = []
    if used.x > free.x:
        result.append(Rect(free.x, free.y, used.x - free.x, free.h))
    if used.x + used.w < free.x + free.w:
        result.append(Rect(used.x + used.w, free.y, free.x + free.w - used.x - used.w, free.h))
    if used.y > free.y:
        result.append(Rect(free.x, free.y, free.w, used.y - free.y))
    if used.y + used.h < free.y + free.h:
        result.append(Rect(free.x, used.y + used.h, free.w, free.y + free.h - used.y - used.h))
    return [r for r in result if r.w > 0 and r.h > 0]


def _pack(regions, width, height, mode, work):
    free, placed = [Rect(0, 0, width, height)], {}
    key = (lambda r: (-r.h, -r.w, r.y, r.x)) if mode == "height" else (lambda r: (-r.w * r.h, -max(r.w, r.h), -r.h, -r.w, r.y, r.x))
    for source in sorted(regions, key=key):
        candidates = []
        for slot in free:
            w, h = source.w + 2, source.h + 2
            if w <= slot.w and h <= slot.h:
                candidates.append(((min(slot.w - w, slot.h - h), max(slot.w - w, slot.h - h), slot.y, slot.x), Rect(slot.x, slot.y, w, h)))
        if not candidates:
            return None
        used = min(candidates, key=lambda v: v[0])[1]
        placed[source] = Rect(used.x + 2, used.y + 2, source.w, source.h)
        split = list(dict.fromkeys(r for slot in free for r in _split(slot, used)))
        if len(split) > MAX_PACK_FREE:
            return None
        work["packingWork"] += len(free) + len(split) ** 2
        if work["packingWork"] > MAX_PACK_WORK:
            work["packingWorkLimited"] = True
            return None
        free = [r for r in split if not any(r != other and _contains(other, r) for other in split)]
    size = (max(r.x + r.w for r in placed.values()), max(r.y + r.h for r in placed.values()))
    return placed, size


def _metrics(image, records, regions, png_raw, atlas_raw):
    return {"width": image.width, "height": image.height, "rawArea": image.width * image.height,
            "paddedArea": (image.width + 2) * (image.height + 2), "records": len(records),
            "uniqueRegions": len(regions), "regionRawArea": sum(r.w * r.h for r in regions),
            "regionPaddedArea": sum((r.w + 2) * (r.h + 2) for r in regions),
            "pngBytes": len(png_raw), "atlasBytes": len(atlas_raw)}


def _cells(image, records):
    cells = {}
    for record in records:
        r = _rect(record)
        crop = image.crop((r.x, r.y, r.x + r.w, r.y + r.h))
        # Packed rotation is metadata: compare stored RGBA and the resolved view.
        view = crop.transpose(Image.Transpose.ROTATE_90) if record.get("r") else crop
        cells[record["n"]] = {"rgba": _sha(crop.tobytes()), "viewRGBA": _sha(view.tobytes()),
                                "viewSize": view.size, "metadata": {k: v for k, v in record.items() if k not in ("x", "y")}}
    return cells


def _parts_frames(parts, names, options):
    if not isinstance(parts, dict) or parts.get("m") or parts.get("o"):
        raise AtlasOptimizationError("unsupported MovieClip/other resource parts")
    images, groups, matrices = (parts.get(k) for k in ("i", "g", "t"))
    if not all(isinstance(v, list) for v in (images, groups, matrices)) or not groups:
        raise AtlasOptimizationError("missing parts arrays/groups")
    if any(not isinstance(group, dict) for group in groups):
        raise AtlasOptimizationError("invalid parts group object")
    if len(images) > options["max_rects"] or len(groups) > options["max_ticks"]:
        raise AtlasOptimizationError("parts resource budget exceeded")
    if any(not isinstance(v, dict) or v.get("p") not in names or v.get("s") not in (False, None) for v in images):
        raise AtlasOptimizationError("parts image reference missing/foreign/unsupported")
    if not isinstance(parts.get("s", 1), (int, float)) or isinstance(parts.get("s", 1), bool) or not math.isfinite(parts.get("s", 1)):
        raise AtlasOptimizationError("invalid parts scale")
    for matrix in matrices:
        if not isinstance(matrix, dict) or any(isinstance(matrix.get(k), bool) or not isinstance(matrix.get(k), (int, float)) or not math.isfinite(matrix[k]) for k in ("a", "b", "c", "d", "x", "y")):
            raise AtlasOptimizationError("invalid matrix")
    lengths = [_int(group.get("t"), "group ticks", 1, options["max_ticks"]) for group in groups]
    if sum(lengths) > options["max_ticks"]:
        raise AtlasOptimizationError("tick budget exceeded")
    graph, states = [[] for _ in groups], 0
    custom = parts.get("c", [])
    if not isinstance(custom, list) or len(custom) > options["max_rects"]:
        raise AtlasOptimizationError("invalid custom tweens")
    for resource in custom:
        if not isinstance(resource, list) or len(resource) > 4096 or len(resource) < 4 or (len(resource) + 2) % 6 or any(isinstance(v, bool) or not isinstance(v, int) for v in resource):
            raise AtlasOptimizationError("unsupported custom tween resource")
    for gi, group in enumerate(groups):
        if not isinstance(group.get("s"), list):
            raise AtlasOptimizationError("invalid group segments")
        for segment in group["s"]:
            if not isinstance(segment, dict):
                raise AtlasOptimizationError("invalid segment object")
            packed = _int(segment.get("s"), "segment start", -0x80000000) & 0xffffffff
            kind, start = packed >> 30, packed & 0x3fffffff
            child = _int(segment.get("i"), "segment resource")
            if kind not in (0, 2) or child >= (len(images) if kind == 0 else len(groups)) or start >= lengths[gi]:
                raise AtlasOptimizationError("unsupported kind/bad segment reference")
            if kind == 2:
                graph[gi].append(child)
            keys = segment.get("l")
            if not isinstance(keys, list) or not keys:
                raise AtlasOptimizationError("missing segment keys")
            for key in keys:
                if not isinstance(key, dict):
                    raise AtlasOptimizationError("invalid key object")
                packed_m = _int(key.get("m"), "matrix reference", 0)
                if packed_m >> 12 >= len(matrices):
                    raise AtlasOptimizationError("bad matrix reference")
                duration = _int(key.get("t", 1), "key duration", 1)
                if not duration & 0xffff:
                    raise AtlasOptimizationError("zero key duration")
                states += duration & 0xffff
                if states > options["max_commands"]:
                    raise AtlasOptimizationError("key/state budget exceeded")
                if "c" in key:
                    _int(key["c"], "color", -0x80000000)
                tween = (duration >> 16) & 3
                if tween == 3:
                    raise AtlasOptimizationError("unsupported tween kind")
                if tween == 1 and duration >> 18 >= len(custom):
                    raise AtlasOptimizationError("bad custom tween reference")
                if kind == 2:
                    loop = _int(key.get("r", 0), "loop", -0x80000000) & 0xffffffff
                    if loop >> 30 == 3 or (loop & 0x3fffffff) >= lengths[child]:
                        raise AtlasOptimizationError("unsupported loop/bad child tick")
    # Detect recursion before building/expanding any commands; sharing a DAG is safe.
    # Memoized depths avoid exponential validation of a DAG with shared children.
    cache, active = {}, set()
    def depth(node):
        if node in active:
            raise AtlasOptimizationError("recursive parts group cycle")
        if node in cache:
            return cache[node]
        if len(active) > options["max_depth"]:
            raise AtlasOptimizationError("parts depth budget exceeded")
        active.add(node)
        value = max([0] + [1 + depth(child) for child in graph[node]])
        active.remove(node)
        if value > options["max_depth"]:
            raise AtlasOptimizationError("parts depth budget exceeded")
        cache[node] = value
        return value
    for group in range(len(groups)):
        depth(group)
    return flatomo._build_frames(parts)


def _parts_replay(parts, cells, options):
    frames = _parts_frames(parts, cells, options)
    digest, count, tick_count = hashlib.sha256(), 0, 0
    cell_signatures = {name: _sha(_canonical(cell)) for name, cell in cells.items()}
    def leaves(group, tick, parent=(1, 0, 0, 1, 0, 0), alpha=1, color=(1, 0, 0, 0), blend=0, path=()):
        nonlocal count
        if len(path) > options["max_depth"]:
            raise AtlasOptimizationError("parts depth budget exceeded")
        for state in frames[group][tick]:
            count += 1
            if count > options["max_commands"]:
                raise AtlasOptimizationError("expanded command budget exceeded")
            matrix = flatomo._concat(state.parameters.matrix, parent)
            a = alpha * state.parameters.alpha
            packed = state.parameters.color
            multiplier = ((packed >> 24) & 255) / 100
            c = (color[0] * multiplier, *(color[0] * ((packed >> shift) & 255) + color[i + 1] for i, shift in enumerate((16, 8, 0))))
            b = state.parameters.blend or blend
            channel = path + (state.segment_id,)
            if state.kind == 2:
                yield from leaves(state.item_id, state.child_frame, matrix, a, c, b, channel)
            else:
                name = parts["i"][state.item_id]["p"]
                yield {"cell": cell_signatures[name], "matrix": matrix, "alpha": a, "colorTransform": c,
                       "blend": b, "channel": channel, "partsScale": parts.get("s", 1)}
    peak, leaf_count = 0, 0
    for group, ticks in enumerate(frames):
        for tick in range(len(ticks)):
            digest.update(_canonical([group, tick]))
            tick_leaves = 0
            for command in leaves(group, tick):
                digest.update(b"\0" + _canonical(command))
                tick_leaves += 1
            digest.update(b"\n")
            peak = max(peak, tick_leaves)
            leaf_count += tick_leaves
            tick_count += 1
    return {"signature": digest.hexdigest(), "ticks": tick_count, "groups": len(frames),
            "leafCommands": leaf_count, "peakLeafCommands": peak, "expandedStates": count}


def _timeline(raw, max_tick, options):
    value = _amf(raw)
    if not isinstance(value, dict) or not isinstance(value.get("sequences"), list):
        raise AtlasOptimizationError("missing/invalid timeline sequences")
    for key in ("sounds", "points", "circles"):
        if not isinstance(value.get(key), list):
            raise AtlasOptimizationError("missing/invalid timeline " + key)
    for sequence in value["sequences"]:
        if not isinstance(sequence, dict):
            raise AtlasOptimizationError("invalid timeline sequence")
        begin = _int(sequence.get("begin"), "sequence begin", 1, max_tick)
        _int(sequence.get("end"), "sequence end", begin, max_tick)
    _canonical(value)
    return value


def _replay(files, png_path, records, cells, options):
    root = str(PurePosixPath(png_path).parent)
    logical_root = _logical_root(root)
    stem = PurePosixPath(png_path).stem
    names = set(cells)
    local_parts = [p for p in files if str(PurePosixPath(p).parent) == root and p.endswith(".parts.amf3.deflate")]
    if local_parts:
        if len(local_parts) != 1:
            raise AtlasOptimizationError("ambiguous parts consumers")
        path = local_parts[0]
        parts = _amf(files[path])
        result = _parts_replay(parts, cells, options)
        timeline_path = path.replace(".parts.amf3.deflate", ".timeline.amf3.deflate")
        if timeline_path not in files:
            raise AtlasOptimizationError("missing effect timeline")
        timeline = _timeline(files[timeline_path], parts["g"][0]["t"], options)
        result.update(kind="parts", partsPath=path, timelinePath=timeline_path,
                      timelineSHA256=_sha(files[timeline_path]), timelineEventsSHA256=_sha(_canonical(timeline)))
        return result
    frame_stem = {"sprite_sheet": "pixelart", "special_sprite_sheet": "special"}.get(stem)
    if not frame_stem:
        raise AtlasOptimizationError("unsupported/unknown atlas consumer")
    frame_path = f"{root}/{frame_stem}.frame.amf3.deflate"
    timeline_path = f"{root}/{frame_stem}.timeline.amf3.deflate"
    if frame_path not in files or timeline_path not in files:
        raise AtlasOptimizationError("missing pixelart frame/timeline")
    frame = _amf(files[frame_path])
    expected = f"{logical_root}/{frame_stem}"
    if not isinstance(frame, dict) or frame.get("name") != expected:
        raise AtlasOptimizationError("unexpected pixelart frame name")
    for key in ("x", "y", "scale"):
        if isinstance(frame.get(key), bool) or not isinstance(frame.get(key), (int, float)) or not math.isfinite(frame[key]):
            raise AtlasOptimizationError("invalid pixelart frame transform")
    endpoints = []
    for record in records:
        match = re.fullmatch(re.escape(expected) + r"([0-9]{4})", record["n"])
        if not match:
            raise AtlasOptimizationError("unknown pixelart logical frame selection")
        endpoints.append(int(match[1]))
    if endpoints != sorted(set(endpoints)) or endpoints[0] < 1:
        raise AtlasOptimizationError("ambiguous pixelart endpoint order")
    if endpoints[-1] > options["max_ticks"]:
        raise AtlasOptimizationError("tick budget exceeded")
    timeline = _timeline(files[timeline_path], endpoints[-1], options)
    digest = hashlib.sha256()
    cell_signatures = {name: _sha(_canonical(cell)) for name, cell in cells.items()}
    frame_signature = _sha(_canonical(frame))
    for tick in range(1, endpoints[-1] + 1):
        index = bisect.bisect_left(endpoints, tick)
        digest.update(_canonical([tick, cell_signatures[records[index]["n"]], frame_signature]))
    return {"kind": "pixelart", "signature": digest.hexdigest(), "ticks": endpoints[-1], "groups": 1,
            "leafCommands": endpoints[-1], "peakLeafCommands": 1, "expandedStates": endpoints[-1],
            "framePath": frame_path, "timelinePath": timeline_path, "timelineSHA256": _sha(files[timeline_path]),
            "timelineEventsSHA256": _sha(_canonical(timeline))}


def _check_external_consumers(files, root, names, budget):
    for path, raw in files.items():
        if str(PurePosixPath(path).parent) == root or not path.endswith((".parts.amf3.deflate", ".frame.amf3.deflate")):
            continue
        # Predecoded once per invocation, including malformed files. Unknown reference
        # semantics cannot silently certify an otherwise eligible atlas.
        if path not in budget["consumers"]:
            budget["consumers"][path] = _amf(raw)
        value = budget["consumers"][path]
        if path.endswith(".parts.amf3.deflate"):
            refs = [v.get("p") for v in value.get("i", []) if isinstance(v, dict)] if isinstance(value, dict) else []
            if any(n in names for n in refs):
                raise AtlasOptimizationError("external parts consumer outside bundle")
        elif isinstance(value, dict) and isinstance(value.get("name"), str) and any(n.startswith(value["name"]) for n in names):
            raise AtlasOptimizationError("external frame consumer outside bundle")


def _optimize_bundle(files, png_path, atlas_path, options, budget):
    root = str(PurePosixPath(png_path).parent)
    receipt = {"png": png_path, "atlas": atlas_path, "collection": "unknown", "layer": "unknown",
               "scope": root, "status": "skipped", "gameReady": False, "accepted": False,
               "checks": {"serializedRGBA": False, "metadata": False, "tickCommands": False,
                          "nonAtlasBytesUnchanged": True, "dimensionsNonWorsening": False, "paddedAreaNonWorsening": False}}
    try:
        if png_path not in files:
            raise AtlasOptimizationError("missing paired PNG")
        logical_root = _logical_root(root)
        receipt.update(scope=logical_root, fileRoot=root)
        image = _image(files[png_path], options["max_pixels"])
        records = _amf(files[atlas_path], require_reencodable=True)
        regions = _validate_atlas(image, records, options, logical_root)
        before = _metrics(image, records, regions, files[png_path], files[atlas_path])
        receipt["before"] = receipt["after"] = before
        for key, value in (("pixels", image.width * image.height), ("rects", len(records))):
            budget[key] += value
            if budget[key] > options["max_" + key]:
                raise AtlasOptimizationError(key + " invocation budget exceeded")
        cells = _cells(image, records)
        _check_external_consumers(files, root, cells, budget)
        replay = _replay(files, png_path, records, cells, options)
        receipt["replay"] = replay
        for key, value in (("ticks", replay["ticks"]), ("commands", replay["expandedStates"])):
            budget[key] += value
            if budget[key] > options["max_" + key]:
                raise AtlasOptimizationError(key + " invocation budget exceeded")
        minimum = max(r.w + 2 for r in regions)
        area = sum((r.w + 2) * (r.h + 2) for r in regions)
        widths = sorted({image.width, minimum, min(image.width, max(minimum, math.ceil(math.sqrt(area))))}
                        | {max(minimum, image.width // divisor) for divisor in (2, 3, 4, 8)})
        candidates = []
        for width in widths:
            if width > image.width:
                continue
            for mode in ("height", "area"):
                if budget["packingWorkLimited"]:
                    break
                result = _pack(regions, width, image.height, mode, budget)
                if result:
                    placements, size = result
                    padded = (size[0] + 2) * (size[1] + 2)
                    if size[0] <= image.width and size[1] <= image.height and padded < before["paddedArea"]:
                        candidates.append(((padded, size[0] * size[1], size[0], size[1], mode), placements, size))
        if not candidates:
            receipt["reason"] = "no dimension/area improving whole-rectangle candidate"
            if budget["packingWorkLimited"]:
                receipt["reason"] += "; bounded packing work exhausted"
            return {}, receipt
        _score, placements, size = min(candidates, key=lambda v: v[0])
        output = Image.new("RGBA", size)
        for source, target in placements.items():
            output.paste(image.crop((source.x, source.y, source.x + source.w, source.y + source.h)), (target.x, target.y))
        updated = copy.deepcopy(records)
        for record in updated:
            target = placements[_rect(record)]
            record.update(x=target.x, y=target.y)
        png_raw, atlas_raw = _png_bytes(output, files[png_path][:8]), _amf_bytes(updated)
        decoded_image, decoded_records = _image(png_raw, options["max_pixels"]), _amf(atlas_raw)
        after_regions = _validate_atlas(decoded_image, decoded_records, options, logical_root)
        decoded_cells = _cells(decoded_image, decoded_records)
        if len(records) != len(decoded_records) or list(cells) != list(decoded_cells) or _canonical(cells) != _canonical(decoded_cells):
            raise AtlasOptimizationError("serialized RGBA/metadata equivalence failed")
        replacement = {png_path: png_raw, atlas_path: atlas_raw}
        candidate_files = dict(files, **replacement)
        after_replay = _replay(candidate_files, png_path, decoded_records, decoded_cells, options)
        if replay != after_replay:
            raise AtlasOptimizationError("serialized per-tick command equivalence failed")
        after = _metrics(decoded_image, decoded_records, after_regions, png_raw, atlas_raw)
        if after["width"] > before["width"] or after["height"] > before["height"] or after["paddedArea"] > before["paddedArea"]:
            raise AtlasOptimizationError("candidate dimension/padded-area regression")
        receipt.update(status="optimized", accepted=True, reason="serialized whole-rectangle equivalence passed", after=after,
                       savedPaddedArea=before["paddedArea"] - after["paddedArea"],
                       originalSHA256={png_path: _sha(files[png_path]), atlas_path: _sha(files[atlas_path])},
                       optimizedSHA256={png_path: _sha(png_raw), atlas_path: _sha(atlas_raw)})
        receipt["equivalence"] = {"beforeCellsSHA256": _sha(_canonical(cells)),
                                  "afterCellsSHA256": _sha(_canonical(decoded_cells)),
                                  "beforeCommandsSHA256": replay["signature"],
                                  "afterCommandsSHA256": after_replay["signature"],
                                  "rgbaIncludesHiddenRGB": True,
                                  "metadataExceptXYUnchanged": True,
                                  "preservedConsumerSHA256": {path: _sha(files[path]) for key in ("partsPath", "framePath", "timelinePath") if (path := replay.get(key))}}
        receipt["checks"] = {key: True for key in receipt["checks"]}
        return replacement, receipt
    except (ValueError, TypeError, KeyError, IndexError, RecursionError, zlib.error, OSError, ArithmeticError) as error:
        receipt["reason"] = str(error) or type(error).__name__
        receipt["status"] = "skipped"
        return {}, receipt


def optimize_files(files, options=None):
    """Optimize independent bundles; unsupported/invalid bundles remain exact bytes.

    None explicitly runs default budgets. A configuration object follows enabled
    (default false). All budgets apply to an invocation; an exhausted bundle is
    skipped. Unrelated files, including reports/audio/DSL, are never rewritten.
    """
    options = validate_options({"enabled": True} if options is None else options)
    if not isinstance(files, dict) or len(files) > MAX_FILES:
        raise AtlasOptimizationError("files must be a bounded path->bytes dictionary")
    for path, value in files.items():
        if not isinstance(path, str) or not path or "\\" in path or ":" in path or PurePosixPath(path).is_absolute() or ".." in PurePosixPath(path).parts or not isinstance(value, bytes):
            raise AtlasOptimizationError("files require safe relative paths and immutable bytes")
    output = dict(files)
    report = {"version": 1, "enabled": options["enabled"], "mode": "whole-rectangle-lossless",
              "gameReady": False, "nativeAccepted": False, "options": options, "bundles": [],
              "basis": "offline serialized RGBA, unchanged metadata and per-tick commands; collection/layer unknown",
              "nonAtlasBytesUnchanged": True}
    if not options["enabled"]:
        report.update(status="disabled", optimizedBundles=0, skippedBundles=0, savedPaddedArea=0)
        return output, report
    budget = {"pixels": 0, "rects": 0, "ticks": 0, "commands": 0, "packingWork": 0,
              "packingWorkLimited": False, "consumers": {}}
    changed = set()
    for atlas_path in sorted(path for path in files if path.endswith(ATLAS_SUFFIX)):
        png_path = atlas_path[:-len(ATLAS_SUFFIX)] + ".png"
        replacement, receipt = _optimize_bundle(files, png_path, atlas_path, options, budget)
        report["bundles"].append(receipt)
        output.update(replacement)
        changed.update(replacement)
    # Receipt for other atlas encodings: they never become invisible successes.
    for path in sorted(p for p in files if p.endswith(".atlas.json")):
        report["bundles"].append({"atlas": path, "status": "skipped", "accepted": False,
                                   "reason": "unsupported JSON/UI atlas; preserved bytes", "gameReady": False})
    if any(output[path] != raw for path, raw in files.items() if path not in changed):
        raise AtlasOptimizationError("unexpected non-atlas mutation")
    report.update(status="complete", optimizedBundles=sum(v["accepted"] for v in report["bundles"]),
                  skippedBundles=sum(not v["accepted"] for v in report["bundles"]),
                  savedPaddedArea=sum(v.get("savedPaddedArea", 0) for v in report["bundles"]),
                  budgetUsed={k: v for k, v in budget.items() if k != "consumers"},
                  changedPaths=sorted(changed), preservedFileCount=len(files) - len(changed))
    return output, report
