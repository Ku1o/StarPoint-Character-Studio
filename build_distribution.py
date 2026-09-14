"""Build a new portable Windows folder and source-inclusive ZIP."""
import argparse
import hashlib
import importlib.metadata
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
import zipfile
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
from app_metadata import VERSION
from distribution_sources import MOD, CORE, CORE_DATA, export_source
DESKTOP_PACKAGES = ("pywebview", "pythonnet", "clr_loader", "cffi", "pycparser", "proxy_tools", "bottle", "typing_extensions")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    # Fail before producing a partial release if the desktop host is unavailable.
    package_versions = {name: importlib.metadata.version(name) for name in ("Pillow", "pyinstaller", *DESKTOP_PACKAGES)}
    output = args.output.resolve()
    if output.exists():
        raise SystemExit("输出目录必须是全新目录")
    if "/.cdn" in output.as_posix().lower() or "/startpoint-cn-main" in output.as_posix().lower():
        raise SystemExit("输出不能位于 CDN 或游戏运行目录")
    output.mkdir(parents=True)
    icon = Image.new("RGBA", (256, 256))
    drawing = ImageDraw.Draw(icon)
    drawing.rounded_rectangle((8, 8, 248, 248), radius=62, fill="#b4a2ff")
    drawing.polygon([(128, 38), (153, 100), (218, 128), (153, 154), (128, 218), (102, 154), (38, 128), (102, 100)], fill="#191426")
    icon.save(output / "studio.ico", sizes=[(16, 16), (32, 32), (48, 48), (128, 128), (256, 256)])
    command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--windowed", "--onedir", "--name", "星点角色工坊",
               "--distpath", str(output / "portable"), "--workpath", str(output / "build"), "--specpath", str(output),
               "--paths", str(HERE), "--paths", str(MOD), "--icon", str(output / "studio.ico"),
               "--add-data", str(HERE / "web") + os.pathsep + "web",
               "--add-data", str(HERE / "docs") + os.pathsep + "docs",
               "--add-data", str(output / "studio.ico") + os.pathsep + ".",
               "--collect-data", "webview", "--collect-binaries", "pythonnet",
               "--collect-binaries", "clr_loader"]
    # WinForms loads these dynamically; explicit inclusion also activates their
    # PyInstaller hooks for WebView2Loader, Python.Runtime and ClrLoader DLLs.
    for module in ("webview.platforms.winforms", "webview.platforms.edgechromium", "clr", "pythonnet", "clr_loader.netfx"):
        command += ["--hidden-import", module]
    for name in CORE_DATA:
        command += ["--add-data", str(MOD / name) + os.pathsep + "."]
    for module in ("tkinter", "numpy", "matplotlib", "scipy", "pandas", "torch", "pytest", "IPython"):
        command += ["--exclude-module", module]
    for module in ("webview.platforms.android", "webview.platforms.cocoa", "webview.platforms.gtk", "webview.platforms.qt", "webview.platforms.cef", "PyQt5", "PyQt6", "PySide2", "PySide6", "cefpython3"):
        command += ["--exclude-module", module]
    # The legacy CLI has optional imports in commands that this product never uses.
    for module in sorted(MOD.glob("wf_*.py")):
        if module.name not in CORE:
            command += ["--exclude-module", module.stem]
    command.append(str(HERE / "studio.py"))
    subprocess.run(command, check=True, timeout=600)
    folder = output / "portable" / "星点角色工坊"
    # .NET Framework otherwise rejects bundled Python.NET/WebView2 assemblies
    # when Windows propagated the downloaded ZIP's Internet-zone mark.
    shutil.copy2(HERE / "starpoint-runtime.config", folder / "星点角色工坊.exe.config")
    # The .NET loader reads the config beside the frozen EXE; bundled Python
    # and WebView2 binaries remain under _internal.
    for relative in ("webview/js/api.js", "webview/lib/Microsoft.Web.WebView2.Core.dll",
                     "webview/lib/Microsoft.Web.WebView2.WinForms.dll",
                     "webview/lib/runtimes/win-x64/native/WebView2Loader.dll",
                     "pythonnet/runtime/Python.Runtime.dll", "clr_loader/ffi/dlls/amd64/ClrLoader.dll", "studio.ico"):
        if not (folder / "_internal" / relative).is_file():
            raise SystemExit("桌面运行依赖漏打包：" + relative)
    if not (folder / "星点角色工坊.exe.config").is_file():
        raise SystemExit("桌面运行依赖漏打包：星点角色工坊.exe.config")
    shutil.copy2(HERE / "docs" / "USER_GUIDE.md", folder / "使用说明.md")
    shutil.copy2(HERE / "README.md", folder / "README.md")
    shutil.copy2(HERE / "NOTICE.md", folder / "来源声明.md")
    shutil.copy2(MOD / "LICENSE", folder / "LICENSE")
    notices = folder / "第三方许可"
    notices.mkdir()
    shutil.copy2(Path(sys.base_prefix) / "LICENSE.txt", notices / "Python-LICENSE.txt")
    for package in ("Pillow", "pyinstaller", *DESKTOP_PACKAGES):
        distribution = importlib.metadata.distribution(package)
        package_notice = notices / package
        package_notice.mkdir(exist_ok=True)
        metadata = distribution.read_text("METADATA") or ""
        (package_notice / "PACKAGE-METADATA.txt").write_text(metadata, encoding="utf-8")
        for item in distribution.files or []:
            if "/licenses/" in str(item).replace("\\", "/").lower():
                target = notices / package / Path(*item.parts[item.parts.index("licenses") + 1:])
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(distribution.locate_file(item), target)
    for file in sorted((HERE / "third_party").iterdir()):
        if file.is_file():
            shutil.copy2(file, notices / file.name)
    sources = folder / "source"
    export_source(sources)
    (folder / "双击使用.txt").write_text("完整解压后，双击 星点角色工坊.exe。工作台显示在独立桌面窗口与任务栏中。\n再次双击会唤回已打开的同一窗口，不会重复启动一套服务。\n点击窗口右上角 × 或工具的电源按钮，保存成功后退出整个程序；保存失败会保留窗口。\n无需安装 Python、原 MOD 修改器或游戏服务器。桌面窗口使用系统 Microsoft Edge WebView2 Runtime 和 .NET Framework 4.6.2+；Windows 11 通常已提供，离线使用前请确保组件已安装。\n创作者按工具与完整角色资源两类下载，GitHub 资源分为两份普通 ZIP，两份均需解压：把资源包中的 templates 和 definitions 文件夹一起放在本 EXE 旁边，即可基于官方模板新建角色。没有素材库也可制作原创角色。\n工程保存在本目录 projects 文件夹，也可导出 .wfchar.zip 备份。\n升级时先在旧版保存并退出，把新版完整解压到新目录，打开“工程与升级”选择旧工具文件夹迁入。画稿、动作、特效、声音、能力与历史都会复制，旧目录保留。templates 和 definitions 可继续使用原来下载的素材库，另行复制到新版 EXE 旁。不要只替换 EXE 或覆盖旧目录。\n自动历史记录随 projects 保存；要保留完整历史，请把整个 projects 文件夹备份到其他位置。\n\n当前为独立制作版：包含图片制作要求、多帧编辑、技能声音事件、动画完整显示、技能组合及编译回读预览；不自动发布到游戏。模板复杂特效与原始资源缺项会逐项显示。\n", encoding="utf-8")
    (folder / "完整角色资源说明.txt").write_text("完整角色资源包已合并图片、动作、特效、声音与角色定义。将其中 templates 和 definitions 两个文件夹一起放到 EXE 旁。旧版小型角色定义 ZIP 仍可单独导入。\n可在「技能与能力 → 自由组合 / 拆解与组合」中独立配置条件、触发和效果，也可从词条库单独取材；导出的工程可在 MOD 的角色工坊模块继续使用。\n能力草稿通过原 MOD 格式编译和回读，但尚未分配新游戏 ID，不能覆盖游戏主表。完整战斗技能预览仍未实现。\n", encoding="utf-8")
    manifest = {"version": VERSION, "created": datetime.now().isoformat(), "runtimePackages": package_versions, "sourceModules": {name: hashlib.sha256((MOD / name).read_bytes()).hexdigest() for name in CORE + CORE_DATA}, "files": []}
    for file in sorted(folder.rglob("*")):
        if file.is_file():
            manifest["files"].append({"path": file.relative_to(folder).as_posix(), "sha256": hashlib.sha256(file.read_bytes()).hexdigest(), "size": file.stat().st_size})
    (folder / "distribution-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    archive_path = output / f"StarPoint-Character-Studio-{VERSION}-Windows.zip"
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for file in sorted(folder.rglob("*")):
            if file.is_file():
                archive.write(file, "星点角色工坊/" + file.relative_to(folder).as_posix())
    with zipfile.ZipFile(archive_path) as archive:
        if archive.testzip():
            raise SystemExit("分发 ZIP 校验失败")
        for info in archive.infolist():
            relative = info.filename.removeprefix("星点角色工坊/")
            if archive.read(info) != (folder / relative).read_bytes():
                raise SystemExit("分发文件回读不一致")
    digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    archive_path.with_suffix(".zip.sha256").write_text(digest + "  " + archive_path.name + "\n", encoding="ascii")
    print(json.dumps({"folder": str(folder), "zip": str(archive_path), "sha256": digest}, ensure_ascii=False))


if __name__ == "__main__":
    main()
