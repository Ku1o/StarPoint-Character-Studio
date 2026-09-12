"""Validate complete image batches before mutating an artist project."""
from __future__ import annotations

import base64
import binascii
import copy
import hashlib
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


def import_images(store, pid, request):
    from studio_core import StudioError, integer, image_from, png_bytes, validate
    with store.lock:
        old = store.load(pid)
        if request.get("revision") != old["revision"]:
            raise StudioError("工程已更新，请重新打开导入窗口")
        p = copy.deepcopy(old)
        files = request.get("files")
        if not isinstance(files, list) or not 1 <= len(files) <= MAX_FILES or not all(isinstance(item, dict) for item in files):
            raise StudioError(f"一次请选择 1 至 {MAX_FILES} 张 PNG")
        hold = integer(request.get("hold", 6), 1, 4096, "每张画稿停留帧数")
        mode = request.get("mode", "append")
        alignment = request.get("alignment", "feet")
        if mode not in ("append", "replace") or alignment not in ("feet", "center"):
            raise StudioError("导入方式或对齐方式无效")
        pending, names, total_bytes, pixels, new_targets = [], set(), 0, 0, {}
        targets = {a["id"]: a for a in p["animations"]}
        known = {s["slot"]: s for s in ACTION_PRESETS}
        for item in sorted(files, key=lambda f: natural_key(str(f.get("path") or f.get("name", "")))):
            name = item.get("path") or item.get("name")
            if not isinstance(name, str) or not name or len(name) > 1024:
                raise StudioError("图片文件名无效")
            path = PurePosixPath(name.replace("\\", "/"))
            if path.is_absolute() or ".." in path.parts or ":" in name or path.suffix.lower() != ".png":
                raise StudioError("请使用安全路径下的静态 PNG 图片")
            if path.as_posix().casefold() in names:
                raise StudioError("重复选择了同一路径的图片")
            names.add(path.as_posix().casefold())
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
            target = item.get("target") or None
            if target is not None and not isinstance(target, str):
                raise StudioError("请选择目标动作或素材收件箱")
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
                raise StudioError("目标像素动作不存在，请重新选择")
            settings = item.get("sheet")
            if settings is not None and not isinstance(settings, dict):
                raise StudioError("精灵图切片设置无效")
            rectangles = sheet_rectangles(image.size, settings) if settings is not None else [(0, 0, image.width, image.height)]
            if settings is None and max(image.size) > PIXEL_EDGE:
                raise StudioError(f"{path.name} 为 {image.width}×{image.height}，单帧宽高需 ≤ {PIXEL_EDGE}；若为精灵图，请启用网格切分")
            for index, (x, y, w, h) in enumerate(rectangles):
                cell = image.crop((x, y, x + w, y + h))
                if settings and settings.get("skipEmpty", False) and not cell.getchannel("A").getbbox():
                    continue
                payload = png_bytes(cell)
                digest = hashlib.sha256(payload).hexdigest()
                aid = digest[:24] + "_png"
                cell_name = path.name if settings is None else f"{path.stem}_{index + 1:03}.png"
                # Preview the entire mutation before add_asset writes any payload.
                p["assets"].setdefault(aid, {"id": aid, "name": cell_name, "category": "pixel", "mime": "image/png", "width": w, "height": h})
                pending.append((target, aid, cell_name, payload, w, h))
                if len(pending) > MAX_FRAMES:
                    raise StudioError(f"一次最多导入 {MAX_FRAMES} 张画稿，请分批导入")
        if not pending:
            raise StudioError("所选网格全部透明，没有可导入的画稿；可关闭“跳过全透明格”")
        changed_targets, inbox = set(), list(p.get("pixelInbox", []))
        for target, aid, name, payload, w, h in pending:
            if not target:
                if aid not in inbox:
                    inbox.append(aid)
                continue
            animation = targets[target]
            if target not in changed_targets and mode == "replace":
                animation["clips"] = []
            changed_targets.add(target)
            animation["clips"].append({"asset": aid, "hold": hold, "x": -w / 2, "y": -h if alignment == "feet" else -h / 2, "flip": False, "rotation": 0, "scale": 1, "opacity": 1})
        p["pixelInbox"] = inbox
        validate(p)
        # Existing history/undo is retained, including frames replaced by this batch.
        history = store.directory(pid) / "history"
        history.mkdir(exist_ok=True)
        from studio_core import json_bytes
        (history / f"{old['revision']:06}.json").write_bytes(json_bytes(old))
        for target, aid, name, payload, w, h in pending:
            store.add_asset(p, name, payload, "pixel", enforce_limits=True)
        p["revision"] += 1
        p["updated"] = time.time()
        store._write(p)
        return {"project": p, "frames": len(pending), "animations": len(changed_targets),
                "targets": sorted(changed_targets), "createdTargets": new_targets,
                "inbox": len({aid for target, aid, *_ in pending if not target})}
