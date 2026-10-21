# -*- coding: utf-8 -*-
"""Read-only diagnosis of global LOD settings and meshes used in the level.

Environment:
    Unreal Engine 4.27 Editor Python 3.7, Cmd mode.

Use:
    py "PATH/TO/PortKit/scripts/tools/diag_lod.py" --config "PATH/TO/config.json"

Output:
    paths.reports/diag_lod.json/txt. Meshes are flagged EARLY when LOD1 starts
    at screen size >= 0.5; forced and minimum LOD usage is also reported.
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


CVARS = [
    "sg.ViewDistanceQuality",
    "sg.TextureQuality",
    "sg.FoliageQuality",
    "sg.ShadowQuality",
    "sg.ResolutionQuality",
    "r.StaticMeshLODDistanceScale",
    "r.ViewDistanceScale",
    "r.ForceLOD",
    "r.ForceLODShadow",
    "r.MipMapLODBias",
    "r.ScreenPercentage",
    "foliage.LODDistanceScale",
    "foliage.ForceLOD",
    "r.Streaming.PoolSize",
    "r.Streaming.MipBias",
    "r.SkeletalMeshLODBias",
]


def safe(function, *args):
    try:
        return function(*args)
    except Exception as exc:
        return "ERROR: %s" % exc


def run(config):
    if unreal is None:
        raise RuntimeError("Run diag_lod.py inside UE 4.27 Editor Python")
    system_library = unreal.SystemLibrary
    mesh_library = unreal.EditorStaticMeshLibrary
    cvars = {
        key: safe(system_library.get_console_variable_float_value, key)
        for key in CVARS
    }
    usage = {}
    for actor in unreal.EditorLevelLibrary.get_all_level_actors():
        for component in actor.get_components_by_class(
            unreal.StaticMeshComponent
        ):
            mesh = component.get_editor_property("static_mesh")
            if mesh is None:
                continue
            entry = usage.setdefault(
                mesh.get_path_name(),
                {"mesh": mesh, "components": 0, "forced_components": 0},
            )
            entry["components"] += 1
            if component.get_editor_property("forced_lod_model") > 0:
                entry["forced_components"] += 1
    rows = []
    for path, entry in sorted(usage.items()):
        mesh = entry["mesh"]
        count = safe(mesh_library.get_lod_count, mesh)
        sizes = list(safe(mesh_library.get_lod_screen_sizes, mesh) or [])
        auto = safe(
            mesh.get_editor_property, "auto_compute_lod_screen_size"
        )
        group = str(safe(mesh.get_editor_property, "lod_group"))
        minimum = safe(mesh.get_editor_property, "min_lod")
        if not isinstance(minimum, str):
            minimum = safe(minimum.get_editor_property, "default")
        early = bool(count > 1 and len(sizes) > 1 and sizes[1] >= 0.5)
        rows.append(
            {
                "path": path,
                "lod_count": count,
                "screen_sizes": [round(value, 3) for value in sizes],
                "auto_compute": auto,
                "lod_group": group,
                "min_lod": minimum,
                "forced_components": entry["forced_components"],
                "components": entry["components"],
                "early": early,
            }
        )
    payload = {
        "cvars": cvars,
        "summary": {
            "meshes": len(rows),
            "with_lods": sum(1 for row in rows if row["lod_count"] > 1),
            "early": sum(1 for row in rows if row["early"]),
            "min_lod_gt_zero": sum(
                1
                for row in rows
                if isinstance(row["min_lod"], int) and row["min_lod"] > 0
            ),
            "forced_components": sum(
                row["forced_components"] for row in rows
            ),
        },
        "meshes": rows,
    }
    with open(
        report_path(config, "diag_lod.json"), "w", encoding="utf-8"
    ) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    lines = ["global settings"]
    for key, value in cvars.items():
        lines.append("%-34s %s" % (key, value))
    lines.extend(
        [
            "",
            "meshes=%d lods=%d EARLY=%d min_lod>0=%d forced_components=%d"
            % (
                payload["summary"]["meshes"],
                payload["summary"]["with_lods"],
                payload["summary"]["early"],
                payload["summary"]["min_lod_gt_zero"],
                payload["summary"]["forced_components"],
            ),
        ]
    )
    for row in rows:
        if row["early"] or row["forced_components"]:
            lines.append(
                "%s %s LODs=%d sizes=%s"
                % (
                    "EARLY" if row["early"] else "     ",
                    row["path"],
                    row["lod_count"],
                    row["screen_sizes"],
                )
            )
    with open(
        report_path(config, "diag_lod.txt"), "w", encoding="utf-8"
    ) as handle:
        handle.write("\n".join(lines))
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
                report_path(config, "diag_lod.txt"), "w", encoding="utf-8"
            ) as handle:
                handle.write(traceback.format_exc())
        else:
            raise


if __name__ == "__main__":
    main()
