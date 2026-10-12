"""Additive v1 provenance. Original bytes and generated PNG identities stay separate."""
from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import PurePosixPath

SCHEMA = "starpoint-source-intake-v1"


def _error(message):
    raise ValueError("原稿追溯：" + message)


def safe_source_path(value):
    if not isinstance(value, str) or not value or len(value) > 1024 or "\x00" in value:
        _error("原始相对路径无效")
    path = PurePosixPath(value.replace("\\", "/"))
    if not path.parts or path.is_absolute() or ".." in path.parts or ":" in value:
        _error("原始路径必须为包内安全相对路径")
    return path.as_posix()


def default_source_intake():
    return {"schema": SCHEMA, "schemaVersion": 1, "author": {"name": "", "authorization": ""},
            "packages": [], "sources": [], "derivatives": []}


def normalize_source_intake(project):
    """Return a copy for old projects too; never upgrade a project during reads."""
    if "sourceIntake" not in project:
        return default_source_intake()
    value = project["sourceIntake"]
    if not isinstance(value, dict):
        _error("清单必须为对象")
    result = default_source_intake()
    result.update(copy.deepcopy(value))
    if result.get("schemaVersion") != 1 or isinstance(result.get("schemaVersion"), bool):
        _error("不支持此清单版本")
    if result.get("schema") != SCHEMA:
        _error("清单格式无效")
    if not isinstance(result.get("author"), dict):
        _error("作者信息必须为对象")
    for field in ("name", "authorization"):
        if not isinstance(result["author"].get(field, ""), str):
            _error("作者信息必须为文本")
    for key in ("packages", "sources", "derivatives"):
        if not isinstance(result.get(key), list) or not all(isinstance(row, dict) for row in result[key]):
            _error(key + " 必须为记录数组")
    return result


def _digest(raw):
    if not isinstance(raw, bytes):
        _error("必须提供实际原始 bytes")
    return hashlib.sha256(raw).hexdigest()


def _record_identity(row, package=None):
    digest = row.get("sha256")
    if not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest):
        _error("原始 bytes 哈希无效")
    if not isinstance(row.get("size"), int) or isinstance(row.get("size"), bool) or row["size"] < 0:
        _error("原始 bytes 长度无效")
    if package is None:
        package = str(row.get("blob", "")).startswith("sources/packages/")
    expected = "sources/packages/" + digest + ".zip" if package else "sources/" + digest + ".raw"
    if row.get("blob") != expected:
        _error("原始 bytes 存储路径无效")


def validate_source_intake(project):
    value = normalize_source_intake(project)
    try:
        json.dumps(value, allow_nan=False)
    except (TypeError, ValueError) as exc:
        _error("清单必须为有限数值的 JSON 数据：" + str(exc))
    packages, sources = {}, {}
    for collection, index in ((value["packages"], packages), (value["sources"], sources)):
        for row in collection:
            rid = row.get("id")
            if not isinstance(rid, str) or not re.fullmatch(r"[a-z0-9_-]{1,128}", rid) or rid in index:
                _error("记录编号无效或重复")
            index[rid] = row
            if collection is value["packages"]:
                if row.get("status") not in ("received", "missing"):
                    _error("原包状态无效")
                if not isinstance(row.get("name"), str):
                    _error("原包名称无效")
                if row["status"] == "missing":
                    if any(row.get(key) is not None for key in ("sha256", "size", "blob")):
                        _error("缺失原包不能声明实际 bytes 哈希")
                    continue
            else:
                safe_source_path(row.get("path"))
            _record_identity(row, package=collection is value["packages"])
    for row in value["sources"]:
        if row.get("package") is not None and row["package"] not in packages:
            _error("原图引用的原包不存在")
        canvas = row.get("canvas")
        if canvas is not None and (not isinstance(canvas, list) or len(canvas) != 2 or
                                  not all(isinstance(n, int) and not isinstance(n, bool) and n > 0 for n in canvas)):
            _error("原图画布必须为正整数宽高")
    for row in value["derivatives"]:
        if row.get("source") not in sources or row.get("asset") not in project.get("assets", {}):
            _error("派生关系引用不存在的原稿或素材")
        if row.get("cell") is not None and (not isinstance(row["cell"], int) or isinstance(row["cell"], bool) or row["cell"] < 0):
            _error("源格号必须为从 0 开始的整数")
        rect = row.get("rect")
        if rect is not None and (not isinstance(rect, list) or len(rect) != 4 or
                                 not all(isinstance(n, int) and not isinstance(n, bool) for n in rect) or
                                 min(rect[:2]) < 0 or min(rect[2:]) <= 0):
            _error("裁切矩形无效")
        canvas = sources[row["source"]].get("canvas")
        if rect is not None and canvas is not None and (rect[0] + rect[2] > canvas[0] or rect[1] + rect[3] > canvas[1]):
            _error("裁切矩形超出原图画布")
        if row.get("mask") is not None and not isinstance(row["mask"], dict):
            _error("遮罩来源必须为对象或未标注")
        if row.get("mask", {}) and row["mask"].get("source") is not None and row["mask"]["source"] not in sources:
            _error("遮罩引用的原稿不存在")
        if row.get("transform") is not None and not isinstance(row["transform"], dict):
            _error("变换必须为对象或未标注")
    return value


