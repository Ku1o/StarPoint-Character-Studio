"""Current-client Common condition roots for finite authoring inventory.

All proven static alternatives are collected without author technical switches.
This union is not an observed battle configuration or a complete scene budget.
Dynamic textures and runtime-bound interface contents keep precise pending records.
"""

import copy


def conditional_common_resources(project=None, definitions=None, reference_files=None):
    """Inventory proven alternatives, regardless of untrusted author flags.

    The arguments match the native extractor interface. No project value can
    declare a branch absent or complete. Frozen native tables are used only
    after their actual column parser has been proven for this carrier.
    ``coveredGapPointers`` means replaced by granular accounting, not closed.
    """
    from native_dependencies import _path
    result = {"references": [], "problems": [], "coverage": [], "requiredReferences": [],
              "coveredGapPointers": ["/Common/featuresPermit", "/Common/assetReadKind", "/Attention"],
              "collectorBasis": dict(BASIS),
              "selection": {"mode": "finite-authoring-union", "observedRuntimeConfiguration": False,
                            "source": "current-client-collector", "authorTechnicalFlagsRequired": False,
                            "completeSceneBudget": False}}

    def proof(condition, start, end):
        return {"source": "BattleAssetPathCollectionBuilder.addCommonAssets", "sha256": BASIS["BattleAssetPathCollectionBuilder"],
                "condition": condition, "lines": [start, end], "selection": "finite-authoring-union"}

    def pending(pointer, reason, condition, start, end, logicals=(), title="公共资源待核"):
        basis = proof(condition, start, end)
        required = [{"logical": logical, "kind": "html" if logical.startswith("rich_text/") else "ui",
                     "pointer": pointer, "callerPointer": pointer, "title": "公共界面实际入口",
                     "sourceEvidence": copy.deepcopy(basis)} for logical in logicals]
        result["requiredReferences"].extend(required)
        result["problems"].append({"domain": "shared", "pointer": pointer, "reason": reason, "dynamic": True,
                                   "conditionEvidence": basis, "knownLogicals": list(logicals),
                                   "requiredReferences": required})
        result["coverage"].append({"pointer": pointer, "condition": condition, "status": "pending",
                                    "title": title, "sourceEvidence": basis, "knownLogicals": list(logicals)})

    for condition, start, end, logicals in STATIC_BRANCHES:
        pointer = f"/Common/addCommonAssets/conditions/lines-{start}-{end}"
        basis = proof(condition, start, end)
        for logical in logicals:
            logical = _path(logical)
            layer = 1 if logical.startswith("battle/common/layer1/") else 0
            result["references"].append({"logical": logical, "pointer": pointer, "domain": "shared",
                "origin": "collector-authoring-union", "definitionEvidence": copy.deepcopy(basis),
                "context": {"category": "shared", "layer": layer, "kind": "effect", "bucket": "Common",
                            "collection": "common-battle-authoring"}})
        result["coverage"].append({"pointer": pointer, "condition": condition, "status": "included-authoring-union",
                                   "title": BRANCH_TITLES[start], "referenceCount": len(logicals), "sourceEvidence": basis})

    # An exact literal sound call is independent of the master loading sets.
    bell = "sound_effect/common/se_attention_recieve_bell_battle.mp3"
    result["references"].append({"logical": bell, "pointer": "/Common/addCommonAssets/conditions/playsSoundEffect/pause-bell",
        "domain": "shared", "origin": "collector-authoring-union",
        "definitionEvidence": proof("displaysPause && !displaysTutorial && playsSoundEffect", 562, 573),
        "context": {"category": "shared", "layer": "independent", "kind": "sound", "bucket": "Common",
                    "collection": "common-battle-authoring"}})

    sounds = _sound_resources(definitions, reference_files)
    for field in ("references", "problems", "coverage"):
        result[field].extend(sounds[field])
    # These are FollowingLogic UI and View rich-text inputs. The graph now
    # parses their proven consumers; actual content binding keeps granular gaps.
    for pointer, title, condition, start, end, logicals in UI_BRANCHES:
        basis = proof(condition, start, end)
        for logical in logicals:
            kind = "html" if logical.startswith("rich_text/") else "ui"
            result["requiredReferences"].append({"logical": logical, "kind": kind, "pointer": pointer,
                "callerPointer": pointer, "title": "公共界面实际入口", "sourceEvidence": copy.deepcopy(basis)})
            result["references"].append({"logical": logical, "pointer": pointer, "domain": "shared",
                "origin": "collector-authoring-union", "definitionEvidence": copy.deepcopy(basis),
                "context": {"category": "shared", "layer": "independent", "kind": kind, "bucket": "Common",
                            "resourceOwner": "game-common-ui",
                            "collection": "common-following-logic" if kind == "ui" else "common-view-rich-text"}})
        result["coverage"].append({"pointer": pointer, "condition": condition, "title": title,
            "status": "included-authoring-union", "resourceOwner": "game-common-ui", "referenceCount": len(logicals),
            "sourceEvidence": basis, "knownLogicals": list(logicals), "runtimeContentsVerified": False})
    pending("/Common/addCommonAssets/conditions/displaysAttention/dynamic-textures",
        "AttentionConfigLogic.getMaxNumOfHoldingAttention决定动态AttentionThumbnail(index)与Badge(index+1)；缺当前配置与动态生成来源，不能默认不适用",
        "displaysAttention", 580, 591, title="求援动态图")
    skin = _skin_resources(definitions, reference_files)
    for field in ("references", "problems", "coverage"):
        result[field].extend(skin[field])
    return result


