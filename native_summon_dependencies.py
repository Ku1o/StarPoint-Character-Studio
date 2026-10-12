"""Finite summon collectors from the inspected current client.

Definitions come exclusively from frozen reference bytes. Every authored level
is inventoried; runtime level, watch actions and enemy BattleScript branches
remain explicit gaps. Recursive ActionDSL edges are returned to the existing
bounded graph walker, which also retains the summoned body's own element.
"""

MULTIBALL_TABLES = ("master/battle/multiball/multiball_iosbundled.orderedmap", "master/battle/multiball/multiball.orderedmap")
ABILITY_TABLE = "master/ability/ability.orderedmap"
FUNNEL_TABLES = ("master/battle/boss/funnel/general_funnel_iosbundled.orderedmap", "master/battle/boss/funnel/general_funnel.orderedmap")
FUNNEL_STATE_TABLES = ("master/battle/boss/funnel/general_funnel_state_iosbundled.orderedmap", "master/battle/boss/funnel/general_funnel_state.orderedmap")
ZAKO_TABLES = ("master/battle/zako/general_zako_iosbundled.orderedmap", "master/battle/zako/general_zako.orderedmap")
STANDARD_TABLES = ("master/battle/boss/funnel/standard_funnel_iosbundled.orderedmap", "master/battle/boss/funnel/standard_funnel.orderedmap")
BASIS = {
    "swf": "9418137820c007b52a11ad0d7955c102795d8dd903213670577bf3407ed709f7",
    "registry": "e7da4efa9d1e44495b949b86d0ff0f74781f869cfbecc0e8d1935fed9ed30848",
    "FunnelSource": "89a6bb7564d1ccca96aef257fbb96bee34dc8b7356f138ac172d30e5fe3c7f3f",
    "ZakoSource": "bee7fe336fa1bbde8b424f3652374502522e9b7ad581be3c4d313c7247194e4e",
    "EnemySourceBase": "6e5999843ac6c1cc51ec981ff985a8cef74d5f8424fd6ac2b052eac2176a8a16",
    "GeneralFunnelValues": "ad9659b7cf4cfc2f710afedce805a7d8089dc484c38b90e501de9e78e5e9a029",
    "GeneralZakoValues": "a97dad333bb3fbdbbe96735c1d2cd7775d461e6fca10a08ce047105d6c873b7c",
    "StandardFunnelValues": "4be15788098bee60803d8e99acf4b07b721f7f74b5513404fbbebabd6f94334d",
    "GeneralFunnelStateValues": "113fca6741b226144f7eda46a2d28f7811b5cfffadf48e914696d5f5e58e0ac3",
    "EnemyDslHandler": "b14fb29cd4ba08f745e6dcb85cb80c4b6fcf806866232e29b0475a8c30739d36",
}


