"""Validate complete image batches before mutating an artist project."""
from __future__ import annotations

import base64
import binascii
import copy
import hashlib
import json
import re
import time
from pathlib import PurePosixPath

from action_presets import ACTION_PRESETS, preset_animation
from asset_rules import FILE_BYTES, PIXEL_EDGE

MAX_FILES = 256
MAX_FRAMES = 512
MAX_BATCH_BYTES = 128 * 1024 * 1024
MAX_BATCH_PIXELS = 32_000_000


def natural_key(name):
    return tuple((1, int(part)) if part.isdecimal() else (0, part.casefold())
                 for part in re.split(r"(\d+)", name))


def sheet_rectangles(size, settings):
    from studio_core import StudioError, integer
    width = integer(settings.get("width"), 1, PIXEL_EDGE, "单格宽度")
    height = integer(settings.get("height"), 1, PIXEL_EDGE, "单格高度")
    mx = integer(settings.get("marginX", 0), 0, size[0], "左侧留白")
    my = integer(settings.get("marginY", 0), 0, size[1], "顶部留白")
    gx = integer(settings.get("gapX", 0), 0, 4096, "横向间隔")
    gy = integer(settings.get("gapY", 0), 0, 4096, "纵向间隔")
    columns = max(0, (size[0] - mx + gx) // (width + gx))
    rows = max(0, (size[1] - my + gy) // (height + gy))
    if not columns or not rows:
        raise StudioError("精灵图放不下一个完整网格，请检查单格尺寸和留白")
    if columns * rows > 10000:
        raise StudioError("网格超过 10000 格，请增大单格尺寸")
    order = settings.get("order", "row")
    if order not in ("row", "column"):
        raise StudioError("切片顺序必须为横向或纵向")
    start = integer(settings.get("start", 0), 0, columns * rows - 1, "起始格")
    count = integer(settings.get("count", 0), 0, MAX_FRAMES, "切片数量")
    indices = [(r, c) for r in range(rows) for c in range(columns)] if order == "row" else [(r, c) for c in range(columns) for r in range(rows)]
    chosen = indices[start:start + count] if count else indices[start:]
    if count and len(chosen) != count:
        raise StudioError("精灵图剩余网格不足所选切片数量")
    if len(chosen) > MAX_FRAMES:
        raise StudioError(f"一次最多切分 {MAX_FRAMES} 格，请限制切片数量")
    return [(mx + c * (width + gx), my + r * (height + gy), width, height) for r, c in chosen]


def add_presets(store, pid, revision, slots=None):
    from studio_core import StudioError
    with store.lock:
        p = store.load(pid)
        if p["revision"] != revision:
            raise StudioError("工程已更新，请刷新后再补充动作槽位")
        wanted = [s["slot"] for s in ACTION_PRESETS if s["default"]] if slots is None else slots
        if not isinstance(wanted, list) or not all(isinstance(s, str) for s in wanted):
            raise StudioError("动作槽位清单无效")
        known = {s["slot"]: s for s in ACTION_PRESETS}
        if any(s not in known for s in wanted):
            raise StudioError("未知的常用动作槽位")
        occupied = {(a.get("variant", "normal"), a.get("slot")) for a in p["animations"]}
        ids = []
        for slot in dict.fromkeys(wanted):
            preset = known[slot]
            key = (preset["variant"], slot)
            if key not in occupied:
                a = preset_animation(preset)
                p["animations"].append(a)
                occupied.add(key)
                ids.append(a["id"])
        if ids:
            p = store.save(p)
        return {"project": p, "ids": ids}


# Source identity is deliberately independent of payload bytes and leaf names.
# Keep this grammar in sync with pixelSourceInfo in web/pixel-import.js.
COMPOSITE_MARKERS = {"sp", "summon", "fx", "eff", "glow", "composite", "合成", "合成帧", "附属物"}
PLAIN_MARKERS = {"plain", "本体", "纯本体", "纯本体帧"}
NATIVE_DIRECTORIES = {"native", "native_effect", "native_effects", "原生特效"}
SOURCE_FILTERS = {"all", "plain", "composite", "unknown"}


def _source_stem(value):
    stem, sequence, composite = value.casefold(), "", False
    while True:
        marker = re.search(r"_(sp|summon|fx|eff|glow)$", stem)
        if marker:
            composite = True
            stem = stem[:marker.start()]
            continue
        number = re.search(r"[\s_-]*(\d+)$", stem) if not sequence else None
        if number:
            sequence = str(int(number.group(1)))
            stem = stem[:number.start()]
            continue
        return stem, sequence, composite


def source_identity(name):
    """Infer naming evidence; never classify an arbitrary unmarked PNG as plain."""
    from studio_core import StudioError
    if not isinstance(name, str) or not name or len(name) > 1024 or any(ord(c) < 32 for c in name):
        raise StudioError("图片文件名无效")
    path = PurePosixPath(name.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts or ":" in name or path.suffix.lower() != ".png":
        raise StudioError("请使用安全路径下的静态 PNG 图片")
    aliases = {alias.casefold(): p["slot"] for p in ACTION_PRESETS for alias in (p["slot"], *p["aliases"])}
    parents, actions, explicit_plain, composite = [], [], False, False
    for part in path.parts[:-1]:
        folded = part.casefold()
        if folded in NATIVE_DIRECTORIES:
            raise StudioError("原生特效请使用特效工作台，不要混入像素动作图片")
        if folded in COMPOSITE_MARKERS:
            composite = True
            continue
        if folded in PLAIN_MARKERS:
            explicit_plain = True
            continue
        # Folder numbers distinguish different source batches; do not strip them.
        folder = folded
        while re.search(r"_(sp|summon|fx|eff|glow)$", folder):
            composite = True
            folder = re.sub(r"_(sp|summon|fx|eff|glow)$", "", folder)
        slot = aliases.get(folder)
        if slot:
            actions.append(slot)
        parents.append(slot or folder)
    stem, sequence, leaf_composite = _source_stem(path.stem)
    action = actions[-1] if actions else aliases.get(stem, "")
    composite = composite or leaf_composite
    variant = "composite" if composite else "plain" if action or explicit_plain else "unknown"
    canonical_stem = aliases.get(stem, stem)
    return {"sourceName": path.as_posix(), "variant": variant, "action": action,
            "stem": canonical_stem, "sequence": sequence,
            "pairKey": json.dumps([parents, canonical_stem, sequence], ensure_ascii=False, separators=(",", ":")),
            "groupKey": json.dumps([parents, canonical_stem, variant], ensure_ascii=False, separators=(",", ":"))}


def import_images(store, pid, request):
    from studio_core import StudioError, integer, image_from, png_bytes, validate, BASE_STATE_SLOTS
    from project_storage import safe_child, write_bytes
    with store.lock:
        old = store.load(pid)
        if request.get("revision") != old["revision"]:
            raise StudioError("工程已更新，请重新打开导入窗口")
        p = copy.deepcopy(old)
        files = request.get("files")
        if not isinstance(files, list) or not 1 <= len(files) <= MAX_FILES or not all(isinstance(item, dict) for item in files):
            raise StudioError(f"一次请选择 1 至 {MAX_FILES} 张 PNG")
        source_filter = request.get("filter", "all")
        if not isinstance(source_filter, str) or source_filter not in SOURCE_FILTERS:
            raise StudioError("图片来源筛选无效")
        confirmations = request.get("companionConfirmations", {})
        if not isinstance(confirmations, dict) or any(not isinstance(k, str) or not isinstance(v, str) or not v.strip() or len(v) > 2000 for k, v in confirmations.items()):
            raise StudioError("请逐个确认基础状态的附属物，并填写出现时机")
        hold = integer(request.get("hold", 6), 1, 4096, "每张画稿停留帧数")
        mode, alignment = request.get("mode", "append"), request.get("alignment", "feet")
        if mode not in ("append", "replace") or alignment not in ("feet", "center"):
            raise StudioError("导入方式或对齐方式无效")
        pending, names, total_bytes, pixels, new_targets, excluded = [], set(), 0, 0, {}, 0
        targets = {a["id"]: a for a in p["animations"]}
        known = {s["slot"]: s for s in ACTION_PRESETS}
        reviewed = [(item, source_identity(item.get("path") or item.get("name"))) for item in files]
        composite_keys = {info["pairKey"] for _, info in reviewed if info["variant"] == "composite"}
        for _, info in reviewed:
            if info["variant"] == "unknown" and info["pairKey"] in composite_keys:
                info["variant"] = "plain"  # A same-path counterpart is evidence, not a content swap.
        reviewed.sort(key=lambda row: (natural_key(row[1]["pairKey"]), natural_key(row[1]["sourceName"])))
        for item, info in reviewed:
            name, variant = info["sourceName"], info["variant"]
            if name.casefold() in names:
                raise StudioError("重复选择了同一路径的图片")
            names.add(name.casefold())
            if source_filter != "all" and variant != source_filter:
                excluded += 1
                continue
            path = PurePosixPath(name)
            encoded = item.get("data")
            if not isinstance(encoded, str) or len(encoded) > ((FILE_BYTES + 2) // 3) * 4:
                raise StudioError("单个素材超过 64 MiB")
            try:
                raw = base64.b64decode(encoded, validate=True)
            except (binascii.Error, ValueError) as exc:
                raise StudioError("图片数据不完整，请重新选择") from exc
            total_bytes += len(raw)
            if total_bytes > MAX_BATCH_BYTES:
                raise StudioError("本次图片总量超过 128 MiB，请分批导入")
            image = image_from(raw)
            pixels += image.width * image.height
            if pixels > MAX_BATCH_PIXELS:
                raise StudioError("本次图片总像素超过 3200 万，请分批导入")
            target = item.get("target")
            if target is not None and not isinstance(target, str):
                raise StudioError("请选择目标动作或素材收件箱")
            target = target or None
            requested_target = target
            if target and target.startswith("preset:"):
                slot = target.removeprefix("preset:")
                if slot not in known:
                    raise StudioError("未知的目标动作槽位")
                preset = known[slot]
                found = next((a for a in p["animations"] if a.get("slot") == slot and a.get("variant", "normal") == preset["variant"]), None)
                if found is None:
                    found = preset_animation(preset)
                    p["animations"].append(found)
                    targets[found["id"]] = found
                new_targets[target] = found["id"]
                target = found["id"]
            if target and (target not in targets or targets[target].get("native")):
                raise StudioError("目标像素动作不存在或属于原生特效，请重新选择")
            settings = item.get("sheet")
            if settings is not None and not isinstance(settings, dict):
                raise StudioError("精灵图切片设置无效")
            if settings is not None and type(settings.get("skipEmpty", False)) is not bool:
                raise StudioError("跳过透明格设置无效")
            rectangles = sheet_rectangles(image.size, settings) if settings is not None else [(0, 0, image.width, image.height)]
            if settings is None and max(image.size) > PIXEL_EDGE:
                raise StudioError(f"{path.name} 为 {image.width}×{image.height}，单帧宽高需 ≤ {PIXEL_EDGE}；若为精灵图，请启用网格切分")
            note = item.get("sourceNote", "")
            if not isinstance(note, str) or len(note) > 2000:
                raise StudioError("素材来源说明需为不超过 2000 字的文字")
            note = note.strip() or {"plain": "按动作路径或本体目录推断为纯本体帧，仍需核对画面。", "composite": "文件名或目录带附属物标记：疑似合成帧。", "unknown": "未分类：命名不能证明是否为纯本体，请核对画面。"}[variant]
            for index, (x, y, w, h) in enumerate(rectangles):
                cell = image.crop((x, y, x + w, y + h))
                if settings is not None and settings.get("skipEmpty", False) and not cell.getchannel("A").getbbox():
                    continue
                if variant == "composite" and target and targets[target].get("slot") in BASE_STATE_SLOTS:
                    confirmation = confirmations.get(requested_target, "").strip()
                    if not confirmation:
                        raise StudioError(f"基础状态『{targets[target]['name']}』选中了疑似合成帧：{name}。请改放收件箱/改选纯本体；确实需要附属物时逐组确认并填写出现时机。")
                    targets[target].update(includesCompanion=True, companionNote=confirmation)
                payload = png_bytes(cell)
                digest = hashlib.sha256(payload).hexdigest()
                source_cell = {"index": index + 1, "x": x, "y": y, "width": w, "height": h} if settings is not None else None
                identity = json.dumps([digest, name, variant, source_cell, note], ensure_ascii=False, sort_keys=True)
                aid = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24] + "_png"
                cell_name = path.name if settings is None else f"{path.stem}_{index + 1:03}.png"
                evidence = {"sourceName": name, "variant": variant, "sourceNote": note}
                if source_cell is not None:
                    evidence["sourceCell"] = source_cell
                metadata = {"id": aid, "name": cell_name, "category": "pixel", "mime": "image/png",
                            "width": w, "height": h, "alpha": cell.getchannel("A").getextrema()[0] < 255,
                            "file": digest[:24] + "_png.png", "sha256": digest, "size": len(payload), **evidence}
                # Same bytes from a different directory/variant get independent references.
                # This never overwrites the metadata of an existing author-selected asset.
                if aid in p["assets"] and p["assets"][aid] != metadata:
                    raise StudioError("素材来源标识冲突，请重新选择；原素材未覆盖")
                p["assets"].setdefault(aid, metadata)
                pair_key = (info["pairKey"], (x, y, w, h) if settings is not None else None)
                pending.append({"target": target, "aid": aid, "payload": payload, "meta": metadata, "pairKey": pair_key, "evidence": evidence})
                if len(pending) > MAX_FRAMES:
                    raise StudioError(f"一次最多导入 {MAX_FRAMES} 张画稿，请分批导入")
        if not pending:
            raise StudioError("筛选后没有可导入画稿，或所选网格全部透明；请调整筛选或关闭『跳过全透明格』")
        changed_targets, inbox, base_slots, variants = set(), list(p.get("pixelInbox", [])), set(), {}
        counts = {v: 0 for v in ("plain", "composite", "unknown")}
        for row in pending:
            target, aid, meta = row["target"], row["aid"], row["meta"]
            counts[meta["variant"]] += 1
            variants.setdefault(row["pairKey"], set()).add(meta["variant"])
            if not target:
                if aid not in inbox:
                    inbox.append(aid)
                continue
            animation = targets[target]
            if target not in changed_targets and mode == "replace":
                animation["clips"] = []
            changed_targets.add(target)
            if meta["variant"] == "composite" and animation.get("slot") in BASE_STATE_SLOTS:
                base_slots.add(animation["slot"])
            animation["clips"].append({"asset": aid, "hold": hold, "x": -meta["width"] / 2,
                                       "y": -meta["height"] if alignment == "feet" else -meta["height"] / 2,
                                       "flip": False, "rotation": 0, "scale": 1, "opacity": 1, **row["evidence"]})
        p["pixelInbox"] = inbox
        validate(p)
        p["revision"] += 1
        p["updated"] = time.time()
        directory = store.directory(pid)
        asset_dir = safe_child(directory, "assets")
        asset_dir.mkdir(exist_ok=True)
        created = []
        try:
            for row in pending:
                path = safe_child(directory, "assets/" + row["meta"]["file"])
                if not path.exists():
                    created.append(path)
                    write_bytes(path, row["payload"], "xb")
                elif hashlib.sha256(path.read_bytes()).hexdigest() != row["meta"]["sha256"]:
                    raise StudioError("已有素材文件校验失败，已停止导入，原素材未覆盖")
            store._write(p)  # Atomic project write also preserves the old revision in history.
        except Exception:
            # Do not remove payloads if a post-commit failure was raised by storage.
            if store.load(pid)["revision"] == old["revision"]:
                for path in created:
                    path.unlink(missing_ok=True)
            raise
        pairs = sum({"plain", "composite"} <= values for values in variants.values())
        notice = {**counts, "pairs": pairs, "base_state_targets": sorted(base_slots),
                  "hint": "疑似合成帧已保留来源标记；基础状态的附属物确认不会将其改为纯本体。"} if counts["composite"] else None
        return {"project": p, "frames": len(pending), "animations": len(changed_targets),
                "targets": sorted(changed_targets), "createdTargets": new_targets,
                "inbox": len({row["aid"] for row in pending if not row["target"]}),
                "variantCounts": counts, "companionNotice": notice, "excludedFiles": excluded}
