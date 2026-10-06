"""Portable authoring projects, safe import, and offline animation compilation."""
from __future__ import annotations

import base64
import bisect
import copy
import hashlib
import io
import json
import math
import re
import threading
import time
import uuid
import zipfile
import zlib
from pathlib import Path, PurePosixPath

from PIL import Image, ImageOps
from bridge import AMF3Reader, encode_amf3, flatomo
from asset_rules import PIXEL_EDGE, EFFECT_EDGE, FILE_BYTES
from audio_rules import voice_usage, USAGES
from action_presets import default_animations
from character_contract import normalize_gameplay
from production_brief import default_production_brief, normalize_production_brief, hydrate_from_project, checks as production_checks, export_handoff

MAX_ARCHIVE = 256 * 1024 * 1024
MAX_IMAGE_PIXELS = 32_000_000
MAX_TICKS = 4096
Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
PNG = b"\x89PNG\r\n\x1a\n"
FAKE_PNG = b"\x89png\r\n\x1a\n"
SAFE = re.compile(r"[a-zA-Z0-9_-]+\Z")
LABELS = {"neutral": "待机", "walk_front": "向前移动", "walk_back": "向后移动", "skill_ready": "技能准备", "kachidoki": "胜利", "into_coffin": "倒下", "ghost_raise": "灵魂出现", "ghost_neutral": "灵魂待机", "revive": "复活", "special_land": "获取·登场", "special_pose": "获取·定格", "attack_initial": "攻击·起手", "attack_charge": "攻击·蓄力", "attack_finish": "攻击·收招"}
# 附属物/合成帧命名后缀（2026-10-06 凉月基础帧事故：作者同帧同时提供
# 纯本体 <名>.png 与"本体+召唤物" <名>_sp.png，编译误把合成帧当基础帧）。
COMPANION_SUFFIXES = ("_sp", "_summon", "_fx", "_eff", "_glow")
BASE_STATE_SLOTS = ("neutral", "walk_front", "walk_back", "kachidoki",
                    "into_coffin", "ghost_raise", "ghost_neutral", "revive")
COMPANION_STATE_SLOTS = ("skill_ready", "special_land", "special_pose")
KEY_UI_SLOTS = ("square", "thumb_party_main", "skill_cutin",
                "battle_control_board", "cutin_skill_chain")
UI_MASK_VALUES = ("auto", "none", "rounded", "cone", "hexagon", "circle")
EFFECT_ORIGINS = ("reuse", "reskin", "original")
VOICE_ENTRIES = ("ally", "battle", "home", "login", "words")
UI_SLOTS = {
    "full_shot": ("立绘", 1440, 1920), "square_132_132": ("头像", 132, 132),
    "square_round_95_95": ("圆角头像", 95, 95), "square_round_136_136": ("大圆角头像", 136, 136),
    "square": ("方形头像", 212, 212), "skill_cutin": ("技能切入", 1024, 512),
    "thumb_level_up": ("升级", 252, 329), "thumb_party_main": ("编队主位", 186, 392),
    "thumb_party_unison": ("编队副位", 144, 188), "battle_control_board": ("技能栏", 104, 268),
    "battle_member_status": ("队员状态", 58, 58), "cutin_skill_chain": ("连锁切入", 276, 319),
}


class StudioError(ValueError):
    pass


def identifier(value):
    if not isinstance(value, str) or not SAFE.fullmatch(value) or len(value) > 100:
        raise StudioError("工程或素材标识无效")
    return value


def integer(value, minimum, maximum, label):
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise StudioError(f"{label}必须是 {minimum} 至 {maximum} 的整数")
    return value


