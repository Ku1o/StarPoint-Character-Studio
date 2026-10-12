"""Native root extraction from preserved definitions, never a deployment gate.

This module reads the definition bytes and edited rows already in a project.
It deliberately does not accept user supplied collector mappings or a declared
"complete" flag. Unknown runtime conversions remain explicit gaps. The fixed
collector fingerprints describe the inspected client; they are not evidence
that another client, platform, party or feature configuration is equivalent.
"""
from __future__ import annotations

import copy
import csv
import hashlib
import json
import math
import re
import struct
import zlib

SCHEMA = "native-character-dependencies-v1"
DOMAINS = ("skill", "pixelart", "special", "ability", "summon", "powerFlip", "shared", "ui", "cutin")
LIMIT = 48 * 1024 * 1024
MAX_ITEMS = 100000
COLLECTOR_BASIS = {
    "ActionDslAssetResolver": "91d871f3b0fed9c423563a5c974f6c6d72b888d91322ca78343ccf7cfd799bfe",
    "BattleCharacterLogic": "37d10cbfe69077f69e6ff8ba25fb0b026e0160c159ff4af0c1f78093df3025ba",
    "CharacterBaseImpl": "3921cbbb1f199bcc3b6c8fa6db947d8c80a317e983eb308f2b9fb267d2f89d6d",
    "ActionSkillLogic": "4d1f18d6d152d01754119f8b606e49d6a3e364d591653ccbe47ea58e064e24cb",
    "BattlePartyLogic": "90986dc8097379c3d792b74dad2d9590e26311ebbaa9f13aade3a2fc71248688",
    "InstantAbilitySource.resolveInstantContent.body": "b920769d365cae73818ed25a5ef2e243714122e218ed2061f7657d36acc38056",
    "InstantAbilitySource.collector": "ebed7d46b5e295f7237c861adf4b27506a543b0cc6dd03f48a01ddf92abcc741",
    "DuringAbilitySource": "edfaaec6d4384c466388b7f1547b6970e991bb688d47b9e220e091d5030c6537",
    "CommonAbilityContentTools": "0b847849d3e5cd0becaea9ae8a954720355919f6d026e7a9ea80e48353978d0d",
    "ConditionChangeContentTools": "06442ba3c9cbc1b30b5e258a6ecf005921b2e9d493d8f3bdabd9161c386908ca",
    "MemberImpl.conditionRuntime": "ffa4cb6583255ee3a79f5fe0079b90bff5a351345e12cfd65f30181ad3257f93",
    "UniqueConditionLogic": "cc0c4a20bba8daac4fddb4a574e98936d3e3581db81c2f946212f5ed4f4b58ca",
    "UniqueConditionValues": "a5996a9093b9f2cb8ce6ef3735bd26e3b5d56859a3337718ae59e8d7c36e8b5b",
    "MultiballValues": "f959261bd0363256e494d9b01ef5ee76c5cc086ea6154ca1cc8dd38213ae4dd6",
    "ActionDslCommand": "269e74d62146a47472d38344b3ccb55c5c0a9179fc716485bf25b1f0c2f3f175",
    "InahoAbilityVisuals": "cf957db67e23000e36a732a2bb6ba608561b25b7addc660f86aa8d4d49382c3a",
}
COLORS = ("red", "blue", "yellow", "green", "white", "black", "colorless")
PF_KEYS = ("knight", "fighter", "ranged", "supporter", "special")
UNIQUE_TABLE = "master/character/unique_condition.orderedmap"
INAHO_PRELOAD = ("battle/effect/ability_damage/inaho_midautumn_wip/moonlight_launch",
    "battle/effect/ability_damage/inaho_midautumn_wip/moonlight_shot_gold_jade",
    "battle/effect/ability_damage/inaho_midautumn_wip/moonlight_hit",
    "battle/effect/skill_unique/inaho_midautumn_wip/midautumn_native/effect")


def _inflate_limited(raw, label, limit=None):
    """One exact zlib stream with an allocation bound, including its index."""
    try:
        decoder = zlib.decompressobj()
        limit = LIMIT if limit is None else min(LIMIT, limit)
        output = decoder.decompress(raw, limit + 1)
    except zlib.error as exc:
        raise ValueError(label + "压缩格式无效") from exc
    if len(output) > limit or decoder.unconsumed_tail:
        raise ValueError(label + "解压输出超限")
    if not decoder.eof:
        raise ValueError(label + "压缩数据截断")
    if decoder.unused_data:
        raise ValueError(label + "压缩数据含尾字节")
    return output


