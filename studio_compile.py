"""Compile authoring frames; read back every stored asset before offering export."""
from __future__ import annotations

import copy
import base64
import bisect
import hashlib
import io
import json
import math
import re
import zlib
from PIL import Image, ImageChops, ImageDraw, ImageOps

from bridge import AMF3Reader, flatomo
from asset_rules import PIXEL_EDGE, EFFECT_EDGE
from audio_compile import effect_audio, encoded_sound, sound_path, mp3_decode
from character_contract import export_contract
from studio_core import (StudioError, UI_SLOTS, PNG, FAKE_PNG, amf_bytes, image_from,
                         json_bytes, png_bytes, make_zip, project_checks, validate, atlas_crop, native_commands,
                         clip_variant, declaration_payload, author_readme,
                         BASE_STATE_SLOTS)

# 官方/donor 键集（deepcopy 模板 + 编译期断言）。来源：
# character/ekaki_girl/pixelart/{pixelart.timeline,pixelart.frame,sprite_sheet.atlas}
# 与既有 MOD cnmod_inaho_midautumn；effect timeline/parts 与官方 skill_unique 同构。
PIXELART_TIMELINE_TEMPLATE = {"sequences": [], "sounds": [], "points": [], "circles": []}
EFFECT_TIMELINE_TEMPLATE = {"sequences": [], "sounds": [], "points": [], "circles": [],
                            "rectangles": [], "matrices": []}
PIXELART_ATLAS_RECORD_TEMPLATE = {"n": "", "w": 0, "h": 0, "x": 0, "y": 0,
                                  "fx": 0, "fy": 0, "fw": 256, "fh": 256}
PIXELART_FRAME_TEMPLATE = {"name": "", "x": -128, "y": -128, "scale": 6, "smoothing": False}
EFFECT_PARTS_TEMPLATE = {"i": [], "g": [], "m": [], "a": [], "o": [], "t": [], "c": [], "s": 1}


def _assert_key_contract(tree, template, label):
    """编译期键集对齐：产物键集必须与官方模板完全一致（缺键/多键都失败）。"""
    if not isinstance(tree, dict):
        raise StudioError(f"{label} 必须是对象（结构契约）")
    missing = sorted(set(template) - set(tree))
    extra = sorted(set(tree) - set(template))
    if missing or extra:
        raise StudioError(
            f"{label} 键集与官方模板不一致：缺键 {missing}，多键 {extra}"
            "（2026-10-06 F1009：timeline 缺 sounds 会让客户端 loadDynamicSoundEffect 抛 #1009）"
        )
    return tree


def pixelart_timeline(sequences):
    """官方模板 deepcopy：保证 sequences/sounds/points/circles 四键永不缺。"""
    timeline = copy.deepcopy(PIXELART_TIMELINE_TEMPLATE)
    timeline["sequences"] = list(sequences)
    return _assert_key_contract(timeline, PIXELART_TIMELINE_TEMPLATE, "pixelart.timeline")


def effect_timeline(sequences, sounds):
    timeline = copy.deepcopy(EFFECT_TIMELINE_TEMPLATE)
    timeline["sequences"] = list(sequences)
    timeline["sounds"] = list(sounds)
    return _assert_key_contract(timeline, EFFECT_TIMELINE_TEMPLATE, "effect.timeline")


def crop_portrait(store, p, form, slot):
    from portrait_editor import render
    return image_from(render(store, p, form, slot))


def transformed_cell(store, p, clip, aid=None):
    cell = image_from(store.asset_bytes(p, aid or clip["asset"]))
    if clip.get("flip"):
        cell = ImageOps.mirror(cell)
    scale = float(clip.get("scale", 1))
    if cell.width * cell.height * scale * scale > 32_000_000 or max(cell.size) * scale > 8192:
        raise StudioError("画稿缩放后过大，请降低画稿缩放值")
    if scale != 1:
        cell = cell.resize((max(1, round(cell.width * scale)), max(1, round(cell.height * scale))), Image.Resampling.NEAREST)
    angle = float(clip.get("rotation", 0))
    # Rotate around the cell centre and preserve the unrotated top-left position.
    before = cell.size
    if angle:
        cell = cell.rotate(-angle, Image.Resampling.NEAREST, expand=True)
    if clip.get("opacity", 1) != 1:
        opacity = float(clip["opacity"])
        cell.putalpha(cell.getchannel("A").point(lambda value: round(value * opacity)))
    x = round(clip.get("x", 0) - (cell.width - before[0]) / 2)
    y = round(clip.get("y", 0) - (cell.height - before[1]) / 2)
    return cell, x, y


