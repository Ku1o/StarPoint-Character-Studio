"""Independent UI images and non-destructive portrait crops.

An official PNG is already composed artwork. It must never be resized or
masked merely because the user selects a different UI purpose.

形状遮罩（2026-10-06 凉月插画复盘）：官方 8 类资源把几何形状烘焙在 alpha 里
（技能指引=冰锥/水滴、技能连锁=六边形、队员状态=圆、圆角与缩略图类=圆角矩形），
战斗侧没有运行时裁剪，所以工坊必须能按声明生成并校验这些形状。
"""
from __future__ import annotations

import hashlib
import math
from pathlib import Path
from PIL import Image, ImageChops, ImageDraw
from studio_core import UI_SLOTS, StudioError, image_from, png_bytes, number

# 8 类形状的几何参数来自官方样本测量（2026-10-06 凉月插画裁剪报告 §3.6.2）。
SHAPE_MASKS = {
    "round_95": {"kind": "rounded", "radius": 14},
    "round_136": {"kind": "rounded", "radius": 21},
    "level_up": {"kind": "rounded", "radius": 24},
    "party_main": {"kind": "rounded", "radius": 24},
    "party_unison": {"kind": "rounded", "radius": 14},
    "member_status": {"kind": "circle"},
    "control_board": {"kind": "cone"},
    "chain": {"kind": "hexagon"},
}
SLOT_SHAPES = {
    "square_round_95_95": "round_95",
    "square_round_136_136": "round_136",
    "thumb_level_up": "level_up",
    "thumb_party_main": "party_main",
    "thumb_party_unison": "party_unison",
    "battle_member_status": "member_status",
    "battle_control_board": "control_board",
    "cutin_skill_chain": "chain",
}
# 官方填充率（规范蒙版 mask-canonical 实测），用于生成校验的容差参照。
OFFICIAL_FILL = {
    "round_95": 0.9823, "round_136": 0.9801, "level_up": 0.9940,
    "party_main": 0.9931, "party_unison": 0.9938, "member_status": 0.7824,
    "control_board": 0.6726, "chain": 0.7501,
}
MASK_SCALE = 8
# Public author declarations use shape names; legacy selections use these
# measured, slot-specific keys. Keep both vocabularies valid without copying
# or approximating the official geometry.
MASK_ALIASES = {"cone": "control_board", "hexagon": "chain", "circle": "member_status"}
VALID_MASKS = frozenset(("", "auto", "none", "rounded", *MASK_ALIASES, *SHAPE_MASKS))


def _cone_half(row: int, height: int, width: int, scale: int = 1) -> float:
    """冰锥/水滴：顶部圆头、25% 处最宽、底部收窄。

    行宽剖面按官方规范蒙版（battle_control_board.png，104×268）实测：
    0%/2%/10%/25%/50%/75%/90%/98% 高度处行宽 = 13.5%/44.2%/86.5%/96.2%/
    73.1%/51.0%/37.5%/24.0%（合成 vs 官方 IoU 0.98）。
    """
    half = width / 2
    t = (row + 0.5) / max(1, height * scale)
    points = ((0.0, 0.135), (0.02, 0.442), (0.05, 0.673), (0.10, 0.865),
              (0.25, 0.962), (0.50, 0.731), (0.75, 0.510), (0.90, 0.375),
              (0.95, 0.327), (0.98, 0.240), (1.0, 0.077))
    value = points[-1][1]
    for (t0, v0), (t1, v1) in zip(points, points[1:]):
        if t <= t0:
            value = v0
            break
        if t0 <= t <= t1:
            value = v0 + (v1 - v0) * (t - t0) / (t1 - t0)
            break
    return max(0.0, value * half)


def _hexagon_half(row: int, height: int, width: int, scale: int = 1) -> float:
    half = width / 2
    tip = max(1.0, height * 0.25)
    slope = half / tip
    y = (row + 0.5) / scale
    return max(0.0, min(half, slope * y, slope * (height - y)))


