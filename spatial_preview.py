"""Validate optional preview-only stage metadata without migrating projects.

Stage coordinates belong to preview/handoff, not art compilation, scene tracks,
or game combat bindings. Validation deliberately never supplies defaults or
normalizes coordinates.
"""
from __future__ import annotations

import math


def validate_preview_stage(project):
    """Reject malformed previewStage; leave absent/valid metadata untouched."""
    from studio_core import StudioError

    if "previewStage" not in project:
        return
    stage = project["previewStage"]
    if not isinstance(stage, dict):
        raise StudioError("预览场地设置必须是对象，不能为 null")
    required = ("version", "profile", "width", "height",
                "originX", "originY", "targetX", "targetY")
    missing = [key for key in required if key not in stage]
    if missing:
        raise StudioError("预览场地设置缺少必填字段：" + "、".join(missing))
    if type(stage["version"]) is not int or stage["version"] != 1:
        raise StudioError("预览场地设置版本无效，仅支持整数版本 1")
    if stage["profile"] not in ("reference", "custom"):
        raise StudioError("预览场地设置模式无效，仅支持 reference 或 custom")

    def coordinate(key, minimum, maximum, label):
        value = stage[key]
        # Check bounds before isfinite: huge Python ints must produce StudioError,
        # not OverflowError from their implicit conversion to float.
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not minimum <= value <= maximum or not math.isfinite(value)):
            raise StudioError(f"预览场地{label}必须是 {minimum} 至 {maximum} 的有限数值（不能为布尔值）")
        return value

    width = coordinate("width", 1, 8192, "宽度")
    height = coordinate("height", 1, 8192, "高度")
    coordinate("originX", 0, width, "原点 X")
    coordinate("targetX", 0, width, "目标 X")
    coordinate("originY", 0, height, "原点 Y")
    coordinate("targetY", 0, height, "目标 Y")