# Filename pairs are useful review evidence, not authority to switch artwork.
# Keep the exact offset utility for explicit repair tooling and regression tests.
def detect_frame_offset(plain, composite, max_candidates=65536):
    """纯本体帧在合成帧内的唯一精确偏移；返回 (offset, matches)。

    matches=0 表示不是"同帧纯本体"（不强行替换）；matches>1 表示不唯一
    （例如纯本体全透明），调用方对基础状态按 fail-closed 处理。
    """
    if plain.width > composite.width or plain.height > composite.height:
        return None, 0
    candidates = (composite.width - plain.width + 1) * (composite.height - plain.height + 1)
    if candidates <= 0 or candidates > max_candidates:
        return None, -1
    matches = []
    for dy in range(composite.height - plain.height + 1):
        for dx in range(composite.width - plain.width + 1):
            window = composite.crop((dx, dy, dx + plain.width, dy + plain.height))
            # 注意：RGBA 的 getbbox() 只看 alpha，两图 alpha 相同时会误判相等；
            # getextrema 逐通道返回 (lo,hi)，全 0 才是真正逐像素相等。
            extrema = ImageChops.difference(window, plain).getextrema()
            if all(low == 0 and high == 0 for low, high in extrema):
                matches.append((dx, dy))
                if len(matches) > 1:
                    return None, len(matches)
    return (matches[0] if matches else None), len(matches)


def plan_pixel_frames(store, p, animations, variant):
    """Keep the artist-selected frames; never infer a replacement from a filename pair.

    Filenames are evidence for review, not permission to add/remove a companion.
    This guard also protects single-animation previews which bypass compile_project.
    The empty swap mapping is retained for the atlas compiler's existing interface.
    """
    report = {"variant": variant, "slots": [], "kept": [], "swaps": [], "issues": [],
              "problems": []}
    for anim in animations:
        if anim.get("variant", "normal") != variant or not anim.get("clips"):
            continue
        slot = anim.get("slot", "")
        companion = anim.get("includesCompanion", "")
        note = anim.get("companionNote", "")
        note = note.strip() if isinstance(note, str) else ""
        row = {"slot": slot, "name": anim.get("name"), "clips": len(anim["clips"]),
               "keep_summon": False, "swapped": 0, "problems": []}
        for index, clip in enumerate(anim["clips"]):
            if clip_variant(p, clip.get("asset")) != "composite":
                continue
            label = f"{anim.get('name') or slot}（{slot}）第 {index + 1} 段"
            if companion is False:
                row["problems"].append(
                    label + "使用合成帧，但声明为不包含附属物；请替换为纯本体帧，"
                    "或确认包含附属物并填写出现时机。")
            elif slot in BASE_STATE_SLOTS and (companion is not True or not note):
                row["problems"].append(
                    label + "是基础状态合成帧，尚未确认附属物及出现时机；"
                    "请在动作说明中确认，或手动选择纯本体帧。")
            else:
                row["keep_summon"] = True
                report["kept"].append({"slot": slot, "clip": index})
        report["slots"].append(row)
        report["problems"].extend(row["problems"])
    if report["problems"]:
        raise StudioError("素材来源与动作声明不一致：\n- " + "\n- ".join(report["problems"]))
    return {}, report


