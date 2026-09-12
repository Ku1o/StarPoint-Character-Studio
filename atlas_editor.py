"""Inspect real compiler atlases and pack lossless UI artwork for handoff."""
import base64
import json
import zlib
from PIL import Image
from studio_core import StudioError, UI_SLOTS, image_from, png_bytes, atlas_crop
from bridge import AMF3Reader
from portrait_editor import selection, render, ui_name


def ui_atlas(store, p):
    cells, records = [], []
    x, y, row = 1, 1, 0
    for form in ("base", "evolved"):
        for slot in UI_SLOTS:
            if slot in ("full_shot", "skill_cutin"):
                continue
            spec = selection(p, form, slot)
            if not spec.get("asset"):
                continue
            cell = image_from(render(store, p, form, slot))
            if cell.width > 2046 or cell.height > 8190:
                raise StudioError("UI 单图超出交接图集容量，请检查尺寸")
            if x + cell.width + 1 > 2048:
                x, y, row = 1, y + row + 2, 0
            if y + cell.height + 1 > 8192:
                raise StudioError("UI 交接图集超过 8192 像素高，请检查图片尺寸")
            records.append({"n": ui_name(form, slot).removesuffix(".png"), "x": x, "y": y, "w": cell.width, "h": cell.height,
                            "form": form, "slot": slot, "asset": spec["asset"], "mode": spec["mode"]})
            cells.append(cell)
            x, row = x + cell.width + 2, max(row, cell.height)
    if not cells:
        return None
    sheet = Image.new("RGBA", (2048, y + row + 1))
    for cell, record in zip(cells, records):
        sheet.paste(cell, (record["x"], record["y"]))
    # Verify serialized PNG + JSON, including semi-transparent/hidden pixels.
    sheet = image_from(png_bytes(sheet))
    records = json.loads(json.dumps(records))
    for expected, record in zip(cells, records):
        if atlas_crop(sheet, record).tobytes() != expected.tobytes():
            raise StudioError("UI 图集回读与单图不一致")
    return sheet, records


def atlas_data(store, p, group, animation=None):
    if group == "ui":
        value = ui_atlas(store, p)
        if not value:
            raise StudioError("请先添加界面小图或从立绘裁剪")
        return *value, "UI 交接图集", "此图集用于交接与逐张检查。游戏的 illustration 图集是另一套布局，仍需由 MOD 接入流程处理；大立绘与技能切入保留为独立文件。"
    from studio_compile import compile_pixelart, compile_effect
    code = p["identity"].get("code", "new_character")
    anim = next((a for a in p.get(group, []) if a["id"] == animation), None) if group in ("animations", "effects") else None
    if not anim:
        raise StudioError("请选择一个动作或特效")
    if group == "animations":
        files, _ = compile_pixelart(store, p, p["animations"], anim.get("variant", "normal"), code)
        label = "像素动作 · 实际编译图集"
    else:
        files, _ = compile_effect(store, p, anim, code)
        label = anim["name"] + " · 实际编译图集"
    atlas_path = next((k for k in files if k.endswith(".atlas.amf3.deflate")), None)
    if not atlas_path:
        raise StudioError("当前动作没有可编译图片")
    records = AMF3Reader(zlib.decompress(files[atlas_path], -15)).read_value()
    sheet = image_from(files[atlas_path.removesuffix(".atlas.amf3.deflate") + ".png"])
    return sheet, records, label, "回读本次实际编译的 PNG 和图集坐标。点选任一图块可原尺寸导出；动画预览中的偏移、倍率由配套时间轴保存。"


def preview(store, p, group, animation=None):
    sheet, records, label, note = atlas_data(store, p, group, animation)
    return {"label": label, "note": note, "width": sheet.width, "height": sheet.height, "records": records,
            "url": "data:image/png;base64," + base64.b64encode(png_bytes(sheet)).decode()}
