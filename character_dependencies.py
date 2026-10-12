"""Read-only dependency closure for frozen portable authoring resources.

Finite resource closure is distinct from character semantics and runtime/native
acceptance. Catalog entries carry byte identities; declarations never prove that
an unknown command, native ability mapping, or dynamic load has been resolved.
"""
from __future__ import annotations

import copy
import hashlib
import io
import json
import math
import re
import zlib
from collections import Counter
from pathlib import PurePosixPath

SCHEMA = "character-dependencies-v1"
DOMAINS = ("skill", "pixelart", "special", "ability", "summon", "powerFlip", "shared", "ui", "cutin")
LIMIT = 16 * 1024 * 1024
MAX_VISITS = 100000
MAX_NESTING = 128
MAX_IMAGE_PIXELS = 32_000_000
# Names checked against the retained ActionDslAssetResolver and enum source.
# Only no-resource cases and callback-only cases are admitted here.
SCALAR_COMMANDS = frozenset(("Trace", "RemoveEvent", "RemoveEventFromOwner", "ShakeCamera",
    "HideEffect", "HideEffectFromOwner", "MoveBall", "StopBall", "MoveHitArea", "RotateHitArea",
    "EraseHitArea", "HideCharacter", "AddCombo", "TargetMate", "ConsumeUniqueCondition",
    "SuppressBallActivity", "RemoveCollider", "RemoveColliderFromOwner", "SuppressSkill",
    "BindConditionAccumulationVariable", "BindCoffinRevivalCountVariableOf", "BindCoffinRevivalCountVariable",
    "MultiballNumberVariable", "NotifyPowerflipEnd", "FadeOutBgm"))
CALLBACK_COMMANDS = frozenset(("FindAllSubjects", "FindNearSubjects", "CreateReferencePoint",
    "CreateReferencePointAtSpecifiedPosition", "SetHitAreaSomeHitsWithAnyTargetHandler",
    "SetHitAreaSomeHitsWithSpecificTargetHandler", "SetHitAreaTerminateHandler", "ConditionalsHitAreaHitCount",
    "ConditionalsHealthPointRatio", "ConditionalsHealthPointRatioOf", "ConditionalsSkillPoint200Percent",
    "ConditionalsFeverMode", "ConditionalsCombo", "ConditionalsNumCoffins", "IfThisCharacterIsBoss",
    "IfThisCharacterIsSpecificBoss", "IfThisCharacterIsSpecificFunnel", "IfThisCharacterIsLeader",
    "ConditionalsNumExecutionsOddOrEven", "ConditionalsNumExecutions2", "ConditionalsNumExecutions3",
    "ConditionalsNumExecutions4", "ConditionalsNumExecutions5", "ConditionalsChangeSkillFlag",
    "CreateWallDistanceDetector", "CreatePointsDistanceDetector", "ConditionalsCoffinCountSubject",
    "ConditionalsCoffinCountFilter", "ConditionalsMainOrUnison", "FindMultiballSubjects",
    "ConditionalsRelativePositionVertical", "ConditionalsProbability", "ProbabilityWeight"))
EVENTS = frozenset(("Wait", "Repeat", "CollisionOfBallAndEnemy", "CollisionOfBallAndSpecificEnemy",
    "CollisionOfSpecificBallAndSpecificEnemy", "ActivatedMultiballOfExecutorSelf"))
RESOLVER_BASIS = "retained ActionDslAssetResolver.eval/resolveEffect; core flatomo _build_frames; studio_compile"


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _path(value):
    if not isinstance(value, str) or not value or "\\" in value or ":" in value or value.startswith("/") or any(p in (".", "..", "") for p in value.split("/")):
        raise ValueError("依赖逻辑路径必须在工程资源范围内")
    return value


def _integer(value):
    # AMF numbers exported as doubles retain exact signed packed uint32 values.
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value) and value == int(value)


def _sound_target(path, catalog):
    if not isinstance(path, str):
        return path
    return path if path in catalog or path.endswith(".mp3") else path + ".mp3"


def validate(project):
    value = project.get("dependencyScope")
    if value is None:
        return
    if not isinstance(value, dict):
        raise ValueError("dependencyScope必须是对象")
    if value.get("kind", "finite-resources") not in ("finite-resources", "character-semantic", "project-resources"):
        raise ValueError("dependencyScope.kind不受支持")
    for key in ("roles", "forms", "switches"):
        if key in value and (not isinstance(value[key], list) or any(not isinstance(v, str) or not v for v in value[key])):
            raise ValueError("dependencyScope." + key + "必须是字符串数组")
    if any(v not in ("main", "unison", "leader") for v in value.get("roles", [])):
        raise ValueError("依赖角色仅支持main/unison/leader")
    if "element" in value and (not _integer(value["element"]) or not 0 <= value["element"] <= 6):
        raise ValueError("冻结element必须是已查证原生0至6枚举")
    roots = value.get("roots", [])
    if not isinstance(roots, list) or len(roots) > 10000:
        raise ValueError("依赖根必须是最多10000项的数组")
    for root in roots:
        if not isinstance(root, dict):
            raise ValueError("依赖根必须是对象")
        _path(root.get("logical"))
        for key in ("bucket", "collection", "requester", "category", "source", "kind", "resourceOwner"):
            if key in root and not isinstance(root[key], str):
                raise ValueError("依赖根" + key + "必须是字符串")
        if "layer" in root and (isinstance(root["layer"], bool) or root["layer"] not in (None, 0, 1, "independent")):
            raise ValueError("依赖根layer无效")
        if "element" in root and (not _integer(root["element"]) or not 0 <= root["element"] <= 6):
            raise ValueError("依赖根element必须是已查证原生0至6枚举")
        for key in ("roles", "forms", "switches"):
            if key in root and (not isinstance(root[key], list) or any(not isinstance(v, str) or not v for v in root[key])):
                raise ValueError("依赖根" + key + "必须是字符串数组")
        if "lookup" in root and root["lookup"] not in ("exact-texture", "standalone-file-texture"):
            raise ValueError("界面纹理lookup需要已核读取类型")
        if "requiredLayouts" in root and (not isinstance(root["requiredLayouts"], list) or
                len(root["requiredLayouts"]) > 1000 or
                any(not isinstance(item, str) or not item for item in root["requiredLayouts"])):
            raise ValueError("复用界面requiredLayouts必须是有界字符串数组")
    domains = value.get("domains", {})
    if not isinstance(domains, dict) or any(k not in DOMAINS for k in domains):
        raise ValueError("依赖语义域无效")
    for domain in domains.values():
        if not isinstance(domain, dict) or domain.get("status") not in ("included", "not-applicable", "pending"):
            raise ValueError("依赖语义域必须含有效status")
        if "roots" in domain and (not isinstance(domain["roots"], list) or any(not isinstance(v, str) or not v for v in domain["roots"])):
            raise ValueError("语义域根必须是逻辑路径数组")
        if "evidence" in domain:
            proof = domain["evidence"]
            if not isinstance(proof, dict) or not isinstance(proof.get("logical"), str) or not re.fullmatch(r"[0-9a-f]{64}", str(proof.get("sha256", ""))):
                raise ValueError("语义域evidence需要logical与sha256")
            _path(proof["logical"])
    canonical(value)