def _orderedmap_ranges(raw, budget=None):
    """Validate the complete index; leave unselected rows compressed."""
    if len(raw) < 8:
        raise ValueError("原生表缺orderedmap索引")
    index_length = struct.unpack_from("<I", raw)[0]
    if not index_length or index_length > len(raw) - 4:
        raise ValueError("原生表索引长度无效")
    index = _inflate_limited(memoryview(raw)[4:4+index_length], "原生表索引", None if budget is None else budget[0])
    if budget is not None:
        budget[0] -= len(index)
    if len(index) < 4:
        raise ValueError("原生表索引缺条目数量")
    count = struct.unpack_from("<I", index)[0]
    if count > MAX_ITEMS:
        raise ValueError("原生表条目超限")
    key_start = 4 + count * 8
    if key_start > len(index):
        raise ValueError("原生表索引条目截断")
    data_start = 4 + index_length
    key_length, data_length = len(index) - key_start, len(raw) - data_start
    ranges, previous_key, previous_row = {}, 0, 0
    for offset in range(4, key_start, 8):
        key_end, row_end = struct.unpack_from("<II", index, offset)
        if not previous_key < key_end <= key_length or not previous_row <= row_end <= data_length:
            raise ValueError("原生表键或行偏移无效")
        key = index[key_start+previous_key:key_start+key_end].decode("utf-8")
        if key in ranges:
            raise ValueError("原生表含重复键")
        ranges[key] = (data_start + previous_row, data_start + row_end)
        previous_key, previous_row = key_end, row_end
    if previous_key != key_length or previous_row != data_length:
        raise ValueError("原生表索引或数据含尾字节")
    return ranges


class _DefinitionReader:
    """Only exact project-supplied binary members, never a live directory."""
    def __init__(self, files):
        self.files, self.tables = files or {}, {}

    def _table(self, logical):
        if logical not in self.tables:
            raw = self.files.get(logical)
            if not isinstance(raw, bytes) or not raw or len(raw) > LIMIT:
                raise ValueError(f"缺冻结原生表 {logical}")
            self.tables[logical] = (_orderedmap_ranges(raw), raw,
                {"logical": logical, "sha256": hashlib.sha256(raw).hexdigest()})
        return self.tables[logical]

    def rows(self, logical, key):
        if not isinstance(key, (str, int)) or isinstance(key, bool) or not str(key):
            raise ValueError("原生定义ID无效")
        ranges, table_raw, proof = self._table(logical)
        selected = ranges.get(str(key))
        if selected is None:
            raise ValueError(f"冻结原生表 {logical} 缺ID {key}")
        start, end = selected
        raw = _inflate_limited(memoryview(table_raw)[start:end], "原生表选中行") if end > start else b""
        import bridge
        import wf_mod_tool as mod
        try:
            rows = mod.read_csv_lines(raw.decode("utf-8-sig"))
        except (csv.Error, UnicodeError) as exc:
            raise ValueError("原生定义行CSV无法可信读取") from exc
        if not rows or len(rows) > MAX_ITEMS or sum(len(row) for row in rows) > MAX_ITEMS:
            raise ValueError("原生定义行字段或条目超限")
        return rows, dict(proof, key=str(key))

    def row(self, logical, key):
        rows, proof = self.rows(logical, key)
        if len(rows) != 1:
            raise ValueError(f"原生定义 {logical}:{key} 不是单行平表")
        return rows[0], proof

    def _union_selection(self, logicals, key):
        """Mirror current multi-file union, retaining missing sources as gaps."""
        available, missing, seen = [], [], set()
        for logical in logicals:
            if logical not in self.files:
                missing.append(logical)
                continue
            ranges, _, proof = self._table(logical)
            duplicates = seen.intersection(ranges)
            if duplicates:
                raise ValueError("原生合并表含重复键：" + min(duplicates))
            seen.update(ranges)
            available.append((logical, ranges, proof))
        for logical, ranges, proof in available:
            if str(key) in ranges:
                selected = dict(proof, key=str(key))
                selected["unionSources"] = [item[2] for item in available]
                return logical, selected, missing
        raise ValueError(f"冻结原生合并表缺ID {key}（{', '.join(logicals)}）")

    def union_rows(self, logicals, key):
        logical, proof, missing = self._union_selection(logicals, key)
        rows, _ = self.rows(logical, key)
        return rows, proof, missing

    def nested_union_rows(self, logicals, key, depth=1):
        """Current MasterStringMap/IntMap layers: raw children, zlib CSV leaves.

        Preserve every frozen version in authoring mode; a concrete live level
        is intentionally not invented. All selected indexes and leaves share
        one decompression/structure budget.
        """
        if depth not in (1, 2):
            raise ValueError("原生嵌套维度未支持")
        logical, proof, missing = self._union_selection(logicals, key)
        ranges, raw, _ = self._table(logical)
        start, end = ranges[str(key)]
        pending = [(memoryview(raw)[start:end], (), depth)]
        rows, budget, visits, fields = [], [LIMIT], 0, 0
        while pending:
            data, keys, level = pending.pop()
            visits += 1
            if visits > MAX_ITEMS:
                raise ValueError("原生嵌套条目超限")
            if level:
                nested = _orderedmap_ranges(data, budget)
                if len(nested) + len(pending) + visits > MAX_ITEMS:
                    raise ValueError("原生嵌套条目超限")
                pending.extend((data[a:b], keys + (inner_key,), level-1) for inner_key, (a, b) in reversed(list(nested.items())))
            else:
                csv_raw = _inflate_limited(data, "原生嵌套选中行", budget[0]) if data else b""
                budget[0] -= len(csv_raw)
                import bridge
                import wf_mod_tool as mod
                try:
                    parsed = mod.read_csv_lines(csv_raw.decode("utf-8-sig"))
                except (csv.Error, UnicodeError) as exc:
                    raise ValueError("原生嵌套CSV无法可信读取") from exc
                if len(parsed) != 1:
                    raise ValueError("原生嵌套叶不是单行CSV")
                fields += len(parsed[0])
                if fields > MAX_ITEMS:
                    raise ValueError("原生嵌套字段超限")
                rows.append({"innerKeys": list(keys), "fields": parsed[0]})
        return rows, proof, missing

    def unique(self, key):
        row, proof = self.row(UNIQUE_TABLE, key)
        if len(row) < 3:
            raise ValueError("UniqueCondition行缺icon_image列2")
        return _path(row[2]), proof

    def unique_hit(self, key):
        row, proof = self.row(UNIQUE_TABLE, key)
        if len(row) <= 11 or row[11] not in ("0", "1"):
            raise ValueError("UniqueCondition行缺合法condition_direction列11")
        direction = "buff" if row[11] == "0" else "debuff"
        return f"battle/effect/hit/condition/{direction}/{direction}", proof


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _path(value):
    if not isinstance(value, str) or not value or "\\" in value or ":" in value or value.startswith("/") or any(p in ("", ".", "..") for p in value.split("/")) or any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise ValueError("原生资源逻辑路径无效")
    return value


