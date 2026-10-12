"""Read-only character collection budgets; measured area is not native packing.

The optional v1 characterAudit declaration names scope and actual collection
semantics. Unknown metadata stays unknown, including for generated assets.
"""
from __future__ import annotations

import copy
import hashlib
import io
import math
import zlib
from collections import Counter

from PIL import Image

CAPACITY = 4096 * 4096
ROLES = {"main", "unison", "leader"}
CATEGORIES = {"pixelart", "skill", "ability", "summon", "powerFlip", "shared", "ui", "cutin"}


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def validate(project):
    """Validate known optional fields without rewriting or dropping extensions."""
    audit = project.get("characterAudit")
    if audit is None:
        return
    if not isinstance(audit, dict):
        raise ValueError("characterAudit 必须是对象")
    scope = audit.get("scope", {})
    if not isinstance(scope, dict):
        raise ValueError("characterAudit.scope 必须是对象")
    for key in ("roles", "forms", "switches"):
        if key in scope and (not isinstance(scope[key], list) or any(not isinstance(v, str) or not v for v in scope[key])):
            raise ValueError(f"characterAudit.scope.{key} 必须是非空字符串数组")
    if any(role not in ROLES for role in scope.get("roles", [])):
        raise ValueError("characterAudit.scope.roles 仅支持 main/unison/leader")
    if "closed" in scope and not isinstance(scope["closed"], bool):
        raise ValueError("characterAudit.scope.closed 必须是布尔值")
    if "closureEvidence" in audit:
        evidence = audit["closureEvidence"]
        if not isinstance(evidence, dict) or "source" not in evidence or not isinstance(evidence["source"], str) or not isinstance(evidence.get("verified", False), bool):
            raise ValueError("characterAudit.closureEvidence必须是含source/verified的对象")
    deps = audit.get("dependencies", [])
    if not isinstance(deps, list) or len(deps) > 10000:
        raise ValueError("characterAudit.dependencies 必须是最多10000项的数组")
    for i, item in enumerate(deps):
        if not isinstance(item, dict):
            raise ValueError(f"characterAudit.dependencies[{i}] 必须是对象")
        for key in ("logical", "bucket", "collection", "source", "requester", "category", "file"):
            if key in item and item[key] is not None and not isinstance(item[key], str):
                raise ValueError(f"characterAudit.dependencies[{i}].{key} 必须是字符串")
        if "layer" in item and item["layer"] not in (None, 0, 1, "independent"):
            raise ValueError(f"characterAudit.dependencies[{i}].layer 必须是0/1/independent或null")
        if isinstance(item.get("layer"), bool):
            raise ValueError("layer 不接受布尔值")
        for key in ("width", "height"):
            if key in item and item[key] is not None and (not _number(item[key]) or item[key] <= 0 or item[key] > 65536):
                raise ValueError(f"characterAudit.dependencies[{i}].{key} 必须是有效正尺寸")
        if item.get("collectionDedupe", "none") not in ("none", "logical"):
            raise ValueError("collectionDedupe 必须是none/logical")
        for key in ("roles", "forms", "switches"):
            if key in item and (not isinstance(item[key], list) or any(not isinstance(v, str) or not v for v in item[key])):
                raise ValueError(f"依赖{key}必须是字符串数组")
        if any(v not in ROLES for v in item.get("roles", [])):
            raise ValueError("依赖roles仅支持main/unison/leader")
        if "unknown" in item and not isinstance(item["unknown"], (str, list, bool)):
            raise ValueError("依赖unknown必须是字符串、数组或布尔值")


def _selected(item, scope):
    return all(not item.get(key) or not scope.get(key) or bool(set(item[key]) & set(scope[key]))
               for key in ("roles", "forms", "switches"))


def _area(item):
    w, h = item.get("width"), item.get("height")
    if not (_number(w) and _number(h) and w > 0 and h > 0):
        return None
    return (math.ceil(w) + 2) * (math.ceil(h) + 2)


