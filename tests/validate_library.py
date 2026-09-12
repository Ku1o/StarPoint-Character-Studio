"""Validate every delivered template using the actual project importer."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys
import tempfile
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from template_library import TemplateLibrary
from studio_core import ProjectStore, validate, json_bytes


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--library", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument("--update-catalog", action="store_true", help="Write verified counts and categorized diagnostics to the generated library")
    parser.add_argument("--recheck", nargs="+", help="Re-import affected ids and retain previously checked results")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    library = TemplateLibrary(args.library)
    catalog = library.catalog()
    results, failures = [], []
    entries = catalog["entries"]
    if args.retry_failed:
        previous = json.loads((output / "library-validation.json").read_bytes())
        retry_ids = {entry["id"] for entry in previous["failures"]}
        results = previous["results"]
        entries = [entry for entry in entries if entry["id"] in retry_ids]
    if args.recheck:
        previous = json.loads((output / "library-validation.json").read_bytes())
        results = [r for r in previous["results"] if r["id"] not in args.recheck]
        failures = [r for r in previous["failures"] if r["id"] not in args.recheck]
        entries = [entry for entry in entries if entry["id"] in args.recheck]
    started = time.monotonic()
    for index, entry in enumerate(entries):
        try:
            with tempfile.TemporaryDirectory(dir=output, prefix="template-") as temporary:
                store = ProjectStore(Path(temporary) / "projects")
                p = store.import_archive(library.archive(entry["id"]))
                validate(p)
                missing_events = sorted({event.get("path", "") for a in p["effects"] for event in a.get("soundEvents", []) if not event.get("asset")})
                if missing_events:
                    raise AssertionError("模板特效音效依赖仍然缺失：" + ", ".join(missing_events))
                for anim in p["animations"]:
                    if not anim["clips"]:
                        raise AssertionError("已导入动作没有播放帧：" + anim["name"])
                result = {"id": entry["id"], "name": entry["name"], "actions": len(p["animations"]), "effects": len(p["effects"]), "voices": len(p["voices"]), "sounds": len(p["sounds"]),
                          "warnings": p["warnings"], "effectWarnings": [issue for a in p["effects"] for issue in a.get("issues", [])]}
                results.append(result)
        except Exception as error:
            failures.append({"id": entry["id"], "name": entry["name"], "error": type(error).__name__ + ": " + str(error)})
        if (index + 1) % 25 == 0:
            print(json.dumps({"checked": index + 1, "total": len(catalog["entries"]), "failed": len(failures), "seconds": round(time.monotonic() - started)}, ensure_ascii=False), flush=True)
            (output / "library-validation-progress.json").write_bytes(json_bytes({"results": results, "failures": failures}))
    report = {"version": catalog["version"], "total": len(catalog["entries"]), "passed": len(results), "failures": failures, "seconds": round(time.monotonic() - started), "results": results}
    if args.recheck:
        report["previousFullRunSeconds"] = previous.get("previousFullRunSeconds", previous["seconds"])
        report["rechecked"] = sorted(set(previous.get("rechecked", []) + args.recheck))
    (output / "library-validation.json").write_bytes(json_bytes(report))
    if args.update_catalog and not failures:
        by_id = {r["id"]: r for r in results}
        for entry in catalog["entries"]:
            r = by_id[entry["id"]]
            diagnostics = []
            for warning in sorted(set(r["warnings"])):
                category = "source" if (int(entry["id"]) >= 700000 or "原始时间轴" in warning) else "missing"
                diagnostics.append({"category": category, "text": warning})
            diagnostics.extend({"category": "preview", "text": w} for w in sorted(set(r["effectWarnings"])))
            entry["diagnostics"] = diagnostics
            entry["warnings"] = [d["text"] for d in diagnostics]
            categories = {d["category"] for d in diagnostics}
            entry["status"] = "missing_assets" if "missing" in categories else "preview_limited" if "preview" in categories else "source_notes" if categories else "ready"
            entry["counts"].update(actions=r["actions"], effects=r["effects"], voices=r["voices"], sounds=r["sounds"])
        catalog.pop("installed", None)
        for entry in catalog["entries"]:
            entry.pop("available", None)
        catalog["validation"] = {"toolVersion": "0.3.0", "entries": len(results), "boundEffectAudio": True, "checks": "逐角色导入、动作帧、图层引用、音效绑定及预览能力检查"}
        (args.library / "catalog.json").write_bytes(json_bytes(catalog))
    print(json.dumps({k: v for k, v in report.items() if k != "results"}, ensure_ascii=False), flush=True)
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
