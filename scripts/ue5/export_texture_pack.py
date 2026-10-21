# -*- coding: utf-8 -*-
"""Export a decal/texture pack from UE5 as TGA while preserving alpha.

Environment:
    Unreal Engine 5.4 Editor Python, Cmd mode.

Use:
    py "PATH/TO/PortKit/scripts/ue5/export_texture_pack.py" --config "PATH/TO/config.json"

Output:
    TGA textures and report.json/txt in ue5.exports.texture_pack.output.
    Material-instance parameters are recorded for the 4.27 rebuild.
"""
import argparse
import importlib
import os
import sys
import traceback

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_ROOT = os.path.dirname(SCRIPT_DIR)
if SCRIPTS_ROOT not in sys.path:
    sys.path.insert(0, SCRIPTS_ROOT)

import portkit_config

importlib.reload(portkit_config)
portkit_config.reload_shared_modules()

from portkit_config import load_config
from ue5.export_common import write_json, write_text

try:
    import unreal
except ImportError:
    unreal = None


def run(config):
    if unreal is None:
        raise RuntimeError(
            "Run export_texture_pack.py inside UE 5.4 Editor Python"
        )
    options = (
        config.get("ue5", {})
        .get("exports", {})
        .get("texture_pack", {})
    )
    source = options.get("asset_root")
    output = options.get("output")
    skip_contains = options.get(
        "skip_contains", ["/Demo/", "_height"]
    )
    if not source or not output:
        raise ValueError(
            "ue5.exports.texture_pack requires asset_root and output"
        )
    if not os.path.isdir(output):
        os.makedirs(output)
    eal = unreal.EditorAssetLibrary
    assets = [
        path.split(".")[0]
        for path in eal.list_assets(
            source, recursive=True, include_folder=False
        )
        if not any(value in path for value in skip_contains)
    ]
    progress = unreal.ScopedSlowTask(
        max(1, len(assets)), "PortKit texture pack export"
    )
    progress.make_dialog_visible()
    report = {
        "textures": [],
        "material_instances": {},
        "failures": [],
    }
    exported = 0
    for path in assets:
        if progress.should_cancel():
            report["failures"].append("CANCELLED - rerun to continue")
            break
        progress.enter_progress_frame(1, path.rsplit("/", 1)[-1])
        asset = unreal.load_asset(path)
        if isinstance(asset, unreal.Texture2D):
            if any(value in asset.get_name() for value in skip_contains):
                continue
            destination = os.path.join(output, asset.get_name() + ".tga")
            if os.path.isfile(destination):
                ok = True
            else:
                task = unreal.AssetExportTask()
                task.object = asset
                task.filename = destination
                task.automated = True
                task.prompt = False
                task.replace_identical = True
                try:
                    task.exporter = unreal.TextureExporterTGA()
                except Exception:
                    pass
                try:
                    ok = bool(
                        unreal.Exporter.run_asset_export_task(task)
                    )
                except Exception:
                    ok = False
            record = {
                "asset": path,
                "file": os.path.basename(destination),
                "ok": bool(ok),
                "size": [
                    asset.blueprint_get_size_x(),
                    asset.blueprint_get_size_y(),
                ],
            }
            report["textures"].append(record)
            if ok:
                exported += 1
            else:
                report["failures"].append("texture " + path)
        elif isinstance(asset, unreal.MaterialInstanceConstant):
            parent = asset.get_editor_property("parent")
            record = {
                "parent": parent.get_name() if parent else None,
                "scalars": {},
                "vectors": {},
                "textures": {},
            }
            for value in asset.get_editor_property(
                "scalar_parameter_values"
            ):
                record["scalars"][str(value.parameter_info.name)] = float(
                    value.parameter_value
                )
            for value in asset.get_editor_property(
                "vector_parameter_values"
            ):
                color = value.parameter_value
                record["vectors"][str(value.parameter_info.name)] = [
                    color.r,
                    color.g,
                    color.b,
                    color.a,
                ]
            for value in asset.get_editor_property(
                "texture_parameter_values"
            ):
                record["textures"][str(value.parameter_info.name)] = (
                    value.parameter_value.get_name()
                    if value.parameter_value
                    else None
                )
            report["material_instances"][path] = record
    write_json(os.path.join(output, "report.json"), report)
    lines = [
        "exported textures: %d" % exported,
        "material instances: %d" % len(report["material_instances"]),
        "failures: %d" % len(report["failures"]),
    ] + report["failures"]
    write_text(os.path.join(output, "report.txt"), "\n".join(lines))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", help="Path to PortKit JSON config")
    args = parser.parse_args()
    config = load_config(args.config)
    try:
        run(config)
    except Exception:
        if unreal is not None:
            output = (
                config.get("ue5", {})
                .get("exports", {})
                .get("texture_pack", {})
                .get("output")
                or os.getcwd()
            )
            write_json(
                os.path.join(output, "report.json"),
                {"errors": [traceback.format_exc()]},
            )
            unreal.log_error("[PortKit] texture pack export failed")
        else:
            raise


if __name__ == "__main__":
    main()