def _int(value):
    # Python JSON integers may exceed a float's range; comparing bounded
    # selectors later must not overflow before returning a readable problem.
    return isinstance(value, int) and not isinstance(value, bool) or isinstance(value, float) and math.isfinite(value) and value == int(value)


def _program(value):
    value = _path(value)
    return value if value.endswith(".action.dsl.amf3.deflate") else value + ".action.dsl.amf3.deflate"


def _decode(raw):
    if not isinstance(raw, bytes) or not raw or len(raw) > LIMIT:
        raise ValueError("定义字节无效或超限")
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("定义JSON含重复键")
            result[key] = value
        return result
    def constant(value):
        raise ValueError("定义JSON含非有限数值")
    value = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=pairs, parse_constant=constant)
    pending, visits = [(value, 0)], 0
    while pending:
        node, depth = pending.pop()
        visits += 1
        if visits > MAX_ITEMS or depth > 160:
            raise ValueError("定义JSON结构超限")
        children = list(node.values()) if isinstance(node, dict) else node if isinstance(node, list) else ()
        if len(children) + len(pending) + visits > MAX_ITEMS:
            raise ValueError("定义JSON容器超限")
        pending.extend((child, depth + 1) for child in children)
    return value


def extract_native_roots(project, reference_files=None, *, roles=None):
    """Return evidence-bearing native roots for all preserved skill versions.

    This is an authoring inventory, not a selected live party. Main/unison/leader
    and both illustration forms are kept as separate provenance. A root does not
    prove its bytes are present: the caller must resolve it in a frozen catalog.
    ``reference_files`` contains project-declared bytes, never a directory scan.
    """
    reference_files = reference_files or {}
    definitions = _DefinitionReader(reference_files)
    receipt = {"schema": SCHEMA, "roots": [], "domains": {}, "roles": list(roles or ("main", "unison", "leader")),
               "forms": [], "switches": [], "element": None, "problems": [], "sourceIdentity": {},
               "complete": False, "collectorBasis": copy.deepcopy(COLLECTOR_BASIS),
               "nativePackingVerified": False, "runtimeAccepted": False, "gameReady": False,
               "selection": "authoring-superset: self-main/other-main UI union and all preserved versions; learned/awake/equipment/EX and party activation are not simulated",
               "selectedPartyTotals": False}
    if any(role not in ("main", "unison", "leader") for role in receipt["roles"]):
        raise ValueError("依赖角色仅支持main/unison/leader")
    def problem(domain, reason, pointer="", **details):
        item = {"domain": domain, "reason": reason, "pointer": pointer, **copy.deepcopy(details)}
        if item not in receipt["problems"]:
            receipt["problems"].append(item)
    def domain(name, status="pending", reason="缺原生提取依据"):
        receipt["domains"][name] = {"status": status, "roots": [], "reason": reason}
    for name in DOMAINS:
        domain(name)
    native = project.get("nativeGameplay")
    if not isinstance(native, dict) or native.get("schema") != "starpoint-native-gameplay-v1":
        problem("definition", "工程未含完整原生定义；美术素材与手工范围不证明能力或技能根")
        return receipt
    source = native.get("source")
    try:
        data = source["data"]
        raw = canonical(data)
        if len(raw) > LIMIT or source.get("sha256") != hashlib.sha256(raw).hexdigest():
            raise ValueError("原始角色定义校验不一致")
        character = data["character"]
        records = character["records"]
        cid = character["id"]
        row = records["character"]["selected"][cid]["rows"][0]
        if not isinstance(row, list) or len(row) < 37 or any(not isinstance(v, str) for v in row):
            raise ValueError("角色原生行结构无效")
        if row[0] != character.get("code"):
            raise ValueError("角色代号与定义行不一致")
        code = _path(row[0])
        if "/" in code:
            raise ValueError("角色代号不能包含目录")
        element = int(row[3])
        rarity = int(row[2])
        if not 0 <= element <= 6 or not 1 <= rarity <= 5:
            raise ValueError("角色属性或稀有度枚举无效")
    except (ValueError, TypeError, KeyError, IndexError, AttributeError, OverflowError, RecursionError) as exc:
        problem("definition", str(exc))
        return receipt
    receipt["element"] = element
    receipt["sourceIdentity"] = {"sha256": source["sha256"], "characterId": cid, "code": code,
        "version": data.get("version"), "encoding": "canonical-json-utf8",
        "editedRowsSha256": hashlib.sha256(canonical({key: native.get(key) for key in ("skills", "leader", "abilities")})).hexdigest()}
    proof = {"logical": "native-definition/source.json", "sha256": source["sha256"]}
    def add(logical, category, role, form="all", switch="base", layer=0, bucket="BattlePart", pointer="", kind="effect", evidence=None, origin="collector", collection="character-authoring", resource_owner=None):
        try:
            logical = _path(logical)
        except ValueError as exc:
            problem(category, str(exc), pointer)
            return
        root = {"logical": logical, "category": category, "roles": [role], "forms": [str(form)], "switches": [switch],
                "requester": f"character:{cid}:{role}:{form}:{switch}:{pointer}", "source": "native-definition/source.json" + pointer,
                "sourceSha256": source["sha256"], "bucket": bucket, "collection": collection, "layer": layer, "kind": kind}
        root["origin"] = origin
        if resource_owner:
            root["resourceOwner"] = resource_owner
        if evidence:
            root["definitionEvidence"] = evidence
        if root not in receipt["roots"]:
            receipt["roots"].append(root)
        if logical not in receipt["domains"][category]["roots"]:
            receipt["domains"][category]["roots"].append(logical)
    main_roles = [role for role in receipt["roles"] if role in ("main", "leader")]
    for role in main_roles:
        add(f"character/{code}/pixelart/pixelart", "pixelart", role, pointer="/character/records/character/0")
        if rarity >= 4:
            add(f"character/{code}/pixelart/special", "special", role, pointer="/character/records/character/2")
        for form in ("0", "1"):
            for name in ("cutin_skill_chain", "battle_member_status", "battle_control_board", "square"):
                add(f"character/{code}/ui/{name}_{form}", "ui", role, form, layer=1, pointer="/character/records/character/0", kind="image")
    for role in receipt["roles"]:
        for form in ("0", "1"):
            add(f"character/{code}/ui/skill_cutin_{form}", "cutin", role, form, layer="independent", bucket="characters", kind="image")
    for name in ("pixelart", "special", "ui", "cutin"):
        status = "not-applicable" if name == "special" and rarity < 4 else "included"
        receipt["domains"][name].update(status=status, reason="原生getter与主副位收集规则；枚举两种图像形态，实际存在性由冻结catalog核对", evidence=proof)
    skills = native.get("skills")
    if not isinstance(skills, list) or len(skills) > 32 or not skills:
        problem("skill", "技能版本行缺失或结构无效")
    else:
        for index, skill in enumerate(skills):
            fields = skill.get("fields") if isinstance(skill, dict) else None
            form = str(skill.get("inner_key", "")) if isinstance(skill, dict) else ""
            if not form or not isinstance(fields, list) or len(fields) < 8:
                problem("skill", "技能版本缺原生字段", f"/skills/{index}")
                continue
            if form not in receipt["forms"]:
                receipt["forms"].append(form)
            for role in receipt["roles"]:
                if role != "unison" or fields[3] == "true":
                    try:
                        add(_program(fields[7]), "skill", role, form, pointer=f"/skills/{index}/fields/7", kind="dsl")
                    except ValueError as exc:
                        problem("skill", str(exc), f"/skills/{index}/fields/7")
            if fields[3] not in ("true", "false"):
                problem("skill", "技能副位准入Bool无效", f"/skills/{index}/fields/3")
        receipt["domains"]["skill"].update(status="included" if not any(p["domain"] == "skill" for p in receipt["problems"]) else "pending",
                                                reason="全部保留技能版本；不冒充当前阵容激活结果", evidence=proof)
    # CharacterValues: switching Option is column9, its referenced key14.
    # Column28 is pedestal_image and must never become a switching key.
    switching = row[14]
    if row[9] not in ("(None)", ""):
        if row[9] not in ("0", "1", "2", "3", "4") or not switching:
            problem("skill", "技能切换条件枚举或program key无效", "/character/records/character/9")
        receipt["switches"].append(switching)
        switched = records.get("switched_skill", {})
        rows = switched.get("rows") if isinstance(switched, dict) else None
        if not isinstance(rows, list) or not rows:
            problem("skill", "有技能切换条件但缺switched_skill原始行", "/character/records/character/14")
            receipt["domains"]["skill"]["status"] = "pending"
        else:
            for index, entry in enumerate(rows):
                fields = entry.get("fields") if isinstance(entry, dict) else None
                form = str(entry.get("inner_key", "all")) if isinstance(entry, dict) else "all"
                if not isinstance(fields, list) or not fields:
                    problem("skill", "切换技能行缺原生program_path", f"/character/records/switched_skill/rows/{index}")
                    continue
                # SwitchedActionSkillValues: program_path[0]. It is not the
                # action_skill table and has no name/description prefix.
                for role in receipt["roles"]:
                    try:
                        add(_program(fields[0]), "skill", role, form, switching, pointer=f"/character/records/switched_skill/rows/{index}/fields/0", kind="dsl")
                    except ValueError as exc:
                        problem("skill", str(exc), f"/character/records/switched_skill/rows/{index}/fields/0")
    if not receipt["switches"]:
        receipt["switches"] = ["base"]
    # Real row widths and case offsets are read from the bundled generated map.
    import bridge  # register the bundled core without touching game resources
    import wf_describe as describe
    from wf_client_legality import client_legality_problems
    groups = [("leader", "leader_ability", native.get("leader"))]
    groups.extend(("ability-" + str(g.get("slot")), "ability", g) for g in native.get("abilities", []) if isinstance(g, dict))
    for label, kind, group in groups:
        rows = group.get("rows") if isinstance(group, dict) else None
        if not isinstance(rows, list):
            problem("ability", "能力组缺原始行", "/" + label)
            continue
        base = describe.layout(kind)["blocks"]["instant_content"]
        # AbilityLogic.get_unisonable reads values[0].unisonable for the whole
        # group. Individual later rows cannot open a group refused by row0.
        group_unisonable = bool(rows and isinstance(rows[0], list) and len(rows[0]) > 1 and rows[0][1] == "true")
        for index, ability in enumerate(rows):
            pointer = f"/{label}/rows/{index}"
            try:
                for issue in client_legality_problems(kind, ability):
                    problem("ability", issue, pointer)
                if len(ability) <= base + 24:
                    raise ValueError("原生能力行宽不足")
                if kind == "ability" and ability[1] not in ("true", "false"):
                    problem("ability", "能力行unisonable必须为true/false", pointer + "/1")
                eligible = ["leader"] if kind == "leader_ability" else [r for r in receipt["roles"] if r != "unison" or group_unisonable]
                if kind == "leader_ability" and "leader" not in receipt["roles"]:
                    eligible = []
                from native_ability_dependencies import resolve_ability_resources
                mapped = resolve_ability_resources(ability, kind, element, definitions, pointer)
                receipt.setdefault("abilityCoverage", []).extend(mapped["coverage"])
                for reference in mapped["references"]:
                    context = reference["context"]
                    for role in eligible:
                        add(reference["logical"], reference["domain"], role, pointer=reference["pointer"],
                            layer=context.get("layer", 0), kind=context.get("kind", "effect"),
                            evidence=reference.get("definitionEvidence"), origin=reference.get("origin", "collector"))
                for item in mapped["problems"]:
                    problem(item["domain"], item["reason"], item["pointer"])
            except (ValueError, TypeError, IndexError, KeyError) as exc:
                problem("ability", "能力原生解析失败：" + str(exc), pointer)
    effect_coverage = receipt.get("abilityCoverage", [])
    receipt["abilityConversionSummary"] = {
        "mappedEffectBlocks": sum(item.get("status") == "included" for item in effect_coverage),
        "pendingEffectBlocks": sum(item.get("status") != "included" for item in effect_coverage),
        "reportedAbilityProblems": sum(item.get("domain") == "ability" for item in receipt["problems"]),
        "scope": "preserved-instant-and-during-effects-only",
        "triggerAdmissionVerified": False, "completeAbilityDomain": False}
    receipt["domains"]["ability"].update(reason="已检查当前保存能力的可确认效果；未识别分支、额外能力、觉醒、装备、EX及实际触发范围继续待核", evidence=proof)
    receipt["domains"]["shared"].update(reason="已提取instant共享计数、当前伤害分支Inaho预载、460/156伪装血量图集；完整Common/Attention和阵容公共预载仍待核", evidence=proof)
    receipt["domains"]["summon"].update(reason="召唤/funnel/UniqueCondition需从可达DSL和真实召唤定义递归解析；不能从无自有图推断不适用", evidence=proof)
    # A preserved selected PF row is evidence; the speciality name alone is not.
    pf = records.get("power_flip")
    if isinstance(pf, dict):
        pf_rows = pf.get("rows", [])
        pf_source = pf.get("source", {})
        if isinstance(pf_rows, list) and len(pf_rows) == 1 and isinstance(pf_rows[0], list) and len(pf_rows[0]) >= 3 and re.fullmatch(r"[0-9a-f]{64}", str(pf_source.get("sha256", ""))):
            if "leader" in receipt["roles"]:
                for level, logical in enumerate(pf_rows[0][:3], 1):
                    try:
                        add(_program(logical), "powerFlip", "leader", pointer=f"/character/records/power_flip/rows/0/{level-1}", kind="dsl")
                    except ValueError as exc:
                        problem("powerFlip", str(exc), f"/character/records/power_flip/rows/0/{level-1}")
            receipt["domains"]["powerFlip"].update(status="included", reason="真实选中PF原生三等级路径，限定队长入口", evidence=proof)
        else:
            problem("powerFlip", "PF定义需带真实三等级行与源成员SHA")
    else:
        problem("powerFlip", "缺原生PF三等级定义；职业名不证明PF程序根")
    from native_ability_dependencies import common_resources, BASIS as complex_basis
    from native_common_dependencies import conditional_common_resources
    from native_summon_dependencies import BASIS as summon_basis
    common = common_resources()
    conditional = conditional_common_resources(project, definitions, reference_files)
    receipt["commonConditionalCoverage"] = copy.deepcopy(conditional["coverage"])
    receipt["commonSelection"] = copy.deepcopy(conditional["selection"])
    receipt["requiredReferences"] = copy.deepcopy(conditional["requiredReferences"])
    covered = set(conditional["coveredGapPointers"])
    common["references"].extend(conditional["references"])
    common["problems"] = [item for item in common["problems"] if item["pointer"] not in covered]
    common["problems"].extend(conditional["problems"])
    receipt["collectorBasis"].update(complex_basis)
    receipt["collectorBasis"].update(conditional["collectorBasis"])
    receipt["collectorBasis"].update(summon_basis)
    for reference in common["references"]:
        context = reference["context"]
        for role in receipt["roles"]:
            add(reference["logical"], "shared", role, bucket=context["bucket"], layer=context["layer"],
                kind=context["kind"], pointer=reference["pointer"], collection=context["collection"],
                evidence=reference.get("definitionEvidence"), origin=reference.get("origin", "collector"),
                resource_owner=context.get("resourceOwner"))
    for item in common["problems"]:
        problem(item["domain"], item["reason"], item["pointer"],
                **{key: value for key, value in item.items() if key not in ("domain", "reason", "pointer")})
    receipt["domains"]["shared"]["reason"] = "已自动检查公共固定根、条件候选及12个界面/说明入口；运行时文字、奖励内容、配置与动态来源仍逐项待核，制作范围不代表实际阵容"
    if not receipt["forms"]:
        receipt["forms"] = ["all"]
    for root in receipt["roots"]:
        for form in root["forms"]:
            if form not in receipt["forms"]:
                receipt["forms"].append(form)
        for switch in root["switches"]:
            if switch not in receipt["switches"]:
                receipt["switches"].append(switch)
    for item in receipt["problems"]:
        if item["domain"] in receipt["domains"]:
            receipt["domains"][item["domain"]]["status"] = "pending"
    # No manual declarations, empty directories or parser success can upgrade
    # the unimplemented ability, summon and scene semantics to complete.
    return receipt