def _kind(name):
    if name.endswith((".ui.amf3.deflate", ".ui.json")):
        return "native-ui"
    if name.endswith((".html.deflate", ".html")):
        return "native-html"
    for suffix, kind in ((".action.dsl.amf3.deflate", "dsl"), (".esdl.amf3.deflate", "enemy-dsl"), (".parts.amf3.deflate", "parts"), (".frame.amf3.deflate", "frame"),
                         (".timeline.amf3.deflate", "timeline"), (".atlas.amf3.deflate", "atlas"),
                         (".parts.json", "parts"), (".frame.json", "frame"), (".timeline.json", "timeline"), (".atlas.json", "atlas")):
        if name.endswith(suffix):
            return kind
    return "texture" if name.endswith(".png") else "sound" if name.endswith(".mp3") else "opaque"


def _decode_amf(raw):
    from bridge import AMF3Reader
    decoder = zlib.decompressobj(-15)
    decoded = decoder.decompress(raw, LIMIT + 1)
    if len(decoded) > LIMIT or decoder.unconsumed_tail or decoder.unused_data or not decoder.eof:
        raise ValueError("AMF解压超过有界上限、流不完整或含尾随压缩数据")

    class BoundedReader(AMF3Reader):
        def __init__(self, data):
            super().__init__(data)
            self.depth = 0
            self.visits = 0

        def budget(self):
            self.visits += 1
            if self.visits > MAX_VISITS:
                raise ValueError("AMF节点/字符串数量超过有界上限")

        def read_byte(self):
            if self.pos >= len(self.data):
                raise ValueError("AMF流截断")
            return super().read_byte()

        def peek_header(self):
            begin = self.pos
            value = self.read_u29()
            self.pos = begin
            return value

        def read_string_body(self):
            self.budget()
            begin = self.pos
            header = self.read_u29()
            if header & 1 and (header >> 1) > len(self.data) - self.pos:
                raise ValueError("AMF字符串长度超过剩余字节")
            self.pos = begin
            return super().read_string_body()

        def read_value(self):
            self.budget()
            self.depth += 1
            try:
                if self.depth > 160:
                    raise ValueError("AMF嵌套深度超过有界上限")
                if self.pos >= len(self.data) or (self.data[self.pos] == 5 and len(self.data) - self.pos < 9):
                    raise ValueError("AMF值截断")
                return super().read_value()
            finally:
                self.depth -= 1

        def read_array(self):
            header = self.peek_header()
            if header & 1 and (header >> 1) > MAX_VISITS:
                raise ValueError("AMF数组声明数量超过有界上限")
            return super().read_array()

        def read_object(self):
            header = self.peek_header()
            if header & 3 == 3 and (header >> 4) > MAX_VISITS:
                raise ValueError("AMF对象字段声明数量超过有界上限")
            return super().read_object()

    reader = BoundedReader(decoded)
    data = reader.read_value()
    if reader.pos != len(decoded):
        raise ValueError("AMF单值后含尾随数据")
    return data


def _decode_json(raw):
    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise ValueError("JSON对象包含重复键")
            result[key] = value
        return result

    def constant(value):
        raise ValueError("JSON包含非有限数值: " + value)

    data = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=pairs, parse_constant=constant)
    pending, visits = [(data, 0)], 0
    while pending:
        node, depth = pending.pop()
        visits += 1
        if visits > MAX_VISITS or depth > 160:
            raise ValueError("JSON节点数量或嵌套深度超过有界上限")
        values = list(node.values()) if isinstance(node, dict) else node if isinstance(node, list) else ()
        if len(values) + len(pending) + visits > MAX_VISITS:
            raise ValueError("JSON声明容器数量超过有界上限")
        pending.extend((value, depth + 1) for value in values)
    return data


def _decode_png(raw):
    from PIL import Image
    if raw[:8] not in (b"\x89PNG\r\n\x1a\n", b"\x89png\r\n\x1a\n"):
        raise ValueError("PNG存储头不匹配真实/游戏PNG格式")
    data = b"\x89PNG\r\n\x1a\n" + raw[8:]
    position, chunks = 8, []
    while position < len(data):
        if len(data) - position < 12:
            raise ValueError("PNG chunk截断")
        length = int.from_bytes(data[position:position + 4], "big")
        end = position + 12 + length
        if end > len(data):
            raise ValueError("PNG chunk长度超过文件")
        kind = data[position + 4:position + 8]
        payload = data[position + 4:position + 8 + length]
        checksum = int.from_bytes(data[position + 8 + length:end], "big")
        if zlib.crc32(payload) & 0xffffffff != checksum:
            raise ValueError("PNG chunk CRC不匹配")
        chunks.append(kind)
        if len(chunks) > MAX_VISITS:
            raise ValueError("PNG chunk数量超过有界上限")
        if len(chunks) == 1 and (kind != b"IHDR" or length != 13):
            raise ValueError("PNG缺有效首IHDR")
        if len(chunks) == 1:
            width = int.from_bytes(data[position + 8:position + 12], "big")
            height = int.from_bytes(data[position + 12:position + 16], "big")
            if width <= 0 or height <= 0 or width * height > MAX_IMAGE_PIXELS:
                raise ValueError("PNG尺寸无效或像素数量超过有界上限")
        if kind == b"IEND":
            if length != 0 or end != len(data):
                raise ValueError("PNG IEND无效或含尾随数据")
            position = end
            break
        position = end
    if not chunks or chunks[-1] != b"IEND" or b"IDAT" not in chunks or chunks.count(b"IHDR") != 1:
        raise ValueError("PNG必需chunk结构不完整")
    with Image.open(io.BytesIO(data)) as image:
        if image.width * image.height > MAX_IMAGE_PIXELS:
            raise ValueError("PNG像素数量超过有界上限")
        image.verify()
    with Image.open(io.BytesIO(data)) as image:
        image.load()
        return image.width, image.height


def resource_catalog(files):
    """Decode exact file-map members, including AMF, without reading game assets."""
    catalog = {}
    for name, raw in files.items():
        _path(name)
        if not isinstance(raw, bytes):
            raise ValueError("资源filemap仅接受bytes")
        logical = re.sub(r"^compiled/(?:common|medium|android|ios)/", "", name)
        kind = _kind(logical)
        record = {"kind": kind, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw), "file": name, "source": "project-filemap"}
        try:
            if len(raw) > LIMIT:
                raise ValueError("资源超出有界解码上限")
            if kind in ("dsl", "parts", "frame", "timeline", "atlas"):
                if logical.endswith(".json"):
                    record["data"] = _decode_json(raw)
                else:
                    record["data"] = _decode_amf(raw)
            elif kind == "texture":
                width, height = _decode_png(raw)
                record.update(width=width, height=height)
            elif kind in ("native-ui", "native-html"):
                # Retain exact bytes for the bounded, consumer-proven decoder.
                # Layout JSON is not an ordinary parts/atlas adapter.
                record["raw"] = raw
        except (ValueError, TypeError, IndexError, KeyError, OSError, RecursionError, zlib.error) as exc:
            record["decodeError"] = f"{type(exc).__name__}: {exc}"
        if logical in catalog and (catalog[logical]["sha256"] != record["sha256"] or
                                   catalog[logical].get("decodeError") == "同logical多个文件字节冲突"):
            catalog[logical]["decodeError"] = "同logical多个文件字节冲突"
        else:
            catalog[logical] = record
    return catalog


