# -*- coding: utf-8 -*-
"""Inspect selected Content Browser assets and level actors without changing them.

Environment:
    Unreal Engine 4.27 Editor Python 3.7.

Use:
    py "PATH/TO/PortKit/scripts/tools/inspect_selected.py" --config "PATH/TO/config.json"

Output:
    paths.reports/selected.json with object classes, properties, transforms,
    components, materials and supported material parameters.
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


def json_value(value):
    if isinstance(value, (bool, int, float, str)) or value is None:
        return value
    if hasattr(value, "x") and hasattr(value, "y"):
        result = {"x": value.x, "y": value.y}
        if hasattr(value, "z"):
            result["z"] = value.z
        return result
    return str(value)


def describe(obj):
    result = {
        "name": obj.get_name(),
        "class": obj.get_class().get_name()
        if hasattr(obj, "get_class")
        else type(obj).__name__,
    }
    if isinstance(obj, unreal.Actor):
        result["label"] = obj.get_actor_label()
        result["folder"] = str(obj.get_folder_path())
        result["transform"] = json_value(obj.get_actor_transform())
        result["components"] = []
        for component in obj.get_components_by_class(unreal.ActorComponent):
            result["components"].append(
                {
                    "name": component.get_name(),
                    "class": component.get_class().get_name(),
                }
            )
    else:
        result["path"] = obj.get_path_name().split(".")[0]
    if isinstance(obj, unreal.MaterialInterface):
        for group, getter in (
            ("scalars", unreal.MaterialEditingLibrary.get_scalar_parameter_names),
            ("vectors", unreal.MaterialEditingLibrary.get_vector_parameter_names),
            ("textures", unreal.MaterialEditingLibrary.get_texture_parameter_names),
            (
                "switches",
                getattr(
                    unreal.MaterialEditingLibrary,
                    "get_static_switch_parameter_names",
                    None,
                ),
            ),
        ):
            if getter is None:
                continue
            try:
                result[group] = sorted(str(value) for value in getter(obj))
            except Exception:
                result[group] = []
    if isinstance(obj, unreal.StaticMesh):
        result["materials"] = [
            {
                "slot": str(slot.material_slot_name),
                "interface": (
                    slot.material_interface.get_path_name()
                    if slot.material_interface
                    else None
                ),
            }
            for slot in obj.get_editor_property("static_materials")
        ]
    return result


def run(config):
    if unreal is None:
        raise RuntimeError(
            "Run inspect_selected.py inside UE 4.27 Editor Python"
        )
    objects = list(unreal.EditorUtilityLibrary.get_selected_assets()) + list(
        unreal.EditorLevelLibrary.get_selected_level_actors()
    )
    payload = {
        "selected": [describe(obj) for obj in objects],
        "note": None if objects else "nothing selected",
    }
    with open(
        report_path(config, "selected.json"), "w", encoding="utf-8"
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
                report_path(config, "selected.txt"),
                "w",
                encoding="utf-8",
            ) as handle:
                handle.write(traceback.format_exc())
        else:
            raise


if __name__ == "__main__":
    main()
