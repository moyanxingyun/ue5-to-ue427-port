# -*- coding: utf-8 -*-
"""Apply and persist the UE 4.27 texture streaming pool size.

Environment:
    Unreal Engine 4.27 Editor Python 3.7, Cmd mode.

Use:
    py "PATH/TO/PortKit/scripts/tools/set_streaming_pool.py" --config "PATH/TO/config.json"

Output:
    Runtime r.Streaming.PoolSize, RendererSettings in DefaultEngine.ini, an
    automatic .bak of the previous ini and a JSON report.
"""
import argparse
import importlib
import json
import os
import shutil
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


def run(config):
    if unreal is None:
        raise RuntimeError(
            "Run set_streaming_pool.py inside UE 4.27 Editor Python"
        )
    pool = int(
        config.get("tools", {})
        .get("streaming_pool", {})
        .get("megabytes", 6000)
    )
    key = "r.Streaming.PoolSize"
    section = "[/Script/Engine.RendererSettings]"
    unreal.SystemLibrary.execute_console_command(
        None, "%s %d" % (key, pool)
    )
    ini = os.path.join(
        unreal.Paths.convert_relative_path_to_full(
            unreal.Paths.project_config_dir()
        ),
        "DefaultEngine.ini",
    )
    if os.path.isfile(ini):
        shutil.copyfile(ini, ini + ".portkit.bak")
        with open(ini, "r", encoding="utf-8-sig") as handle:
            lines = handle.read().splitlines()
    else:
        lines = []
    result = []
    in_section = False
    found_section = False
    written = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            if in_section and not written:
                result.append("%s=%d" % (key, pool))
                written = True
            in_section = stripped == section
            found_section = found_section or in_section
            result.append(line)
            continue
        if in_section and stripped.startswith(key + "="):
            if not written:
                result.append("%s=%d" % (key, pool))
                written = True
            continue
        result.append(line)
    if in_section and not written:
        result.append("%s=%d" % (key, pool))
    if not found_section:
        result.extend(["", section, "%s=%d" % (key, pool)])
    with open(ini, "w", encoding="utf-8") as handle:
        handle.write("\n".join(result) + "\n")
    payload = {
        "pool_megabytes": pool,
        "actual": unreal.SystemLibrary.get_console_variable_int_value(key),
        "ini": ini,
    }
    with open(
        report_path(config, "streaming_pool.json"), "w", encoding="utf-8"
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
                report_path(config, "streaming_pool.txt"),
                "w",
                encoding="utf-8",
            ) as handle:
                handle.write(traceback.format_exc())
        else:
            raise


if __name__ == "__main__":
    main()
