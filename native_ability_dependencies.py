"""Finite current-client ability collectors, with frozen source provenance.

The inspected ABC299/body14488 conversion is fixed here. This is a resource
inventory across preserved rows, not a simulation of trigger admission or a
claim that every generated case has been implemented.
"""
import copy
import math

PF_TABLES = ("master/skill/power_flip_action_iosbundled.orderedmap", "master/skill/power_flip_action.orderedmap")
BASIS = {
    "swf": "9418137820c007b52a11ad0d7955c102795d8dd903213670577bf3407ed709f7",
    "registry": "e7da4efa9d1e44495b949b86d0ff0f74781f869cfbecc0e8d1935fed9ed30848",
    "PowerFlipActionValues": "65c4956ab0115f9b8d80b9c1cefd8534951b748ad3cac322f0d7f08bbde468d5",
    "BattleAssetPathCollectionBuilder": "d7edd14b03f296fa47803a71db13aa8120374b0a097d97cada97adad70e3e525",
    "InstantAbilityInstantCharacterContent": "410f57957b2a8e113c52acaaf347abf7ef80c5a6b4d5a889a6ad4b7e7b8f21d7",
    "InstantAbilityContent": "ad9e1ed57e40d28504831bc095ef184cca6cc9ebc3805653f7cc30a163b2818e",
    "ConditionChangeContent": "8744db539b5fcaa792a53e1e02c5a7ad8e598c5a3dff6a03c7eeab57f5df3d2c",
    "CommonAbilityContent": "8d05b5635699b804ed9cc0161f771e7f4951479e0b39efe49b7cc1627274cdc5",
    "CommonAbilityCharacterContent": "1e4bd1280e5333ba3ba8c674bf94844235d42f851ac757c6da3b3d8ae0632839",
    "CommonAbilityBattleContent": "cad099bc3ac073a42b5cdd62eef252be7c962629505d9965f885d2c786e267c0",
    "InstantAbilitySource.resolveInstantContent.body": "b920769d365cae73818ed25a5ef2e243714122e218ed2061f7657d36acc38056",
    "InstantAbilitySource.collector": "ebed7d46b5e295f7237c861adf4b27506a543b0cc6dd03f48a01ddf92abcc741",
    "DuringAbilitySource": "edfaaec6d4384c466388b7f1547b6970e991bb688d47b9e220e091d5030c6537",
    "CommonAbilityContentTools": "0b847849d3e5cd0becaea9ae8a954720355919f6d026e7a9ea80e48353978d0d",
    "ConditionChangeContentTools": "06442ba3c9cbc1b30b5e258a6ecf005921b2e9d493d8f3bdabd9161c386908ca",
    "MemberImpl.conditionRuntime": "ffa4cb6583255ee3a79f5fe0079b90bff5a351345e12cfd65f30181ad3257f93",
}
# Fixed conversion paths, not master/wf enum-name guesses. Instant instruction
# windows are in ABC299/body14488; during conversions use the current source
# createFromDuringAbilityValues switch. Other codes remain independently pending.
BRANCHES = {
    ("instant_content", "24"): {"meaning": "特殊状态伤害加成", "runtimePath": ["InstantAbilityContent.ConditionCharacter:0", "ConditionChangeContent.PinchSlayer:18"],
        "instructions": [3254, 3390], "resourceBehavior": "runtime-implicit-hit", "collectorBranch": "resolveConditionPathCollection:18 break"},
    ("instant_content", "26"): {"meaning": "赋予贯通", "runtimePath": ["InstantAbilityContent.ConditionBattle:1", "ConditionChangeContent.Piercing:20"],
        "instructions": [3529, 3612], "resourceBehavior": "runtime-implicit-hit", "collectorBranch": "resolveConditionPathCollection:20 break"},
    ("instant_content", "27"): {"meaning": "赋予浮游", "runtimePath": ["InstantAbilityContent.ConditionBattle:1", "ConditionChangeContent.Flying:21"],
        "instructions": [3613, 3696], "resourceBehavior": "runtime-implicit-hit", "collectorBranch": "resolveConditionPathCollection:21 break"},
    ("instant_content", "96"): {"meaning": "状态相关伤害加成", "runtimePath": ["InstantAbilityContent.Common:2", "CommonAbilityContent.Character:1", "CommonAbilityCharacterContent.ConditionSlayer:23"],
        "instructions": [6291, 6330], "resourceBehavior": "no-additional-static-collector-roots", "collectorBranch": "CommonAbilityContentTools Character:23 break"},
    ("instant_content", "191"): {"meaning": "延长浮游持续时间", "runtimePath": ["InstantAbilityContent.InstantCharacter:4", "InstantAbilityInstantCharacterContent.ConditionExtend:10"],
        "instructions": [9870, 9897], "resourceBehavior": "no-additional-static-collector-roots", "collectorBranch": "InstantAbilitySource InstantCharacter:10 break"},
    ("instant_content", "200"): {"meaning": "改变PF所需连击数", "runtimePath": ["InstantAbilityContent.Common:2", "CommonAbilityContent.Battle:0", "CommonAbilityBattleContent.PowerFlipComboCountDown:9"],
        "instructions": [10167, 10190], "resourceBehavior": "no-additional-static-collector-roots", "collectorBranch": "CommonAbilityContentTools Battle:9 is not PowerFlipOverride:19"},
    ("instant_content", "211"): {"meaning": "改变技能槽", "runtimePath": ["InstantAbilityContent.InstantCharacter:4", "InstantAbilityInstantCharacterContent.SkillGauge:8"],
        "instructions": [10515, 10545], "resourceBehavior": "no-additional-static-collector-roots", "collectorBranch": "InstantAbilitySource InstantCharacter:8 break"},
    ("during_content", "3"): {"meaning": "技能槽充能速度", "runtimePath": ["CommonAbilityContent.Character:1", "CommonAbilityCharacterContent.SkillGaugeCharging:8"],
        "resourceBehavior": "no-additional-static-collector-roots", "collectorBranch": "CommonAbilityContentTools Character:8 break"},
    ("during_content", "23"): {"meaning": "PF伤害", "runtimePath": ["CommonAbilityContent.Battle:0", "CommonAbilityBattleContent.PowerFlipDamage:0"],
        "resourceBehavior": "no-additional-static-collector-roots", "collectorBranch": "CommonAbilityContentTools Battle:0 is not PowerFlipOverride:19"},
}