def _augment(catalog):
    catalog = copy.deepcopy(catalog)
    # FileReader reads parts first, falling back to frame only when absent.
    for logical, record in list(catalog.items()):
        if record.get("kind") == "parts" and logical.endswith(".parts.amf3.deflate"):
            base = logical.removesuffix(".parts.amf3.deflate")
            catalog.setdefault(base, {"kind": "effect", "sha256": record.get("sha256"), "source": record.get("file", logical),
                                     "data": {"parts": logical, "timeline": base + ".timeline.amf3.deflate"}})
    for logical, record in list(catalog.items()):
        if record.get("kind") == "frame":
            suffix = ".frame.json" if logical.endswith(".json") else ".frame.amf3.deflate"
            base = logical.removesuffix(suffix)
            timeline = base + (".timeline.json" if logical.endswith(".json") else ".timeline.amf3.deflate")
            catalog.setdefault(base, {"kind": "effect", "sha256": record.get("sha256"), "source": record.get("file", logical),
                                     "data": {"layout": logical, "timeline": timeline}, "mappingSource": "FileReader.parts-frame-fallback"})
        if record.get("kind") == "texture" and logical.endswith(".png"):
            catalog.setdefault(logical.removesuffix(".png"), {**copy.deepcopy(record), "mappingSource": "FileReader.readTexture.png"})
    for logical, record in list(catalog.items()):
        if record.get("kind") != "atlas" or not isinstance(record.get("data"), list):
            continue
        if len(record["data"]) > MAX_VISITS:
            record["decodeError"] = "atlas记录数量超过有界上限"
            continue
        sheet = re.sub(r"\.atlas\.(?:amf3\.deflate|json)$", ".png", logical)
        names = [cell.get("n") for cell in record["data"] if isinstance(cell, dict) and isinstance(cell.get("n"), str)]
        if len(names) != len(set(names)):
            record["decodeError"] = "atlas同n重复声明"
        for cell in record["data"]:
            if not isinstance(cell, dict) or not isinstance(cell.get("n"), str):
                continue
            name = cell["n"]
            entry = {"kind": "atlas-cell", "sha256": record.get("sha256"), "source": logical,
                     "data": {"atlas": logical, "sheet": sheet, "cell": copy.deepcopy(cell)}}
            if record.get("decodeError"):
                entry["decodeError"] = "atlas来源无效: " + record["decodeError"]
            if name in catalog and catalog[name] != entry:
                catalog[name]["decodeError"] = "atlas cell logical映射冲突"
            else:
                catalog[name] = entry
    return catalog


def _atlas_rect_errors(data, sheet):
    if not isinstance(data, list) or len(data) > MAX_VISITS:
        return ["atlas记录数组无效或超限"]
    errors, seen = [], set()
    for index, cell in enumerate(data):
        if not isinstance(cell, dict):
            errors.append(f"atlas[{index}]记录不是对象"); continue
        name = cell.get("n")
        try:
            _path(name)
        except ValueError:
            errors.append(f"atlas[{index}]n逻辑路径无效")
        if isinstance(name, str):
            if name in seen: errors.append(f"atlas[{index}]n重复声明")
            seen.add(name)
        if any(not _integer(cell.get(field)) for field in ("x", "y", "w", "h")):
            errors.append(f"atlas[{index}]矩形必须是有限整数"); continue
        x, y, width, height = (int(cell[field]) for field in ("x", "y", "w", "h"))
        if x < 0 or y < 0 or width <= 0 or height <= 0:
            errors.append(f"atlas[{index}]矩形非正或起点为负"); continue
        if sheet is not None:
            if not _integer(sheet.get("width")) or not _integer(sheet.get("height")) or sheet.get("width", 0) <= 0 or sheet.get("height", 0) <= 0:
                errors.append("atlas目标sheet缺有效解码尺寸")
            elif x + width > sheet["width"] or y + height > sheet["height"]:
                errors.append(f"atlas[{index}]矩形越出目标sheet")
    return list(dict.fromkeys(errors))