def shape_mask_image(key: str, size) -> Image.Image:
    """按官方几何合成 8 类形状遮罩（L 通道，8× 超采样抗锯齿）。"""
    if key not in SHAPE_MASKS:
        raise StudioError("未知的界面形状遮罩")
    width, height = size
    if width <= 0 or height <= 0:
        raise StudioError("遮罩尺寸无效")
    spec = SHAPE_MASKS[key]
    scale = MASK_SCALE
    big = Image.new("L", (width * scale, height * scale), 0)
    draw = ImageDraw.Draw(big)
    kind = spec["kind"]
    if kind == "rounded":
        radius = max(1, int(spec["radius"] * scale))
        draw.rounded_rectangle((0, 0, width * scale - 1, height * scale - 1),
                               radius=radius, fill=255)
    elif kind == "circle":
        draw.ellipse((0, 0, width * scale - 1, height * scale - 1), fill=255)
    else:
        for row in range(height * scale):
            if kind == "cone":
                half = _cone_half(row, height, width, scale)
            else:
                half = _hexagon_half(row, height, width, scale)
            if half <= 0:
                continue
            left = max(0, int(round((width / 2 - half) * scale)))
            right = min(width * scale - 1, int(round((width / 2 + half) * scale)))
            draw.rectangle((left, row, right, row), fill=255)
    return big.resize((width, height), Image.Resampling.LANCZOS)


def apply_shape_mask(image: Image.Image, key: str) -> dict:
    """把形状遮罩乘进 alpha，并回执遮罩外 alpha 检查所需的统计。"""
    mask = shape_mask_image(key, image.size)
    rgba = image.convert("RGBA")
    before = rgba.getchannel("A")
    rgba.putalpha(ImageChops.multiply(before, mask))
    outside = ImageChops.subtract(before, mask)
    outside_bbox = outside.getbbox()
    covered = sum(1 for value in mask.getdata() if value > 127) / (mask.width * mask.height)
    return {
        "image": rgba,
        "mask": mask,
        "coverage": covered,
        "official_fill": OFFICIAL_FILL.get(key),
        "outside_alpha_bbox": outside_bbox,
        "outside_alpha_max": (outside.getextrema()[1] if outside_bbox else 0),
    }


def _shape_geometry_problems(key: str, mask: Image.Image) -> list[str]:
    """Check generated geometry independently of the author's source pixels."""
    problems: list[str] = []
    pixels = mask.load()
    for y in range(mask.height):
        occupied = [x for x in range(mask.width) if pixels[x, y] > 32]
        if not occupied:
            continue
        run = 0
        for x in range(occupied[0], occupied[-1] + 1):
            if pixels[x, y] <= 32:
                run += 1
            else:
                if run >= 2:
                    problems.append(f"{key}: 遮罩第 {y} 行有 {run} 像素孔洞")
                    break
                run = 0
        else:
            continue
        break
    coverage = sum(1 for value in mask.getdata() if value > 127) / (mask.width * mask.height)
    official = OFFICIAL_FILL.get(key)
    if official is not None and abs(coverage - official) > 0.03:
        problems.append(
            f"{key}: 遮罩填充率 {coverage:.4f} 与官方 {official:.4f} 偏差超过 0.03"
        )
    return problems


def validate_shape_geometry(key: str, size) -> list[str]:
    return _shape_geometry_problems(key, shape_mask_image(key, size))


def validate_shape_output(key: str, image: Image.Image) -> list[str]:
    """Generated geometry and actual output alpha use the same mask contract."""
    mask = shape_mask_image(key, image.size)
    problems = _shape_geometry_problems(key, mask)
    alpha = image.convert("RGBA").getchannel("A")
    if ImageChops.subtract(alpha, mask).getbbox():
        problems.insert(0, f"{key}: 遮罩外仍有不透明像素（alpha 越界）")
    return problems

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


def _declaration(p, form, slot):
    declarations = p.get("uiDeclarations")
    if not isinstance(declarations, dict):
        return {}
    declared = declarations.get(form + ":" + slot)
    return declared if isinstance(declared, dict) else {}