def compile_pixelart_with_report(store, p, animations, variant, code, frame_plan=None):
    animations = [a for a in animations if a.get("variant", "normal") == variant and a.get("clips")]
    if not animations:
        return {}, [], {"variant": variant, "slots": [], "swaps": [], "kept": [],
                        "issues": [], "problems": []}
    if frame_plan is None:
        frame_plan, plan_report = plan_pixel_frames(store, p, animations, variant)
    else:
        plan_report = {"variant": variant, "slots": [], "swaps": [], "kept": [],
                       "issues": [], "problems": []}
    names = [a["slot"] for a in animations]
    if len(set(names)) != len(names) or any(not re.fullmatch(r"[A-Za-z0-9_]+", n) for n in names):
        raise StudioError("同组动作槽位不能重复，槽位只能使用英文、数字和下划线")
    root = f"character/{code}/pixelart"
    stem = "pixelart" if variant == "normal" else "special"
    sheet_stem = "sprite_sheet" if variant == "normal" else "special_sprite_sheet"
    cells, atlas, sequences = [], [], []
    rects = {}
    cursor_x, cursor_y, row_h, tick = 1, 1, 0, 1
    for anim in animations:
        if anim.get("fps", 60) != 60:
            raise StudioError("游戏动画编译使用 60 帧时间基准，请调整停留帧数")
        begin = tick
        for index, clip in enumerate(anim["clips"]):
            decision = frame_plan.get((anim["id"], index))
            if decision is not None:
                asset_id, dx, dy = decision
                cell, x, y = transformed_cell(
                    store, p, dict(clip, x=clip.get("x", 0) + dx,
                                   y=clip.get("y", 0) + dy),
                    aid=asset_id,
                )
            else:
                cell, x, y = transformed_cell(store, p, clip)
            if cell.width > PIXEL_EDGE or cell.height > PIXEL_EDGE or abs(x) > 1024 or abs(y) > 1024:
                raise StudioError("像素画稿尺寸或位置过大")
            digest = hashlib.sha256(png_bytes(cell)).hexdigest()
            if digest not in rects:
                if cursor_x + cell.width + 1 > 1024:
                    cursor_y += row_h + 2
                    cursor_x, row_h = 1, 0
                rects[digest] = (cursor_x, cursor_y, cell.width, cell.height)
                cells.append((cell, cursor_x, cursor_y))
                cursor_x += cell.width + 2
                row_h = max(row_h, cell.height)
            rx, ry, rw, rh = rects[digest]
            end_tick = tick + clip["hold"] - 1
            atlas.append({"n": f"{root}/{stem}{end_tick:04}", "w": rw, "h": rh, "x": rx, "y": ry,
                          "fx": -x - 128, "fy": -y - 128, "fw": 256, "fh": 256})
            tick += clip["hold"]
        sequences.append({"name": anim["slot"], "kind": anim["kind"], "begin": begin, "end": tick - 1})
    if tick > 10000:
        raise StudioError("同组动作超过四位帧编号的范围，请缩短时长或拆分普通/特殊动作组")
    height = cursor_y + row_h + 1
    if height > 4096:
        raise StudioError("像素图集高度超过 4096，请减少画稿尺寸或拆分动作")
    sheet = Image.new("RGBA", (1024, height))
    for cell, x, y in cells:
        sheet.paste(cell, (x, y))
    scales = {a.get("frameScale", 6) for a in animations}
    if len(scales) != 1:
        raise StudioError("同组动作的游戏显示倍率需一致")
    frame = {"name": f"{root}/{stem}", "x": -128, "y": -128, "scale": scales.pop(), "smoothing": False}
    # Official character pixelart timelines carry the key set
    # sequences/sounds/points/circles. The client coerces a missing `sounds`
    # member to null and AssetPathCollectionBuilder/loadDynamicSoundEffect
    # dereferences sounds.length (TypeError #1009), so `sounds` must always be
    # written; circles/points are safe as explicit empty anchor arrays because
    # PlayheadTimeline treats null and empty identically for them.
    # 官方模板 deepcopy + 键集断言：sequences/sounds/points/circles 四键永不缺
    # （客户端 loadDynamicSoundEffect 无判空，缺 sounds 抛 TypeError #1009）。
    timeline = pixelart_timeline(sequences)
    files = {f"{root}/{sheet_stem}.png": FAKE_PNG + png_bytes(sheet)[8:],
             f"{root}/{sheet_stem}.atlas.amf3.deflate": amf_bytes(atlas),
             f"{root}/{stem}.frame.amf3.deflate": amf_bytes(frame),
             f"{root}/{stem}.timeline.amf3.deflate": amf_bytes(timeline)}
    for record in atlas:
        if set(record) != set(PIXELART_ATLAS_RECORD_TEMPLATE):
            raise StudioError("图集记录键集与官方模板不一致（结构契约）")
    if set(frame) != set(PIXELART_FRAME_TEMPLATE):
        raise StudioError("frame 键集与官方模板不一致（结构契约）")
    # Read the exact encoded arrays and stored sheet, then prove original cells remain equal.
    read_atlas = AMF3Reader(zlib.decompress(files[f"{root}/{sheet_stem}.atlas.amf3.deflate"], -15)).read_value()
    read_sheet = image_from(files[f"{root}/{sheet_stem}.png"])
    for record in read_atlas:
        extracted = read_sheet.crop((record["x"], record["y"], record["x"] + record["w"], record["y"] + record["h"]))
        if hashlib.sha256(png_bytes(extracted)).hexdigest() not in rects:
            raise StudioError("编译回读的画稿不一致")
    return files, sequences, plan_report