def resolve_summon_resources(kind, key, definitions, pointer=""):
    from native_dependencies import MAX_ITEMS, _path, _program, _int
    from native_ability_dependencies import resolve_ability_resources
    result = {"references": [], "problems": [], "requiredDefinitions": [], "coverage": [], "collectorBasis": BASIS}
    seen = set()

    def issue(reason, at=pointer, domain="summon"):
        if len(result["problems"]) >= MAX_ITEMS:
            raise ValueError("召唤问题条目超限")
        result["problems"].append({"domain": domain, "pointer": at, "reason": reason, "dynamic": True})

    def required(name, value, at):
        if len(result["requiredDefinitions"]) >= MAX_ITEMS:
            raise ValueError("召唤定义条目超限")
        result["requiredDefinitions"].append({"kind": name, "key": value, "pointer": at, "domain": "summon"})

    def add(logical, at, proof, element=None, resource_kind="effect", layer=0):
        logical = _program(logical) if resource_kind == "dsl" else _path(logical)
        signature = (logical, at, element, resource_kind, layer)
        if signature in seen:
            return
        if len(result["references"]) >= MAX_ITEMS:
            raise ValueError("召唤素材条目超限")
        seen.add(signature)
        result["references"].append({"logical": logical, "pointer": at, "domain": "summon",
            "origin": "native-definition-reference", "definitionEvidence": proof,
            "context": {"category": "summon", "layer": layer, "kind": resource_kind, "element": element}})

    def gaps(missing, at):
        for logical in missing:
            issue(f"召唤合并源未冻结：{logical}，key {key}；已知根已纳入，合并完整性仍待核", at)

    def rowscope(proof, inner_keys):
        return dict(proof, innerKeys=inner_keys)

    try:
        if kind not in ("Multiball", "Funnel", "Zako", "StandardFunnel"):
            raise ValueError("召唤定义类型未支持")
        if kind == "Multiball" and _int(key):
            key = int(key)
        if not isinstance(key, (str, int)) or isinstance(key, bool) or not str(key):
            raise ValueError("召唤定义ID无效")
        if kind == "Multiball" and (not str(key).isdecimal() or int(key) > 2147483647):
            raise ValueError("Multiball定义ID须为非负int")
        required(kind, key, pointer)
        if kind == "Multiball":
            rows, proof, missing = definitions.union_rows(MULTIBALL_TABLES, key)
            gaps(missing, pointer)
            if len(rows) != 1 or len(rows[0]) < 28:
                raise ValueError("Multiball定义不是合法28列平表")
            fields = rows[0]
            if fields[3] not in tuple(str(i) for i in range(7)):
                raise ValueError("Multiball自身element无效")
            element = int(fields[3])
            prefix = _path(fields[1])
            add(f"character/{prefix}/pixelart/pixelart", pointer + "/image_prefix", proof, element)
            if fields[9] != "(None)":
                add(fields[9], pointer + "/action", proof, element, "dsl")
                issue("召唤技能名为dynamicActionSkillName，需对应名称及字体生成来源", pointer + "/action/name")
            for slot, value in enumerate(fields[20:24], 1):
                at = pointer + f"/support_skill{slot}"
                if value == "(None)":
                    continue
                if not value.isdecimal() or int(value) > 2147483647:
                    issue("support_skill定义ID无效", at); continue
                required("Ability", value, at)
                try:
                    support_rows, support_proof = definitions.rows(ABILITY_TABLE, value)
                    import bridge
                    from wf_client_legality import client_legality_problems
                    for index, support in enumerate(support_rows):
                        if len(result["coverage"]) >= MAX_ITEMS:
                            raise ValueError("召唤支持能力条目超限")
                        source_at = at + f"/rows/{index}"
                        for problem in client_legality_problems("ability", support):
                            issue("支持能力原生行不合法：" + str(problem), source_at, "ability")
                        mapped = resolve_ability_resources(support, "ability", element, definitions, source_at)
                        parents = [proof, support_proof]
                        for reference in mapped["references"]:
                            if len(result["references"]) >= MAX_ITEMS:
                                raise ValueError("召唤素材条目超限")
                            own_proof = reference.get("definitionEvidence", {})
                            result["references"].append(dict(reference, origin="native-support-ability",
                                definitionEvidence=dict(own_proof, parents=parents)))
                        result["problems"].extend(mapped["problems"])
                        result["coverage"].extend(mapped["coverage"])
                        if len(result["problems"]) > MAX_ITEMS or len(result["coverage"]) > MAX_ITEMS:
                            raise ValueError("召唤支持能力解析条目超限")
                except (ValueError, UnicodeError) as exc:
                    issue(str(exc), at, "ability")
            result["coverage"].append({"kind": kind, "key": str(key), "pointer": pointer,
                "status": "partial", "reason": "小人、固定action、4项支持能力已按冻结定义递归；动态技能名与触发准入不声称闭合"})
        else:
            tables = {"Funnel": FUNNEL_TABLES, "Zako": ZAKO_TABLES, "StandardFunnel": STANDARD_TABLES}[kind]
            versions, proof, missing = definitions.nested_union_rows(tables, key)
            gaps(missing, pointer)
            for version in versions:
                try:
                    fields, inner_keys = version["fields"], version["innerKeys"]
                    at = pointer + "/levels/" + "/".join(inner_keys)
                    selected_proof = rowscope(proof, inner_keys)
                    if kind == "StandardFunnel":
                        if not fields:
                            raise ValueError("StandardFunnel定义缺EnemyDsl路径列0")
                        path = _path(fields[0])
                        logical = path if path.endswith(".esdl.amf3.deflate") else path + ".esdl.amf3.deflate"
                        add(logical, at + "/path", selected_proof, resource_kind="enemy-dsl")
                        required("EnemyDsl", path, at + "/path")
                        issue(f"StandardFunnel已定位EnemyDsl {path}；其格式、动态来源与递归收集待核", at + "/path")
                        continue
                    minimum, marker, shadow, checks, routine, first_action, last_action = (
                        (139, 23, 24, (25, 26, 27, 28), 37, 89, 138) if kind == "Funnel"
                        else (40, 10, 11, (12, 13, 14, 15), 17, 30, 39))
                    if len(fields) < minimum or fields[0] not in tuple(str(i) for i in range(8)):
                        raise ValueError(f"{kind}定义字段/element无效")
                    inherited = fields[0] == "0"
                    element = None if inherited else int(fields[0]) - 1
                    body_paths = fields[2:8] if inherited else fields[1:2]
                    for index, path in enumerate(body_paths):
                        add(path, at + f"/body/{index}", selected_proof, element)
                    add(fields[shadow], at + "/shadow", selected_proof, element)
                    timeline = _path(fields[marker])
                    if not timeline.endswith(".timeline.amf3.deflate"):
                        timeline += ".timeline.amf3.deflate"
                    add(timeline, at + "/marker", selected_proof, element, "timeline")
                    for column in range(first_action, last_action + 1):
                        if fields[column]:
                            paths = fields[column].split(",")
                            if len(paths) > MAX_ITEMS:
                                raise ValueError("召唤动作条目超限")
                            for index, path in enumerate(paths):
                                add(path, at + f"/registered_actions/{column}/{index}", selected_proof, element, "dsl")
                    required(kind + "State", fields[routine], at + "/routine")
                    if kind == "Funnel":
                        try:
                            states, state_proof, state_missing = definitions.nested_union_rows(FUNNEL_STATE_TABLES, fields[routine], depth=2)
                            gaps(state_missing, at + "/routine")
                            damage, hits = False, False
                            for state in states:
                                sf = state["fields"]
                                state_at = at + "/routine/" + "/".join(state["innerKeys"])
                                if len(sf) < 29:
                                    raise ValueError("GeneralFunnelState定义字段不足")
                                damage = damage or sf[16] != "(None)"
                                hits = hits or sf[22] != "(None)"
                                for column in (27, 28):
                                    if sf[column] != "(None)":
                                        issue(f"Funnel state BattleScript资源转换待核：{sf[column]}", state_at + f"/{column}")
                            for enabled, names, columns in (
                                (damage, ("battle/common/layer1/hostile_damage_gauge", "battle/common/layer1/hostile_damage_gauge_indicator"), checks[:2]),
                                (hits, tuple("battle/uncommon/layer1/trial_gauge/" + name for name in ("trial_gauge1", "trial_gauge2", "trial_gauge_numbers", "trial_gauge_indicator")), checks[2:])):
                                if enabled:
                                    for name in names:
                                        add(name, at + "/routine/gauges", state_proof, element, layer=1)
                                    for column in columns:
                                        if fields[column] != "(None)":
                                            add(fields[column], at + f"/checks/{column}", selected_proof, element)
                        except (ValueError, UnicodeError) as exc:
                            issue(str(exc), at + "/routine")
                    else:
                        issue(f"Zako routine定义与BattleScript资源转换待核：{fields[routine]}", at + "/routine")
                    if inherited:
                        issue("继承关卡元素的全部6种body已纳入；动作的255选择仍需实际quest element", at + "/element")
                    issue(f"{kind}已纳入body/shadow/marker/注册动作；watch、动态cutin、等级及变量选择仍待核", at)
                except (ValueError, TypeError, IndexError, UnicodeError) as exc:
                    issue("召唤等级解析待核：" + str(exc), pointer + "/levels/" + "/".join(version["innerKeys"]))
            result["coverage"].append({"kind": kind, "key": str(key), "pointer": pointer,
                "status": "partial", "reason": "冻结等级的已知定义边已纳入，未模拟运行时等级/状态选择"})
    except (ValueError, TypeError, IndexError, UnicodeError) as exc:
        # Keep finite known edges, but do not invent empty/completed branches.
        result["problems"].append({"domain": "summon", "pointer": pointer,
            "reason": "召唤资源解析待核：" + str(exc), "dynamic": True})
    return result
