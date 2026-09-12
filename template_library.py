"""Optional adjacent offline template library; no network or arbitrary path API."""
import hashlib
import json
import time
import threading
from pathlib import Path

from studio_core import StudioError, identifier, archive_files, make_zip


class TemplateLibrary:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self._cached = None
        self._signature = None
        self._checked = 0
        self._lock = threading.RLock()

    def safe_path(self, relative):
        if not isinstance(relative, str) or "\\" in relative or ":" in relative:
            raise StudioError("模板库路径无效")
        path = (self.root / relative).resolve()
        if not path.is_relative_to(self.root):
            raise StudioError("模板文件不能位于库目录之外")
        return path

    def catalog(self):
        with self._lock:
            return self._catalog()

    def _catalog(self):
        path = self.root / "catalog.json"
        if not path.is_file():
            return {"installed": False, "entries": [], "name": "国服官方角色美术模板库"}
        stat = path.stat()
        signature = (stat.st_mtime_ns, stat.st_size)
        if self._cached is not None and signature == self._signature and time.monotonic() - self._checked < 5:
            return self._cached
        if stat.st_size > 16 * 1024 * 1024:
            raise StudioError("模板目录过大")
        catalog = json.loads(path.read_bytes())
        if catalog.get("schema") != "starpoint-template-library-v1":
            raise StudioError("模板目录版本不支持")
        ids = set()
        for entry in catalog["entries"]:
            identifier(entry["id"])
            if entry["id"] in ids:
                raise StudioError("模板编号重复")
            ids.add(entry["id"])
            entry["available"] = self.safe_path(entry["file"]).is_file()
            if entry.get("audio"):
                entry["available"] &= self.safe_path(entry["audio"]["file"]).is_file()
        catalog["installed"] = True
        self._cached, self._signature, self._checked = catalog, signature, time.monotonic()
        return catalog

    def entry(self, cid):
        identifier(cid)
        entry = next((e for e in self.catalog()["entries"] if e["id"] == cid), None)
        if not entry:
            raise StudioError("模板不存在")
        return entry

    def archive(self, cid):
        entry = self.entry(cid)
        def read(record):
            raw = self.safe_path(record["file"]).read_bytes()
            if hashlib.sha256(raw).hexdigest() != record["sha256"]:
                raise StudioError("模板校验不一致，请重新解压模板库")
            return raw
        raw = read(entry)
        if not entry.get("audio"):
            return raw
        files = archive_files(raw)
        audio = archive_files(read(entry["audio"]))
        for path in audio:
            if not (path.startswith(("reference/voice/", "reference/sound/")) or path == "reference/audio_catalog.json") or path in files:
                raise StudioError("声音补充包包含无效或重复路径")
        files.update(audio)
        return make_zip(files)

    def thumbnail(self, cid):
        entry = self.entry(cid)
        if not entry.get("thumbnail"):
            raise StudioError("模板没有缩略图")
        return self.safe_path(entry["thumbnail"]).read_bytes()
