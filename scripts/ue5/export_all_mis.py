# -*- coding: utf-8 -*-
"""Add every relevant MaterialInstanceConstant from a UE5 pack to the export.

Environment:
    Unreal Engine 5.4 Editor Python, Cmd mode.

Use:
    py "PATH/TO/PortKit/scripts/ue5/export_all_mis.py" --config "PATH/TO/config.json"

Output:
    Updates materials.json and textures_map.json in the configured export
    directory and writes report_allMIs.json/txt. Existing records and textures
    are preserved so the operation is resumable.
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

from portkit_config import load_config
from ue5.export_common import (
    asset_path,
    class_name,
    exception_text,
    export_summary,
    export_texture,
    material_info,
    write_json,
)

try:
    import unreal
except ImportError:
    unreal = None


def run(config):
    if unreal is None:
        raise RuntimeError("Run export_all_mis.py inside UE 5.4 Editor Python")
    options = config.get("ue5", {}).get("exports", {}).get("all_mis", {})
    asset_root = options.get("asset_root") or config.get("ue5", {}).get(
        "asset_root"
    )
    output = options.get("output")
    masters = set(options.get("masters", []))
    if not asset_root or not output or not masters:
        raise ValueError(
            "ue5.exports.all_mis requires asset_root, output and masters"
        )
    materials_path = os.path.join(output, "materials.json")
    texture_map_path = os.path.join(output, "textures_map.json")
    with open(materials_path, "r", encoding="utf-8") as handle:
        materials = json.load(handle)
    with open(texture_map_path, "r", encoding="utf-8") as handle:
        texture_map = json.load(handle)
    eal = unreal.EditorAssetLibrary
    instances = [
        path.split(".")[0]
        for path in eal.list_assets(
            asset_root, recursive=True, include_folder=False
        )
        if class_name(eal.find_asset_data(path))
        == "MaterialInstanceConstant"
    ]
    used_names = {
        os.path.splitext(value["file"])[0]: key
        for key, value in texture_map.items()
    }
    added = 0
    skipped_master = 0
    textures_added = 0
    failures = []
    progress = unreal.ScopedSlowTask(
        max(1, len(instances)), "PortKit unassigned material instances"
    )
    progress.make_dialog_visible()
    for path in instances:
        if progress.should_cancel():
            failures.append("CANCELLED - rerun to continue")
            break
        progress.enter_progress_frame(1, path.rsplit("/", 1)[-1])
        if path in materials:
            continue
        instance = unreal.load_asset(path)
        if instance is None:
            continue
        info = material_info(instance)
        parent = (
            info["parents"][-1].rsplit("/", 1)[-1]
            if info["parents"]
            else ""
        )
        if parent not in masters:
            skipped_master += 1
            continue
        materials[path] = info
        added += 1
        for texture_path in info["textures"].values():
            if (
                not texture_path
                or not texture_path.startswith("/Game/")
                or texture_path in texture_map
            ):
                continue
            texture = unreal.load_asset(texture_path)
            if not isinstance(texture, unreal.Texture2D):
                continue
            filename = export_texture(
                texture,
                os.path.join(output, "Textures"),
                used_names,
                texture_map,
            )
            if filename is None:
                failures.append("texture " + texture_path)
            else:
                textures_added += 1
    write_json(materials_path, materials)
    write_json(texture_map_path, texture_map)
    counts = {
        "instances_found": len(instances),
        "instances_added": added,
        "other_masters_skipped": skipped_master,
        "textures_added": textures_added,
    }
    export_summary("all_mis", output, counts, failures)
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", help="Path to PortKit JSON config")
    args = parser.parse_args()
    config = load_config(args.config)
    try:
        run(config)
    except Exception:
        output = (
            config.get("ue5", {})
            .get("exports", {})
            .get("all_mis", {})
            .get("output")
            or os.getcwd()
        )
        if unreal is not None:
            export_summary(
                "all_mis", output, {}, ["fatal"], [exception_text()]
            )
        else:
            raise


if __name__ == "__main__":
    main()
