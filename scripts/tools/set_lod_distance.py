# -*- coding: utf-8 -*-
"""Set editor LOD-distance CVars and persist them in DefaultEngine.ini.

Environment:
    Unreal Engine 4.27 Editor Python 3.7, Cmd mode.

Use:
    py "PATH/TO/PortKit/scripts/tools/set_lod_distance.py" --config "PATH/TO/config.json"

Output:
    Runtime CVars plus [SystemSettings] values in DefaultEngine.ini, with a
    portable JSON report. Use scale 1.0 and foliage 1.0 to undo.
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


def _write_ini(ini, values):
    lines = []
    if os.path.isfile(ini):
        with open(ini, "r", encoding="utf-8-sig") as handle:
            lines = handle.read().splitlines()
    section_index = None
    for index, line in enumerate(lines):
        if line.strip() == "[SystemSettings]":
            section_index = index
        if any(line.strip().startswith(key + "=") for key in values):
            lines[index] = ""
    if section_index is None:
        lines.extend(["", "[SystemSettings]"])
        section_index = len(lines) - 1
    insert_at = section_index + 1
    for key, value in sorted(values.items()):
        lines.insert(insert_at, "%s=%s" % (key, value))
        insert_at += 1
    with open(ini, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def run(config):
    if unreal is None:
        raise RuntimeError(
            "Run set_lod_distance.py inside UE 4.27 Editor Python"
        )
    options = config.get("tools", {}).get("lod_distance", {})
    values = {
        "r.StaticMeshLODDistanceScale": options.get("static_scale", 0.35),
        "foliage.LODDistanceScale": options.get("foliage_scale", 2.5),
    }
    for key, value in values.items():
        unreal.SystemLibrary.execute_console_command(
            None, "%s %s" % (key, value)
        )
    config_dir = unreal.Paths.convert_relative_path_to_full(
        unreal.Paths.project_config_dir()
    )
    ini = os.path.join(config_dir, "DefaultEngine.ini")
    _write_ini(ini, values)
    payload = {
        "values": values,
        "ini": ini,
        "applied_now": {
            key: unreal.SystemLibrary.get_console_variable_float_value(key)
            for key in values
        },
    }
    with open(
        report_path(config, "lod_distance.json"), "w", encoding="utf-8"
    ) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
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
                report_path(config, "lod_distance.txt"),
                "w",
                encoding="utf-8",
            ) as handle:
                handle.write(traceback.format_exc())
        else:
            raise


if __name__ == "__main__":
    main()