CONDITION_NAMES = frozenset(("ACAttackPoint", "ACSkillDamage", "ACAbilityDamage", "ACAbilityDamageResistance", "ACDirectAttackDamageResistance",
    "ACPowerFlipDamageResistance", "ACSkillDamageResistance", "ACToleranceOfElement", "ACDamageOfElement", "ACDamageOfElementPercent", "ACSpecialEfficacy",
    "ACRegeneration", "ACPoison", "ACInvincible", "ACParalysis", "ACFrozen", "ACBuffRejection", "ACHealRejection", "ACFeverPoint", "ACStun", "ACOiuchi",
    "ACToleranceOfDebuff", "ACPiercing", "ACFlying", "ACPowerFlipDamage", "ACDirectDamage", "ACSilence", "ACAdditionalDirectAttack", "ACSpeedup", "ACAdversity",
    "ACGuts", "ACUnique", "ACComboBoost", "ACBipolar", "ACGeneralBipolar", "ACFixedSpeed", "ACSkillGaugeCharging", "ACComboRestriction",
    "ACPowerFlipComboCountDown", "ACSeparatedTermPowerFlipDamage", "ACSeparatedTermDirectDamage", "ACSwift"))
CONDITION_FIXED = {
    "ACRegeneration": ["battle/effect/hit/condition/enhancing_regeneration/enhancing_regeneration"],
    "ACHealRejection": ["battle/effect/hit/condition/enfeebling_no_heal/enfeebling_no_heal"],
    "ACStun": ["battle/effect/hit/condition/buff_ease_stun/buff_ease_stun", "battle/effect/hit/condition/debuff_ease_stun/debuff_ease_stun"],
    "ACAdversity": ["battle/effect/hit/condition/buff_adverse/buff_adverse", "battle/effect/hit/condition/debuff_adverse/debuff_adverse"],
    "ACGuts": ["battle/effect/hit/condition/enhancing_grit/enhancing_grit"],
    "ACComboBoost": ["battle/effect/hit/condition/buff_combo_boost/buff_combo_boost"],
    "ACPowerFlipComboCountDown": ["battle/effect/hit/condition/combo_reduction/combo_reduction"],
}
for _name in ("ACAbilityDamageResistance", "ACDirectAttackDamageResistance", "ACPowerFlipDamageResistance", "ACSkillDamageResistance"):
    CONDITION_FIXED[_name] = ["battle/effect/hit/condition/buff_specific_defence/up_defense", "battle/effect/hit/condition/debuff_specific_defence/down_defense"]