def register_package(project, name, raw=None, status="missing", metadata=None):
    value = normalize_source_intake(project)
    digest = _digest(raw) if raw is not None else None
    if raw is not None:
        status = "received"
    elif status != "missing":
        _error("没有原包 bytes，不能标为已收到")
    rid = "package_" + (digest if digest else hashlib.sha256(str(name).encode()).hexdigest())[:24]
    row = copy.deepcopy(metadata or {})
    row.update(id=rid, name=name, status=status, sha256=digest,
               size=len(raw) if raw is not None else None, blob="sources/packages/" + digest + ".zip" if digest else None)
    old = next((r for r in value["packages"] if r["id"] == rid), None)
    if old is None:
        value["packages"].append(row)
    validate_source_intake({**project, "sourceIntake": value})
    project["sourceIntake"] = value
    return copy.deepcopy(old or row)


def register_source(project, source_path, raw, package_id=None, metadata=None):
    path, digest = safe_source_path(source_path), _digest(raw)
    value = normalize_source_intake(project)
    identity = json.dumps([package_id, path, digest], ensure_ascii=False).encode()
    rid = "source_" + hashlib.sha256(identity).hexdigest()[:24]
    row = copy.deepcopy(metadata or {})
    row.update(id=rid, path=path, sha256=digest, size=len(raw), blob="sources/" + digest + ".raw", package=package_id)
    old = next((r for r in value["sources"] if r["id"] == rid), None)
    if old is None:
        value["sources"].append(row)
    validate_source_intake({**project, "sourceIntake": value})
    project["sourceIntake"] = value
    return copy.deepcopy(old or row)


def record_derivative(project, asset_id, source_id, cell=None, rect=None, mask=None, transform=None):
    value = normalize_source_intake(project)
    row = {"asset": asset_id, "source": source_id, "cell": cell, "rect": copy.deepcopy(rect),
           "mask": copy.deepcopy(mask), "transform": copy.deepcopy(transform)}
    if row not in value["derivatives"]:
        value["derivatives"].append(row)
    validate_source_intake({**project, "sourceIntake": value})
    project["sourceIntake"] = value
    return copy.deepcopy(row)


def source_intake_payload(project):
    return validate_source_intake(project)


def verify_source_bytes(record, raw):
    _record_identity(record)
    if len(raw) != record["size"] or _digest(raw) != record["sha256"]:
        _error("原稿文件 bytes 与清单不一致")
    return True


def preserve_source_identity(previous, incoming):
    """Saving may append provenance, but cannot rewrite or drop original identities."""
    old, new = validate_source_intake(previous), validate_source_intake(incoming)
    for key in ("sources", "packages"):
        index = {row["id"]: row for row in new[key]}
        for row in old[key]:
            if index.get(row["id"]) != row:
                _error("已登记的原稿身份不能覆盖或删除；请新增接收记录")
    return True
