"""Version checks, durable snapshots and non-destructive project transfer.

The existing v1 structure remains shared with the MOD editor. Reading never
writes migrations; the first successful edit snapshots the exact old JSON.
"""
from __future__ import annotations

import copy
from contextlib import closing
import hashlib
import json
import math
import os
import re
import shutil
import tempfile
import time
import uuid
from pathlib import Path

from app_metadata import VERSION
from studio_core import StudioError, SAFE, identifier, json_bytes, validate

FORMAT_VERSION = 1
HISTORY_NAME = re.compile(r"[0-9]{6,}(?:-[0-9a-f]{64})?\.json\Z")


def check_format(p):
    if not isinstance(p, dict) or p.get("schema") != "starpoint-character-studio-v1":
        raise StudioError("工程格式暂不支持，请使用创建它的版本；原文件未修改")
    version = p.get("formatVersion", 1)
    if type(version) is not int or version != FORMAT_VERSION:
        raise StudioError("工程由更新的数据格式保存，请升级工具后再打开；原文件未修改")
    if type(p.get("revision")) is not int or p["revision"] < 0:
        raise StudioError("工程修订记录无效，请从历史记录恢复副本")
    if (not isinstance(p.get("name"), str) or not isinstance(p.get("assets"), dict)
            or any(not isinstance(a, dict) for a in p["assets"].values())
            or type(p.get("updated")) not in (int, float) or not math.isfinite(p["updated"])):
        raise StudioError("工程数据不完整或已损坏，请从历史记录恢复副本")
    return p


def linked(path):
    try:
        return path.is_symlink() or bool(getattr(path.lstat(), "st_file_attributes", 0) & 0x400)
    except FileNotFoundError:
        return False


def safe_child(root, relative):
    path = root / relative
    if path == root or not path.is_relative_to(root):
        raise StudioError("工程文件路径无效")
    current = path
    while current != root:
        if linked(current):
            raise StudioError("工程中含链接目录或文件，请先复制为普通文件夹")
        current = current.parent
    if not path.resolve().is_relative_to(root.resolve()):
        raise StudioError("工程文件超出目录")
    return path


def write_bytes(path, raw, mode="wb"):
    with path.open(mode) as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def snapshot(directory, raw):
    old = check_format(json.loads(raw))
    history = safe_child(directory, "history")
    history.mkdir(exist_ok=True)
    target = safe_child(directory, f"history/{old['revision']:06}.json")
    if target.exists():
        if target.read_bytes() == raw:
            return target
        digest = hashlib.sha256(raw).hexdigest()
        target = safe_child(directory, f"history/{old['revision']:06}-{digest}.json")
        if target.exists():
            if target.read_bytes() != raw:
                raise StudioError("历史备份校验失败，已停止保存，原工程未修改")
            return target
    # Publish only after flushing; a full disk must not leave a truncated JSON
    # looking like a usable history entry. The store lock serializes writers.
    pending = safe_child(directory, "history/.pending-" + uuid.uuid4().hex)
    try:
        write_bytes(pending, raw, "xb")
        pending.rename(target)
    finally:
        if pending.exists():
            pending.unlink()
    return target


def persist(store, p):
    check_format(p)
    directory = store.directory(p["id"])
    target = safe_child(directory, "project.json")
    pending = safe_child(directory, "project.pending")
    if target.exists():
        raw = target.read_bytes()
        old = check_format(json.loads(raw))
        if old.get("id") != p["id"]:
            raise StudioError("工程编号与文件夹不一致，已停止保存")
        snapshot(directory, raw)  # Failure must stop before replacing project.json.
    p["formatVersion"] = FORMAT_VERSION
    p["lastSavedWith"] = VERSION
    write_bytes(pending, json_bytes(p))
    pending.replace(target)
    store.asset_catalog_cache.pop(p["id"], None)


def history(store, pid):
    directory = store.directory(pid)
    folder = safe_child(directory, "history")
    records = []
    if folder.is_dir():
        for path in folder.iterdir():
            if not HISTORY_NAME.fullmatch(path.name):
                continue
            try:
                p = check_format(json.loads(safe_child(directory, "history/" + path.name).read_bytes()))
                records.append({"file": path.name, "name": p.get("name", pid),
                                "revision": p["revision"], "updated": p.get("updated", 0)})
            except (OSError, ValueError, TypeError):
                continue
    return sorted(records, key=lambda r: (r["revision"], r["updated"]), reverse=True)


def inventory(directory):
    """Hash regular files without following junctions, including old history."""
    files = {}
    for parent, dirs, names in os.walk(directory, followlinks=False):
        for name in dirs + names:
            path = Path(parent) / name
            safe_child(directory, path.relative_to(directory))
        for name in sorted(names):
            path = Path(parent) / name
            with path.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            files[path.relative_to(directory).as_posix()] = digest
    return files


def fingerprint(files):
    return hashlib.sha256(json_bytes(dict(sorted(files.items())))).hexdigest()


def verify_payloads(directory, p):
    validate(p)
    for asset in p["assets"].values():
        name = asset.get("file", "")
        if Path(name).name != name or not name or any(c in name for c in "\\/:"):
            raise StudioError("工程素材路径无效")
        with safe_child(directory, "assets/" + name).open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if digest != asset.get("sha256"):
            raise StudioError("工程素材校验不一致，未迁入该工程")
    for rel in p.get("referenceFiles", []):
        if not isinstance(rel, str) or ".." in Path(rel).parts or any(c in rel for c in "\\:"):
            raise StudioError("参考文件路径无效")
        if not safe_child(directory, Path("reference") / rel).is_file():
            raise StudioError("工程参考文件缺失，未迁入该工程")