UI_BRANCHES = (
    ("/Common/addCommonAssets/conditions/displaysPause/ui", "暂停界面", "displaysPause", 562, 566,
     ("scene/battle/pause_menu", "scene/battle/pause_menu_balloon", "scene/common_ui_iosbundled/switch_button")),
    ("/Common/addCommonAssets/conditions/displaysPause/nonTutorial-ui", "非教程暂停界面", "displaysPause && !displaysTutorial", 566, 574,
     ("scene/common_ui_iosbundled/result_stamp", "scene/common_ui/battle_quest_reward")),
    ("/Common/addCommonAssets/conditions/canGameover/ui-html", "继续游戏界面和说明", "canGameover", 575, 579,
     ("scene/battle/continue_dialog", "scene/common_ui/item_thumbnail", "scene/shop/shop",
      "scene/stone_buy_dialog/stone_buy_dialog", "scene/common_ui_bundled/panel", "rich_text/settlement", "rich_text/transaction_law_android")),
)


SKIN_TABLE = "master/equipment_enhancement/equipment_flipper_skin/flipper_skin.orderedmap"
SKIN_CONDITION = "ApplicationOption.flipperSkin.enable && !GlobalLogic.isDuringTutorial()"


def _skin_resources(definitions, reference_files):
    """Read all frozen skin rows with one total index/leaf/field budget."""
    import csv
    import hashlib
    import io
    from native_dependencies import LIMIT, MAX_ITEMS, _inflate_limited, _orderedmap_ranges, _path
    result = {"references": [], "problems": [], "coverage": []}
    pointer = "/Common/addCommonAssets/conditions/flipperSkin"
    source = {"source": "BattleAssetPathCollectionBuilder.addCommonAssets", "sha256": BASIS["BattleAssetPathCollectionBuilder"],
              "condition": SKIN_CONDITION, "lines": [600, 634], "selection": "finite-authoring-union",
              "valuesSha256": BASIS["FlipperSkinValues"], "tableClassSha256": BASIS["FlipperSkinTable"],
              "binaryRowSha256": BASIS["MasterBinarySlice"], "csvReaderSha256": BASIS["CsvReader"]}

    def issue(at, reason, evidence=None):
        result["problems"].append({"domain": "shared", "pointer": at, "reason": reason, "dynamic": True,
                                   "conditionEvidence": copy.deepcopy(source), "definitionEvidence": evidence})

    files = dict(getattr(definitions, "files", {}) or {})
    if isinstance(reference_files, dict):
        for name, raw in reference_files.items():
            files.setdefault(name, raw)
    raw = files.get(SKIN_TABLE)
    budget, fields_seen, rows_seen = [LIMIT], 0, 0
    try:
        if not isinstance(raw, bytes) or not raw or len(raw) > LIMIT:
            raise ValueError("缺冻结真实皮肤表：" + SKIN_TABLE)
        ranges = _orderedmap_ranges(raw, budget)
        table_proof = {"logical": SKIN_TABLE, "sha256": hashlib.sha256(raw).hexdigest()}
        for key, (start, end) in ranges.items():
            at = pointer + "/rows/" + key.replace("~", "~0").replace("/", "~1")
            evidence = dict(table_proof, key=key, collectorSource=copy.deepcopy(source))
            try:
                row_raw = _inflate_limited(memoryview(raw)[start:end], "皮肤表行", budget[0]) if end > start else b""
                budget[0] -= len(row_raw)
                rows = [row for row in csv.reader(io.StringIO(row_raw.decode("utf-8-sig")), strict=True) if row]
                fields_seen += sum(len(row) for row in rows)
                rows_seen += len(rows)
                if rows_seen > MAX_ITEMS or fields_seen > MAX_ITEMS:
                    issue(at, "皮肤全表行或字段超限；已知引用保留，后续行待核", evidence)
                    break
                if len(rows) != 1 or len(rows[0]) < 4:
                    raise ValueError("皮肤定义不是至少四列单行；需真实animation列1/additional列3")
                row = rows[0]
                for column, name in ((1, "flipper_animation_path"), (3, "flipper_additional_animation_path")):
                    value = row[column]
                    field_at = at + f"/fields/{column}"
                    field_proof = dict(evidence, column=column, field=name)
                    if value in ("", "(None)"):
                        issue(field_at, f"皮肤{name}是无效固定动画路径；原生CSV保持字符串，不将空串或(None)当null排除", field_proof)
                        continue
                    try:
                        logical = _path(value)
                    except ValueError as exc:
                        issue(field_at, str(exc), field_proof)
                        continue
                    layer = 1 if logical.startswith("battle/common/layer1/") else 0
                    result["references"].append({"logical": logical, "pointer": field_at, "domain": "shared",
                        "origin": "collector-authoring-union", "definitionEvidence": field_proof,
                        "context": {"category": "shared", "layer": layer, "kind": "effect", "bucket": "Common",
                                    "collection": "common-battle-authoring"}})
            except (ValueError, UnicodeError, csv.Error) as exc:
                issue(at, "皮肤定义待核：" + str(exc), evidence)
                if "解压输出超限" in str(exc):
                    issue(pointer + "/budget", "皮肤全表共享解压预算达到上限；后续行待核")
                    break
        result["coverage"].append({"pointer": pointer, "condition": SKIN_CONDITION, "title": "弹板皮肤",
            "status": "pending" if result["problems"] else "included-authoring-union",
            "referenceCount": len(result["references"]), "definitionEvidence": table_proof,
            "sourceEvidence": source})
    except (ValueError, UnicodeError, TypeError) as exc:
        issue(pointer + "/table", "皮肤全表制作并集待核：" + str(exc) + "；遍历全部行与非null追加动画，不按所选皮肤或默认禁用排除")
        result["coverage"].append({"pointer": pointer, "condition": SKIN_CONDITION, "title": "弹板皮肤",
                                   "status": "pending", "sourceEvidence": source})
    return result