CONDITION_FIXED["ACToleranceOfElement"] = [f"battle/effect/hit/condition/{direction}_element_defence/{direction}_defense_{color}/{direction}_defense_{color}"
    for direction in ("buff", "debuff") for color in ("all", *COLORS[:6])]


def resolve_command_resources(command, element=None, pointer="", *, reference_files=None, _definitions=None):
    """Resolve inspected command resource slots; callbacks remain caller-owned.

    ``handled`` means this command's resource slots were examined, not that its
    types, targets, callbacks, mechanics or resulting resources are valid.
    """
    result = {"references": [], "problems": [], "handled": False, "handledPointers": [], "requiredDefinitions": [], "coverage": []}
    definitions = _definitions or _DefinitionReader(reference_files)
    def issue(reason, at=pointer, dynamic=False, domain="shared"):
        result["problems"].append({"pointer": at, "reason": reason, "domain": domain, "dynamic": dynamic})
    def add(logical, at, domain="shared", layer=0, kind="effect", evidence=None):
        try:
            _path(logical)
        except ValueError as exc:
            issue(str(exc), at, domain=domain)
            return
        item = {"logical": logical, "pointer": at, "domain": domain, "context": {"category": domain, "layer": layer, "bucket": "BattlePart", "kind": kind}}
        if evidence:
            item["definitionEvidence"] = evidence
        if item not in result["references"]:
            result["references"].append(item)
    def effect(value, at, domain="shared"):
        if isinstance(value, list) and len(value) == 2 and value[0] == "SpecifyEffectDirectly":
            add(value[1], at, domain)
        elif isinstance(value, list) and len(value) == 3 and value[0] == "SpecifyEffectByElement":
            selector = value[2]
            resolved = element if selector == 255 else int(selector) - 1 if _int(selector) and 1 <= selector <= 7 else None
            if not _int(resolved) or not 0 <= resolved <= 6:
                issue("属性特效缺已确认的角色元素或有效选择条件（element/selector）", at, True, domain)
                return
            try:
                base = _path(value[1]); suffix = base.rsplit("/", 1)[-1] + "_" + COLORS[int(resolved)]
                add(base + "/" + suffix + "/" + suffix, at, domain)
            except ValueError as exc:
                issue(str(exc), at, domain=domain)
        else:
            issue("Effect枚举结构未支持", at)
    if not isinstance(command, list) or not command or not isinstance(command[0], str):
        return result
    tag = command[0]
    def slot(index):
        return command[index] if len(command) > index else None
    def ready(value, at):
        if isinstance(value, list) and ((len(value) == 2 and value[0] == "E1") or (len(value) == 4 and value[0] == "E2")):
            for index, item in enumerate(value[1:], 1):
                effect(item, at + "/" + str(index), "summon")
        else:
            issue("MultiballReadyEffect结构未支持", at, domain="summon")
    def required(kind, key, at):
        result["requiredDefinitions"].append({"kind": kind, "key": key, "pointer": at, "domain": "summon"})
    def summon(kind, key, at):
        from native_summon_dependencies import resolve_summon_resources
        mapped = resolve_summon_resources(kind, key, definitions, at)
        for field in ("references", "problems", "requiredDefinitions", "coverage"):
            result[field].extend(mapped[field])
    if tag == "SetPowerFilpSuppress":
        # Current ActionDslCommand index75, AssetResolver case75 is break.
        result["handled"] = True
        if len(command) != 2 or not _int(slot(1)):
            issue("SetPowerFilpSuppress参数结构无效", pointer)
    elif tag == "CreateBombMultiball":
        result["handled"] = True
        add(slot(2), pointer + "/2", "summon")
        ready(slot(3), pointer + "/3")
        for index in (4, 5):
            effect(slot(index), pointer + "/" + str(index), "summon")
    elif tag == "CreateSummonsMultiball":
        result["handled"] = True
        summon("Multiball", slot(2), pointer + "/2")
        ready(slot(4), pointer + "/4")
        for index in (5, 6):
            effect(slot(index), pointer + "/" + str(index), "summon")
    elif tag == "SpawnFunnel":
        result["handled"] = True
        value = slot(1)
        if isinstance(value, list) and len(value) == 2 and value[0] in ("Funnel", "Zako", "StandardFunnel") and isinstance(value[1], str) and value[1]:
            summon(value[0], value[1], pointer + "/1")
        else:
            issue("SpawnFunnelKind枚举结构未支持", pointer + "/1", domain="summon")
    elif tag == "ShowEffect":
        result["handled"] = True
        effect(slot(2), pointer + "/2")
    elif tag == "CreateNormalAttack":
        result["handled"] = True
        hit = slot(15); selector = slot(2)
        if hit == ["None"]:
            pass
        elif isinstance(hit, list) and len(hit) == 3 and hit[0] == "SpecifyHitEffectDirectly":
            effect(hit[1], pointer + "/15/1")
        elif isinstance(hit, list) and len(hit) == 1 and isinstance(hit[0], str):
            known = {"Dark": "dark", "Explosion": "explosion", "Fire": "fire", "Frozen": "frozen", "Shine": "shine", "Splash": "splash", "ThunderLight": "thunder_light", "ThunderSmall": "thunder_small", "Tornado": "tornado"}
            if hit[0] in known:
                name = known[hit[0]]; add(f"battle/effect/hit/normal_damage/{name}/{name}", pointer + "/15")
            elif hit[0] in ("Fine", "Coarse", "Slash", "CriticalSlash"):
                resolved = element if selector == 255 else int(selector) - 1 if _int(selector) and 1 <= selector <= 7 else None
                if not _int(resolved) or not 0 <= resolved <= 6:
                    issue("属性命中特效缺冻结element", pointer + "/2", True)
                elif resolved == 6:
                    issue("原生不存在colorless的fine/coarse/slash命中特效", pointer + "/15")
                else:
                    name = {"Fine": "fine", "Coarse": "coarse", "Slash": "slash", "CriticalSlash": "slash_strong"}[hit[0]]
                    suffix = name + "_" + COLORS[int(resolved)]
                    add(f"battle/effect/hit/normal_damage/{name}/{suffix}/{suffix}", pointer + "/15")
            else:
                issue("未知AttackHitEffect", pointer + "/15")
        else:
            issue("AttackHitEffect结构无效", pointer + "/15")
    elif tag == "CreateCondition":
        result["handled"] = True
        conditions, hit = slot(2), slot(4)
        if not isinstance(conditions, list) or len(conditions) > 4096:
            issue("CreateCondition缺conditions数组", pointer + "/2"); conditions = []
        generic = hit == ["GenericConditionHitEffect"]
        if hit == ["None"] or generic:
            pass
        elif isinstance(hit, list) and len(hit) == 2 and hit[0] == "SpecifyConditionHitEffectDirectly":
            effect(hit[1], pointer + "/4/1")
        else:
            issue("ConditionHitEffect枚举未支持", pointer + "/4")
        for index, condition in enumerate(conditions):
            at = pointer + f"/2/{index}"
            if not isinstance(condition, list) or not condition or not isinstance(condition[0], str) or condition[0] not in CONDITION_NAMES:
                issue("未知AdditionalConditionKind", at)
                continue
            name = condition[0]
            if generic:
                for logical in CONDITION_FIXED.get(name, []):
                    add(logical, at)
            if name == "ACUnique":
                try:
                    logical, proof = definitions.unique(condition[1] if len(condition) > 1 else None)
                    add(logical, at + "/1", "ability", layer=1, kind="image", evidence=proof)
                except (ValueError, UnicodeError) as exc:
                    issue(str(exc), at, True, "ability")
            elif name == "ACComboBoost":
                add("battle/uncommon/layer1/combo_boost/boost_text_ui", at, layer=1)
            elif name == "ACComboRestriction":
                for logical in ("combo_restrict_frame", "combo_restrict_label"):
                    add("battle/uncommon/layer1/combo_restrict/" + logical, at, layer=1)
        # Null means no check target. An empty/unknown enum is not null.
        if slot(8) is not None:
            if isinstance(slot(8), list) and slot(8):
                for logical in ("hit_gauge_blink", "hit_link_condition"):
                    add("battle/uncommon/layer1/hit_check_link_condition/" + logical, pointer + "/8", layer=1)
            else:
                issue("HitCountCheckTargetKind结构无效", pointer + "/8")
    if result["handled"]:
        result["handledPointers"].append(pointer)
    return result