def analyze(roots, catalog, scope=None, *, reference_files=None):
    """Resolve a finite, evidence-bearing graph; unknown semantics leave it open.

    Caller catalogs may add kind='references' with data={'references': [...]} for
    an explicitly decoded model/master/ability root. These are declared graph
    adapters, never inferred native mappings. Declared inventories can close a
    finite declared graph; full native semantic-domain extraction remains open.
    """
    scope = copy.deepcopy(scope or {})
    validate({"dependencyScope": {**scope, "roots": roots}})
    catalog = _augment(catalog)
    report = {"schema": SCHEMA, "scope": scope, "roots": copy.deepcopy(roots), "dependencies": [], "edges": [],
              "missingReferences": [], "unresolvedDynamic": [], "unsupported": [], "scopeGaps": [], "cycles": [], "requiredDefinitions": [],
              "nativeUiCoverage": [],
              "resolverBasis": RESOLVER_BASIS, "nativePackingVerified": False, "runtimeAccepted": False, "gameReady": False}
    entries, visited, active = {}, set(), set()
    visits = 0
    nesting = 0

    def bounded(gap):
        # Share a depth budget across graph edges, nested DSL and parts groups.
        # Separate per-resource limits cannot bound a deep tree at every level
        # of a long graph. On cutoff retain known edges and an explicit gap.
        def decorate(function):
            def call(*args, **kwargs):
                nonlocal nesting
                if nesting >= MAX_NESTING:
                    gap(*args, **kwargs)
                    return
                nesting += 1
                try:
                    return function(*args, **kwargs)
                finally:
                    nesting -= 1
            return call
        return decorate

    def problem(kind, logical, pointer, reason, context, **details):
        item = {"logical": logical, "pointer": pointer, "reason": reason, "requester": context.get("requester"),
                "bucket": context.get("bucket"), "collection": context.get("collection"), "layer": context.get("layer"),
                "domain": context.get("domain"), "category": context.get("category")}
        for field in ("definitionEvidence", "definitionPointer", "origin", "resourceOwner"):
            if field in context:
                item[field] = copy.deepcopy(context[field])
        item.update(copy.deepcopy(details))
        if item not in report[kind]:
            report[kind].append(item)

    @bounded(lambda logical, context, parent=None, pointer="": problem("unsupported", logical, pointer, "资源和内部结构嵌套超过有界上限，已知引用保留", context))
    def visit(logical, context, parent=None, pointer=""):
        nonlocal visits
        visits += 1
        if visits > MAX_VISITS:
            problem("unsupported", logical, pointer, "依赖遍历达到有界上限", context)
            return
        if not isinstance(logical, str) or not logical:
            problem("unresolvedDynamic", parent, pointer, "引用不是固定逻辑路径", context)
            return
        try:
            _path(logical)
        except ValueError:
            problem("unsupported", parent, pointer, "引用逻辑路径无效", context)
            return
        if parent is not None:
            report["edges"].append({"from": parent, "to": logical, "pointer": pointer, "requester": context.get("requester"),
                                    "bucket": context.get("bucket"), "collection": context.get("collection"), "layer": context.get("layer")})
        key = (context.get("bucket"), context.get("collection"), context.get("layer"), logical)
        if context.get("kind") == "sprite-sheet":
            atlas = logical + (".atlas.json" if logical + ".atlas.json" in catalog else ".atlas.amf3.deflate")
            visit(atlas, {**context, "kind": "atlas"}, logical, pointer + "/atlas")
            return
        if context.get("kind") in ("ui", "html"):
            suffixes = ((".ui.amf3.deflate", ".ui.json") if context["kind"] == "ui"
                        else (".html.deflate", ".html"))
            if not logical.endswith(suffixes):
                candidates = [logical + suffix for suffix in suffixes if logical + suffix in catalog]
                if len(candidates) > 1:
                    problem("unsupported", logical, pointer, "同界面有多个读取格式，缺明确冻结读取模式；不猜选其中一份", context,
                            requiredReferences=candidates)
                    return
                physical = candidates[0] if candidates else logical + suffixes[0]
                visit(physical, {**context, "uiEntry": logical}, logical, pointer + "/file")
                return
        if context.get("lookup") == "standalone-file-texture" and not logical.endswith(".png"):
            visit(logical + ".png", {**context, "kind": "texture"}, logical, pointer + "/file")
            return
        record = catalog.get(logical)
        if record is None:
            problem("missingReferences", logical, pointer, "固定引用不在冻结资源catalog", context)
            return
        if context.get("lookup") == "standalone-file-texture" and record.get("kind") != "texture":
            problem("unsupported", logical, pointer, "rich-text直接读取PNG，图集同名图块不能代替独立图片", context)
            return
        if (context.get("origin") in ("ui-consumer", "html-consumer") and
                context.get("kind") in ("image", "texture") and record.get("kind") not in ("texture", "atlas-cell")):
            problem("unsupported", logical, pointer, "界面纹理引用未对应已核PNG或图块；同名其他资源不能代替", context,
                    definitionEvidence=context.get("definitionEvidence"))
            return
        if key not in entries:
            entry = {**{k: copy.deepcopy(v) for k, v in context.items() if k != "logical"}, "logical": logical,
                     "kind": record.get("kind"), "sha256": record.get("sha256"), "file": record.get("file"),
                     "resourceSource": record.get("source"), "requesters": [], "contexts": [], "collectionDedupe": "logical"}
            for field in ("width", "height", "bytes", "referenceSha256", "sha256Encoding", "mappingSha256", "mappingSource"):
                if field in record:
                    entry[field] = record[field]
            entries[key] = entry
            report["dependencies"].append(entry)
        entry = entries[key]
        if context.get("requester") not in entry["requesters"]:
            entry["requesters"].append(context.get("requester"))
        preserved_context = {k: copy.deepcopy(context.get(k)) for k in ("requester", "category", "domain", "element", "roles", "forms", "switches", "source", "origin", "definitionEvidence", "definitionPointer", "kind", "lookup", "requiredLayouts", "preloadRequired", "runtimeLoad", "resourceOwner") if k in context}
        if preserved_context not in entry["contexts"]:
            entry["contexts"].append(preserved_context)
        # Traverse separately per requester so provenance is not lost at merges.
        walk_key = key + (context.get("requester"), context.get("element"), tuple(context.get("roles", [])), tuple(context.get("forms", [])), tuple(context.get("switches", [])),
                          context.get("lookup"), tuple(context.get("requiredLayouts", [])), context.get("resourceOwner"))
        if walk_key in active:
            report["cycles"].append({"logical": logical, "from": parent, "pointer": pointer, "requester": context.get("requester")})
            return
        if walk_key in visited:
            return
        visited.add(walk_key)
        active.add(walk_key)
        if not re.fullmatch(r"[0-9a-f]{64}", str(record.get("sha256", ""))):
            problem("unsupported", logical, pointer, "资源缺SHA256身份", context)
        if record.get("decodeError"):
            problem("unsupported", logical, pointer, "资源未解码: " + record["decodeError"], context)
            active.remove(walk_key)
            return
        kind, data = record.get("kind"), record.get("data")
        def child(target, at):
            visit(target, context, logical, at)
        if kind == "dsl":
            tree = data.get("tree", data) if isinstance(data, dict) else data
            walk_dsl(tree, logical, context, child)
        elif kind in ("native-ui", "native-html"):
            from native_ui_dependencies import resolve_ui_resources
            receipt = resolve_ui_resources(logical, record.get("raw"),
                                           "ui" if kind == "native-ui" else "html", context=context)
            for required in context.get("requiredLayouts", []):
                if required not in receipt.get("layoutIds", []):
                    problem("unsupported", logical, pointer, "复用按钮所需内部布局不存在或未核验：" + str(required), context,
                            requiredLayout=required)
            identity = receipt.get("sourceIdentity", {})
            existing = next((item for item in report["nativeUiCoverage"]
                             if item["logical"] == logical and item["sha256"] == record["sha256"]), None)
            if existing is None:
                existing = {"logical": logical, "entry": context.get("uiEntry", logical),
                            "sha256": record["sha256"], "format": identity.get("format"),
                            "parserCoverage": copy.deepcopy(receipt.get("parserCoverage", {})),
                            "referenceCount": len(receipt.get("references", [])),
                            "textCount": len(receipt.get("texts", [])),
                            "texts": copy.deepcopy(receipt.get("texts", [])),
                            "sourceProof": copy.deepcopy(receipt.get("sourceProof", {})),
                            "resourceOwner": context.get("resourceOwner"),
                            "requesters": [], "runtimeAccepted": False}
                report["nativeUiCoverage"].append(existing)
            if context.get("requester") not in existing["requesters"]:
                existing["requesters"].append(context.get("requester"))
            for issue in receipt.get("problems", []):
                problem("unresolvedDynamic" if issue.get("dynamic") else "unsupported", logical,
                        issue.get("pointer", ""), issue.get("reason", "界面子资源尚未核验"), context,
                        **{key: value for key, value in issue.items()
                           if key not in ("logical", "pointer", "reason", "domain", "category", "dynamic")})
            for reference in receipt.get("references", []):
                mapped = {**context, **reference.get("context", {}),
                          "kind": reference.get("kind", "image"), "domain": "shared", "category": "shared",
                          "origin": reference.get("origin", "ui-consumer"),
                          "definitionEvidence": copy.deepcopy(reference.get("definitionEvidence")),
                          "definitionPointer": reference.get("pointer", "")}
                for field in ("lookup", "requiredLayouts", "preloadRequired", "runtimeLoad"):
                    mapped.pop(field, None)
                    if field in reference:
                        mapped[field] = copy.deepcopy(reference[field])
                mapped.pop("uiEntry", None)
                visit(reference.get("logical"), mapped, logical, reference.get("pointer", ""))
        elif kind == "enemy-dsl":
            problem("unsupported", logical, pointer, "EnemyDsl格式与递归资源尚未核实，原字节和来源保留", context)
        elif kind == "effect":
            for field in (("layout", "timeline") if isinstance(data, dict) and "layout" in data else ("parts", "timeline")):
                child(data.get(field) if isinstance(data, dict) else None, "/" + field)
        elif kind == "frame":
            # ViewAssetCache.getTextures selects the character sheet or the
            # fixed Common layer0/1 sheet, then atlas names with this prefix.
            base = re.sub(r"\.frame\.(?:amf3\.deflate|json)$", "", logical)
            if (not isinstance(data, dict) or not isinstance(data.get("name"), str) or
                    any(isinstance(data.get(key), bool) or not isinstance(data.get(key), (int, float)) or not math.isfinite(data[key]) for key in ("x", "y", "scale")) or
                    data.get("scale", 0) <= 0 or not isinstance(data.get("smoothing"), bool)):
                problem("unsupported", logical, "/name", "frame缺有效原生前缀、变换或采样字段", context)
            else:
                try:
                    prefix = _path(data["name"])
                except ValueError:
                    prefix = None
                if not prefix:
                    problem("unsupported", logical, "/name", "frame前缀无效", context)
                else:
                    if prefix.startswith(("battle/common/layer0/", "battle/common/layer1/")):
                        sheet = "/".join(prefix.split("/")[:3])
                    elif base.startswith("character/") and len(base.split("/")) >= 4:
                        sheet = base.rsplit("/", 1)[0] + ("/special_sprite_sheet" if base.rsplit("/", 1)[1] == "special" else "/sprite_sheet")
                    else:
                        problem("unsupported", logical, "/name", "此frame收集规则尚未核验", context)
                        active.remove(walk_key)
                        return
                    atlas = sheet + (".atlas.json" if sheet + ".atlas.json" in catalog else ".atlas.amf3.deflate")
                    child(atlas, "/spriteSheet")
                    atlas_data = catalog.get(atlas, {}).get("data")
                    if isinstance(atlas_data, list):
                        frames = sorted(cell["n"] for cell in atlas_data if isinstance(cell, dict) and isinstance(cell.get("n"), str) and cell["n"].startswith(prefix))
                        if not frames:
                            problem("missingReferences", prefix, "/name", "指定图集中没有frame前缀对应的帧", context)
                        for index, name in enumerate(frames[:MAX_VISITS]):
                            child(name, "/frames/" + str(index))
        elif kind == "parts":
            if not isinstance(data, dict) or not isinstance(data.get("i"), list) or not isinstance(data.get("g"), list) or not data["g"]:
                problem("unsupported", logical, "", "parts缺少i/g原生结构", context)
            else:
                groups_seen, groups_active = set(), set()
                @bounded(lambda index: problem("unsupported", logical, "/g/" + str(index), "parts group嵌套超过有界上限，已知引用保留", context))
                def group(index):
                    if not _integer(index) or not 0 <= index < len(data["g"]):
                        problem("unsupported", logical, "/g", "parts group索引无效", context)
                        return
                    index = int(index)
                    if index in groups_active:
                        problem("unsupported", logical, "/g/" + str(index), "parts递归group循环", context)
                        return
                    if index in groups_seen:
                        return
                    groups_seen.add(index); groups_active.add(index)
                    segments = data["g"][index].get("s", []) if isinstance(data["g"][index], dict) else None
                    if not isinstance(segments, list):
                        problem("unsupported", logical, "/g/" + str(index), "parts segment结构无效", context)
                        segments = []
                    for n, segment in enumerate(segments):
                        at = f"/g/{index}/s/{n}"
                        if not isinstance(segment, dict) or not _integer(segment.get("s")):
                            problem("unsupported", logical, at, "parts packed kind无效", context)
                            continue
                        native_kind = (int(segment["s"]) & 0xffffffff) >> 30
                        target = segment.get("i")
                        if native_kind == 2:
                            group(target)
                        elif native_kind == 0:
                            if not _integer(target) or not 0 <= target < len(data["i"]) or not isinstance(data["i"][int(target)], dict):
                                problem("unsupported", logical, at, "parts image索引无效", context)
                            else:
                                child(data["i"][int(target)].get("p"), at + "/i/p")
                        else:
                            problem("unsupported", logical, at, f"parts native kind{native_kind}未支持", context)
                    groups_active.remove(index)
                group(0)
        elif kind == "timeline":
            if not isinstance(data, dict) or not isinstance(data.get("sounds"), list):
                problem("unsupported", logical, "/sounds", "timeline缺sounds数组", context)
            else:
                for n, sound in enumerate(data["sounds"]):
                    path = sound.get("path") if isinstance(sound, dict) else None
                    child(_sound_target(path, catalog), f"/sounds/{n}/path")
        elif kind == "atlas-cell":
            # The UI consumer selects a texture key. Its atlas and sheet are
            # proven carriers, not another getTexture(key) invocation.
            carrier = {k: v for k, v in context.items() if k != "lookup"}
            visit(data.get("atlas"), {**carrier, "kind": "atlas"}, logical, "/atlas")
            visit(data.get("sheet"), {**carrier, "kind": "texture"}, logical, "/sheet")
            for reason in _atlas_rect_errors([data.get("cell")], catalog.get(data.get("sheet"))):
                problem("unsupported", logical, "/cell", reason, context)
        elif kind == "atlas":
            sheet = re.sub(r"\.atlas\.(?:amf3\.deflate|json)$", ".png", logical)
            child(sheet, "/sheet")
            for reason in _atlas_rect_errors(data, catalog.get(sheet)):
                problem("unsupported", logical, "", reason, context)
        elif kind == "references":
            references = data.get("references") if isinstance(data, dict) else None
            if not isinstance(references, list):
                problem("unsupported", logical, "", "显式依赖adapter缺references", context)
            else:
                for n, target in enumerate(references):
                    child(target, f"/references/{n}")
        elif kind not in ("texture", "sound", "evidence"):
            problem("unsupported", logical, "", "未支持的资源语义类型: " + str(kind), context)
        active.remove(walk_key)

    def walk_dsl(tree, logical, context, child):
        from native_dependencies import resolve_command_resources
        tree_seen = set()
        handled_resource_pointers = set()
        @bounded(lambda node, pointer="", command=False, event=False, depth=0: problem("unsupported", logical, pointer, "DSL和资源图嵌套超过有界上限，已知引用保留", context))
        def walk(node, pointer="", command=False, event=False, depth=0):
            if depth > 160:
                problem("unsupported", logical, pointer, "DSL结构超过递归上限", context); return
            if not isinstance(node, (list, dict)):
                if command or event:
                    problem("unsupported", logical, pointer, "DSL命令/事件不是数组", context)
                return
            if id(node) in tree_seen:
                return
            tree_seen.add(id(node))
            if isinstance(node, dict):
                if set(node) == {"min", "max"} and all(not isinstance(v, bool) and isinstance(v, (int, float)) and math.isfinite(v) for v in node.values()):
                    return  # observed scalar ranges, never resource names
                problem("unsupported", logical, pointer, "DSL对象结构不支持", context)
                for key, value in node.items(): walk(value, pointer + "/" + str(key), depth=depth + 1)
                return
            tag = node[0] if node and isinstance(node[0], str) else None
            native_handled = False
            if command and tag not in SCALAR_COMMANDS:
                mapped = resolve_command_resources(node, context.get("element", scope.get("element")), pointer, reference_files=reference_files)
                native_handled = mapped["handled"]
                if native_handled:
                    handled_resource_pointers.add(pointer)
                for reference in mapped["references"]:
                    # Formula category/layer must not merge distinct collectors.
                    mapped_context = {key: value for key, value in reference.get("context", {}).items() if key != "bucket"}
                    mapped_context.update({key: copy.deepcopy(reference[key]) for key in ("domain", "origin", "definitionEvidence", "definitionPointer") if key in reference})
                    visit(reference["logical"], {**context, **mapped_context},
                          logical, reference["pointer"])
                for item in mapped["problems"]:
                    problem("unresolvedDynamic" if item.get("dynamic") else "unsupported",
                            logical, item["pointer"], item["reason"], {**context, **({'domain':item['domain']} if item.get('domain') else {})})
                for definition in mapped.get("requiredDefinitions", []):
                    entry={**copy.deepcopy(definition), "source":logical, "requester":context.get("requester")}
                    if entry not in report["requiredDefinitions"]:
                        report["requiredDefinitions"].append(entry)
            if command and not native_handled and tag not in SCALAR_COMMANDS | CALLBACK_COMMANDS | {"ShowEffect", "ChangeBgm", "CreateNormalAttack", "CreateHitArea"}:
                problem("unsupported", logical, pointer, "命令缺原生资源映射: " + str(tag), context)
            if event and tag not in EVENTS:
                problem("unsupported", logical, pointer, "事件缺分支语义: " + str(tag), context)
            if command and tag in SCALAR_COMMANDS:
                # Trace payloads, labels and movement parameters do not become
                # resources just because they resemble a typed Effect or path.
                return
            resource_slot_handled = any(pointer.startswith(parent + "/") for parent in handled_resource_pointers)
            if resource_slot_handled and tag in ("SpecifyEffectDirectly", "SpecifyEffectByElement"):
                pass  # exact resource slots already mapped by the native helper
            elif tag == "SpecifyEffectDirectly":
                child(node[1] if len(node) == 2 else None, pointer + "/1")
            elif tag == "SpecifyEffectByElement":
                problem("unresolvedDynamic", logical, pointer, "元素选择effect缺冻结元素/映射", context)
            elif command and tag == "ShowEffect" and not native_handled:
                effect = node[2] if len(node) > 2 else None
                if not isinstance(effect, list) or not effect or effect[0] not in ("SpecifyEffectDirectly", "SpecifyEffectByElement"):
                    problem("unresolvedDynamic", logical, pointer + "/2", "ShowEffect目标不是已支持的固定Effect枚举", context)
            elif command and tag == "ChangeBgm":
                path = node[1] if len(node) > 1 else None
                child(_sound_target(path, catalog), pointer + "/1")
            elif command and tag == "CreateHitArea":
                guard = node[26] if len(node) > 26 else None
                if guard == ["None"]:
                    pass
                elif isinstance(guard, list) and len(guard) == 4 and guard[0] == "Suppress":
                    child("battle/uncommon/layer1/guard/damage_effect_to_friendly_perfect_gurad", pointer + "/26")
                    child("battle/uncommon/layer0/guard/attack_to_friendly_perfect_gurad", pointer + "/26")
                else:
                    problem("unsupported", logical, pointer + "/26", "CreateHitArea guard模式未解析", context)
            elif command and tag == "CreateNormalAttack" and not native_handled:
                hit = node[15] if len(node) > 15 else None
                target_element = node[2] if len(node) > 2 else None
                if hit == ["None"]:
                    pass
                elif isinstance(hit, list) and len(hit) >= 2 and hit[0] == "SpecifyHitEffectDirectly":
                    pass  # nested fixed Effect is visited below
                elif isinstance(hit, list) and len(hit) == 1:
                    known = {"Dark": "dark", "Explosion": "explosion", "Fire": "fire", "Frozen": "frozen", "Shine": "shine",
                             "Splash": "splash", "ThunderLight": "thunder_light", "ThunderSmall": "thunder_small", "Tornado": "tornado"}
                    if hit[0] in known:
                        name = known[hit[0]]
                        child(f"battle/effect/hit/normal_damage/{name}/{name}", pointer + "/15")
                    elif hit[0] in ("Fine", "Coarse", "Slash", "CriticalSlash"):
                        element = context.get("element", scope.get("element")) if target_element == 255 else int(target_element) - 1 if _integer(target_element) and 1 <= target_element <= 7 else None
                        if element is None:
                            problem("unresolvedDynamic", logical, pointer + "/2", "CreateNormalAttack隐式命中纹理缺冻结element，参数=" + str(target_element), context)
                        elif element == 6:
                            problem("unsupported", logical, pointer + "/15", "原生无colorless对应hit effect", context)
                        else:
                            name = {"Fine": "fine", "Coarse": "coarse", "Slash": "slash", "CriticalSlash": "slash_strong"}[hit[0]]
                            colored = name + "_" + ("red", "blue", "yellow", "green", "white", "black")[int(element)]
                            child(f"battle/effect/hit/normal_damage/{name}/{colored}/{colored}", pointer + "/15")
                    else:
                        problem("unsupported", logical, pointer + "/15", "CreateNormalAttack未知AttackHitEffect=" + str(hit), context)
                else:
                    problem("unsupported", logical, pointer + "/15", "CreateNormalAttack缺AttackHitEffect枚举", context)
            if tag in ("Command", "Event"):
                if len(node) != 2:
                    problem("unsupported", logical, pointer, "DSL包装结构无效", context)
                for i, value in enumerate(node[1:], 1): walk(value, pointer + "/" + str(i), tag == "Command", tag == "Event", depth + 1)
            else:
                if tag == "Block":
                    statements = node[1] if len(node) == 2 else None
                    if not isinstance(statements, list) or any(not isinstance(value, list) or not value or value[0] not in ("Block", "Command", "Event") for value in statements):
                        problem("unsupported", logical, pointer, "Block语句/包装结构无效", context)
                if tag == "ActionDsl" and (len(node) < 12 or not isinstance(node[11], list) or not node[11] or node[11][0] != "Block"):
                    problem("unsupported", logical, pointer, "ActionDsl缺完整根Block结构", context)
                for i, value in enumerate(node):
                    if isinstance(value, (list, dict)): walk(value, pointer + "/" + str(i), depth=depth + 1)
        if not isinstance(tree, list) or not tree or tree[0] not in ("ActionDsl", "Block", "Command", "Event"):
            problem("unsupported", logical, "", "DSL根结构未确认", context)
        walk(tree)

    selected = []
    for root in roots:
        if any(root.get(key) and scope.get(key) and not set(root[key]) & set(scope[key]) for key in ("roles", "forms", "switches")):
            continue
        selected.append(root)
        visit(root["logical"], root)
    if not selected:
        report["scopeGaps"].append({"domain": "roots", "reason": "没有冻结范围内的依赖根"})
    root_names = {r["logical"] for r in selected}
    for root in selected:
        for field in ("requester", "source"):
            if not root.get(field): report["scopeGaps"].append({"domain": "roots", "logical": root["logical"], "reason": "根缺" + field})
    resource_closed = bool(selected and not any(report[k] for k in ("missingReferences", "unresolvedDynamic", "unsupported", "scopeGaps")))
    semantic_gaps = []
    for domain in DOMAINS:
        inventory = scope.get("domains", {}).get(domain, {})
        proof = inventory.get("evidence", {})
        record = catalog.get(proof.get("logical"), {})
        proof_data = record.get("data")
        proven = bool(record.get("kind") == "evidence" and isinstance(proof_data, dict) and
                      proof_data.get("schema") == "declared-root-inventory-v1" and
                      isinstance(proof_data.get("domains"), dict) and proof_data["domains"].get(domain) ==
                      {"status": inventory.get("status"), "roots": inventory.get("roots", [])} and
                      record.get("sha256") and record.get("sha256") == proof.get("sha256") and not record.get("decodeError"))
        domain_roots = inventory.get("roots", [])
        if inventory.get("status") not in ("included", "not-applicable") or not proven:
            semantic_gaps.append({"domain": domain, "reason": "缺已冻结身份的根清单/不适用依据"})
        elif inventory["status"] == "included" and (not domain_roots or not set(domain_roots) <= root_names):
            semantic_gaps.append({"domain": domain, "reason": "域根清单未全部纳入所选roots", "roots": domain_roots})
    if not scope.get("roles") or not scope.get("forms"):
        semantic_gaps.append({"domain": "role-form", "reason": "main/unison/leader与形态范围未冻结"})
    # Hashes authenticate bytes, not completeness. There is currently no full
    # native-domain extractor in portable projects. Even a hand-authored evidence
    # inventory with all domains is only a finite declared graph. Future domain
    # extractors must derive applicability/roots from decoded native definitions
    # and the selected role/form/switch mapping, rather than trust this flag.
    declared_inventory_closed = bool(resource_closed and not semantic_gaps)
    for domain in DOMAINS:
        semantic_gaps.append({"domain": domain, "reason": "完整原生域提取器尚未支持；手写inventory或资源hash不证明域根完整"})
    semantic_closed = False
    report["characterSemanticGaps"] = semantic_gaps
    finite = scope.get("kind", "finite-resources") != "character-semantic"
    report["closure"] = {"fullyClosed": resource_closed if finite else semantic_closed, "compiledResourceClosure": resource_closed,
        "characterSemanticClosure": semantic_closed, "completeCharacterTotal": semantic_closed,
        "declaredRootInventoryClosed": declared_inventory_closed,
        "scopeKind": scope.get("kind", "finite-resources"), "basis": "resolved-frozen-resource-graph",
        "nativeRuntimeAccepted": False, "reason": "冻结有限资源图闭合" if resource_closed else "资源图存在缺失或未解析项"}
    counts = Counter(entry["kind"] for entry in report["dependencies"])
    report["counts"] = {"roots": len(selected), "resolved": len(report["dependencies"]), "edges": len(report["edges"]),
        "byKind": dict(counts), "missing": len(report["missingReferences"]), "dynamic": len(report["unresolvedDynamic"]),
        "unsupported": len(report["unsupported"]), "semanticDomainGaps": len(semantic_gaps),
        "completeSemanticMissingCount": None, "missingCountBasis": "fixed-references-in-frozen-catalog-only"}
    # Shared game UI belongs to integration diagnostics, not an author's MOD
    # asset debts. A shared node with any character requester remains relevant.
    def author_entry(entry):
        return any(context.get("resourceOwner") != "game-common-ui" for context in entry.get("contexts", [{}]))
    report["authorCounts"] = {"resolved": sum(author_entry(entry) for entry in report["dependencies"]),
        **{name: sum(item.get("resourceOwner") != "game-common-ui" for item in report[key])
           for name, key in (("missing", "missingReferences"), ("dynamic", "unresolvedDynamic"), ("unsupported", "unsupported"))}}
    return report