SOUND_TABLES = {
    "bgm": tuple("master/asset/bgm_asset" + suffix + ".orderedmap" for suffix in ("", "_bundled", "_iosbundled")),
    "sound": tuple("master/asset/sound_effect_asset" + suffix + ".orderedmap" for suffix in ("", "_bundled", "_iosbundled")),
}


def _sound_resources(definitions, reference_files):
    """Exact loading-field authoring union of current registered sources."""
    import csv
    import hashlib
    import io
    import re
    from native_dependencies import LIMIT, MAX_ITEMS, _inflate_limited, _orderedmap_ranges, _path
    result = {"references": [], "problems": [], "coverage": []}
    pointer = "/Common/addCommonAssets/conditions/playsSoundEffect/master-loading"
    source = {"source": "AssetPathCollectionBuilder.addSoundFromMaster", "sha256": BASIS["AssetPathCollectionBuilder"],
              "lines": [317, 353], "condition": "playsSoundEffect", "loading": 6,
              "additionalSoundEffectSelection": "loading == 7 || (loading == 12 && key contains _skill_chain_attack_)",
              "selection": "finite-authoring-union", "registrationSha256": BASIS["registry"],
              "unionConsumerSha256": BASIS["RootMasterBinary"]}
    files = dict(getattr(definitions, "files", {}) or {})
    if isinstance(reference_files, dict):
        for name, raw in reference_files.items():
            files.setdefault(name, raw)
    budget, fields_seen = [LIMIT], 0

    def issue(at, reason, evidence=None):
        result["problems"].append({"domain": "shared", "pointer": at, "reason": reason, "dynamic": True,
            "conditionEvidence": copy.deepcopy(source), "consumerEvidence": copy.deepcopy(source), "definitionEvidence": evidence})

    def finish():
        result["coverage"].append({"pointer": pointer, "condition": "playsSoundEffect", "title": "公共声音",
            "status": "pending" if result["problems"] else "included-authoring-union",
            "referenceCount": len(result["references"]), "sourceEvidence": source})
        return result

    for kind, names in SOUND_TABLES.items():
        tables, seen = [], set()
        for name in names:
            at = pointer + "/sources/" + name.replace("~", "~0").replace("/", "~1")
            try:
                raw = files.get(name)
                if not isinstance(raw, bytes) or not raw or len(raw) > LIMIT:
                    raise ValueError("缺冻结公共声音表 " + name + "；已知候选保留，不按默认静音排除")
                ranges = _orderedmap_ranges(raw, budget)
                table_proof = {"logical": name, "sha256": hashlib.sha256(raw).hexdigest()}
                duplicate = seen.intersection(ranges)
                if duplicate:
                    issue(at, "公共声音合并表含重复键：" + min(duplicate), table_proof)
                seen.update(ranges)
                tables.append((raw, {key: offsets for key, offsets in ranges.items() if key not in duplicate}, table_proof))
            except (ValueError, UnicodeError, TypeError) as exc:
                issue(at, str(exc))
        union_sources = [table[2] for table in tables]
        for raw, ranges, table_proof in tables:
            for key, (start, end) in ranges.items():
                at = pointer + "/rows/" + key.replace("~", "~0").replace("/", "~1")
                column = 5 if kind == "bgm" else 3
                evidence = dict(table_proof, key=key, column=column, field="loading", unionSources=union_sources,
                                valuesSha256=BASIS["BgmAssetValues" if kind == "bgm" else "SoundEffectAssetValues"],
                                collectorSource=copy.deepcopy(source))
                try:
                    row_raw = _inflate_limited(memoryview(raw)[start:end], "公共声音表行", budget[0]) if end > start else b""
                    budget[0] -= len(row_raw)
                    rows = [row for row in csv.reader(io.StringIO(row_raw.decode("utf-8-sig")), strict=True) if row]
                    fields_seen += sum(len(row) for row in rows)
                    if fields_seen > MAX_ITEMS:
                        issue(at, "公共声音表共享字段预算达到上限；已知候选保留，后续行待核", evidence)
                        return finish()
                    if len(rows) != 1 or len(rows[0]) <= column or not re.fullmatch(r"-?[0-9]+", rows[0][column]):
                        raise ValueError("公共声音定义缺合法单行loading整数列" + str(column))
                    loading = int(rows[0][column])
                    if not -2147483648 <= loading <= 2147483647:
                        raise ValueError("公共声音loading超过原生Int范围")
                    if loading == 6 or kind == "sound" and (loading == 7 or loading == 12 and "_skill_chain_attack_" in key):
                        logical = _path(key)
                        logical = logical if logical.endswith(".mp3") else logical + ".mp3"
                        result["references"].append({"logical": logical, "pointer": at, "domain": "shared",
                            "origin": "collector-authoring-union", "definitionEvidence": evidence,
                            "context": {"category": "shared", "layer": "independent", "kind": "sound", "bucket": "Common",
                                        "collection": "common-battle-authoring"}})
                except (ValueError, UnicodeError, csv.Error) as exc:
                    issue(at, "公共声音定义待核：" + str(exc), evidence)
                    if "解压输出超限" in str(exc):
                        issue(pointer + "/budget", "公共声音全表共享解压预算达到上限；后续行待核")
                        return finish()
    return finish()