def resolve_dsl_resources(tree, element=None, *, reference_files=None):
    """Return extra refs and handled command pointers for the existing walker."""
    from native_summon_dependencies import BASIS as summon_basis
    result = {"references": [], "problems": [], "handledPointers": [], "requiredDefinitions": [], "coverage": [], "collectorBasis": dict(COLLECTOR_BASIS, **summon_basis)}
    definitions = _DefinitionReader(reference_files)
    pending, visits = [(tree, "", 0)], 0
    while pending:
        node, pointer, depth = pending.pop()
        visits += 1
        if visits > MAX_ITEMS or depth > 160:
            result["problems"].append({"pointer": pointer, "domain": "dsl", "reason": "DSL遍历超限", "dynamic": False})
            break
        if not isinstance(node, list):
            continue
        if node and node[0] == "Command" and len(node) == 2:
            resolved = resolve_command_resources(node[1], element, pointer + "/1", _definitions=definitions)
            for key in ("references", "problems", "handledPointers", "requiredDefinitions", "coverage"):
                result[key].extend(resolved[key])
            # These are callbacks, not arbitrary nested parameter values.
            cmd = node[1]
            if isinstance(cmd, list) and cmd and cmd[0] == "CreateHitArea":
                pending.extend((cmd[index], pointer + f"/1/{index}", depth + 1) for index in (20, 23) if len(cmd) > index)
            elif isinstance(cmd, list) and cmd and cmd[0] == "CreateSummonsMultiball":
                if len(cmd) > 12 and cmd[12] is not None:
                    pending.append((cmd[12], pointer + "/1/12", depth + 1))
            elif not resolved["handled"] and isinstance(cmd, list):
                # The existing walker owns callback command semantics. Only
                # already-typed expression children are examined here; scalar
                # command payloads are never guessed to contain executable DSL.
                from character_dependencies import CALLBACK_COMMANDS
                if cmd and cmd[0] in CALLBACK_COMMANDS:
                    pending.extend((child, pointer + f"/1/{index}", depth + 1) for index, child in enumerate(cmd)
                                   if isinstance(child, list) and child and child[0] in ("Block", "Command", "Event"))
        else:
            if node and node[0] == "ActionDsl":
                if len(node) > 11:
                    pending.append((node[11], pointer + "/11", depth + 1))
            elif node and node[0] == "Block" and len(node) == 2 and isinstance(node[1], list):
                pending.extend((child, pointer + "/1/" + str(index), depth + 1) for index, child in enumerate(node[1]) if isinstance(child, list))
            elif node and node[0] == "Event" and len(node) == 2 and isinstance(node[1], list):
                event = node[1]
                from character_dependencies import EVENTS
                if event and event[0] in EVENTS:
                    pending.extend((child, pointer + "/1/" + str(index), depth + 1) for index, child in enumerate(event)
                                   if isinstance(child, list) and child and child[0] in ("Block", "Command", "Event"))
    return result
