"""Independent UI images and non-destructive portrait crops.

An official PNG is already composed artwork. It must never be resized or
masked merely because the user selects a different UI purpose.
"""
from __future__ import annotations

import hashlib
import math
from pathlib import Path
from PIL import Image, ImageChops, ImageDraw
from studio_core import UI_SLOTS, StudioError, image_from, png_bytes, number


def ui_name(form, slot):
    if form not in ("base", "evolved") or slot not in UI_SLOTS:
        raise StudioError("未知形态或界面用途")
    stem = "full_shot_1440_1920" if slot == "full_shot" else slot
    return f"{stem}_{0 if form == 'base' else 1}.png"


def source_key(name):
    return next((f"{form}:{slot}" for form in ("base", "evolved") for slot in UI_SLOTS
                 if name == "ui/" + ui_name(form, slot)), None)


def hydrate(store, p):
    """Recover mappings for old projects without changing any files or edits."""
    if "uiSources" in p:
        return
    known = store.ui_source_cache.get(p["id"])
    if known is None:
        known = {}
        by_hash = {a["sha256"]: aid for aid, a in p["assets"].items() if a.get("mime") == "image/png"}
        for rel in p.get("referenceFiles", []):
            key = source_key(rel)
            if not key:
                continue
            path = store.directory(p["id"]) / "reference" / rel
            if not path.is_file() or path.is_symlink():
                continue
            # Asset names can be shared or deduplicated across both forms.
            # Match the normalized original pixels, never a similarly named upload.
            digest = hashlib.sha256(png_bytes(image_from(path.read_bytes()))).hexdigest()
            if digest in by_hash:
                known[key] = by_hash[digest]
        store.ui_source_cache[p["id"]] = known
    p["uiSources"] = {key: aid for key, aid in known.items() if aid in p["assets"]}


def selection(p, form, slot):
    ui_name(form, slot)
    key = form + ":" + slot
    if key in p.get("uiImages", {}):
        return dict(p["uiImages"][key])
    # Explicit old crop edits remain intact. Unedited legacy templates now
    # correctly select their official UI image, including trimmed full shots.
    if key in p.get("crops", {}) and p["portraits"].get(form):
        aid = p["portraits"][form]
        a = p["assets"][aid]
        _, w, h = UI_SLOTS[slot]
        c = p["crops"][key]
        fit = (min if slot == "full_shot" else max)(w / a["width"], h / a["height"])
        if slot not in ("full_shot", "skill_cutin"):
            fit = max(fit, w / a["width"] * 2.5)
        scale = fit * float(c.get("zoom", 1))
        if not math.isfinite(scale) or scale <= 0:
            raise StudioError("旧版裁剪参数无效")
        rw, rh = w / scale, h / scale
        return {"mode": "crop", "asset": aid, "width": w, "height": h,
                "rect": {"x": c.get("x", .5) * a["width"] - rw / 2,
                         "y": c.get("y", .5 if slot == "full_shot" else .25) * a["height"] - rh / 2,
                         "width": rw, "height": rh},
                "mask": "rounded" if "round" in slot else "none", "legacy": True}
    aid = p["portraits"].get(form) if slot == "full_shot" else p.get("uiSources", {}).get(key)
    return {"mode": "image", "asset": aid}


def validate_selection(p, spec):
    if not isinstance(spec, dict) or spec.get("mode") not in ("image", "crop"):
        raise StudioError("界面图片来源无效")
    asset = p["assets"].get(spec.get("asset"))
    if not asset or asset.get("mime") != "image/png":
        raise StudioError("请先导入该用途图片，或从立绘裁剪")
    if spec["mode"] == "crop":
        for k in ("width", "height"):
            v = spec.get(k)
            if isinstance(v, bool) or not isinstance(v, int) or not 1 <= v <= 4096:
                raise StudioError("输出宽高必须是 1 至 4096 的整数")
        rect = spec.get("rect", {})
        if not isinstance(rect, dict):
            raise StudioError("裁剪区域无效")
        for k in ("x", "y"):
            number(rect.get(k), -32768, 32768, "裁剪位置")
        for k in ("width", "height"):
            number(rect.get(k), .1, 65536, "裁剪范围")
        if spec.get("mask", "none") not in ("none", "rounded"):
            raise StudioError("裁剪蒙版无效")


def validate_ui(p):
    for field in ("uiImages", "uiSources"):
        if not isinstance(p.get(field, {}), dict):
            raise StudioError("界面图片清单无效")
        for key, value in p.get(field, {}).items():
            parts = key.split(":")
            if len(parts) != 2:
                raise StudioError("界面用途无效")
            ui_name(*parts)
            validate_selection(p, value if field == "uiImages" else {"mode": "image", "asset": value})


def render(store, p, form, slot, spec=None):
    ui_name(form, slot)
    spec = selection(p, form, slot) if spec is None else spec
    validate_selection(p, spec)
    raw = store.asset_bytes(p, spec["asset"])
    if spec["mode"] == "image":
        return raw
    source = image_from(raw)
    rect = spec["rect"]
    w, h = spec["width"], spec["height"]
    if rect["width"] == w and rect["height"] == h and all(float(rect[k]).is_integer() for k in ("x", "y")):
        x, y = int(rect["x"]), int(rect["y"])
        result = source.crop((x, y, x + w, y + h))
    else:
        result = source.transform((w, h), Image.Transform.AFFINE,
                                  (rect["width"] / w, 0, rect["x"], 0, rect["height"] / h, rect["y"]),
                                  resample=Image.Resampling.BICUBIC)
    if spec.get("mask") == "rounded":
        mask = Image.new("L", (w, h))
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), radius=round(min(w, h) * .18), fill=255)
        result.putalpha(ImageChops.multiply(result.getchannel("A"), mask))
    return png_bytes(result)