def report(project):
    """Audit declarations, preserving requesters and per-collection duplicates."""
    validate(project)
    audit = copy.deepcopy(project.get("characterAudit") or {})
    scope = audit.get("scope", {})
    entries, unknown, seen = [], [], {}
    groups = {}
    for index, item in enumerate(audit.get("dependencies", [])):
        if not _selected(item, scope):
            continue
        item["declarationIndex"] = index
        missing = [key for key in ("logical", "bucket", "collection", "layer", "source", "requester", "category")
                   if item.get(key) is None or item.get(key) == ""]
        area = _area(item)
        if area is None:
            missing.append("dimensions")
        if item.get("category") not in CATEGORIES:
            missing.append("categorySemantics")
        if item.get("category") == "cutin" and item.get("layer") != "independent":
            missing.append("cutinMustBeIndependent")
        if item.get("category") == "ui" and item.get("layer") != 1:
            missing.append("uiLayerNotConfirmed")
        item.update(paddedAreaPixels=area, layerPercent=(100 * area / CAPACITY) if area is not None and item.get("layer") in (0, 1) else None,
                    unknownFields=missing)
        if item.get("unknown") or missing:
            unknown.append({"index": index, "logical": item.get("logical"), "fields": missing,
                            "reason": item.get("unknown") or "收集来源或尺寸未完整声明"})
        key = (item.get("bucket"), item.get("collection"), item.get("layer"), item.get("logical"))
        # There is deliberately no global logical-path set. A concat of buckets
        # can contain the same target more than once.
        dedupe = item.get("collectionDedupe") == "logical" and all(v is not None and v != "" for v in key)
        if dedupe and key in seen:
            previous = entries[seen[key]]
            if previous.get("width") != item.get("width") or previous.get("height") != item.get("height"):
                unknown.append({"index": index, "logical": item.get("logical"), "reason": "同collection同logical尺寸冲突"})
            item["deduplicatedTo"] = previous["declarationIndex"]
        elif dedupe:
            seen[key] = len(entries)
        entries.append(item)
        if "deduplicatedTo" in item or area is None or missing or item.get("unknown"):
            continue
        group_key = (item["bucket"], item["collection"], item["layer"])
        group = groups.setdefault(group_key, {"bucket": item["bucket"], "collection": item["collection"], "layer": item["layer"],
                                              "targetCount": 0, "paddedAreaPixels": 0, "categories": {}})
        group["targetCount"] += 1
        group["paddedAreaPixels"] += area
        group["categories"][item["category"]] = group["categories"].get(item["category"], 0) + area
    layers = {}
    for layer in (0, 1):
        area = sum(g["paddedAreaPixels"] for g in groups.values() if g["layer"] == layer)
        layers[str(layer)] = {"knownAreaPixels": area, "knownLayerPercent": area * 100 / CAPACITY,
                              "complete": False, "packing": "not-verified",
                              "shapeLimitExceeded": any(e.get("layer") == layer and _area(e) is not None and
                                                        (math.ceil(e["width"]) > 4094 or math.ceil(e["height"]) > 4094) for e in entries)}
    missing_categories = sorted(CATEGORIES - {e.get("category") for e in entries})
    closed = bool(scope.get("closed") and scope.get("roles") and scope.get("forms") and entries and not unknown and not missing_categories)
    evidence = audit.get("closureEvidence", {})
    evidence_provided = bool(evidence.get("source"))
    return {"schema": "character-audit-v1", "scope": scope, "declared": bool(project.get("characterAudit")),
            "dependencies": entries, "collections": list(groups.values()), "layers": layers,
            "independent": [e for e in entries if e.get("layer") == "independent"], "unknown": unknown,
            "missingCategories": missing_categories, "closure": {"complete": closed, "basis": "declaration-only",
                                                                  "semanticTotalVerified": False,
                                                                  "completeCharacterTotal": False,
                                                                  "evidenceProvided": evidence_provided,
                                                                  "evidence": evidence,
                                                                  "reason": "声明范围闭合" if closed else "范围或依赖尚未闭合，未知成本不能按零计"},
            "reference": {"kind": "project-reference-not-quota", "staticBaselinePercent": [2.3, 3, 4.7],
                          "skillPercent": [.8, 1.3, 2.6], "sample": "447 direct-skill static baselines",
                          "scope": "独有静态基底，非整角色、完整场景或硬配额"},
            "optimizer": {"status": "pending", "losslessTickReadbackVerified": False},
            "nativePackingVerified": False, "gameReady": False}


