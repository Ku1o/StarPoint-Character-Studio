"""Explicit source export shared by public repository preparation and packaging."""
from pathlib import Path
import argparse
import hashlib
import json
import shutil

HERE = Path(__file__).resolve().parent
MOD = HERE / "core" if (HERE / "core").is_dir() else HERE.parent / "fantasy-gauntlet-mod-tools"
CORE = ("wf_mod_tool.py", "wf_dsl.py", "wf_flatomo_preview_render.py", "wf_assets.py",
        "wf_character_requirements.py", "wf_ability_composer.py", "wf_describe.py", "wf_client_legality.py")
CORE_DATA = ("ability_enum_map.json", "词条条件代码全表.md")
SOURCE_FILES = (
    'studio.py',
    'asset_rules.py',
    'audio_rules.py',
    'audio_compile.py',
    'template_library.py',
    'studio_core.py',
    'studio_compile.py',
    'bridge.py',
    'build_distribution.py',
    'README.md',
    'GITHUB.md',
    '.gitignore',
    'web/index.html',
    'web/style.css',
    'web/app.js',
    'web/compiled-preview.js',
    'web/preview-layout.js',
    'web/authoring-guide.js',
    'web/audio-workbench.js',
    'web/sound-preview.js',
    'web/template-library.js',
    'tests/test_studio.py',
    'tests/preview_layout.test.js',
    'tests/ui_smoke.py',
    'tests/portable_smoke.py',
    'tests/library_ui_smoke.py',
    'tests/validate_library.py',
    'desktop_host.py',
    'requirements-desktop.txt',
    'web/desktop-window.js',
    'tests/test_desktop_host.py',
    'tests/desktop_smoke.py',
    'action_presets.py',
    'pixel_import.py',
    'skill_preview.py',
    'character_contract.py',
    'MOD-INTEGRATION.md',
    'web/pixel-import.js',
    'web/pixel-import.css',
    'web/skill-workbench.js',
    'web/skill-workbench.css',
    'web/character-workflow.js',
    'tests/test_pixel_workflow.py',
    'tests/test_skill_preview.py',
    'tests/test_scene_playback.py',
    'tests/test_character_contract.py',
    'tests/test_media_catalog.py',
    'tests/pixel_ui_smoke.py',
    'tests/skill_ui_smoke.py',
    'native_gameplay.py',
    'web/native-workbench.js',
    'web/native-workbench.css',
    'web/mod-host.js',
    'PREVIEW-RUNTIME.md',
    'tests/test_native_gameplay.py',
    'tests/native_portable_smoke.py',
    'effect_channels.py',
    'ability_editor.py',
    'web/effect-channels.js',
    'web/effect-channels.css',
    'web/ability-composition.js',
    'web/ability-composition.css',
    'tests/test_effect_channels.py',
    'tests/test_ability_editor.py',
    'tests/component_ui_smoke.py',
    'ability_library.py',
    'web/editor-scroll.js',
    'web/ability-picker.js',
    'tests/test_ability_library.py',
    'tests/authoring_ui_smoke.py',
    'portrait_editor.py',
    'atlas_editor.py',
    'web/portrait-workbench.js',
    'web/portrait-workbench.css',
    'web/image-workbench.js',
    'tests/test_portrait_editor.py',
    'tests/portrait_ui_smoke.py',
    'CORE-PROVENANCE.md',
    'app_metadata.py',
    'distribution_sources.py',
    'web/about-tool.js',
    'web/about-tool.css',
    'docs/USER_GUIDE.md',
    'NOTICE.md',
    'CHANGELOG.md',
    'requirements-build.txt',
    'requirements-test.txt',
    '.github/workflows/check.yml',
    'integrations/mod/wf_character_studio.py',
)


def export_source(destination):
    destination = Path(destination).resolve()
    if destination.exists():
        raise ValueError("源码输出目录必须是全新目录")
    if ".cdn" in destination.parts or "startpoint-cn-main" in destination.parts:
        raise ValueError("输出不能位于 CDN 或游戏运行目录")
    pairs = [(HERE / name, name) for name in SOURCE_FILES]
    pairs += [(file, "third_party/" + file.name) for file in sorted((HERE / "third_party").iterdir()) if file.is_file()]
    pairs += [(MOD / name, "core/" + name) for name in (*CORE, *CORE_DATA, "LICENSE")]
    pairs += [(HERE / "LICENSE" if (HERE / "LICENSE").is_file() else MOD / "LICENSE", "LICENSE")]
    # Resolve and validate the full list before creating output. No project/resource
    # directory is traversed, including source-tree junctions to offline libraries.
    for source, relative in pairs:
        root = MOD if relative.startswith("core/") or relative == "LICENSE" and not (HERE / "LICENSE").is_file() else HERE
        if not source.is_file() or not source.resolve().is_relative_to(root.resolve()):
            raise ValueError("分发文件缺失或越出源码目录：" + relative)
    destination.mkdir(parents=True)
    for source, relative in pairs:
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    return {relative: hashlib.sha256((destination / relative).read_bytes()).hexdigest() for _, relative in pairs}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="只导出工具源码，不复制角色资源和工程")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    files = export_source(args.output)
    print(json.dumps({"output": str(args.output.resolve()), "files": len(files)}, ensure_ascii=False))