def compile_pixelart(store, p, animations, variant, code, frame_plan=None):
    files, sequences, _report = compile_pixelart_with_report(
        store, p, animations, variant, code, frame_plan=frame_plan,
    )
    return files, sequences


def compile_effect(store, p, effect, code):
    if effect.get("native"):
        return compile_native_effect(store, p, effect, code)
    if not effect.get("clips"):
        return {}, "没有特效画稿"
    root = f"battle/effect/skill_unique/{code}/{effect['id']}"
    images, atlas, cells, segments = [], [], [], []
    x, y, row_h, tick = 1, 1, 0, 0
    matrices = [{"a": 4096, "b": 0, "c": 0, "d": 4096, "x": 0, "y": 0}]
    for index, clip in enumerate(effect["clips"]):
        cell, left, top = transformed_cell(store, p, clip)
        if cell.width > EFFECT_EDGE or cell.height > EFFECT_EDGE:
            raise StudioError("特效单图过大")
        if x + cell.width + 1 > 2048:
            x, y, row_h = 1, y + row_h + 2, 0
        path = f"{root}/.gen/effect/{index}"
        images.append({"s": False, "p": path})
        atlas.append({"n": path, "x": x, "y": y, "w": cell.width, "h": cell.height})
        cells.append((cell, x, y))
        matrices.append({"a": 4096, "b": 0, "c": 0, "d": 4096, "x": left * 4096, "y": top * 4096})
        segments.append({"s": tick, "i": index, "l": [{"m": ((index + 1) << 12) | 255, "t": clip["hold"]}]})
        tick += clip["hold"]
        x += cell.width + 2
        row_h = max(row_h, cell.height)
    height = y + row_h + 1
    if height > 4096:
        raise StudioError("特效图集超过 4096 像素高")
    sheet = Image.new("RGBA", (2048, height))
    for cell, px, py in cells:
        sheet.paste(cell, (px, py))
    parts = {"i": images, "g": [{"t": tick, "s": segments}], "m": [], "a": [1] * len(images), "o": [], "t": matrices, "c": [], "s": effect.get("frameScale", 1)}
    sounds, audio_files, audio_issues = effect_audio(store, p, effect, code)
    timeline = effect_timeline(
        [{"begin": 1, "end": tick, "name": "neutral", "kind": effect["kind"]}], sounds,
    )
    return {**audio_files, f"{root}/{effect['id']}.png": FAKE_PNG + png_bytes(sheet)[8:], f"{root}/{effect['id']}.atlas.amf3.deflate": amf_bytes(atlas), f"{root}/effect.parts.amf3.deflate": amf_bytes(parts), f"{root}/effect.timeline.amf3.deflate": amf_bytes(timeline)}, "；".join(audio_issues) or None


