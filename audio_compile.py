"""Encode supported audio and translate editor sound events to native timelines."""
from bridge import mp3_encode, mp3_decode
from studio_core import StudioError


def sound_path(code, asset):
    return f"sound_effect/character_studio/{code}/{asset}"


def encoded_sound(store, p, asset):
    if p["assets"].get(asset, {}).get("mime") != "audio/mpeg":
        raise StudioError("该声音尚非可编译的 CBR MP3；WAV/OGG 可以预览并随工程交接")
    try:
        return mp3_encode(store.asset_bytes(p, asset))
    except ValueError as error:
        raise StudioError("声音编译要求恒定码率（CBR）的 MP3，请在音频软件中转换后重新导入：" + str(error)) from error


def effect_audio(store, p, effect, code, begin=1):
    sounds, files, issues = [], {}, []
    for event in effect.get("soundEvents", []):
        if event.get("enabled") is False:
            continue
        aid = event.get("asset")
        if not aid:
            if event.get("source"):
                sounds.append(dict(event["source"], begin=begin + event["start"]))
            issues.append("尚未绑定音效：" + event.get("path", "未命名"))
            continue
        path = sound_path(code, aid)
        try:
            files[path + ".mp3"] = encoded_sound(store, p, aid)
        except StudioError as error:
            issues.append(p["assets"][aid]["name"] + "：" + str(error))
            continue
        sounds.append({"path": path, "begin": begin + event["start"], "loop": event.get("loop", 1),
                       "end": begin+event["end"] if event.get("end", -1) != -1 else -1,
                       "volume": round(event.get("volume", 1)*10)})
    return sounds, files, issues