BRANCH_TITLES = {
    562: "暂停按钮", 594: "连击提示", 636: "助战角色加入演出", 641: "结束与失败提示",
    647: "冲刺表现", 651: "发射与待机", 657: "Boss受击与中断", 661: "协作标记与表情",
    666: "Fever覆盖表现", 670: "Boss弱点提示", 674: "角色控制面板", 679: "技能就绪提示",
    683: "左右点击提示", 688: "触摸开始提示", 692: "敌人攻击提示", 696: "完整属性粒子",
    713: "能力触发表现", 719: "生命量表", 723: "角色状态生命量表", 727: "Boss阶段与生命量表",
    731: "能力信息量表", 736: "非教程战斗的毅力与量表命中特效", 741: "技能连锁独立动画读取",
}

BASIS = {
    "swf": "9418137820c007b52a11ad0d7955c102795d8dd903213670577bf3407ed709f7",
    "BattleAssetPathCollectionBuilder": "d7edd14b03f296fa47803a71db13aa8120374b0a097d97cada97adad70e3e525",
    "AssetPathCollectionBuilder": "dc1d5dbfe465762aa39873c006179f3532e8cfb8b991344b5f4e57d5db5bce2c",
    "FlipperSkinTable": "5cb7d8e1af96506a45704a6596ea7e3e4e270732aaf8b933828d242feb80b5a8",
    "FlipperSkinValues": "110bd45488dd6ba37fea1a043194f868862894cf10ce3a6eccbe62333d7ac87d",
    "registry": "e7da4efa9d1e44495b949b86d0ff0f74781f869cfbecc0e8d1935fed9ed30848",
    "BgmAssetValues": "18defb7f17015b1e63fec978490e8c163fd14f95b9ed461c42b0f20f2fc35d7b",
    "SoundEffectAssetValues": "e4ca3c2a7d2c59e048829d224de1fb0e7c6057f0d2611ab34cf58e17d969ee72",
    "MasterBinarySlice": "3567daaf3181c9b0d57570433554a5a191b34001f36de5710beeb52cc660a366",
    "CsvReader": "e31cbcb978280fa891a3bdc6fdc8ba4b1327fe4867a545b8347792246d3fd35d",
    "RootMasterBinary": "d33f85d4cfbb10fbe214fbfd346d560f32f42b4aacc7180a27a7c4909e459e09",
}