def compile_native_effect(store, p, effect, code):
    """Keep native interpolation/hierarchy; replace only atlas cells and their origins."""
    from effect_channels import edited,compile_channels
    if edited(effect):return compile_channels(store,p,effect,code)
    path = effect["native"]["path"]
    folder = path.split("/")[1]
    reference_root = (store.directory(p["id"]) / "reference").resolve()
    def read(name):
        if name not in p.get("referenceFiles", []):
            raise StudioError("缺少特效来源文件")
        target = (reference_root / name).resolve()
        if not target.is_relative_to(reference_root):
            raise StudioError("参考素材路径无效")
        return target.read_bytes()
    parts = json.loads(read(path))
    if parts.get("m"):
        return {}, "MovieClip 特效结构尚未支持编译"
    timeline = json.loads(read(path.replace(".parts.json", ".timeline.json")))
    sequence = next(s for s in timeline["sequences"] if s["name"] == effect["native"]["sequence"])
    audio_files, audio_issues = {}, []
    if "soundEvents" in effect:
        sounds, audio_files, audio_issues = effect_audio(store, p, effect, code, sequence["begin"])
        timeline["sounds"] = sounds
        timeline["sequences"] = [sequence]
    missing = sorted(set(EFFECT_TIMELINE_TEMPLATE) - set(timeline))
    if missing:
        raise StudioError(f"原生特效 timeline 缺官方键 {missing}（结构契约）")
    records = json.loads(read(f"effect/{folder}/{folder}.atlas.json"))
    original_sheet = image_from(read(f"effect/{folder}/{folder}.png"))
    root = f"battle/effect/skill_unique/{code}/{effect['id']}"
    cells, atlas, mapping = [], [], {}
    x, y, row_h = 1, 1, 0
    for index, original in enumerate(records):
        cell = atlas_crop(original_sheet, original)
        aid = hashlib.sha256(png_bytes(cell)).hexdigest()[:24] + "_png"
        layer = effect.get("layers", {}).get(aid, {})
        if layer.get("asset"):
            cell = image_from(store.asset_bytes(p, layer["asset"]))
        if layer.get("visible") is False:
            cell = Image.new("RGBA", cell.size)
        if cell.width > EFFECT_EDGE or cell.height > EFFECT_EDGE:
            raise StudioError("特效图层超过单图尺寸上限")
        if x + cell.width + 1 > 2048:
            x, y, row_h = 1, y + row_h + 2, 0
        name = f"{root}/.gen/layer/{index}"
        mapping[original["n"]] = name
        record = {k: v for k, v in original.items() if k not in ("r", "n", "x", "y", "w", "h")}
        record.update(n=name, x=x, y=y, w=cell.width, h=cell.height,
                      fx=original.get("fx", 0) - layer.get("x", 0), fy=original.get("fy", 0) - layer.get("y", 0))
        atlas.append(record)
        cells.append((cell, x, y))
        x += cell.width + 2
        row_h = max(row_h, cell.height)
    height = y + row_h + 1
    if height > 8192:
        raise StudioError("模板特效图集过大，请拆分或缩小替换贴图")
    sheet = Image.new("RGBA", (2048, height))
    for cell, px, py in cells:
        sheet.paste(cell, (px, py))
    for item in parts["i"]:
        item["p"] = mapping[item["p"]]
    parts["s"] = effect.get("frameScale", parts.get("s", 1))
    return {**audio_files, f"{root}/{effect['id']}.png": FAKE_PNG + png_bytes(sheet)[8:],
            f"{root}/{effect['id']}.atlas.amf3.deflate": amf_bytes(atlas),
            f"{root}/effect.parts.amf3.deflate": amf_bytes(parts),
            f"{root}/effect.timeline.amf3.deflate": amf_bytes(timeline)}, "；".join(audio_issues) or None