def _apply_declaration(p, form, slot, spec):
    """Project intent overrides selection settings, never source pixels.

    Only filled fields override: absent/empty declarations retain the exact
    legacy selection. autoCrop=True permits a crop; it never creates one.
    Apply this to saved choices AND transient editor previews so exports and
    compilation cannot silently use a different policy from the preview.
    """
    if not isinstance(spec, dict):
        raise StudioError("界面图片来源无效")
    result = dict(spec)
    declared = _declaration(p, form, slot)
    if declared.get("mask") not in (None, ""):
        result["mask"] = declared["mask"]
    if type(declared.get("autoCrop")) is bool:
        result["autoCrop"] = declared["autoCrop"]
    if declared:
        result["declarationNote"] = declared.get("note") or ""
    return result


def selection(p, form, slot):
    ui_name(form, slot)
    key = form + ":" + slot
    if key in p.get("uiImages", {}):
        return _apply_declaration(p, form, slot, p["uiImages"][key])
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
        spec = {"mode": "crop", "asset": aid, "width": w, "height": h,
                "rect": {"x": c.get("x", .5) * a["width"] - rw / 2,
                         "y": c.get("y", .5 if slot == "full_shot" else .25) * a["height"] - rh / 2,
                         "width": rw, "height": rh},
                "mask": "rounded" if "round" in slot else "none", "legacy": True}
    else:
        aid = p["portraits"].get(form) if slot == "full_shot" else p.get("uiSources", {}).get(key)
        spec = {"mode": "image", "asset": aid}
    return _apply_declaration(p, form, slot, spec)


def resolve_mask(slot: str, spec: dict) -> str:
    mask = spec.get("mask")
    if mask is not None and (not isinstance(mask, str) or mask not in VALID_MASKS):
        raise StudioError("界面遮罩无效")
    if mask == "auto":
        return SLOT_SHAPES.get(slot, "none")
    if mask in (None, ""):
        return "none"
    return MASK_ALIASES.get(mask, mask)


def _ratio_problem(spec) -> str | None:
    rect = spec.get("rect") or {}
    width, height = spec.get("width"), spec.get("height")
    try:
        rect_ratio = float(rect["width"]) / float(rect["height"])
        target_ratio = float(width) / float(height)
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return None
    if rect_ratio <= 0 or target_ratio <= 0:
        return None
    drift = abs(rect_ratio / target_ratio - 1.0)
    if drift > 0.003:
        return (f"裁剪区域长宽比与目标画布偏差 {drift * 100:.2f}%（上限 0.3%），"
                "会产生透明留白或拉伸；请收窄裁剪框或改用专用图片")
    return None


def validate_selection(p, spec, *, enforce_contract=True):
    """Validate source/geometry; draft saves may defer rendering conflicts."""
    if not isinstance(spec, dict) or spec.get("mode") not in ("image", "crop"):
        raise StudioError("界面图片来源无效")
    asset = p["assets"].get(spec.get("asset"))
    if not asset or asset.get("mime") != "image/png":
        raise StudioError("请先导入该用途图片，或从立绘裁剪")
    mask = spec.get("mask")
    if mask is not None and (not isinstance(mask, str) or mask not in VALID_MASKS):
        raise StudioError("界面遮罩无效")
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
        if enforce_contract:
            if spec.get("autoCrop") is False:
                raise StudioError("该用途声明为“禁止从母版自动裁切”，但当前仍选择裁剪；"
                                  "请改用专用图片，或确认取景后修改 uiDeclarations 对应声明")
            if not spec.get("legacy"):
                problem = _ratio_problem(spec)
                if problem:
                    raise StudioError(problem)


def validate_ui(p):
    # A project is also a draft. Persist sound editing data even when its
    # current crop violates intent/ratio; render and contract_report enforce
    # those gates before a PNG or a candidate archive can be produced.
    for field in ("uiImages", "uiSources"):
        if not isinstance(p.get(field, {}), dict):
            raise StudioError("界面图片清单无效")
        for key, value in p.get(field, {}).items():
            if not isinstance(key, str):
                raise StudioError("界面用途无效")
            parts = key.split(":")
            if len(parts) != 2:
                raise StudioError("界面用途无效")
            ui_name(*parts)
            spec = value if field == "uiImages" else {"mode": "image", "asset": value}
            validate_selection(p, spec, enforce_contract=False)


