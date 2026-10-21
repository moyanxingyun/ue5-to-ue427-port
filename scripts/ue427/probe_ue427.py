# -*- coding: utf-8 -*-
"""Probe UE 4.27 material APIs, createable expression classes and graph stats.

Environment:
    Unreal Engine 4.27 Editor Python 3.7, Cmd mode.

Use:
    py "PATH/TO/PortKit/scripts/ue427/probe_ue427.py" --config "PATH/TO/config.json"

Output:
    paths.probe_427 JSON, including createable_classes, pin names, enum members,
    material node-type counts and static-switch combination count. The temporary
    Unreal folder configured for the probe is deleted afterwards.
"""
import argparse
import collections
import importlib
import json
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

from portkit_config import load_config, path_value, write_json
from material_transplant.planner import plan
from material_transplant.t3d_parser import load_graphs, switch_params

try:
    import unreal
except ImportError:
    unreal = None


def safe(function):
    try:
        return function()
    except Exception as exc:
        return {"error": repr(exc)}


def run(config):
    if unreal is None:
        raise RuntimeError("Run probe_ue427.py inside UE 4.27 Editor Python")
    output = path_value(config, "paths", "probe_427")
    temp = config.get("ue427", {}).get(
        "probe_temp_folder", "/Game/_PortKit_Probe"
    )
    folder = temp.rsplit("/", 1)[-1]
    eal = unreal.EditorAssetLibrary
    mel = unreal.MaterialEditingLibrary
    tools = unreal.AssetToolsHelpers.get_asset_tools()
    result = {
        "ue_version": [
            unreal.SystemLibrary.get_engine_version()
            if hasattr(unreal.SystemLibrary, "get_engine_version")
            else "4.27"
        ],
        "mel_functions": [
            name for name in dir(mel) if not name.startswith("_")
        ],
        "engine_functions": {},
        "inputs": {},
        "outputs": {},
        "misc": {},
        "createable_classes": [],
        "graph_stats": {},
    }
    probe_config = config.get("ue427", {}).get("probe", {})
    for path in probe_config.get("engine_functions", []):
        result["engine_functions"][path] = eal.does_asset_exist(path)
    function = tools.create_asset(
        "MF_PortKitProbe",
        temp,
        unreal.MaterialFunction,
        unreal.MaterialFunctionFactoryNew(),
    )

    def create(cls, x=0, y=0):
        return mel.create_material_expression_in_function(
            function, cls, x, y
        )

    source = create(unreal.MaterialExpressionConstant)
    candidates = probe_config.get("test_classes") or [
        name
        for name in dir(unreal)
        if name.startswith("MaterialExpression")
    ]
    progress = unreal.ScopedSlowTask(
        max(1, len(candidates)), "PortKit UE 4.27 capability probe"
    )
    progress.make_dialog_visible()
    for name in sorted(set(candidates)):
        if progress.should_cancel():
            break
        progress.enter_progress_frame(1, name)
        cls = getattr(unreal, name, None)
        if cls is None:
            continue
        try:
            create(cls)
            result["createable_classes"].append(name)
        except Exception:
            pass
    pin_tests = probe_config.get(
        "pin_tests",
        [
            ["MaterialExpressionTextureSample", "Coordinates", ["UVs", "Coordinates", "Coordinate"]],
            ["MaterialExpressionPower", "Base", ["Base", ""]],
            ["MaterialExpressionPower", "Exponent", ["Exp", "Exponent"]],
            ["MaterialExpressionStaticSwitch", "A", ["True", "A"]],
            ["MaterialExpressionStaticSwitch", "B", ["False", "B"]],
            ["MaterialExpressionLinearInterpolate", "Alpha", ["Alpha"]],
            ["MaterialExpressionFunctionOutput", "A", ["", "A"]],
            ["MaterialExpressionParameter", "Input", ["", "Input"]],
        ],
    )
    for cls_name, prop, pins in pin_tests:
        cls = getattr(unreal, cls_name, None)
        if cls is None:
            continue
        target = create(cls)
        accepted = []
        for pin in pins:
            try:
                if mel.connect_material_expressions(
                    source, "", target, pin
                ):
                    accepted.append(pin)
            except Exception as exc:
                accepted.append("ERR:" + repr(exc))
        result["inputs"][cls_name + "." + prop] = accepted
    result["misc"]["mat_props"] = safe(
        lambda: {
            prop: str(
                unreal.MaterialFactoryNew()
                .get_default_object()
                .get_editor_property(prop)
            )
            for prop in ("use_material_attributes",)
        }
    )
    result["misc"]["world_position_offset_property"] = next(
        (
            name
            for name in dir(unreal.MaterialProperty)
            if "WORLD" in name.upper() and "OFFSET" in name.upper()
        ),
        None,
    )
    try:
        dumps_dir = path_value(config, "paths", "dumps")
        graphs = load_graphs(dumps_dir)
        materials_json = path_value(config, "paths", "materials_json")
        combo_count = 0
        if materials_json and os.path.isfile(materials_json):
            with open(materials_json, "r", encoding="utf-8") as handle:
                infos = json.load(handle)
            material = config.get("material", {})
            combo_count = len(
                plan(
                    graphs,
                    infos,
                    material.get("master_name"),
                    material.get("func_dir"),
                )["combos"]
            )
        else:
            for nodes in graphs.values():
                values = switch_params(nodes)
                if values:
                    combo_count += 1
        result["graph_stats"] = {
            "graphs": {
                name: dict(
                    sorted(
                        collections.Counter(
                            node["cls"] for node in nodes.values()
                        ).items()
                    )
                )
                for name, nodes in graphs.items()
            },
            "switch_combination_count": combo_count,
        }
    except Exception:
        result["misc"]["graph_stats_error"] = traceback.format_exc()
    mel.update_material_function(function)
    write_json(output, result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", help="Path to PortKit JSON config")
    args = parser.parse_args()
    config = load_config(args.config)
    temp = config.get("ue427", {}).get(
        "probe_temp_folder", "/Game/_PortKit_Probe"
    )
    try:
        run(config)
    except Exception:
        write_json(
            path_value(config, "paths", "probe_427"),
            {"errors": [traceback.format_exc()]},
        )
        if unreal is not None:
            unreal.log_error("[PortKit] UE 4.27 probe failed")
        else:
            raise
    finally:
        if unreal is not None:
            try:
                unreal.EditorAssetLibrary.delete_directory(temp)
            except Exception:
                pass


if __name__ == "__main__":
    main()