def compiled_preview(store, pid, group, animation_id):
    """The player receives only decoded compiled bytes, never the authoring clips."""
    p = store.load(pid)
    validate(p)
    if group == "scene":
        return compiled_scene_preview(store, p)
    if group not in ("animations", "effects"):
        raise StudioError("预览类型无效")
    anim = next((a for a in p[group] if a["id"] == animation_id), None)
    if not anim:
        raise StudioError("找不到要预览的动作")
    code = p["identity"].get("code", "new_character")
    if group == "animations":
        variant = anim.get("variant", "normal")
        plan, _plan_report = plan_pixel_frames(store, p, p[group], variant)
        output, _ = compile_pixelart(
            store, p, p[group], variant, code, frame_plan=plan,
        )
    else:
        output, issue = compile_effect(store, p, anim, code)
        if issue and not output:
            raise StudioError(issue)
    if not output:
        raise StudioError("请先添加画稿")
    def decoded(suffix):
        raw = next(v for k, v in output.items() if k.endswith(suffix))
        return AMF3Reader(zlib.decompress(raw, -15)).read_value()
    sheet = image_from(next(v for k, v in output.items() if k.endswith(".png")))
    atlas = decoded(".atlas.amf3.deflate")
    timeline = decoded(".timeline.amf3.deflate")
    assets, cells = {}, {}
    for index, record in enumerate(atlas):
        raw = png_bytes(atlas_crop(sheet, record))
        aid = hashlib.sha256(raw).hexdigest()[:24]
        assets[aid] = "data:image/png;base64," + base64.b64encode(raw).decode()
        cells[record["n"]] = (aid, record)
    name = anim["slot"] if group == "animations" else anim.get("native", {}).get("sequence", "neutral")
    sequence = next(s for s in timeline["sequences"] if s["name"] == name)
    frames = []
    if group == "animations":
        frame = decoded(".frame.amf3.deflate")
        keyed = {int(re.search(r"(\d+)$", path).group(1)): cell for path, cell in cells.items()}
        keys = sorted(keyed)
        for tick in range(sequence["begin"], sequence["end"] + 1):
            pos = bisect.bisect_left(keys, tick)
            if tick <= 0 or pos >= len(keys):
                pos = 0
            aid, record = keyed[keys[pos]]
            frames.append([{"asset": aid, "matrix": [1, 0, 0, 1, frame["x"], frame["y"]], "alpha": 1, "fx": record.get("fx", 0), "fy": record.get("fy", 0)}])
        scale = frame["scale"]
    else:
        parts = decoded(".parts.amf3.deflate")
        expanded = flatomo._build_frames(parts)
        frames = [native_commands(expanded, parts, cells, 0, tick) for tick in range(sequence["begin"] - 1, sequence["end"])]
        scale = parts.get("s", 1)
    audio = []
    for sound in timeline.get("sounds", []):
        raw = output.get(sound["path"] + ".mp3")
        if raw and sequence["begin"] <= sound["begin"] <= sequence["end"]:
            volume = sound.get("volume", -1)
            audio.append({"start": sound["begin"] - sequence["begin"], "volume": volume*.1 if volume != -1 else 1,
                          "loop": sound.get("loop", 1), "end": sound["end"]-sequence["begin"] if sound.get("end", -1) != -1 else -1,
                          "url": "data:audio/mpeg;base64," + base64.b64encode(mp3_decode(raw)).decode()})
    issues = list(anim.get("issues", []))
    if group == "effects" and issue:
        issues.append(issue)
    return {"name": anim["name"], "kind": sequence["kind"], "frames": frames, "scale": scale, "audio": audio,
            "runtimeSpeed": anim.get("runtimeSpeed", 1), "assets": assets, "sourceRevision": p["revision"],
            "issues": issues, "files": [{"path": k, "sha256": hashlib.sha256(v).hexdigest()} for k, v in output.items()]}