def parts_metrics(parts):
    """Count definition types, prebuilt instances, and leaf commands per tick.

    The existing decoder expands the exact serialized group hierarchy. These
    command counts describe animation workload and never claim GPU draw calls.
    """
    from bridge import flatomo
    images = parts.get("i", [])
    counts = Counter("image" if "p" in item else "group" if "g" in item else "unknown" for item in images)
    allocations = parts.get("a", [])
    result = {"definitionCount": len(images), "definitionTypes": dict(counts),
              "groupDefinitionCount": len(parts.get("g", [])),
              "prebuiltInstances": sum(allocations) if all(_number(v) and v >= 0 for v in allocations) else None,
              "leafCommandsPerTick": None, "gpuDrawCalls": None, "gpuDrawCallsStatus": "not-measured"}
    groups = parts.get("g", [])
    ticks = groups[0].get("t", 0) if groups else 0
    if not isinstance(ticks, int) or not 0 <= ticks <= 10000:
        result["unknown"] = "时间线超出有界逐tick审计范围"
        return result
    try:
        frames = flatomo._build_frames(parts)
        per_tick = [len(flatomo._flatten(frames, 0, tick, (1, 0, 0, 1, 0, 0), 1)) for tick in range(ticks)]
        result.update(leafCommandsPerTick=per_tick, maxLeafCommandsPerTick=max(per_tick, default=0),
                      totalLeafCommands=sum(per_tick))
    except (KeyError, IndexError, TypeError, ValueError, RecursionError) as exc:
        result["unknown"] = f"叶命令未解析: {type(exc).__name__}"
    return result


def compiled_report(project, files):
    """Read encoded sheets/parts from a compile file map, without filesystem IO."""
    from bridge import AMF3Reader
    candidate = copy.deepcopy(project)
    if candidate.get("characterAudit") is None:
        candidate["characterAudit"] = {}
    audit = candidate["characterAudit"]
    deps = audit.setdefault("dependencies", [])
    sheets, parts, errors = [], [], []
    for name, raw in files.items():
        if name.lower().endswith(".png"):
            try:
                # Game PNG wrappers retain the PNG payload after eight bytes.
                data = b"\x89PNG\r\n\x1a\n" + raw[8:]
                with Image.open(io.BytesIO(data)) as image:
                    image.load()
                    w, h = image.size
                item = {"file": name, "width": w, "height": h, "assetBytes": len(raw),
                        "sha256": hashlib.sha256(raw).hexdigest(), "paddedAreaPixels": (w + 2) * (h + 2)}
                sheets.append(item)
                matches = [dep for dep in deps if dep.get("file") == name or dep.get("logical") in (name, name[:-4])]
                for dep in matches:
                    dep.update(width=w, height=h, assetBytes=len(raw), measurementSource="compiled-readback")
                if not matches:
                    deps.append({**item, "logical": name[:-4], "source": "compiled-readback", "unknown": "collection/layer/requester未声明"})
            except (OSError, ValueError, TypeError) as exc:
                errors.append({"file": name, "reason": str(exc)})
        elif name.endswith(".parts.amf3.deflate"):
            try:
                decoded = AMF3Reader(zlib.decompress(raw, -15)).read_value()
                parts.append({"file": name, **parts_metrics(decoded)})
            except (zlib.error, ValueError, TypeError, KeyError, IndexError) as exc:
                errors.append({"file": name, "reason": str(exc)})
    result = report(candidate)
    result.update(compiledSheets=sheets, compiledParts=parts, readbackErrors=errors,
                  assetBytes=sum(s["assetBytes"] for s in sheets))
    if errors:
        result["closure"].update(complete=False, completeCharacterTotal=False, reason="编译回读存在未解析文件")
    return result