def copy_project(store, source, p, *, recovery=False):
    """Publish a verified staged copy. Never change or remove the source."""
    before = inventory(source)
    digest = fingerprint(before)
    pid = identifier(p["id"])
    if not recovery:
        for row in store.list():
            if row.get("error"):
                continue
            known = store.load(row["id"])
            origin = known.get("upgradeOrigin")
            if isinstance(origin, dict) and origin.get("fingerprint") == digest:
                return {"status": "skipped", "id": row["id"], "name": known["name"]}
            if row["id"] == pid and inventory(store.directory(pid)) == before:
                return {"status": "skipped", "id": pid, "name": known["name"]}
    target_id = uuid.uuid4().hex if recovery or store.directory(pid).exists() else pid
    p = copy.deepcopy(p)
    check_format(p)
    # Temporary directories are hidden from the project list until all payloads
    # and source stability have been checked. Failed copies never become projects.
    with tempfile.TemporaryDirectory(prefix=".transfer-", dir=store.root) as scratch:
        stage = Path(scratch) / target_id
        shutil.copytree(source, stage, symlinks=True)
        if inventory(stage) != before or inventory(source) != before:
            raise StudioError("迁入期间旧工程发生变化，请保存并退出旧版后重试")
        if not recovery and json.loads((stage / "project.json").read_bytes()) != p:
            raise StudioError("迁入期间旧工程发生变化，请保存并退出旧版后重试")
        p.setdefault("sounds", [])
        verify_payloads(stage, p)
        p["id"] = target_id
        if recovery:
            p["name"] = str(p["name"])[:80] + "（恢复副本）"
            p["revision"] = 0
            p["updated"] = time.time()
        elif target_id != pid:
            p["name"] = str(p["name"])[:80] + "（迁入副本）"
        if not recovery:
            p["upgradeOrigin"] = {"id": pid, "fingerprint": digest}
        else:
            p.pop("upgradeOrigin", None)
        # Keep the exact pre-migration metadata even when renaming a conflicting
        # ID. Recovery can originate from a damaged current JSON, so keep it too.
        if not recovery:
            snapshot(stage, (stage / "project.json").read_bytes())
        elif (stage / "project.json").is_file():
            recovery_original = stage / ("recovery-original-" + uuid.uuid4().hex + ".json")
            write_bytes(recovery_original, (stage / "project.json").read_bytes(), "xb")
        p["formatVersion"] = FORMAT_VERSION
        p["lastSavedWith"] = VERSION
        pending = stage / (".migration-pending-" + uuid.uuid4().hex)
        write_bytes(pending, json_bytes(p), "xb")
        pending.replace(stage / "project.json")
        # rename, never replace: an existing destination must not be overwritten.
        stage.rename(store.directory(target_id))
    return {"status": "copied", "id": target_id, "name": p["name"]}


def upgrade_projects(store, selected):
    source = Path(selected).expanduser().resolve()
    if (source / "projects").is_dir():
        source = (source / "projects").resolve()
    if not source.is_dir() or source == store.root or source.is_relative_to(store.root) or store.root.is_relative_to(source):
        raise StudioError("请选择另一份旧工具的文件夹，或它的 projects 文件夹")
    if any(part.lower() in (".cdn", "startpoint-cn-main") for part in source.parts):
        raise StudioError("请选择旧角色工坊的工程目录")
    result = {"copied": [], "skipped": [], "failed": []}
    from desktop_host import WindowsInstance
    with closing(WindowsInstance(source)) as instance, store.lock:
        if not instance.owner:
            raise StudioError("旧版工具仍在运行，请先在旧版保存并退出，再迁入工程")
        for folder in sorted(source.iterdir()):
            if not folder.is_dir() or not SAFE.fullmatch(folder.name):
                continue
            try:
                if linked(folder):
                    raise StudioError("不迁入链接目录")
                raw = safe_child(folder, "project.json").read_bytes()
                p = check_format(json.loads(raw))
                if p.get("id") != folder.name:
                    raise StudioError("工程编号与文件夹不一致")
                row = copy_project(store, folder, p)
                result[row["status"]].append(row)
            except (OSError, ValueError, TypeError, KeyError) as exc:
                # Do not report unrelated installation folders as broken projects.
                if (folder / "project.json").exists() or (folder / "history").is_dir():
                    result["failed"].append({"id": folder.name, "error": str(exc)})
    if not any(result.values()):
        raise StudioError("所选目录中没有工坊工程，请选择旧工具旁的 projects 文件夹")
    return result


def recover(store, pid, filename):
    if not isinstance(filename, str) or not HISTORY_NAME.fullmatch(filename):
        raise StudioError("历史记录名称无效")
    with store.lock:
        source = store.directory(pid)
        p = check_format(json.loads(safe_child(source, "history/" + filename).read_bytes()))
        # Historical copies can carry the ID from before a conflict was renamed.
        p["id"] = pid
        result = copy_project(store, source, p, recovery=True)
        return store.load(result["id"])