def compiled_scene_preview(store, p):
    """Compose decoded outputs with the saved handoff tracks, never source clips."""
    from audio_compile import encoded_sound, sound_path
    if not p["scene"]["tracks"]:
        raise StudioError("技能时间轴为空，请先添加动作或特效，或按官方模板生成演示")
    frames = [[] for _ in range(p["scene"]["duration"])]
    result = {"name": p["skill"].get("name") or "技能组合", "kind": "once", "frames": frames,
              "scale": 1, "runtimeSpeed": 1, "assets": {}, "audio": [], "issues": list(p["scene"].get("source", {}).get("notes", [])),
              "files": [], "sourceRevision": p["revision"]}
    cache = {}
    code = p["identity"].get("code", "new_character")
    for t in p["scene"]["tracks"]:
        if t.get("visible") is False or t["start"] >= len(frames):
            continue
        rate = t.get("speed", 1)
        until = min(len(frames), t["end"]) if t.get("end", -1) >= 0 else len(frames)
        if t["type"] == "audio":
            raw = encoded_sound(store, p, t["ref"])
            result["files"].append({"path": sound_path(code, t["ref"]) + ".mp3", "sha256": hashlib.sha256(raw).hexdigest()})
            result["audio"].append({"start": t["start"], "end": until, "rate": rate, "volume": t.get("volume", 1),
                                    "url": "data:audio/mpeg;base64," + base64.b64encode(mp3_decode(raw)).decode()})
            continue
        key = ("animations" if t["type"] == "actor" else "effects", t["ref"])
        if key not in cache:
            cache[key] = compiled_preview(store, p["id"], *key)
        a = cache[key]
        result["assets"].update(a["assets"])
        result["files"].extend(a["files"])
        result["issues"].extend(a["issues"])
        rate *= a.get("runtimeSpeed", 1)
        angle = math.radians(t.get("rotation", 0))
        scale = t.get("scale", 1) * a["scale"]
        m = (math.cos(angle)*scale, math.sin(angle)*scale, -math.sin(angle)*scale,
             math.cos(angle)*scale, t.get("x", 0), t.get("y", 0))
        mode = t.get("playMode", a["kind"])
        for tick in range(t["start"], until):
            at = t.get("freezeFrame", math.floor((tick-t["start"])*rate))
            if mode == "stop":
                at = 0
            if at >= len(a["frames"]):
                if mode == "loop":
                    at %= len(a["frames"])
                elif mode == "once":
                    at = len(a["frames"])-1
                else:
                    break
            for c in a["frames"][at]:
                frames[tick].append(dict(c, matrix=list(flatomo._concat(c["matrix"], m)), alpha=c["alpha"]*t.get("opacity", 1)))
        loops = math.ceil((until-t["start"])*rate/len(a["frames"])) if mode == "loop" else 1
        for loop in range(loops):
            for sound in a["audio"]:
                if (mode == "stop" or "freezeFrame" in t) and sound["start"] > t.get("freezeFrame", 0):
                    continue
                start = t["start"] + (sound["start"]+loop*len(a["frames"]))/rate
                if start < until:
                    end = min(until, t["start"]+(sound["end"]+loop*len(a["frames"]))/rate) if sound.get("end", -1) != -1 else until
                    result["audio"].append(dict(sound, start=start, end=end, rate=rate, volume=sound.get("volume", 1)*t.get("volume", 1)))
    result["issues"] = sorted(set(result["issues"]))
    result["files"] = list({(f["path"],f["sha256"]): f for f in result["files"]}.values())
    return result