STATIC_BRANCHES = (('displaysPause',
  562,
  566,
  ('battle/common/layer1/hud_pause_button', 'battle/common/layer1/new_hud_pause_button')),
 ('displaysCombo',
  594,
  597,
  ('battle/common/layer1/hud_combo_flash',
   'battle/common/layer1/hud_combo_particle',
   'battle/common/layer0/combo_increased',
   'battle/common/layer1/combo_fixed')),
 ('displaysJoiningAssistCharacterCutin',
  636,
  640,
  ('battle/common/layer1/cutin_joining_assist_character',
   'battle/common/layer1/cutin_action_skill_me_single')),
 ('canGameover',
  641,
  644,
  ('battle/common/layer1/cutin_timeover_type',
   'battle/common/layer1/cutin_gameover_type',
   'battle/common/layer1/cutin_gameover_spotlight')),
 ('dashEnabled',
  647,
  650,
  ('battle/common/layer1/escape_marker',
   'battle/common/layer0/escape_line',
   'battle/common/layer0/escape_particle',
   'battle/common/layer0/escape_shine',
   'battle/common/layer0/escape_failure')),
 ('!autoStart || canGameover',
  651,
  655,
  ('battle/common/layer0/ball_launch_cracker',
   'battle/common/layer0/ball_launch_saturated_linework',
   'battle/common/layer0/ball_launch_magic',
   'battle/common/layer0/ball_launch_appearance',
   'battle/common/layer0/ball_standby')),
 ('displaysBoss',
  657,
  660,
  ('battle/common/layer0/boss_stun',
   'battle/common/layer0/boss_wince1',
   'battle/common/layer0/boss_wince2',
   'battle/common/layer1/boss_text_break',
   'battle/common/layer1/boss_text_cancel')),
 ('displaysCooperative',
  661,
  664,
  ('battle/common/layer1/ball_marker',
   'battle/common/layer0/emotion_help',
   'battle/common/layer0/emotion_nice',
   'battle/common/layer0/emotion_sorry',
   'battle/common/layer0/emotion_follow',
   'battle/common/layer0/emotion_no',
   'battle/common/layer0/emotion_stamina_full',
   'battle/common/layer0/emotion_stamina_none',
   'battle/common/layer0/emotion_auto_battle')),
 ('feverGaugeEnabled',
  666,
  669,
  ('battle/common/layer1/fever_mode_overlay', 'battle/common/layer1/fever_mode_overlay_shadow')),
 ('displaysBoss',
  670,
  673,
  ('battle/common/layer1/boss_weak_point_arrow',
   'battle/common/layer1/boss_weak_point_sight',
   'battle/common/layer1/boss_weak_point_countdown',
   'battle/common/layer1/boss_weak_point_broken',
   'battle/common/layer1/damage_effect_to_hostile_stun',
   'battle/common/layer1/damage_effect_to_hostile_stun_weak')),
 ('displaysControlBoard',
  674,
  677,
  ('battle/common/layer1/control_board_character_background_effect',
   'battle/common/layer1/control_board_character_foreground_effect',
   'battle/common/layer1/control_board_skill_failure',
   'battle/common/layer1/control_board_character1_alive',
   'battle/common/layer1/control_board_character2_alive',
   'battle/common/layer1/control_board_character3_alive',
   'battle/common/layer1/control_board_character1_dead',
   'battle/common/layer1/control_board_character2_dead',
   'battle/common/layer1/control_board_character3_dead',
   'battle/common/layer1/control_board_circle',
   'battle/common/layer1/control_board_character_skill_name')),
 ('displaysSkillReady',
  679,
  682,
  ('battle/common/layer1/skill_ready1_effect',
   'battle/common/layer1/skill_ready2_effect',
   'battle/common/layer1/skill_ready3_effect',
   'battle/common/layer1/skill_ready1_top',
   'battle/common/layer1/skill_ready2_top',
   'battle/common/layer1/skill_ready3_top')),
 ('displaysTapIndicator',
  683,
  686,
  ('battle/common/layer0/tap_indicator_left', 'battle/common/layer0/tap_indicator_right')),
 ('displaysTapInstruction || displaysTutorial', 688, 691, ('battle/common/layer1/touch_to_start',)),
 ('displaysBoss', 692, 695, ('battle/common/layer1/enemy_attack_cutin',)),
 ('ApplicationOption.getWeightSavingMode() == 0',
  696,
  709,
  ('battle/common/layer0/effect_particle_attribution/effect_particle_attribution_black_large',
   'battle/common/layer0/effect_particle_attribution/effect_particle_attribution_black_medium',
   'battle/common/layer0/effect_particle_attribution/effect_particle_attribution_black_small',
   'battle/common/layer0/effect_particle_attribution/effect_particle_attribution_blue_large',
   'battle/common/layer0/effect_particle_attribution/effect_particle_attribution_blue_medium',
   'battle/common/layer0/effect_particle_attribution/effect_particle_attribution_blue_small',
   'battle/common/layer0/effect_particle_attribution/effect_particle_attribution_green_large',
   'battle/common/layer0/effect_particle_attribution/effect_particle_attribution_green_medium',
   'battle/common/layer0/effect_particle_attribution/effect_particle_attribution_green_small',
   'battle/common/layer0/effect_particle_attribution/effect_particle_attribution_red_large',
   'battle/common/layer0/effect_particle_attribution/effect_particle_attribution_red_medium',
   'battle/common/layer0/effect_particle_attribution/effect_particle_attribution_red_small',
   'battle/common/layer0/effect_particle_attribution/effect_particle_attribution_white_large',
   'battle/common/layer0/effect_particle_attribution/effect_particle_attribution_white_medium',
   'battle/common/layer0/effect_particle_attribution/effect_particle_attribution_white_small',
   'battle/common/layer0/effect_particle_attribution/effect_particle_attribution_yellow_large',
   'battle/common/layer0/effect_particle_attribution/effect_particle_attribution_yellow_medium',
   'battle/common/layer0/effect_particle_attribution/effect_particle_attribution_yellow_small',
   'battle/common/layer0/effect_particle_attribution/effect_particle_attribution_colorless_large',
   'battle/common/layer0/effect_particle_attribution/effect_particle_attribution_colorless_medium',
   'battle/common/layer0/effect_particle_attribution/effect_particle_attribution_colorless_small')),
 ('displaysAbility',
  713,
  716,
  ('battle/common/layer0/ability/ability_moment', 'battle/common/layer0/ability/ability_perpetuity')),
 ('displaysMemberStatus || displaysBoss', 719, 722, ('battle/common/layer1/member_hp_gauge',)),
 ('displaysMemberStatus',
  723,
  726,
  ('battle/common/layer1/hud_member_status_hp_gauge',
   'battle/common/layer1/hud_member_status_hp_gauge_glow')),
 ('displaysBoss',
  727,
  730,
  ('battle/common/layer1/boss_subroutine_change_ui',
   'battle/common/layer0/boss_subroutine_change',
   'battle/common/layer1/boss_hp_gauge')),
 ('displaysMemberStatus && ApplicationOption.isAbilityInfoDisplayModeOptionEnable()',
  731,
  734,
  ('battle/common/layer1/hud_ability_gauge/ct_gauge_bar',
   'battle/common/layer1/hud_ability_gauge/flash/flash_red',
   'battle/common/layer1/hud_ability_gauge/flash/flash_purple',
   'battle/common/layer1/hud_ability_gauge/flash/flash_cyan',
   'battle/common/layer1/hud_ability_gauge/flash/flash_orange',
   'battle/common/layer1/hud_ability_gauge/flash/flash_green')),
 ('!displaysTutorial',
  736,
  740,
  ('battle/common/layer0/condition/enhancing_grit_invocation',
   'battle/effect/hit/up_skill_gauge/up_skill_gauge/up_skill_gauge',
   'battle/effect/hit/up_skill_gauge/up_skill_gauge_unconverted/up_skill_gauge_unconverted',
   'battle/effect/hit/down_skill_gauge/down_skill_gauge/down_skill_gauge',
   'battle/effect/hit/down_skill_gauge/down_skill_gauge_unconverted/down_skill_gauge_unconverted',
   'battle/effect/hit/up_fever_gauge/up_fever_gauge/up_fever_gauge',
   'battle/effect/hit/up_fever_gauge/up_fever_gauge_unconverted/up_fever_gauge_unconverted',
   'battle/effect/hit/down_fever_gauge/down_fever_gauge/down_fever_gauge',
   'battle/effect/hit/down_fever_gauge/down_fever_gauge_unconverted/down_fever_gauge_unconverted',
   'battle/common/layer1/damage_resistance/damage_down_ability',
   'battle/common/layer1/damage_resistance/damage_down_direct',
   'battle/common/layer1/damage_resistance/damage_down_powerflip',
   'battle/common/layer1/damage_resistance/damage_down_skill',
   'battle/common/layer1/damage_resistance/damage_up_ability',
   'battle/common/layer1/damage_resistance/damage_up_direct',
   'battle/common/layer1/damage_resistance/damage_up_powerflip',
   'battle/common/layer1/damage_resistance/damage_up_skill')),
 ('DevConfig.assetReadKind == 3',
  741,
  767,
  ('battle/effect/skill_chain/effect_skill_chain_attack_all',
   'battle/effect/skill_chain/effect_skill_chain_attack_large_red',
   'battle/effect/skill_chain/effect_skill_chain_attack_large_blue',
   'battle/effect/skill_chain/effect_skill_chain_attack_large_green',
   'battle/effect/skill_chain/effect_skill_chain_attack_large_yellow',
   'battle/effect/skill_chain/effect_skill_chain_attack_large_black',
   'battle/effect/skill_chain/effect_skill_chain_attack_large_white',
   'battle/effect/skill_chain/effect_skill_chain_attack_medium_red',
   'battle/effect/skill_chain/effect_skill_chain_attack_medium_blue',
   'battle/effect/skill_chain/effect_skill_chain_attack_medium_green',
   'battle/effect/skill_chain/effect_skill_chain_attack_medium_yellow',
   'battle/effect/skill_chain/effect_skill_chain_attack_medium_black',
   'battle/effect/skill_chain/effect_skill_chain_attack_medium_white',
   'battle/effect/skill_chain/effect_skill_chain_attack_small_red',
   'battle/effect/skill_chain/effect_skill_chain_attack_small_blue',
   'battle/effect/skill_chain/effect_skill_chain_attack_small_green',
   'battle/effect/skill_chain/effect_skill_chain_attack_small_yellow',
   'battle/effect/skill_chain/effect_skill_chain_attack_small_black',
   'battle/effect/skill_chain/effect_skill_chain_attack_small_white',
   'battle/common/layer1/cutin_skill_chain4',
   'battle/common/layer1/cutin_skill_chain5',
   'battle/common/layer1/cutin_skill_chain6',
   'battle/common/layer1/cutin_skill_chain7',
   'battle/common/layer1/cutin_skill_chain8',
   'battle/common/layer1/cutin_skill_chain9')))
