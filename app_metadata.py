"""Product identity shared by the service, desktop window and distribution."""

NAME = "星点角色工坊"
VERSION = "0.7.2"
CHANNEL = "预览版"
TITLE = f"{NAME} v{VERSION} · {CHANNEL}"
REPOSITORY_URL = "https://github.com/Ku1o/StarPoint-Character-Studio"
UPSTREAM_URL = "https://github.com/kuronzzhan-droid/startpoint-cn-mod-tools"


def public_info():
    return {"name": NAME, "version": VERSION, "channel": CHANNEL,
            "repository": REPOSITORY_URL, "upstream": UPSTREAM_URL,
            "license": "GPL-3.0"}
