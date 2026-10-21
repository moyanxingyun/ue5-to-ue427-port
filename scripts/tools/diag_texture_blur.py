# -*- coding: utf-8 -*-
"""Read-only diagnosis of texture streaming settings for the current selection.

Environment:
    Unreal Engine 4.27 Editor Python 3.7. Select a mesh/material/actor first.

Use:
    py "PATH/TO/PortKit/scripts/tools/diag_texture_blur.py" --config "PATH/TO/config.json"

Output:
    paths.reports/texture_blur.json with active CVars and texture settings.
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


INT_CVARS = [
    "r.Streaming.PoolSize",
    "sg.TextureQuality",
    "r.Streaming.FullyLoadUsedTextures",
    "r.TextureStreaming",
    "r.Streaming.UseFixedPoolSize",
    "r.Streaming.LimitPoolSizeToVRAM",
    "r.Streaming.DropMips",
    "r.MaxAnisotropy",
]
FLOAT_CVARS = [
    "r.Streaming.MipBias",
    "r.Streaming.Boost",
    "r.MipMapLODBias",
]


def safe(function, *args):
    try:
        return function(*args)
    except Exception as exc:
        return "ERROR: %s" % exc


def texture_info(texture):
    result = {
        "path": texture.get_path_name().split(".")[0],
        "size": [
            safe(texture.blueprint_get_size_x),
            safe(texture.blueprint_get_size_y),
        ],
    }
    for name in (
        "max_texture_size",
        "lod_bias",
        "lod_group",
        "never_stream",
        "mip_gen_settings",
        "compression_settings",
        "srgb",
        "virtual_texture_streaming",
        "num_cinematic_mip_levels",
    ):
        value = safe(texture.get_editor_property, name)
        result[name] = (
            value
            if isinstance(value, (bool, int, float, str))
            else str(value)
        )
    return result


def materials_of(obj):
    if isinstance(obj, unreal.StaticMesh):
        return [
            slot.material_interface
            for slot in obj.get_editor_property("static_materials")
            if slot.material_interface
        ]
    if isinstance(obj, unreal.MaterialInterface):
        return [obj]
    if isinstance(obj, unreal.Actor):
        result = []
        for component in obj.get_components_by_class(
            unreal.MeshComponent
        ):
            result.extend(
                component.get_material(index)
                for index in range(component.get_num_materials())
                if component.get_material(index)
            )
        return result
    return []


def run(config):
    if unreal is None:
        raise RuntimeError(
            "Run diag_texture_blur.py inside UE 4.27 Editor Python"
        )
    system_library = unreal.SystemLibrary
    cvars = {}
    for key in INT_CVARS:
        cvars[key] = safe(
            system_library.get_console_variable_int_value, key
        )
    for key in FLOAT_CVARS:
        cvars[key] = safe(
            system_library.get_console_variable_float_value, key
        )
    objects = list(unreal.EditorUtilityLibrary.get_selected_assets()) + list(
        unreal.EditorLevelLibrary.get_selected_level_actors()
    )
    selection = {}
    for obj in objects:
        materials = {}
        for material in materials_of(obj):
            textures = safe(
                unreal.MaterialEditingLibrary.get_used_textures, material
            )
            materials[material.get_name()] = (
                [texture_info(texture) for texture in textures if texture]
                if isinstance(textures, (list, tuple))
                else str(textures)
            )
        selection[obj.get_name()] = materials
    payload = {
        "cvars": cvars,
        "selection": selection,
        "note": None if objects else "nothing selected",
    }
    with open(
        report_path(config, "texture_blur.json"),
        "w",
        encoding="utf-8",
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
                report_path(config, "texture_blur.txt"),
                "w",
                encoding="utf-8",
            ) as handle:
                handle.write(traceback.format_exc())
        else:
            raise


if __name__ == "__main__":
    main()