def analyze_project(store, project, files=None):
    """Read declared reference members plus optional compiled bytes; never save."""
    validate(project)
    project_root = store.directory(project["id"]).resolve()
    reference = (project_root / "reference").resolve()
    raw_files, read_errors = {}, []
    for name in project.get("referenceFiles", []):
        _path(name)
        target = (reference / name).resolve()
        if not reference.is_relative_to(project_root) or not target.is_relative_to(reference):
            raise ValueError("依赖参考资源越出工程")
        if not target.is_file() or target.stat().st_size > LIMIT:
            read_errors.append({"logical": name, "reason": "工程声明参考文件缺失或超限"}); continue
        raw_files[name] = target.read_bytes()
    catalog = resource_catalog(raw_files)
    # Existing reference exporter explicitly records sound logical/file pairs.
    # Filename-only guesses and directory listings are never logical adapters.
    if "audio_catalog.json" in raw_files:
        try:
            audio_catalog = _decode_json(raw_files["audio_catalog.json"])
            for item in audio_catalog.get("items", []):
                logical, source_file = item.get("logical"), item.get("file")
                if source_file in catalog and catalog[source_file].get("kind") == "sound":
                    logical = _path(logical)
                    alias = logical if logical.endswith(".mp3") else logical + ".mp3"
                    catalog[alias] = {**copy.deepcopy(catalog[source_file]), "mappingSource": "audio_catalog.json",
                                      "mappingSha256": hashlib.sha256(raw_files["audio_catalog.json"]).hexdigest()}
        except (ValueError, TypeError, AttributeError, RecursionError) as exc:
            read_errors.append({"logical": "audio_catalog.json", "reason": "声音逻辑映射解析失败: " + str(exc)})
    if files:
        for name, record in resource_catalog(files).items():
            if name in catalog and (catalog[name]["sha256"] != record["sha256"] or
                                    "冲突" in catalog[name].get("decodeError", "")):
                record["decodeError"] = "参考/编译同logical身份冲突"
            catalog[name] = record
    # Definition getters must see the same frozen inputs as the graph, including
    # explicitly supplied compiled/reference tables. A conflicting identity is
    # never selected for native parsing, even when it is not a graph root.
    definition_files = {}
    for inputs in (raw_files, files or {}):
        for name, raw in inputs.items():
            logical = re.sub(r"^compiled/(?:common|medium|android|ios)/", "", name)
            record = catalog.get(logical, {})
            if record.get("decodeError"):
                if "冲突" in record["decodeError"]:
                    error = {"logical": logical, "reason": record["decodeError"]}
                    if error not in read_errors:
                        read_errors.append(error)
                continue
            if record.get("sha256") == hashlib.sha256(raw).hexdigest():
                definition_files[logical] = raw
    scope = copy.deepcopy(project.get("dependencyScope") or {"kind": "project-resources"})
    roots = copy.deepcopy(scope.get("roots", []))
    # Extract every preserved version and switch program. Do not promote tables,
    # namespace contents, or a source directory to native semantic root proof.
    for name, raw in raw_files.items():
        if name == "data_readable/skill_dependencies.json" or (name.startswith("data_readable/action_dsl/decoded/") and name.endswith(".json")):
            try:
                data = _decode_json(raw)
                programs = data.get("programs", []) if name.endswith("skill_dependencies.json") else [{"logical": data.get("logical_path"), "tree": data.get("tree")}]
                if not isinstance(programs, list): raise ValueError("programs不是数组")
                for n, program in enumerate(programs):
                    logical = _path(program.get("logical"))
                    tree = program.get("tree")
                    record = {"kind": "dsl", "data": tree, "sha256": hashlib.sha256(canonical(tree)).hexdigest(),
                              "source": name, "file": name, "referenceSha256": hashlib.sha256(raw).hexdigest(),
                              "sha256Encoding": "canonical-json-utf8"}
                    encoded_logical = logical if logical.endswith(".action.dsl.amf3.deflate") else logical + ".action.dsl.amf3.deflate"
                    existing = catalog.get(encoded_logical) or catalog.get(logical)
                    if existing:
                        if existing.get("kind") != "dsl" or existing.get("data") != tree:
                            record["decodeError"] = "同program逻辑身份树冲突"
                        else:
                            # Readable receipts never replace the identity of
                            # an actual compressed program with a JSON hash.
                            record = {**copy.deepcopy(existing), "mappingSource": name,
                                      "mappingSha256": hashlib.sha256(raw).hexdigest()}
                    catalog[logical] = record
                    # Definition getters use the real compressed logical while
                    # older readable exports sometimes omit the codec suffix.
                    if not logical.endswith(".action.dsl.amf3.deflate"):
                        if encoded_logical not in catalog:
                            catalog[encoded_logical] = copy.deepcopy(record)
                        elif catalog[encoded_logical].get("data") != tree:
                            catalog[encoded_logical]["decodeError"] = "源program逻辑身份树冲突"
                    if not scope.get("roots"):
                        roots.append({"logical": logical, "requester": "source-program:" + str(n), "source": name,
                                      "category": "skill", "bucket": "BattlePart", "collection": "project", "layer": None})
            except (ValueError, TypeError, AttributeError, RecursionError) as exc:
                read_errors.append({"logical": name, "reason": "参考DSL解析失败: " + str(exc)})
    # Existing export's hashed effect path is the explicit logical-name adapter.
    from skill_preview import effect_path
    for record in list(catalog.values()):
        if record.get("kind") != "dsl": continue
        def aliases(node, depth=0):
            if depth > 160: return
            if not isinstance(node, list): return
            if len(node) == 2 and node[0] == "SpecifyEffectDirectly" and isinstance(node[1], str):
                try: parts = effect_path(node[1])
                except ValueError: return
                if parts in catalog:
                    catalog.setdefault(node[1], {"kind": "effect", "sha256": catalog[parts]["sha256"], "source": parts,
                        "data": {"parts": parts, "timeline": parts.replace(".parts.json", ".timeline.json")}})
            for value in node: aliases(value, depth + 1)
        aliases(record.get("data"))
    if not scope.get("roots"):
        for name, record in catalog.items():
            if record.get("kind") in ("parts", "timeline", "texture", "sound"):
                roots.append({"logical": name, "requester": "project-resource", "source": record.get("file", name),
                              "bucket": "Project", "collection": "project-resources", "layer": None})
    from native_dependencies import extract_native_roots
    native_receipt = extract_native_roots(project, definition_files)
    if native_receipt["sourceIdentity"]:
        for root in native_receipt["roots"]:
            if root not in roots:
                roots.append(root)
        # All retained forms/versions are checked, regardless of a legacy
        # manually declared scope. This is an authoring union, not live-party cost.
        scope["roles"] = native_receipt["roles"]
        scope["forms"] = native_receipt["forms"]
        scope["switches"] = sorted(set(native_receipt["switches"]) | {"base"})
        if native_receipt["element"] is not None:
            scope["element"] = native_receipt["element"]
    result = analyze(roots, catalog, scope, reference_files=definition_files)
    # Recursive summons/support abilities can add resources without adding a
    # top-level root. Report existing logical resources per domain separately
    # from root extraction and semantic completeness.
    for domain, coverage in native_receipt["domains"].items():
        coverage["graphResolved"] = len({entry["logical"] for entry in result["dependencies"]
            if any(context.get("domain", context.get("category")) == domain
                   for context in entry["contexts"])})
        coverage["authorRootCount"] = len({root["logical"] for root in native_receipt["roots"]
            if root["category"] == domain and root.get("resourceOwner") != "game-common-ui"})
        coverage["authorGraphResolved"] = len({entry["logical"] for entry in result["dependencies"]
            if any(context.get("domain", context.get("category")) == domain and context.get("resourceOwner") != "game-common-ui"
                   for context in entry["contexts"])})
    result["nativeDefinitionCoverage"] = native_receipt
    definition_problems = []
    native = project.get("nativeGameplay")
    if isinstance(native, dict):
        import bridge  # register the bundled codec/legality module search path
        from wf_client_legality import client_legality_problems
        groups = [("leader", "leader_ability", native.get("leader")), *[("ability-" + str(g.get("slot")), "ability", g) for g in native.get("abilities", []) if isinstance(g, dict)]]
        for label, kind, group in groups:
            if not isinstance(group, dict) or not isinstance(group.get("rows"), list):
                definition_problems.append({"domain": "ability", "source": label, "reason": "缺原生能力行，不能当无能力"})
                continue
            for index, row in enumerate(group["rows"]):
                try:
                    problems = client_legality_problems(kind, row)
                except (ValueError, TypeError, IndexError, KeyError) as exc:
                    problems = ["原生能力解析失败: " + type(exc).__name__]
                for reason in problems:
                    definition_problems.append({"domain": "ability", "source": label, "row": index, "reason": reason})
        definition_problems.extend(native_receipt["problems"])
    else:
        definition_problems.append({"domain": "definition", "reason": "工程未含nativeGameplay完整定义；仅有美术/参考资源不证明角色能力根"})
    semantic_gaps = list(native_receipt["problems"])
    for domain, coverage in native_receipt["domains"].items():
        if coverage["status"] == "pending":
            semantic_gaps.append({"domain": domain, "reason": coverage["reason"]})
    if not native_receipt["complete"] and not semantic_gaps:
        semantic_gaps.append({"domain": "collector", "reason": "完整原生collector与阵容范围尚未全部提取"})
    result["characterSemanticGaps"] = semantic_gaps
    semantic_closed = bool(native_receipt["complete"] and
                           result["closure"]["compiledResourceClosure"] and
                           not semantic_gaps and not definition_problems and not read_errors)
    result["closure"].update(characterSemanticClosure=semantic_closed,
                             completeCharacterTotal=semantic_closed,
                             basis="native-definition-extraction-and-frozen-resource-graph")
    if scope.get("kind") == "character-semantic":
        result["closure"]["fullyClosed"] = semantic_closed
    result["counts"]["semanticDomainGaps"] = len(semantic_gaps)
    result["sourceDefinitionProblems"] = definition_problems
    result["projectIdentity"] = {"id": project["id"], "revision": project.get("revision"), "sha256": hashlib.sha256(canonical(project)).hexdigest()}
    result["referenceReadErrors"] = read_errors
    if read_errors:
        result["closure"].update(fullyClosed=False, compiledResourceClosure=False, characterSemanticClosure=False, completeCharacterTotal=False)
    from dependency_assistance import build as assistance_report
    result["assistance"] = assistance_report(project, closure=result)
    return result