def _branch_coverage(block, code, pointer, status):
    result = {"block": block, "code": code, "pointer": pointer, "status": status}
    branch = BRANCHES.get((block, code))
    if branch:
        result.update(copy.deepcopy(branch))
        result["sourceProof"] = {"schema": "fixed-current-ability-branch-v1", "swf": BASIS["swf"],
            "method": "ABC299/body14488" if block == "instant_content" else "DuringAbilitySource.createFromDuringAbilityValues",
            "sourceHashes": {name: value for name, value in BASIS.items() if name not in ("swf", "registry", "PowerFlipActionValues", "BattleAssetPathCollectionBuilder")}}
        result["runtimeAcceptance"] = False
    return result


def resolve_ability_resources(fields, kind, element, definitions, pointer=""):
    from native_dependencies import COLORS, INAHO_PRELOAD, CONDITION_FIXED, MAX_ITEMS, _path, _program
    import bridge
    import wf_describe as describe
    result = {"references": [], "problems": [], "coverage": []}
    def issue(reason, at, domain="ability", dynamic=False):
        result["problems"].append({"domain": domain, "pointer": at, "reason": reason, "dynamic": dynamic})
    def add(logical, at, domain="ability", layer=0, resource_kind="effect", proof=None, origin="collector"):
        try:
            logical = _program(logical) if resource_kind == "dsl" else _path(logical)
        except ValueError as exc:
            issue(str(exc), at, domain); return
        reference = {"logical": logical, "pointer": at, "domain": domain, "origin": origin,
                     "context": {"category": domain, "layer": layer, "kind": resource_kind, "element": element}}
        if proof:
            reference["definitionEvidence"] = proof
        if reference not in result["references"]:
            result["references"].append(reference)
    def fixed(names, at, domain="ability", layer=0):
        for logical in names:
            add(logical, at, domain, layer)
    def pf(key, at):
        try:
            rows, proof, missing = definitions.union_rows(PF_TABLES, key)
            if len(rows) != 1 or len(rows[0]) != 3:
                raise ValueError("原生PF定义不是合法三等级平表")
            for index, path in enumerate(rows[0]):
                add(path, at + f"/levels/{index+1}", "powerFlip", resource_kind="dsl", proof=proof)
            for path in missing:
                issue(f"PF合并源未冻结：{path}，key {key}；已知等级已纳入，合并完整性仍待核", at, "powerFlip", True)
        except (ValueError, UnicodeError) as exc:
            issue(str(exc), at, "powerFlip", True)
    try:
        if kind not in ("ability", "leader_ability") or not isinstance(fields, list) or len(fields) > MAX_ITEMS or any(not isinstance(v, str) for v in fields):
            raise ValueError("原生能力行结构无效")
        blocks = describe.layout(kind)["blocks"]
        base, during = blocks["instant_content"], blocks["during_content"]
        if len(fields) <= during + 12:
            raise ValueError("原生能力行宽不足")
        active = fields[blocks["instant_delay"]] not in ("", "(None)")
        code = fields[base]
        if active:
            at = pointer + "/instant/" + code
            fixed(("battle/common/layer1/total_ability_damage_effect", "battle/common/layer1/total_powerflip_damage_effect"), at + "/preload", "shared", 1)
            status = "included"
            if code in ("0", "1", "24", "214", "28", "486", "701", "712", "713"):
                strengths = [float(v) for v in fields[base+4:base+6]]
                if len(strengths) != 2 or any(not math.isfinite(v) for v in strengths):
                    raise ValueError("临时条件强度端点无法确定命中特效方向")
                for direction in sorted({"buff" if value > 0 else "debuff" for value in strengths}):
                    add(f"battle/effect/hit/condition/{direction}/{direction}", at + "/generic-hit", origin="runtime-implicit")
            elif code in ("26", "27"):
                # These current constructors are singletons and do not read
                # strength. Real rows have blank endpoints; never fill them.
                name = "enhancing_penetrate" if code == "26" else "enhancing_waftage"
                add(f"battle/effect/hit/condition/{name}/{name}", at + "/generic-hit", origin="runtime-implicit")
            elif code in tuple(str(n) for n in range(2, 9)):
                fixed(CONDITION_FIXED["ACToleranceOfElement"], at)
            elif code in ("17", "22", "468", "470", "489", "718", "475"):
                condition = {"17": "ACRegeneration", "22": "ACStun", "468": "ACGuts", "470": "ACAdversity", "489": "ACComboBoost", "718": "ACPowerFlipComboCountDown", "475": "ACHealRejection"}[code]
                fixed(CONDITION_FIXED[condition], at)
                if code == "489":
                    add("battle/uncommon/layer1/combo_boost/boost_text_ui", at, layer=1)
            elif code == "227":
                fixed(("battle/effect/hit/condition/barrier/barrier_ball", "battle/effect/hit/condition/barrier/breaking_barrier"), at)
            elif code.isdecimal() and (251 <= int(code) <= 286 or 316 <= int(code) <= 387):
                number = int(code)
                color = COLORS[(number - (251 if number <= 286 else 316)) % 6]
                fixed(tuple(f"battle/effect/ability_damage/ability_damage_{color}/ability_damage_{visual}_{color}" for visual in ("hit", "player", "shot")), at)
                fixed(INAHO_PRELOAD, at + "/InahoAbilityVisuals/preload", "shared")
            elif code in ("413", "436", "459", "461"):
                logical, proof = definitions.unique(fields[base+21])
                add(logical, at + "/Unique/icon", layer=1, resource_kind="image", proof=proof)
                if code != "461":
                    hit, proof = definitions.unique_hit(fields[base+21])
                    add(hit, at + "/Unique/generic-hit", proof=proof)
            elif code == "629":
                add(fields[base+24], at + "/InvokeSkill", resource_kind="dsl")
                if "cnmod_inaho_midautumn" in fields[base+24]:
                    fixed(INAHO_PRELOAD, at + "/InahoAbilityVisuals/preload", "shared")
            elif code == "460":
                add("battle/common/disguise_hp", at, "shared", 1, "sprite-sheet")
            elif code == "722":
                if fields[base+35] != "(None)":
                    pf(fields[base+35], at + "/PowerFlipOverride")
            else:
                # These are explicitly reviewed fixed conversions whose
                # current collector branches contain no resource calls. Hp205
                # is InstantCharacter index2; AddCombo226 is InstantBattle
                # index1. The state
                # selector, triggers and runtime mechanics remain unproven.
                no_assets = {"32", "33", "34", "35", "50", "51", "52", "53", "54", "55", "56", "96", "191", "200", "205", "211", "226", "388", "389", "462", "627", "628", "693", "694", "695", "696", "697", "698", "699", "700", "711", "723"}
                if code not in no_assets:
                    status = "pending"
                    issue(f"generated instant_content {code} 尚缺本分支完整资源转换", at, dynamic=True)
            result["coverage"].append(_branch_coverage("instant_content", code, at, status))
        if fields[during] == "156":
            add("battle/common/disguise_hp", pointer + "/during/156", "shared", 1, "sprite-sheet")
            result["coverage"].append({"block": "during_content", "code": "156", "pointer": pointer + "/during/156", "status": "included"})
        elif fields[during] == "419":
            if fields[during+11] != "(None)":
                pf(fields[during+11], pointer + "/during/419/PowerFlipOverride")
            result["coverage"].append({"block": "during_content", "code": "419", "pointer": pointer + "/during/419", "status": "included"})
        elif fields[during] in ("3", "23"):
            result["coverage"].append(_branch_coverage("during_content", fields[during], pointer + "/during/" + fields[during], "included"))
        elif fields[during] not in ("", "(None)", "0"):
            issue(f"generated during_content {fields[during]} 尚缺本分支完整资源转换", pointer + "/during", dynamic=True)
            result["coverage"].append({"block": "during_content", "code": fields[during], "pointer": pointer + "/during", "status": "pending"})
    except (ValueError, TypeError, IndexError, KeyError, UnicodeError) as exc:
        issue("能力资源解析待核：" + str(exc), pointer, dynamic=True)
    if result["problems"]:
        for item in result["coverage"]:
            if any(problem["pointer"].startswith(item["pointer"]) for problem in result["problems"]):
                item["status"] = "pending"
    return result


