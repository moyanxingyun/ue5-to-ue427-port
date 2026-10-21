# -*- coding: utf-8 -*-
"""Switch mesh slots to fallback materials, with a reversible JSON backup.

Environment:
    Unreal Engine 4.27 Editor Python 3.7, Cmd mode.

Use:
    py "PATH/TO/PortKit/scripts/tools/switch_fallback.py" --config "PATH/TO/config.json"

Output:
    Mesh material slots switched in apply mode or restored in restore mode.
    Original assignments are saved to paths.reports/fallback_materials_backup.json.
"""
import argparse
import importlib
import json
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_ROOT = os.path.dirname(SCRIPT_DIR)
if SCRIPTS_ROOT not in sys.path:
    sys.path.insert(0, SCRIPTS_ROOT)

import portkit_config

importlib.reload(portkit_config)
portkit_config.reload_shared_modules()

from portkit_config import load_config, report_path

try:
    import unreal
except ImportError:
    unreal = None


def _fallback_for(eal, material, folder, prefix, templates):
    name = material.get_name()
    if name.startswith(prefix):
        return material
    short = name[3:] if name.startswith("MI_") else name
    candidates = [
        template.format(short=short, name=name) for template in templates
    ]
    for candidate in candidates:
        path = folder.rstrip("/") + "/" + candidate
        if eal.does_asset_exist(path):
            return unreal.load_asset(path)
    return None


def run(config):
    if unreal is None:
        raise RuntimeError(
            "Run switch_fallback.py inside UE 4.27 Editor Python"
        )
    options = config.get("tools", {}).get("switch_fallback", {})
    mesh_folder = options.get("mesh_folder")
    material_folder = options.get("material_folder")
    if not mesh_folder or not material_folder:
        raise ValueError(
            "tools.switch_fallback requires mesh_folder and material_folder"
        )
    mode = str(options.get("mode", "apply")).lower()
    prefix = options.get(
        "fallback_prefix", options.get("fallback_name_prefix", "MI_Fallback_")
    )
    templates = options.get(
        "candidate_templates", [prefix + "{short}", prefix + "{name}"]
    )
    backup_path = options.get("backup") or report_path(
        config, "fallback_materials_backup.json"
    )
    backup = {}
    if os.path.isfile(backup_path):
        with open(backup_path, "r", encoding="utf-8") as handle:
            backup = json.load(handle)
    eal = unreal.EditorAssetLibrary
    mesh_paths = [
        path.split(".")[0]
        for path in eal.list_assets(
            mesh_folder, recursive=True, include_folder=False
        )
        if "StaticMesh"
        in str(eal.find_asset_data(path).asset_class)
    ]
    switched = kept = missing = restored = 0
    failures = []
    progress = unreal.ScopedSlowTask(
        max(1, len(mesh_paths)), "PortKit fallback materials"
    )
    progress.make_dialog_visible()
    for mesh_path in mesh_paths:
        if progress.should_cancel():
            failures.append("CANCELLED")
            break
        progress.enter_progress_frame(1, mesh_path.rsplit("/", 1)[-1])
        mesh = unreal.load_asset(mesh_path)
        if not isinstance(mesh, unreal.StaticMesh):
            continue
        changed = False
        for index, slot in enumerate(
            mesh.get_editor_property("static_materials")
        ):
            current = slot.material_interface
            if current is None:
                continue
            if mode == "restore":
                original_path = (
                    backup.get(mesh_path, {}).get(str(index))
                )
                if original_path:
                    original = unreal.load_asset(original_path)
                    if original is not None:
                        mesh.set_material(index, original)
                        changed = True
                        restored += 1
                continue
            fallback = _fallback_for(
                eal,
                current,
                material_folder,
                prefix,
                templates,
            )
            if fallback is None:
                missing += 1
                failures.append(
                    "%s[%d] %s" % (mesh.get_name(), index, current.get_name())
                )
            elif fallback == current:
                kept += 1
            else:
                backup.setdefault(mesh_path, {})[str(index)] = (
                    current.get_path_name().split(".")[0]
                )
                mesh.set_material(index, fallback)
                switched += 1
                changed = True
        if changed:
            eal.save_loaded_asset(mesh, False)
    if mode == "restore":
        backup = {}
    with open(backup_path, "w", encoding="utf-8") as handle:
        json.dump(backup, handle, ensure_ascii=False, indent=2)
    payload = {
        "mode": mode,
        "switched": switched,
        "already_fallback": kept,
        "restored": restored,
        "no_match": missing,
        "failures": failures,
        "backup": backup_path,
    }
    with open(
        report_path(config, "switch_fallback.json"),
        "w",
        encoding="utf-8",
    ) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    with open(
        report_path(config, "switch_fallback.txt"),
        "w",
        encoding="utf-8",
    ) as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, indent=2))
    return payload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", help="Path to PortKit JSON config")
    args = parser.parse_args()
    config = load_config(args.config)
    try:
        run(config)
    except Exception:
        if unreal is not None:
            import traceback

            with open(
                report_path(config, "switch_fallback.txt"),
                "w",
                encoding="utf-8",
            ) as handle:
                handle.write(traceback.format_exc())
        else:
            raise


if __name__ == "__main__":
    main()
