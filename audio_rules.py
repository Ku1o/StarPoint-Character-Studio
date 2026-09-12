"""Artist names for observed character voice paths; text is a production note."""
USAGES = {"home": "主界面语音", "join": "加入角色", "evolution": "进化语音", "battle_start": "战斗开始",
          "skill_voice": "技能喊声", "skill_ready": "技能就绪", "power_flip": "强化弹射喊声", "attack": "攻击喊声",
          "outhole": "落穴语音", "win": "胜利语音", "login": "登录语音", "story_words": "剧情短语/语料",
          "battle": "其他战斗语音", "other": "其他角色语音", "skill_sfx": "技能音效", "hit_sfx": "命中音效",
          "charge_sfx": "蓄力音效", "move_sfx": "移动音效", "other_sfx": "其他音效"}


def voice_usage(path):
    path = path.removesuffix(".mp3").removesuffix(".wav").removesuffix(".ogg")
    for prefix, purpose in (("home/", "home"), ("ally/join", "join"), ("ally/evolution", "evolution"),
                            ("battle/battle_start", "battle_start"), ("battle/skill_ready", "skill_ready"),
                            ("battle/skill_", "skill_voice"), ("battle/power_flip", "power_flip"),
                            ("battle/normal_attack", "attack"), ("battle/outhole", "outhole"),
                            ("battle/win", "win"), ("login/", "login"), ("words/", "story_words"), ("battle/", "battle")):
        if path.startswith(prefix):
            return purpose
    return "other"