def common_resources():
    """Only unconditional static Common calls; Attention stays a separate gap."""
    references = []
    names = {0: ("flipper", "flipper_powerflip_spark", "flipper_powerflip_charge", "flipper_powerflip_shot1", "flipper_powerflip_shot2", "flipper_powerflip_shot3", "flipper_powerflip_twinkle",
        "coffin", "ball_aura", "ball_dashcloud", "coffin_revival", "coffin_set", "zako_shrink_back",
        "flipper_guide_line", "flipper_guide_point", "zako_disappear", "saturated_linework", "zako_subscribe", "zako_appearance", "zako_vanishing_smoke_a", "zako_vanishing_smoke_b", "zako_vanishing_sweat",
        "attack_resist", "attack_to_hostile_hit", "attack_to_hostile_smash", "attack_to_friendly_aura", "attack_to_friendly_hit", "damage_effect_out_hole",
        "instant_item_acquired", "instant_item_appeared", "instant_item_shining", "skill_point_indicator1", "skill_point_indicator2", "skill_point_indicator_second1", "skill_point_indicator_second2",
        "ability/ability_objective", "rotation_panel_active", "rotation_panel_close", "rotation_panel_open"),
        1: ("hud_skill_flash", "damage_effect_resist", "damage_effect_to_friendly_normal", "damage_effect_to_friendly_aura", "damage_effect_to_hostile_normal", "damage_effect_to_hostile_weak", "accumulation_damage_effect_to_hostile",
        "total_powerflip_damage_effect", "total_skill_damage_effect", "cure_effect_normal", "health_point_alert_left", "health_point_alert_right", "hud_condition_icon_effect")}
    def add(logical, layer=0, kind="effect"):
        item = {"logical": logical, "pointer": "/Common/addCommonAssets", "domain": "shared",
                "context": {"category": "shared", "layer": layer, "kind": kind, "bucket": "Common", "collection": "common-battle-authoring"}}
        if item not in references:
            references.append(item)
    for layer, values in names.items():
        add(f"battle/common/layer{layer}", layer, "sprite-sheet")
        for value in values:
            add(f"battle/common/layer{layer}/{value}", layer)
    for name in ("buff", "debuff", "enfeebling_poison", "enhancing_invincible", "enfeebling_paralysis", "enfeebling_freeze", "enfeebling_freeze_enemy",
                 "enhancing_penetrate", "enhancing_waftage", "buff_reset", "debuff_reset", "buff_debuff_reset", "general_bipolar_down", "enhancing_swift"):
        add(f"battle/effect/hit/condition/{name}/{name}")
    for name in ("silence_ball", "continuous_attacks_ball", "flying_ball", "speed_up_ball", "frozen_ball", "frozen_boss", "frozen_zako",
                 "invincible_ball", "invincible_boss", "invincible_zako", "paralysis_ball", "paralysis_boss", "paralysis_zako", "piercing_ball",
                 "poison_ball", "poison_boss", "poison_zako", "buff_adverse_ball", "debuff_adverse_ball", "enfeebling_no_heal_ball",
                 "combo_boost_ball", "enhancing_combo_boost", "fixed_speed_ball", "continuous_swift_ball"):
        add("battle/common/layer0/condition/" + name)
    for logical in ("battle/field_object/common/yakumono/instant_item/obtainable_mana/mana_get",
                    "battle/field_object/common/yakumono/instant_item/obtainable_mana/mana_get_ripple",
                    "battle/effect/skill_general/multiball/multiball_general_effect/multiball_general_effect_disappear",
                    "battle/effect/hit/heal/heal/heal"):
        add(logical)
    for name in ("non_attribute", "fire", "splash", "thunder_small", "tornado", "shine", "dark"):
        add(f"battle/effect/hit/normal_damage/{name}/{name}")
    # Current addSkillChainSpriteSheet: all these unconditional compiled
    # effects alias the same parent sprite sheet. Read kind3 uses layouts
    # instead and remains a concrete configuration gap below.
    add("battle/effect/skill_chain/skill_chain", 0, "sprite-sheet")
    return {"references": references, "problems": [{"domain": "shared", "pointer": "/Common/featuresPermit", "reason": "Common条件分支需真实featuresPermit、客户端选项与皮肤定义；仅无条件静态根已纳入", "dynamic": True},
        {"domain": "shared", "pointer": "/Common/assetReadKind", "reason": "skill-chain已按当前compiled sprite-sheet别名纳入；assetReadKind=3独立布局及客户端配置仍待核", "dynamic": True},
        {"domain": "shared", "pointer": "/Attention", "reason": "Attention为独立常驻收集组，需真实配置与动态缩略图生成来源；不能视为角色素材闭合", "dynamic": True}], "collectorBasis": BASIS}