def compile_project(store, pid):
    p = store.load(pid)
    validate(p)
    checks = project_checks(p)
    blockers = [item for item in checks["issues"] if item.get("blocking")]
    if blockers:
        raise StudioError("交付检查发现需先修正的问题（仍可保存并导出草稿工程）：\n- "
                          + "\n- ".join(item["text"] for item in blockers))
    code = p["identity"].get("code", "")
    if not re.fullmatch(r"[a-z][a-z0-9_]{1,70}", code):
        raise StudioError("请在角色资料中填写英文资源代号，以小写字母开头，仅含小写字母、数字和下划线")
    files, receipts, pending = {}, [], []
    for variant in ("normal", "special"):
        plan, plan_report = plan_pixel_frames(store, p, p["animations"], variant)
        output, sequences, _ = compile_pixelart_with_report(
            store, p, p["animations"], variant, code, frame_plan=plan,
        )
        files.update({"compiled/common/" + k: v for k, v in output.items()})
        if output:
            receipts.append({"kind": variant, "sequences": sequences, "readback": True})
            receipts.append({
                "kind": variant + "-frames",
                "clips": sum(row["clips"] for row in plan_report["slots"]),
                "swapped": len(plan_report["swaps"]),
                "kept_composite": len(plan_report["kept"]),
                "slots": plan_report["slots"],
                "swaps": plan_report["swaps"],
                "issues": plan_report["issues"],
                "readback": True,
            })
            pending.extend(plan_report["issues"])
    from portrait_editor import contract_report as ui_contract_report
    ui_contract = ui_contract_report(store, p)
    if ui_contract["problems"]:
        raise StudioError("界面契约未通过：\n- " + "\n- ".join(ui_contract["problems"]))
    receipts.append({"kind": "ui-contract", "slots": ui_contract["slots"],
                     "warnings": ui_contract["warnings"], "readback": True})
    pending.extend(ui_contract["warnings"])
    from portrait_editor import selection, render as render_ui, ui_name
    for form in ("base", "evolved"):
        emitted = []
        for slot in UI_SLOTS:
            spec = selection(p, form, slot)
            if not spec.get("asset"):
                continue
            raw = render_ui(store, p, form, slot)
            root = "medium" if slot in ("full_shot", "skill_cutin") else "common"
            path = f"character/{code}/ui/{ui_name(form, slot)}"
            files[f"compiled/{root}/{path}"] = FAKE_PNG + raw[8:]
            emitted.append({"slot": slot, "mode": spec["mode"], "asset": spec["asset"], "size": list(image_from(raw).size)})
        if emitted:
            receipts.append({"kind": "ui", "form": form, "images": emitted, "readback": True})
    for effect in p["effects"]:
        output, issue = compile_effect(store, p, effect, code)
        files.update({"compiled/common/" + k: v for k, v in output.items()})
        if issue:
            pending.append(effect["name"] + "：" + issue)
        pending.extend(effect["name"] + "：" + item for item in effect.get("issues", []))
    for voice in p.get("voices", []) + p.get("sounds", []):
        aid = voice["asset"]
        try:
            files["compiled/common/" + sound_path(code, aid) + ".mp3"] = encoded_sound(store, p, aid)
        except StudioError as error:
            pending.append(voice["name"] + "：" + str(error))
    if p.get('nativeGameplay'):
        from native_gameplay import compile_native
        draft, receipt = compile_native(p['nativeGameplay'])
        files.update(draft); receipts.append(receipt)
    for path, raw in files.items():
        if path.endswith(".png"):
            if not raw.startswith(FAKE_PNG):
                raise StudioError("PNG 存储格式不一致")
            image_from(raw)
        elif path.endswith(".amf3.deflate"):
            AMF3Reader(zlib.decompress(raw, -15)).read_value()
    from atlas_editor import ui_atlas
    packed = ui_atlas(store, p)
    if packed:
        sheet, records = packed
        files["handoff/ui-images.png"] = png_bytes(sheet)
        files["handoff/ui-images.atlas.json"] = json_bytes(records)
        receipts.append({"kind": "ui-handoff-atlas", "cells": len(records), "readback": True, "gameReady": False})
    pending.extend(["角色/技能/能力/成长/玛纳板与服务端数据接入", "UI 交接图集已可生成；游戏专用 illustration 图集、定位表与界面蒙版仍需接入校准", "Android/iOS 技能切入平台纹理", "原生技能时序、音效挂接与真机验收", "新角色 ID 与存档导入导出兼容"])
    report = {"schema": "studio-compile-report-v1", "project": p["name"], "sourceRevision": p["revision"], "gameReady": False, "receipts": receipts, "pending": pending, "files": [{"path": k, "sha256": hashlib.sha256(v).hexdigest(), "size": len(v)} for k, v in sorted(files.items())]}
    report["checks"] = checks
    report["readiness"] = checks.get("readiness", {})
    files["report.json"] = json_bytes(report)
    files["README-稿主必读.md"] = author_readme(p).encode("utf-8")
    files["声音用途与台词.json"] = json_bytes({"voices": p.get("voices", []), "sounds": p.get("sounds", []), "note": "用途与台词用于交接；主界面语音表、角色喊声槽位与剧情字幕仍需接入绑定。"})
    files["制作需求.json"] = json_bytes({"identity": p["identity"], "skill": p["skill"], "scene": p["scene"], "notes": p["notes"], "template": p["template"]})
    files["MOD角色接入契约.json"] = json_bytes(export_contract(store, p))
    files["declarations.json"] = json_bytes(declaration_payload(p))
    files["接入说明.txt"] = ("离线美术编译产物，不能直接覆盖游戏。\n已回读检查 PNG、AMF3 与像素图块。\n\n待接入项：\n" + "\n".join(pending)).encode("utf-8")
    return make_zip(files), report
