"""Loopback-only launcher. No game server, profile or device operations."""
from __future__ import annotations

import argparse
import base64
import io
import json
import mimetypes
import secrets
import sys
import threading
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from app_metadata import VERSION, TITLE, public_info

from studio_core import ProjectStore, StudioError, json_bytes, project_checks, MAX_ARCHIVE
from studio_compile import compile_project, crop_portrait, compiled_preview
from studio_core import png_bytes
from asset_rules import RULES
from template_library import TemplateLibrary
from desktop_host import WindowsInstance, run_desktop, show_error
from action_presets import catalog as action_presets_catalog
from skill_preview import preview_plans
from native_gameplay import DefinitionLibrary, attach as attach_definition, edit as edit_native, describe_native
from wf_ability_composer import composer_catalog
from ability_library import AbilityLibrary

APP = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))


class StudioHTTPServer(ThreadingHTTPServer):
    # A frame atlas can issue many local image requests at once on Windows.
    request_queue_size = 64


def create_server(root, port=0, templates=None, definitions=None, parent_origin=None, ability_provider=None):
    store = ProjectStore(root)
    library = TemplateLibrary(templates or Path(root).parent / "templates")
    definition_library = DefinitionLibrary(definitions or Path(root).parent / "definitions")
    ability_library = AbilityLibrary(definition_library, ability_provider)
    if parent_origin is not None:
        import re
        if not re.fullmatch(r"http://127\.0\.0\.1:[0-9]{1,5}", parent_origin):
            raise ValueError("MOD 宿主必须是本机窗口")
    token = secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        server_version = f"CharacterStudio/{VERSION}"

        def log_message(self, *_):
            pass

        def respond(self, data, status=200, mime="application/json; charset=utf-8", filename=None):
            if not isinstance(data, bytes):
                data = json_bytes(data)
            self.send_response(status)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            ancestors = parent_origin or "'none'"
            self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' blob: data:; media-src 'self' blob: data:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; frame-ancestors " + ancestors + "; object-src 'none'")
            if filename:
                self.send_header("Content-Disposition", "attachment; filename*=UTF-8''" + urllib.parse.quote(filename))
            self.end_headers()
            self.wfile.write(data)

        def guard(self, mutate=False):
            origin = f"http://127.0.0.1:{self.server.server_port}"
            if self.headers.get("Host") != origin.removeprefix("http://"):
                raise StudioError("访问地址不正确")
            if self.headers.get("Origin") not in (None, origin):
                raise StudioError("请求来源不正确")
            if mutate and self.headers.get("X-Studio-Token") != token:
                raise StudioError("页面已失效，请重新打开工具")

        def do_GET(self):
            try:
                self.guard()
                url = urllib.parse.urlsplit(self.path)
                args = urllib.parse.parse_qs(url.query)
                def arg(key):
                    return args.get(key, [""])[0]
                if url.path == "/api/session":
                    self.respond({"token": token, "projects": store.list(), "version": VERSION, "app": public_info(), "rules": RULES, "desktop": self.server.desktop_mode, "host": "mod" if parent_origin else "standalone", "parentOrigin": parent_origin})
                elif url.path == "/api/user-guide":
                    self.respond((APP / "docs" / "USER_GUIDE.md").read_bytes(), mime="text/markdown; charset=utf-8", filename="星点角色工坊-使用说明.md")
                elif url.path == "/api/definitions":
                    self.respond(definition_library.catalog())
                elif url.path == "/api/ability-editor":
                    from ability_editor import metadata
                    self.respond(metadata())
                elif url.path == "/api/ability-catalog":
                    self.respond(composer_catalog())
                elif url.path == "/api/ability-library":
                    self.respond(ability_library.query(arg('kind'),arg('q'),int(arg('offset') or 0),arg('key') or None))
                elif url.path == "/api/native-gameplay":
                    self.respond(describe_native(store.load(arg("id")).get("nativeGameplay")))
                elif url.path == "/api/project":
                    self.respond(store.load(arg("id")))
                elif url.path == "/api/action-presets":
                    self.respond({"presets": action_presets_catalog()})
                elif url.path == "/api/templates":
                    self.respond(library.catalog())
                elif url.path == "/api/template-thumbnail":
                    self.respond(library.thumbnail(arg("id")), mime="image/png")
                elif url.path == "/api/asset":
                    raw, mime = store.media_asset(arg("project"), arg("id"))
                    filename = store.load(arg("project"))["assets"][arg("id")]["name"] if arg("download") == "1" else None
                    self.respond(raw, mime=mime, filename=filename)
                elif url.path == "/api/export":
                    p = store.load(arg("id"))
                    self.respond(store.export(p["id"]), mime="application/zip", filename=p["name"] + ".wfchar.zip")
                elif url.path == "/api/compile-export":
                    raw, _ = compile_project(store, arg("id"))
                    self.respond(raw, mime="application/zip", filename="角色美术编译产物.zip")
                elif url.path == "/api/portrait":
                    from portrait_editor import render, ui_name
                    raw = render(store, store.load(arg("id")), arg("form"), arg("slot"))
                    self.respond(raw, mime="image/png", filename=ui_name(arg("form"), arg("slot")) if arg("download") == "1" else None)
                elif url.path == "/api/atlas-export":
                    from atlas_editor import atlas_data
                    from studio_core import atlas_crop
                    sheet, records, _, _ = atlas_data(store, store.load(arg("id")), arg("group"), arg("animation"))
                    if arg("cell"):
                        index = int(arg("cell"))
                        if not 0 <= index < len(records):
                            raise StudioError("图块编号无效")
                        record = records[index]
                        self.respond(png_bytes(atlas_crop(sheet, record)), mime="image/png", filename=Path(record["n"]).name + ".png")
                    elif arg("format") == "json":
                        self.respond(json_bytes(records), filename="atlas.json")
                    else:
                        self.respond(png_bytes(sheet), mime="image/png", filename="atlas.png")
                elif url.path in ("/", "/index.html", "/app.js", "/compiled-preview.js", "/preview-layout.js", "/authoring-guide.js", "/template-library.js", "/audio-workbench.js", "/sound-preview.js", "/desktop-window.js", "/pixel-import.js", "/pixel-import.css", "/skill-workbench.js", "/skill-workbench.css", "/character-workflow.js", "/native-workbench.js", "/native-workbench.css", "/mod-host.js", "/editor-scroll.js", "/ability-picker.js", "/effect-channels.js", "/effect-channels.css", "/ability-composition.js", "/ability-composition.css", "/portrait-workbench.js", "/portrait-workbench.css", "/image-workbench.js", "/style.css", "/about-tool.js", "/about-tool.css"):
                    name = "index.html" if url.path == "/" else url.path.removeprefix("/")
                    self.respond((APP / "web" / name).read_bytes(), mime=mimetypes.guess_type(name)[0] or "text/plain")
                elif url.path == "/favicon.ico":
                    self.respond(b"", status=204, mime="image/x-icon")
                else:
                    self.respond({"error": "找不到内容"}, status=404)
            except ConnectionError:
                return
            except (StudioError, OSError, ValueError, KeyError) as exc:
                self.respond({"error": str(exc)}, status=400)

        def do_POST(self):
            try:
                self.guard(True)
                size = int(self.headers.get("Content-Length", 0))
                if not 0 < size <= MAX_ARCHIVE * 2:
                    raise StudioError("请求体积不合法")
                data = json.loads(self.rfile.read(size))
                if self.path == "/api/new":
                    result = store.create(data.get("name", "未命名角色"), data.get("kind", "original"))
                elif self.path == "/api/save":
                    result = store.save(data)
                elif self.path == "/api/upload":
                    result = store.upload(data["id"], data["files"])
                elif self.path == "/api/portrait-render":
                    from portrait_editor import render
                    raw = render(store, store.load(data["id"]), data["form"], data["slot"], data.get("selection"))
                    self.respond(raw, mime="image/png")
                    return
                elif self.path == "/api/atlas-preview":
                    from atlas_editor import preview
                    result = preview(store, store.load(data["id"]), data["group"], data.get("animation"))
                elif self.path == "/api/action-presets":
                    result = store.add_action_presets(data["id"], data["revision"], data.get("slots"))
                elif self.path == "/api/pixel-import":
                    result = store.import_pixel_images(data["id"], data)
                elif self.path == "/api/skill-preview-plan":
                    result = preview_plans(store, data["id"])
                elif self.path == "/api/definition-install":
                    from studio_core import archive_files
                    result = definition_library.install(archive_files(base64.b64decode(data["data"], validate=True)))
                elif self.path == "/api/definition-attach":
                    result = attach_definition(store, data['id'], data['revision'], definition_library, data.get('character'))
                elif self.path == "/api/effect-channels":
                    from effect_channels import prepare
                    result=prepare(store,data["id"],data["revision"],data["effect"])
                elif self.path == "/api/native-edit":
                    result = edit_native(store, data['id'], data['revision'], data['operation'], data.get('slot'), data.get('index'), data.get('spec'))
                elif self.path == "/api/ability-row-draft":
                    from ability_editor import draft
                    result=draft(store,data["id"],data["slot"],data.get("index"))
                elif self.path == "/api/ability-row-preview":
                    from ability_editor import preview
                    result=preview(data["kind"],data["row"])
                elif self.path == "/api/ability-row-apply":
                    from ability_editor import apply
                    result=apply(store,data["id"],data["revision"],data["slot"],data.get("index"),data["row"])
                elif self.path == "/api/ability-row-transfer":
                    from ability_editor import transfer
                    result=transfer(store,data["id"],data["revision"],data["slot"],data["index"],data["target"],data["position"],data.get("copy",False))
                elif self.path == "/api/ability-library-append":
                    result = ability_library.append(store,data['id'],data['revision'],data['slot'],data['key'],data['fingerprint'],data.get('indices'))
                elif self.path == "/api/import":
                    result = store.import_archive(base64.b64decode(data["data"], validate=True))
                elif self.path == "/api/template-create":
                    definitions = definition_library.load()
                    result = store.import_archive(library.archive(data["id"]))
                    template = result.get('template') or {}
                    if definitions and str(data['id']) in definitions['characters'] and str(template.get('version')) == str(definitions['version']):
                        result = attach_definition(store, result['id'], result['revision'], definition_library, str(data['id']))
                elif self.path == "/api/check":
                    result = project_checks(store.load(data["id"]))
                elif self.path == "/api/compile":
                    _, result = compile_project(store, data["id"])
                elif self.path == "/api/compiled-preview":
                    result = compiled_preview(store, data["id"], data["group"], data["animation"])
                elif self.path == "/api/desktop-ready":
                    self.server.desktop_ready()
                    result = {"ok": True}
                elif self.path == "/api/desktop-close-cancel":
                    self.server.desktop_close_cancel()
                    result = {"ok": True}
                elif self.path == "/api/shutdown":
                    self.respond({"ok": True})
                    threading.Thread(target=self.server.shutdown, daemon=True).start()
                    return
                else:
                    raise StudioError("未知操作")
                self.respond(result)
            except ConnectionError:
                return
            except (StudioError, OSError, ValueError, KeyError, TypeError) as exc:
                self.respond({"error": str(exc)}, status=400)

    server = StudioHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    server.store = store
    server.studio_version = VERSION
    server.definition_library = definition_library
    server.desktop_mode = False
    server.desktop_ready = lambda: None
    server.desktop_close_cancel = lambda: None
    server.studio_stopped = threading.Event()
    return server