def _masked_image(image, mask_key):
    if mask_key in SHAPE_MASKS:
        return apply_shape_mask(image, mask_key)["image"]
    if mask_key == "rounded":
        # The existing editor's generic rounded edge remains compatible.
        # Use auto / a legacy official key for the measured per-slot radius.
        mask = Image.new("L", image.size)
        ImageDraw.Draw(mask).rounded_rectangle(
            (0, 0, image.width - 1, image.height - 1),
            radius=round(min(image.size) * .18), fill=255)
        image.putalpha(ImageChops.multiply(image.getchannel("A"), mask))
    return image


def render(store, p, form, slot, spec=None):
    ui_name(form, slot)
    spec = selection(p, form, slot) if spec is None else _apply_declaration(p, form, slot, spec)
    validate_selection(p, spec)
    raw = store.asset_bytes(p, spec["asset"])
    mask_key = resolve_mask(slot, spec)
    if spec["mode"] == "image":
        if mask_key == "none":
            return raw  # Preserve original dimensions, encoding and alpha.
        return png_bytes(_masked_image(image_from(raw), mask_key))
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
    return png_bytes(_masked_image(result, mask_key))


def contract_report(store, p) -> dict:
    """Read-only UI contract; store=None checks intent/geometry without rendering."""
    report: dict = {"slots": [], "problems": [], "warnings": []}
    from studio_core import KEY_UI_SLOTS
    for form in ("base", "evolved"):
        for slot in UI_SLOTS:
            key = f"{form}:{slot}"
            declared = _declaration(p, form, slot)
            row = {"key": key, "declared": isinstance((p.get("uiDeclarations") or {}).get(key), dict)}
            try:
                spec = selection(p, form, slot)
                if not spec.get("asset") and key not in p.get("uiImages", {}):
                    continue
                row.update({"mode": spec.get("mode"), "mask": resolve_mask(slot, spec),
                            "requestedMask": spec.get("mask") or "",
                            "autoCrop": spec.get("autoCrop", ""),
                            "maskSource": "declaration" if declared.get("mask") not in (None, "") else "selection",
                            "autoCropSource": "declaration" if type(declared.get("autoCrop")) is bool else "selection",
                            "declarationNote": spec.get("declarationNote", ""),
                            "declarationLocation": f"uiDeclarations.{key}"})
                validate_selection(p, spec)
                if spec.get("mode") == "crop" and spec.get("legacy"):
                    problem = _ratio_problem(spec)
                    if problem:
                        report["warnings"].append(f"{key}:（旧版裁剪）{problem}")
                shape = row["mask"]
                if shape in SHAPE_MASKS:
                    if store is None:
                        asset = p["assets"][spec["asset"]]
                        size = ((spec["width"], spec["height"]) if spec["mode"] == "crop"
                                else (asset["width"], asset["height"]))
                        problems = validate_shape_geometry(shape, size)
                    else:
                        raw = render(store, p, form, slot, spec)
                        image = image_from(raw)
                        row["shape_coverage"] = sum(
                            1 for value in image.getchannel("A").getdata() if value > 127
                        ) / (image.width * image.height)
                        problems = validate_shape_output(shape, image)
                    for message in problems:
                        report["problems"].append(f"{key}: {message}")
            except StudioError as exc:
                # Report every offending slot, including none/rounded and old
                # crops, rather than bypassing validation or leaking an error
                # only when the later compiler happens to render this mask.
                report["problems"].append(f"{key}: {exc}")
            if slot in KEY_UI_SLOTS and not (type(declared.get("autoCrop")) is bool
                                           or declared.get("mask") not in (None, "")):
                report["warnings"].append(
                    f"{key}: 五类重点用途未声明取景/遮罩意图（检查页有对应提示）")
            report["slots"].append(row)
    return report