def number(value, minimum, maximum, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not minimum <= value <= maximum:
        raise StudioError(f"{label}超出范围")
    return value


def png_bytes(image):
    stream = io.BytesIO()
    image.save(stream, "PNG")
    return stream.getvalue()


def image_from(raw):
    if raw.startswith(FAKE_PNG):
        raw = PNG + raw[8:]
    try:
        with Image.open(io.BytesIO(raw)) as opened:
            if opened.width * opened.height > MAX_IMAGE_PIXELS:
                raise StudioError("图片尺寸过大")
            if opened.format != "PNG":
                raise StudioError("图像源素材请使用 PNG")
            if getattr(opened, "n_frames", 1) != 1:
                raise StudioError("动画 PNG 请先导出为逐帧静态 PNG，再批量导入")
            opened.load()
            return opened.convert("RGBA")
    except (OSError, Image.DecompressionBombError) as exc:
        raise StudioError("无法读取 PNG 素材") from exc


def json_bytes(value):
    return json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")


def asset_variant(name):
    """按文件名后缀推断素材身份：plain(纯本体) / composite(合成帧)。"""
    stem = str(name or "").rsplit(".", 1)[0].casefold()
    return "composite" if any(stem.endswith(suffix) for suffix in COMPANION_SUFFIXES) else "plain"


def clip_variant(p, aid):
    asset = p["assets"].get(aid) or {}
    variant = asset.get("variant")
    if variant in ("plain", "composite"):
        return variant
    return asset_variant(asset.get("name", ""))


def animation_variant(p, anim):
    variants = {clip_variant(p, clip.get("asset")) for clip in anim.get("clips") or []}
    if "composite" in variants and "plain" in variants:
        return "mixed"
    if "composite" in variants:
        return "composite"
    return "plain" if variants else ""


def normalize_declarations(p):
    """补齐可选声明字段（缺省 = 未标注），不改旧文件其余内容。"""
    if not isinstance(p.get("authorNotes"), str):
        p["authorNotes"] = ""
    for group in ("animations", "effects"):
        for anim in p.get(group, []):
            if not isinstance(anim, dict):
                continue
            if not isinstance(anim.get("purpose"), str):
                anim["purpose"] = anim.get("purpose") or ""
            if not isinstance(anim.get("includesCompanion"), bool):
                anim["includesCompanion"] = "" if anim.get("includesCompanion") in (None, "") else bool(anim.get("includesCompanion"))
            if not isinstance(anim.get("companionNote"), str):
                anim["companionNote"] = ""
            if not isinstance(anim.get("origin"), str):
                anim["origin"] = anim.get("origin") or ""
            if not isinstance(anim.get("originNote"), str):
                anim["originNote"] = anim.get("originNote") or ""
    if not isinstance(p.get("uiDeclarations"), dict):
        p["uiDeclarations"] = {}
    if not isinstance(p.get("voiceDeclarations"), list):
        p["voiceDeclarations"] = []
    return p


def validate_declarations(p):
    for group in ("animations", "effects"):
        for anim in p.get(group, []):
            companion = anim.get("includesCompanion")
            if companion is not None and companion not in ("", True, False):
                raise StudioError("动作的“是否包含召唤物”取值无效")
            if anim.get("origin") and anim["origin"] not in ("", *EFFECT_ORIGINS):
                raise StudioError("特效来源声明无效（复用/重皮/原创）")
            for field in ("companionNote", "originNote", "purpose"):
                if len(str(anim.get(field) or "")) > 500:
                    raise StudioError("动作说明过长")
    for key, spec in (p.get("uiDeclarations") or {}).items():
        if ":" not in key or not isinstance(spec, dict):
            raise StudioError("UI 用途声明无效")
        if spec.get("mask") not in (None, "", *UI_MASK_VALUES):
            raise StudioError("UI 遮罩声明无效")
    for item in p.get("voiceDeclarations") or []:
        if not isinstance(item, dict) or len(item.get("text") or "") > 2000:
            raise StudioError("语音声明无效")
        if item.get("entry") not in (None, "", *VOICE_ENTRIES):
            raise StudioError("语音入口声明无效（ally/battle/home/login/words）")
    return p


def declaration_payload(p):
    """导出/编译用的“来源与声明”载荷（wf_character_flow 的 preflight 分组同源）。"""
    normalize_declarations(p)
    animations = []
    for anim in p.get("animations", []):
        animations.append({
            "id": anim.get("id"),
            "name": anim.get("name"),
            "slot": anim.get("slot", ""),
            "variant": animation_variant(p, anim),
            "includesCompanion": anim.get("includesCompanion", ""),
            "companionNote": anim.get("companionNote", ""),
            "purpose": anim.get("purpose", ""),
        })
    effects = [{
        "id": effect.get("id"),
        "name": effect.get("name"),
        "origin": effect.get("origin", ""),
        "originNote": effect.get("originNote", ""),
    } for effect in p.get("effects", [])]
    return {
        "schema": "starpoint-character-studio-declarations-v1",
        "authorNotes": p.get("authorNotes", ""),
        "animations": animations,
        "effects": effects,
        "uiDeclarations": copy.deepcopy(p.get("uiDeclarations") or {}),
        "voiceDeclarations": copy.deepcopy(p.get("voiceDeclarations") or []),
    }


_PLAY_LABELS = {"once": "单次", "loop": "循环", "pass": "衔接下一段", "stop": "停在首帧"}
_VARIANT_LABELS = {"plain": "纯本体", "composite": "合成帧", "mixed": "纯本体+合成帧混用", "": "未标注"}


def author_readme(p):
    """`.wfchar` 包内《README-稿主必读.md》：动作/语音/UI/特效/未标注项清单。"""
    normalize_declarations(p)
    lines = [
        "# 稿主必读（角色工坊自动生成）",
        "",
        "这个包是《星点角色工坊》的可编辑创作工程，不是可直接安装的游戏补丁。",
        "在工坊里用「打开工程 / 参考包」导入本包即可继续制作。",
        "",
        "## 1. 动作清单",
        "",
        "| 槽位 | 中文 | 画稿段数 | 总帧 | 播放 | 帧来源 | 包含召唤物 | 说明 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for anim in p.get("animations", []):
        clips = anim.get("clips") or []
        frames = sum(int(clip.get("hold", 0)) for clip in clips)
        companion = {True: "是", False: "否"}.get(anim.get("includesCompanion"), "未标注")
        note = str(anim.get("companionNote") or anim.get("purpose") or "").replace("|", "／")
        lines.append(
            f"| {anim.get('slot', '')} | {LABELS.get(anim.get('slot'), anim.get('name', ''))} "
            f"| {len(clips)} | {frames} | {_PLAY_LABELS.get(anim.get('kind'), anim.get('kind', ''))} "
            f"| {_VARIANT_LABELS.get(animation_variant(p, anim), '')} | {companion} | {note} |"
        )
    lines += ["", "## 2. 语音入口表", "",
              "| 文件/素材 | 入口 | 用途 | 台词 |", "| --- | --- | --- | --- |"]
    if p.get("voiceDeclarations"):
        for item in p["voiceDeclarations"]:
            lines.append(
                f"| {item.get('file') or item.get('asset') or ''} | {item.get('entry') or '未标注'} "
                f"| {item.get('usage') or ''} | {str(item.get('text') or '').replace('|', '／')} |"
            )
    else:
        lines.append("| （未登记） | — | — | — |")
    lines += ["", "## 3. UI 用途声明", ""]
    if p.get("uiDeclarations"):
        for key, spec in sorted(p["uiDeclarations"].items()):
            lines.append(
                f"- {key}：自动裁切={'是' if spec.get('autoCrop') else '否'}，"
                f"遮罩={spec.get('mask') or 'auto'}，说明={spec.get('note') or '（无）'}"
            )
    else:
        lines.append("- （五类重点用途尚未声明取景/遮罩意图）")
    lines += ["", "## 4. 特效来源声明", ""]
    if p.get("effects"):
        for effect in p["effects"]:
            lines.append(
                f"- {effect.get('name') or effect.get('id')}："
                f"{effect.get('origin') or '未标注'}"
                f"{'（' + effect['originNote'] + '）' if effect.get('originNote') else ''}"
            )
    else:
        lines.append("- （尚未建立特效）")
    unmarked = []
    from action_presets import ACTION_PRESETS
    preset_slots = {item["slot"] for item in ACTION_PRESETS}
    for anim in p.get("animations", []):
        if animation_variant(p, anim) in ("composite", "mixed") and anim.get("includesCompanion") not in (True, False):
            unmarked.append(f"动作『{anim.get('name') or anim.get('slot')}』未说明是否包含召唤物")
        if anim.get("slot") not in preset_slots and not str(anim.get("purpose") or "").strip():
            unmarked.append(f"动作『{anim.get('name') or anim.get('slot')}』缺用途说明")
    if not p.get("voiceDeclarations") and (p.get("voices") or p.get("sounds")):
        unmarked.append("语音缺少入口/台词登记")
    lines += ["", "## 5. 未标注项清单", ""]
    if unmarked:
        lines.extend(f"- {item}" for item in unmarked)
    else:
        lines.append("- 无")
    lines.append("")
    return "\n".join(lines)


def amf_bytes(value):
    compressor = zlib.compressobj(level=9, wbits=-15)
    return compressor.compress(encode_amf3(value)) + compressor.flush()


def archive_files(raw):
    if len(raw) > MAX_ARCHIVE:
        raise StudioError("导入包超过 256 MiB")
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            infos = archive.infolist()
            if len(infos) > 16000 or sum(i.file_size for i in infos) > MAX_ARCHIVE:
                raise StudioError("解压后文件数量或总体积过大")
            files = {}
            folded = set()
            for info in infos:
                name = info.orig_filename
                path = PurePosixPath(name)
                if "\\" in name or path.is_absolute() or ".." in path.parts or ":" in name or any(part.endswith((".", " ")) for part in path.parts):
                    raise StudioError("压缩包含不安全路径")
                if (info.external_attr >> 16) & 0o170000 == 0o120000:
                    raise StudioError("压缩包不接受符号链接")
                if info.is_dir():
                    continue
                if name.casefold() in folded:
                    raise StudioError("压缩包含重复文件名")
                folded.add(name.casefold())
                if info.flag_bits & 1:
                    raise StudioError("请使用未加密的工程包")
                files[name] = archive.read(info)
            return files
    except (zipfile.BadZipFile, RuntimeError) as exc:
        raise StudioError("无法读取压缩包") from exc


def make_zip(files):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, raw in sorted(files.items()):
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, raw)
    return stream.getvalue()


def fresh_project(name="未命名角色", kind="original"):
    if kind not in ("original", "template"):
        raise StudioError("新建方式无效")
    return {"schema": "starpoint-character-studio-v1", "id": uuid.uuid4().hex, "name": str(name)[:100],
            "kind": kind, "revision": 0, "updated": time.time(), "identity": {"title": "", "element": "火", "rarity": 5, "race": "人", "role": "", "description": "", "author": "", "source": "", "code": "new_character"},
            "template": None, "assets": {}, "portraits": {"base": None, "evolved": None}, "crops": {},
            "animations": default_animations() if kind == "original" else [], "effects": [], "scene": {"duration": 120, "tracks": []}, "voices": [],
            "sounds": [], "notes": "", "warnings": [], "referenceFiles": [], "skill": {"name": "", "description": "", "implementation": "待接入"},
            "productionBrief": default_production_brief()}


class ProjectStore:
    def __init__(self, root):
        self.root = Path(root).resolve()
        normalized = self.root.as_posix().lower()
        if "/.cdn" in normalized or "/startpoint-cn-main" in normalized:
            raise StudioError("工程目录不能位于游戏资源或运行目录")
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.asset_catalog_cache = {}
        self.ui_source_cache = {}

    def directory(self, pid):
        directory = self.root / identifier(pid)
        if directory.is_symlink() or (directory.exists() and directory.resolve().parent != self.root):
            raise StudioError("工程路径无效")
        return directory

    def list(self):
        result = []
        for item in self.root.iterdir():
            if item.is_dir() and SAFE.fullmatch(item.name):
                try:
                    p = self.load(item.name)
                    result.append({k: p[k] for k in ("id", "name", "kind", "updated", "revision")})
                except (OSError, ValueError, KeyError, TypeError) as exc:
                    result.append({"id": item.name, "name": item.name, "kind": "recovery",
                                   "updated": 0, "revision": 0, "error": str(exc)})
        return sorted(result, key=lambda p: p["updated"], reverse=True)

    def create(self, name, kind="original"):
        p = fresh_project(name, kind)
        self.directory(p["id"]).mkdir(exist_ok=False)
        self._write(p)
        return p

    def load(self, pid):
        try:
            from project_storage import check_format, safe_child
            p = check_format(json.loads(safe_child(self.directory(pid), "project.json").read_bytes()))
            if p.get("id") != pid:
                raise StudioError("工程编号与文件夹不一致，请从历史记录恢复副本")
            p.setdefault("sounds", [])
            # Additive migration: old projects receive an in-memory default and
            # persist it on their next successful save; the raw JSON is untouched
            # until then and all legacy fields remain intact.
            had_production_brief = "productionBrief" in p
            p["productionBrief"] = normalize_production_brief(p)
            if not had_production_brief and p.get("template"):
                hydrate_from_project(p)
            from portrait_editor import hydrate
            hydrate(self, p)
            return p
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise StudioError("工程记录损坏，请在“工程与升级”中恢复历史副本") from exc
        except FileNotFoundError as exc:
            raise StudioError("找不到这个工程") from exc

    def _write(self, p):
        from project_storage import persist
        with self.lock:
            persist(self, p)

    def save(self, incoming):
        with self.lock:
            old = self.load(incoming.get("id"))
            if incoming.get("revision") != old["revision"]:
                raise StudioError("工程已在另一页面更新，请重新打开后继续")
            p = copy.deepcopy(incoming)
            p["assets"] = old["assets"]
            p["referenceFiles"] = old.get("referenceFiles", [])
            p["uiSources"] = old.get("uiSources", {})
            if "productionBrief" not in p:
                p["productionBrief"] = copy.deepcopy(old.get("productionBrief", default_production_brief()))
            if p.get("nativeGameplay") and old.get("nativeGameplay"):
                p["nativeGameplay"]["source"] = old["nativeGameplay"]["source"]
            validate(p)
            p["revision"] += 1
            p["updated"] = time.time()
            self._write(p)
            return p

    def add_asset(self, p, name, raw, category="image", enforce_limits=False):
        if len(raw) > FILE_BYTES:
            raise StudioError("单个素材超过 64 MiB")
        name = PurePosixPath(str(name).replace("\\", "/")).name[:160]
        ext = Path(name).suffix.lower()
        meta = {"name": name, "category": category}
        if ext == ".png":
            img = image_from(raw)
            edge = PIXEL_EDGE if category == "pixel" else EFFECT_EDGE if category == "effect" else None
            if enforce_limits and edge and max(img.size) > edge:
                raise StudioError(f"{name} 为 {img.width}×{img.height}，当前{'像素画稿' if category == 'pixel' else '特效贴图'}宽高各需 ≤ {edge} 像素；请导入单帧画稿或先缩小")
            raw = png_bytes(img)
            meta.update(width=img.width, height=img.height, mime="image/png", alpha=img.getchannel("A").getextrema()[0] < 255)
        elif ext in (".mp3", ".wav", ".ogg"):
            meta["mime"] = {".mp3": "audio/mpeg", ".wav": "audio/wav", ".ogg": "audio/ogg"}[ext]
        else:
            raise StudioError("可导入 PNG、WAV、MP3 或 OGG")
        if category in ("pixel", "effect"):
            # 来源标记（可手工改）：无后缀=plain，_sp 等后缀=composite。
            meta.setdefault("variant", asset_variant(name))
            meta.setdefault("sourceNote", "")
        digest = hashlib.sha256(raw).hexdigest()
        aid = digest[:24] + ext.replace(".", "_")
        meta.update(id=aid, file=aid + ext, sha256=digest, size=len(raw))
        directory = self.directory(p["id"]) / "assets"
        directory.mkdir(exist_ok=True)
        path = directory / meta["file"]
        if not path.exists():
            path.write_bytes(raw)
        p["assets"][aid] = meta
        return aid

    def asset_bytes(self, p, aid):
        identifier(aid)
        asset = p["assets"].get(aid)
        if not asset:
            raise StudioError("引用的素材不存在")
        filename = asset["file"]
        if Path(filename).name != filename or "\\" in filename:
            raise StudioError("素材路径无效")
        path = self.directory(p["id"]) / "assets" / filename
        if path.is_symlink():
            raise StudioError("素材不能使用链接")
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != asset["sha256"]:
            raise StudioError("素材文件已经在外部改变，请重新导入")
        return raw

    def media_asset(self, pid, aid):
        """Serve many atlas images without parsing the animation JSON per image.

        Only immutable asset metadata is cached, not editable project objects.
        Revisions invalidate it; stat checks also notice external replacements.
        """
        identifier(aid)
        with self.lock:
            stat = (self.directory(pid) / "project.json").stat()
            stamp = (stat.st_mtime_ns, stat.st_size)
            cached = self.asset_catalog_cache.get(pid)
            if cached is None or cached[0] != stamp:
                p = self.load(pid)
                cached = (stamp, p["assets"])
                self.asset_catalog_cache[pid] = cached
                if len(self.asset_catalog_cache) > 8:
                    self.asset_catalog_cache.pop(next(iter(self.asset_catalog_cache)))
            if aid not in cached[1]:
                raise StudioError("引用的素材不存在")
            meta = dict(cached[1][aid])
        raw = self.asset_bytes({"id": pid, "assets": {aid: meta}}, aid)
        return raw, meta["mime"]

    def upload(self, pid, files):
        with self.lock:
            p = self.load(pid)
            ids = []
            for item in files:
                ids.append(self.add_asset(p, item["name"], base64.b64decode(item["data"], validate=True), item.get("category", "image"), enforce_limits=True))
            p["revision"] += 1
            self._write(p)
            return {"project": p, "ids": ids}

    def import_pixel_images(self, pid, request):
        from pixel_import import import_images
        return import_images(self, pid, request)

    def add_action_presets(self, pid, revision, slots=None):
        from pixel_import import add_presets
        return add_presets(self, pid, revision, slots)

    def export(self, pid):
        p = self.load(pid)
        validate(p)
        files = {"project.json": json_bytes(p)}
        for aid, asset in p["assets"].items():
            files["assets/" + asset["file"]] = self.asset_bytes(p, aid)
        for rel in p.get("referenceFiles", []):
            path = PurePosixPath(rel)
            if not path.is_absolute() and ".." not in path.parts and "\\" not in rel:
                files["reference/" + rel] = (self.directory(pid) / "reference" / Path(rel)).read_bytes()
        files["交接说明.txt"] = ("星点角色工坊可编辑工程。用“打开工程 / 参考包”导入继续制作。\n这是创作工程，不是可直接安装的游戏补丁。\n").encode("utf-8")
        files["README-稿主必读.md"] = author_readme(p).encode("utf-8")
        files["declarations.json"] = json_bytes(declaration_payload(p))
        files["制作交接.json"] = json_bytes(export_handoff(p))
        return make_zip(files)

    def import_archive(self, raw):
        files = archive_files(raw)
        matches = [name for name in files if PurePosixPath(name).name == "project.json"]
        if len(matches) == 1:
            name = matches[0]
            prefix = name.removesuffix("project.json")
            from project_storage import check_format
            p = check_format(json.loads(files[name]))
            p.setdefault("sounds", [])
            p["id"] = uuid.uuid4().hex
            p["revision"] = 0
            p["updated"] = time.time()
            p["productionBrief"] = normalize_production_brief(p)
            validate(p)
            payloads = {}
            for aid, a in p["assets"].items():
                identifier(aid)
                filename = a.get("file", "")
                if PurePosixPath(filename).name != filename or "\\" in filename or ":" in filename:
                    raise StudioError("工程素材路径无效")
                payload = files.get(prefix + "assets/" + filename)
                if payload is None or hashlib.sha256(payload).hexdigest() != a.get("sha256"):
                    raise StudioError("工程素材缺失或校验不一致")
                if a.get("mime") == "image/png":
                    image_from(payload)
                payloads[filename] = payload
            references = {}
            for rel in p.get("referenceFiles", []):
                path = PurePosixPath(rel)
                if path.is_absolute() or ".." in path.parts or "\\" in rel or ":" in rel:
                    raise StudioError("参考文件路径无效")
                references[rel] = files[prefix + "reference/" + rel]
            directory = self.directory(p["id"])
            directory.mkdir(exist_ok=False)
            (directory / "assets").mkdir()
            for filename, payload in payloads.items():
                (directory / "assets" / filename).write_bytes(payload)
            for rel, payload in references.items():
                target = directory / "reference" / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(payload)
            from portrait_editor import hydrate
            hydrate(self, p)
            self._write(p)
            return p
        return self.import_reference(files)

    def import_reference(self, files):
        identity_keys = [k for k in files if k.endswith("reference/data_readable/identity.json")]
        if len(identity_keys) != 1:
            raise StudioError("请选择工坊工程包或角色专用参考包")
        base = identity_keys[0].removesuffix("data_readable/identity.json")
        identity = json.loads(files[identity_keys[0]])
        reference = {k[len(base):]: v for k, v in files.items() if k.startswith(base)}
        report = json.loads(reference.get("REFERENCE_REPORT.json", b"{}"))
        p = self.create(identity.get("name", "模板角色") + " · 新角色", "template")
        p["template"] = {"id": identity.get("character_id"), "name": identity.get("name"), "code": identity.get("code_name"), "version": report.get("resource_tail", "未记录"), "timingModel": "frame-end-v1"}
        p["identity"]["code"] = "new_" + str(identity.get("code_name", "character"))
        p["identity"].update({k: identity[k] for k in ("title", "element", "rarity") if k in identity})
        audio_catalog = json.loads(reference.get("audio_catalog.json", b"{}"))
        audio_by_file = {item["file"]: item for item in audio_catalog.get("items", []) if item.get("file")}
        p["warnings"].extend(report.get("warnings", []))
        p["warnings"].extend(audio_catalog.get("warnings", []))
        directory = self.directory(p["id"]) / "reference"
        for name, payload in reference.items():
            if Path(name).suffix.lower() not in (".json", ".png", ".mp3", ".wav", ".deflate", ".csv"):
                continue
            target = directory / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
            p["referenceFiles"].append(name)
        p["uiSources"] = {}
        for name, payload in reference.items():
            if name.startswith("ui/") and name.endswith(".png"):
                aid = self.add_asset(p, Path(name).name, payload, "portrait")
                from portrait_editor import source_key
                key = source_key(name)
                if key:
                    p["uiSources"][key] = aid
                for form, suffix in (("base", "_0.png"), ("evolved", "_1.png")):
                    if "full_shot_" in name and name.endswith(suffix):
                        p["portraits"][form] = aid
            elif name.startswith(("voice/", "sound/")) and Path(name).suffix.lower() in (".mp3", ".wav", ".ogg"):
                sound = name.startswith("sound/")
                meta = audio_by_file.get(name, {})
                audio_name = meta.get("logical", name).rsplit("/", 1)[-1]
                if not Path(audio_name).suffix:
                    audio_name += Path(name).suffix
                aid = self.add_asset(p, audio_name, payload, "sfx" if sound else "voice")
                relative = name.removeprefix("voice/")
                usage = meta.get("usage", "skill_sfx" if sound else voice_usage(relative))
                p["sounds" if sound else "voices"].append({"id": uuid.uuid4().hex[:12], "name": meta.get("logical", relative).rsplit("/", 1)[-1], "asset": aid,
                    "usage": usage, "text": meta.get("text", ""), "logical": meta.get("logical", ""), "sourceFile": name})
        for variant, stem, sheet_name in (("normal", "pixelart", "sprite_sheet"), ("special", "special", "special_sprite_sheet")):
            paths = [f"pixelart/{sheet_name}.png", f"pixelart/{sheet_name}.atlas.json", f"pixelart/{stem}.timeline.json"]
            if not all(path in reference for path in paths):
                continue
            sheet = image_from(reference[paths[0]])
            atlas = json.loads(reference[paths[1]])
            timeline = json.loads(reference[paths[2]])
            frame = json.loads(reference.get(f"pixelart/{stem}.frame.json", b"{}"))
            entries = {}
            for entry in atlas:
                match = re.search(r"(\d+)$", str(entry.get("n", "")))
                if not match:
                    continue
                cell = atlas_crop(sheet, entry)
                aid = self.add_asset(p, Path(entry["n"]).name + ".png", png_bytes(cell), "pixel")
                entries[int(match.group(1))] = (aid, int(entry.get("fx", 0)), int(entry.get("fy", 0)), int(entry.get("fw", 256)), int(entry.get("fh", 256)))
            keys = sorted(entries)
            if not keys:
                continue
            for seq in timeline.get("sequences", []):
                begin, end = int(seq["begin"]), int(seq["end"])
                if end - begin + 1 > MAX_TICKS or begin > end:
                    p["warnings"].append(f"{variant}/{seq['name']} 原始时间轴 {begin}–{end} 无效或超过 {MAX_TICKS} 帧，暂不生成此动作；原始文件保留在参考素材中")
                    continue
                clips = []
                for tick in range(begin, end + 1):
                    # Client FrameAnimationSource fills imageFrames up to each
                    # numbered endpoint, then indexes it at playbackFrame - 1.
                    index = bisect.bisect_left(keys, tick)
                    if tick <= 0 or index >= len(keys):
                        index = 0  # AS3 int(undefined) used by the native player.
                    aid, fx, fy, w, h = entries[keys[index]]
                    clip = {"asset": aid, "hold": 1, "x": -fx + float(frame.get("x", -w / 2)), "y": -fy + float(frame.get("y", -h / 2)), "flip": False, "rotation": 0, "scale": 1, "opacity": 1}
                    if clips and all(clips[-1][k] == clip[k] for k in clip if k != "hold"):
                        clips[-1]["hold"] += 1
                    else:
                        clips.append(clip)
                p["animations"].append({"id": uuid.uuid4().hex[:12], "name": LABELS.get(seq["name"], seq["name"]), "slot": seq["name"], "variant": variant, "kind": seq.get("kind", "once"), "fps": 60, "runtimeSpeed": 0.5 if seq["name"] in ("walk_front", "walk_back") else 1, "frameScale": frame.get("scale", 6), "clips": clips})
        self.import_effects(p, reference)
        hydrate_from_project(p)
        self._write(p)
        return p

    def import_effects(self, p, reference):
        for path in sorted(reference):
            if not path.startswith("effect/") or not path.endswith(".parts.json"):
                continue
            parts = json.loads(reference[path])
            timeline_path = path.replace(".parts.json", ".timeline.json")
            folder = PurePosixPath(path).parts[1]
            atlas_path = f"effect/{folder}/{folder}.atlas.json"
            png_path = f"effect/{folder}/{folder}.png"
            if any(k not in reference for k in (timeline_path, atlas_path, png_path)):
                p["warnings"].append(f"{folder} 特效素材不完整")
                continue
            timeline = json.loads(reference[timeline_path])
            atlas = json.loads(reference[atlas_path])
            sheet = image_from(reference[png_path])
            cells = {}
            for record in atlas:
                cells[record["n"]] = (self.add_asset(p, Path(record["n"]).name + ".png", png_bytes(atlas_crop(sheet, record)), "effect"), record)
            capability = []
            if parts.get("m"):
                capability.append("包含暂未支持的 MovieClip 结构")
            for seq in timeline.get("sequences", []):
                effect = {"id": uuid.uuid4().hex[:12], "name": Path(path).name.removesuffix(".parts.json") + " · " + seq["name"], "kind": seq.get("kind", "once"), "fps": 60, "frameScale": parts.get("s", 1), "clips": [], "native": {"path": path, "sequence": seq["name"], "begin": seq["begin"], "end": seq["end"]}, "issues": list(capability), "layers": {}, "nativeFrames": []}
                effect["soundEvents"] = []
                for sound in timeline.get("sounds", []):
                    begin = sound.get("begin", 1)
                    if not seq["begin"] <= begin <= seq["end"]:
                        continue
                    found = next((s for s in p.get("sounds", []) if s.get("logical") == sound.get("path", "").removesuffix(".mp3")), None)
                    volume = sound.get("volume", -1)
                    event = {"id": uuid.uuid4().hex[:12], "path": sound.get("path", ""), "start": begin - seq["begin"],
                             "asset": found["asset"] if found else None, "volume": max(0, min(1, volume*.1)) if volume != -1 else 1,
                             "loop": sound.get("loop", 1), "end": sound["end"]-seq["begin"] if sound.get("end", -1) != -1 else -1,
                             "source": sound, "enabled": True}
                    effect["soundEvents"].append(event)
                    if not found:
                        effect["issues"].append("未收录音效：" + sound.get("path", ""))
                    if volume > 10:
                        effect["issues"].append("原始声音增益超过当前编辑器上限：" + sound.get("path", ""))
                if not capability:
                    try:
                        frames = flatomo._build_frames(parts)
                        begin, end = int(seq["begin"]), int(seq["end"])
                        if end - begin + 1 > MAX_TICKS:
                            raise StudioError("特效时长超过上限")
                        for tick in range(begin - 1, end):
                            cmds = native_commands(frames, parts, cells, 0, tick)
                            effect["nativeFrames"].append(cmds)
                            for cmd in cmds:
                                effect["layers"].setdefault(cmd["asset"], {"name": p["assets"][cmd["asset"]]["name"], "asset": cmd["asset"], "x": 0, "y": 0, "visible": True})
                            for cmd in cmds:
                                if cmd["blend"] != 0:
                                    issue = f"包含未校准的混合模式 {cmd['blend']}"
                                    if issue not in effect["issues"]:
                                        effect["issues"].append(issue)
                    except (KeyError, IndexError, ValueError, TypeError) as exc:
                        effect["issues"].append(str(exc))
                        effect["nativeFrames"] = []
                if effect["nativeFrames"]:
                    from effect_channels import make_channels
                    make_channels(effect)
                p["effects"].append(effect)


def atlas_crop(sheet, entry):
    x, y, w, h = (int(entry[k]) for k in ("x", "y", "w", "h"))
    if min(x, y) < 0 or min(w, h) <= 0 or x + w > sheet.width or y + h > sheet.height:
        raise StudioError("图集切片超出边界")
    result = sheet.crop((x, y, x + w, y + h))
    if entry.get("r"):
        result = result.transpose(Image.Transpose.ROTATE_90)
    return result


def native_commands(frames, parts, cells, group, tick, matrix=(1, 0, 0, 1, 0, 0), alpha=1, depth=0, color_transform=(1, 0, 0, 0), blend=0, channel_path=()):
    if depth > 40:
        raise StudioError("特效图层嵌套过深")
    result = []
    for state_index, state in enumerate(frames[group][tick]):
        segment_id=getattr(state,'segment_id',-1)
        instance_path=channel_path+(segment_id if segment_id>=0 else state_index,)
        m = flatomo._concat(state.parameters.matrix, matrix)
        a = alpha * state.parameters.alpha
        packed = state.parameters.color
        multiplier = ((packed >> 24) & 255) / 100
        color = (color_transform[0]*multiplier, *(color_transform[0]*((packed >> shift) & 255)+color_transform[i+1] for i, shift in enumerate((16, 8, 0))))
        mode = state.parameters.blend or blend
        if state.kind == 2:
            children = native_commands(frames, parts, cells, state.item_id, state.child_frame, m, a, depth + 1, color, mode, instance_path)
            # A transform on an ancestor also affects rendering capability.
            # Keep the unsupported marker even when leaf parameters are normal.
            for command in children:
                if state.parameters.color != 0x64000000:
                    command["color"] = state.parameters.color
            result.extend(children)
        elif state.kind == 0:
            path = parts["i"][state.item_id]["p"]
            if path not in cells:
                raise StudioError("特效引用的贴图不存在: " + path)
            aid, record = cells[path]
            result.append({"asset": aid, "matrix": list(m), "alpha": a, "fx": record.get("fx", 0), "fy": record.get("fy", 0), "blend": mode, "color": packed, "colorTransform": list(color), "channel":"ch_"+hashlib.sha256(str(instance_path).encode()).hexdigest()[:16], "channelOrder":list(instance_path)})
        else:
            raise StudioError("该特效含未支持的 MovieClip")
    return result


def validate(p):
    from project_storage import check_format
    check_format(p)
    from native_gameplay import validate_native
    validate_native(p.get("nativeGameplay"))
    if p.get("schema") != "starpoint-character-studio-v1":
        raise StudioError("工程格式不受支持")
    p["productionBrief"] = normalize_production_brief(p)
    identifier(p.get("id"))
    if "gameplay" in p:
        normalize_gameplay(p)
    if not isinstance(p.get("assets"), dict) or len(p["assets"]) > 10000:
        raise StudioError("素材清单无效")
    for aid in p["assets"]:
        identifier(aid)
    ids = set()
    for group in ("animations", "effects"):
        for anim in p.get(group, []):
            identifier(anim["id"])
            if anim["id"] in ids:
                raise StudioError("动作或特效标识重复")
            ids.add(anim["id"])
            if anim.get("kind") not in ("once", "loop", "pass", "stop"):
                raise StudioError("动作播放模式无效")
            integer(anim.get("fps", 60), 1, 120, "帧率")
            number(anim.get("frameScale", 1), 0.05, 20, "游戏显示倍率")
            number(anim.get("runtimeSpeed", 1), 0.1, 4, "游戏播放倍率")
            for event in anim.get("soundEvents", []):
                identifier(event["id"])
                integer(event.get("start"), 0, MAX_TICKS - 1, "声音开始帧")
                number(event.get("volume", 1), 0, 1, "声音音量")
                integer(event.get("loop", 1), -1, 100, "声音播放次数")
                end = integer(event.get("end", -1), -1, MAX_TICKS, "声音结束帧")
                if end != -1 and end <= event["start"]:
                    raise StudioError("声音结束帧必须晚于开始帧")
                if event.get("asset") and not p["assets"].get(event["asset"], {}).get("mime", "").startswith("audio/"):
                    raise StudioError("声音事件引用了不存在的音频")
            if len(anim.get("nativeFrames", [])) > MAX_TICKS:
                raise StudioError("骨架动画超过帧数上限")
            for layer_id, layer in anim.get("layers", {}).items():
                identifier(layer_id)
                aid = layer.get("asset")
                if aid not in p["assets"] or p["assets"][aid].get("mime") != "image/png":
                    raise StudioError("特效图层引用了不存在的图片")
                number(layer.get("x", 0), -4096, 4096, "图层 X 偏移")
                number(layer.get("y", 0), -4096, 4096, "图层 Y 偏移")
            from effect_channels import validate_channels
            validate_channels(anim,p["assets"])
            total = 0
            for clip in anim.get("clips", []):
                if clip.get("asset") not in p["assets"]:
                    raise StudioError("动作引用了不存在的图片")
                if p["assets"][clip["asset"]].get("mime") != "image/png":
                    raise StudioError("动作画稿必须是 PNG")
                total += integer(clip.get("hold"), 1, MAX_TICKS, "停留帧数")
                for key, lo, hi in (("x", -4096, 4096), ("y", -4096, 4096), ("rotation", -360, 360), ("scale", 0.05, 20), ("opacity", 0, 1)):
                    number(clip.get(key, {"scale": 1, "opacity": 1}.get(key, 0)), lo, hi, key)
            if total > MAX_TICKS:
                raise StudioError("单个动作超过 4096 帧")
    from portrait_editor import validate_ui
    validate_ui(p)
    for aid in p.get("portraits", {}).values():
        if aid is not None and (aid not in p["assets"] or p["assets"][aid].get("mime") != "image/png"):
            raise StudioError("立绘引用无效")
    scene = p.get("scene", {})
    integer(scene.get("duration", 120), 1, MAX_TICKS, "演出时长")
    if not isinstance(scene.get("tracks", []), list) or len(scene.get("tracks", [])) > 512:
        raise StudioError("组合预览轨道最多 512 条")
    for track in scene.get("tracks", []):
        identifier(track["id"])
        integer(track.get("start", 0), 0, MAX_TICKS, "轨道开始帧")
        if "freezeFrame" in track:
            integer(track["freezeFrame"], 0, MAX_TICKS - 1, "固定画面帧")
        end = integer(track.get("end", -1), -1, MAX_TICKS, "轨道结束帧")
        if end != -1 and end <= track.get("start", 0):
            raise StudioError("轨道结束帧必须晚于开始帧")
        if track.get("playMode") is not None and track["playMode"] not in ("once", "loop", "pass", "stop"):
            raise StudioError("轨道播放方式无效")
        kind = track.get("type")
        if kind not in ("actor", "effect", "audio"):
            raise StudioError("演出轨道类型无效")
        if kind in ("actor", "effect"):
            group = p["animations"] if kind == "actor" else p["effects"]
            if track.get("ref") not in {a["id"] for a in group}:
                raise StudioError("演出轨道引用的动作已被删除或类型不匹配")
        if kind == "audio" and not p["assets"].get(track.get("ref"), {}).get("mime", "").startswith("audio/"):
            raise StudioError("演出音频不存在")
        for key, lo, hi, default in (("x", -4096, 4096, 0), ("y", -4096, 4096, 0), ("scale", .05, 20, 1), ("rotation", -360, 360, 0), ("opacity", 0, 1, 1), ("volume", 0, 1, 1), ("speed", .1, 4, 1)):
            number(track.get(key, default), lo, hi, "轨道 " + key)
    for voice in p.get("voices", []) + p.get("sounds", []):
        identifier(voice["id"])
        if not p["assets"].get(voice.get("asset"), {}).get("mime", "").startswith("audio/"):
            raise StudioError("语音引用无效")
    validate_declarations(p)
    return True


def project_checks(p):
    issues = []
    from portrait_editor import selection

    def issue(level, page, text, position="", fix="", **extra):
        parts = [text]
        if position:
            parts.append("位置：" + position)
        if fix:
            parts.append("改法：" + fix)
        issues.append({"level": level, "page": page, "text": "　".join(parts),
                       "position": position, "fix": fix, **extra})

    for key, label in (("base", "基础立绘"), ("evolved", "进化立绘")):
        if not p["portraits"].get(key):
            issues.append({"level": "todo", "page": "portraits", "text": f"尚未提供{label}"})
        missing = [UI_SLOTS[slot][0] for slot in UI_SLOTS if slot != "full_shot" and not selection(p, key, slot).get("asset")]
        if missing:
            issues.append({"level": "todo", "page": "portraits", "text": f"{'基础' if key == 'base' else '进化'}形态有 {len(missing)} 项界面图片待导入或裁剪：" + "、".join(missing)})
    if not p["animations"]:
        issues.append({"level": "todo", "page": "animations", "text": "尚未建立角色动作"})
    if not p["effects"]:
        issues.append({"level": "todo", "page": "effects", "text": "尚未建立技能特效，可导入模板或新建序列特效"})
    if not p["voices"]:
        issues.append({"level": "todo", "page": "voices", "text": "尚未提供语音和台词；无配音角色可在交接备注说明"})
    if not p.get("sounds"):
        issues.append({"level": "todo", "page": "voices", "text": "尚未提供技能/战斗音效；角色喊声与技能音效需要分别准备"})
    if not p["scene"]["tracks"]:
        issues.append({"level": "info" if p.get("template") else "todo", "page": "scene",
                       "text": "尚未生成技能演示，可打开技能预览检查并生成可用演示。" if p.get("template") else "尚未编排小人、特效与声音的整体演出"})
    for group, page in (("animations", "animations"), ("effects", "effects")):
        for anim in p[group]:
            length = len(anim.get("nativeFrames", [])) or sum(c["hold"] for c in anim.get("clips", []))
            for event in anim.get("soundEvents", []):
                if not event.get("asset"):
                    issues.append({"level": "todo", "page": page, "id": anim["id"], "text": anim["name"] + "有未绑定的声音事件"})
                elif event["start"] >= length:
                    issues.append({"level": "warning", "page": page, "id": anim["id"], "text": anim["name"] + "有声音安排在画面结束之后"})
            for issue in anim.get("issues", []):
                issues.append({"level": "warning", "page": page, "id": anim["id"], "text": anim["name"] + "：" + issue})
            if not anim.get("clips") and not anim.get("nativeFrames"):
                issues.append({"level": "todo", "page": page, "id": anim["id"], "text": anim["name"] + "没有可播放画面"})
    # ------------------------------------------------------------------
    # 来源与声明（2026-10-06 凉月复盘；提案《角色工坊交互改进提案》第 3 节）
    # ------------------------------------------------------------------
    from action_presets import ACTION_PRESETS
    preset_slots = {item["slot"] for item in ACTION_PRESETS}
    for anim in p["animations"]:
        if anim.get("native"):
            continue
        variant = animation_variant(p, anim)
        slot = anim.get("slot", "")
        companion = anim.get("includesCompanion", "")
        if slot in BASE_STATE_SLOTS and variant in ("composite", "mixed") and companion is not True:
            clips = sum(1 for clip in anim.get("clips", [])
                        if clip_variant(p, clip.get("asset")) == "composite")
            issue("warning", "animations",
                  f"{anim.get('name') or slot} 等基础状态有 {clips} 段画稿疑似带附属物（_sp 合成帧）",
                  position=f"像素动作 → {anim.get('name') or slot}（{slot}）",
                  fix="若设计上确实要带，请在『是否包含召唤物』改为“是”并写明出现时机；"
                      "否则请替换为无后缀的纯本体帧",
                  id=anim["id"])
        elif slot in COMPANION_STATE_SLOTS and variant in ("composite", "mixed") and companion not in (True, False):
            issue("todo", "animations",
                  f"『{anim.get('name') or slot}』尚未说明是否带召唤物",
                  position=f"像素动作 → {anim.get('name') or slot}（{slot}）",
                  fix="在该动作的『附属物说明』中二选一填写“带/不带”，否则制作方只能按默认处理",
                  id=anim["id"])
        if variant == "mixed" and companion not in (True, False):
            issue("warning", "animations",
                  f"动作『{anim.get('name') or slot}』同时导入了纯本体帧和合成帧",
                  position=f"像素动作 → {anim.get('name') or slot}",
                  fix="只保留一套，或明确说明两套各自的用途", id=anim["id"])
        if slot not in preset_slots and not str(anim.get("purpose") or "").strip():
            issue("todo", "animations",
                  f"自定义动作『{anim.get('name') or slot}』还没有用途说明",
                  position=f"像素动作 → {anim.get('name') or slot}",
                  fix="填写用途、帧数、每帧停留与循环方式", id=anim["id"])
    for effect in p["effects"]:
        if not str(effect.get("origin") or "").strip():
            issue("warning", "effects",
                  f"技能特效『{effect.get('name') or effect.get('id')}』未声明来源",
                  position=f"技能制作 → {effect.get('name') or effect.get('id')}",
                  fix="选择：复用（某角色）/ 重皮（模板+配色）/ 完全原创（四件套）",
                  id=effect["id"])
    declared_voice_ids = {str(item.get("asset") or item.get("file") or "")
                          for item in p.get("voiceDeclarations") or []}
    missing_voice = [voice for voice in p.get("voices", [])
                     if voice.get("asset") not in declared_voice_ids
                     and voice.get("id") not in declared_voice_ids]
    if missing_voice:
        issue("todo", "voices",
              f"有 {len(missing_voice)} 条语音没有登记入口分类或台词文本",
              position="声音与台词 → 语音对照表",
              fix="补 文件 / ally·battle·home / 用途 / 台词 四列")
    if not p.get("voiceDeclarations") and (p.get("voices") or p.get("sounds")):
        issue("info", "voices", "尚未登记语音入口对照表",
              position="声音与台词", fix="按《稿主资源提供指南》补入口与台词登记")
    for key in KEY_UI_SLOTS:
        entries = [value for name, value in (p.get("uiDeclarations") or {}).items()
                   if str(name).endswith(key)]
        if entries:
            continue
        replaced = any(
            selection(p, form, key).get("mode") == "image"
            and selection(p, form, key).get("asset")
            for form in ("base", "evolved")
        )
        if replaced:
            issue("info", "portraits",
                  f"『{UI_SLOTS[key][0]}』使用了单独替换图，但未声明取景/遮罩意图",
                  position=f"立绘与界面 → {UI_SLOTS[key][0]}",
                  fix="补充声明：是否禁止从母版自动裁切、是否需要形状遮罩")
    for warning in p.get("warnings", []):
        issues.append({"level": "warning", "page": "checks", "text": warning})
    issues.extend(production_checks(p))
    issues.append({"level": "info", "page": "identity", "text": "游戏接入待完成：角色与技能数据、平台纹理、存档兼容及真机验收由制作方确认"})
    brief = p.get("productionBrief") or default_production_brief()
    return {"issues": issues, "assets": len(p["assets"]), "animations": len(p["animations"]), "effects": len(p["effects"]),
            "production": {"status": brief["workflow"]["status"], "resources": len(brief["resources"]), "voices": len(brief["voices"])},
            "gameReady": False}