def main():
    parser = argparse.ArgumentParser(description="星点角色工坊")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--projects", type=Path)
    parser.add_argument("--templates", type=Path)
    parser.add_argument("--definitions", type=Path)
    parser.add_argument("--open", action="store_true")
    parser.add_argument("--no-open", action="store_true", help="仅启动本机服务，供自动验收使用")
    args = parser.parse_args()
    base = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent
    projects = (args.projects or base / "projects").resolve()
    instance = WindowsInstance(projects)
    if not instance.owner:
        instance.notify_existing()
        instance.close()
        return
    server = None
    try:
        server = create_server(projects, args.port, args.templates or base / "templates", args.definitions or base / "definitions")
        address = f"http://127.0.0.1:{server.server_port}"
        print(TITLE + " " + address, flush=True)
        if not args.no_open and (args.open or getattr(sys, "frozen", False)):
            if sys.platform == "win32":
                run_desktop(server, address, instance, base)
            else:
                webbrowser.open(address)
                server.serve_forever()
        else:
            server.serve_forever()
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        if getattr(sys, "frozen", False) and not args.no_open:
            show_error("角色工坊未能启动。\n" + str(exc))
            raise SystemExit(1)
        raise
    finally:
        if server is not None:
            server.server_close()
        instance.close()


if __name__ == "__main__":
    main()
