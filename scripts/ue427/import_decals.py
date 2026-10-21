# -*- coding: utf-8 -*-
"""Import a decal texture pack and rebuild its UE 4.27 decal material.

Environment:
    Unreal Engine 4.27 Editor Python 3.7, Cmd mode.

Use:
    py "PATH/TO/PortKit/scripts/ue427/import_decals.py" --config "PATH/TO/config.json"

Output:
    Textures, one translucent deferred-decal master, one material instance per
    complete texture set, and JSON/TXT reports. The base colour cannot exceed
    MaxColor, preventing large tints from clipping to white.
"""
import argparse
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

from portkit_config import load_config

try:
    import unreal
except ImportError:
    unreal = None


FAIL = []


def tga_has_alpha(filename):
    with open(filename, "rb") as handle:
        header = handle.read(18)
    return len(header) == 18 and header[16] == 32


def link(a, a_out, b, b_ins):
    for b_in in b_ins:
        try:
            if unreal.MaterialEditingLibrary.connect_material_expressions(
                a, a_out, b, b_in
            ):
                return True
        except Exception:
            pass
    FAIL.append(
        "wire %s.%s -> %s.%s"
        % (a.get_name(), a_out, b.get_name(), b_ins)
    )
    return False


def connect_property(source, source_out, prop):
    try:
        if unreal.MaterialEditingLibrary.connect_material_property(
            source, source_out, prop
        ):
            return True
    except Exception:
        pass
    FAIL.append("property %s <- %s" % (prop, source.get_name()))
    return False


def node(material, cls, x, y):
    return unreal.MaterialEditingLibrary.create_material_expression(
        material, cls, x, y
    )


def scalar(material, name, value, x, y):
    result = node(material, unreal.MaterialExpressionScalarParameter, x, y)
    result.set_editor_property("parameter_name", name)
    result.set_editor_property("default_value", value)
    return result


def vector(material, name, value, x, y):
    result = node(material, unreal.MaterialExpressionVectorParameter, x, y)
    result.set_editor_property("parameter_name", name)
    result.set_editor_property("default_value", unreal.LinearColor(*value))
    return result


def multiply(material, left, left_out, right, right_out, x, y):
    result = node(material, unreal.MaterialExpressionMultiply, x, y)
    link(left, left_out, result, ["A"])
    link(right, right_out, result, ["B"])
    return result


def minimum(material, left, right, x, y):
    result = node(material, unreal.MaterialExpressionMin, x, y)
    link(left, "", result, ["A"])
    link(right, "", result, ["B"])
    return result


def texture_parameter(material, name, texture, sampler, x, y):
    result = node(
        material, unreal.MaterialExpressionTextureSampleParameter2D, x, y
    )
    result.set_editor_property("parameter_name", name)
    result.set_editor_property("texture", texture)
    result.set_editor_property("sampler_type", sampler)
    return result


def run(config):
    if unreal is None:
        raise RuntimeError(
            "Run import_decals.py inside UE 4.27 Editor Python"
        )
    options = (
        config.get("ue427", {}).get("imports", {}).get("decals", {})
    )
    source = options.get("input")
    destination = (options.get("destination") or "").rstrip("/")
    if not source or not destination:
        raise ValueError(
            "ue427.imports.decals requires input and destination"
        )
    texture_destination = destination + "/" + options.get(
        "texture_folder", "Textures"
    )
    max_size = int(options.get("max_texture_size", 2048))
    master_name = options.get("master_name", "M_Port_Decal")
    master_path = destination + "/" + master_name
    eal = unreal.EditorAssetLibrary
    mel = unreal.MaterialEditingLibrary
    tools = unreal.AssetToolsHelpers.get_asset_tools()
    files = sorted(
        value
        for value in os.listdir(source)
        if value.lower().endswith(".tga")
    )
    texture_sets = {}
    no_alpha = []
    progress = unreal.ScopedSlowTask(
        max(1, len(files)), "PortKit decal textures"
    )
    progress.make_dialog_visible()
    for filename in files:
        if progress.should_cancel():
            FAIL.append("CANCELLED during textures")
            break
        progress.enter_progress_frame(1, filename)
        name = os.path.splitext(filename)[0]
        asset_path = texture_destination + "/" + name
        if not eal.does_asset_exist(asset_path):
            task = unreal.AssetImportTask()
            task.filename = os.path.join(source, filename)
            task.destination_path = texture_destination
            task.automated = True
            task.replace_existing = True
            task.save = False
            tools.import_asset_tasks([task])
        texture = unreal.load_asset(asset_path)
        if texture is None:
            FAIL.append("texture import " + filename)
            continue
        lower = name.lower()
        if lower.endswith("_normal"):
            kind = "Normal"
            texture.set_editor_property(
                "compression_settings",
                unreal.TextureCompressionSettings.TC_NORMALMAP,
            )
            texture.set_editor_property("srgb", False)
        elif lower.endswith("_rmao"):
            kind = "RMAO"
            texture.set_editor_property(
                "compression_settings",
                unreal.TextureCompressionSettings.TC_MASKS,
            )
            texture.set_editor_property("srgb", False)
        elif lower.endswith("_basecolor"):
            kind = "BaseColor"
            if not tga_has_alpha(os.path.join(source, filename)):
                no_alpha.append(name)
        else:
            continue
        texture.set_editor_property("max_texture_size", max_size)
        eal.save_loaded_asset(texture, False)
        base = name.rsplit("_", 1)[0]
        texture_sets.setdefault(base, {})[kind] = texture
    if not texture_sets:
        raise RuntimeError("No decal texture sets found in " + source)
    if eal.does_asset_exist(master_path):
        material = unreal.load_asset(master_path)
        if options.get("rebuild_existing", False):
            mel.delete_all_material_expressions(material)
        else:
            material = None
    else:
        material = tools.create_asset(
            master_name,
            destination,
            unreal.Material,
            unreal.MaterialFactoryNew(),
        )
    if material is not None:
        material.set_editor_property(
            "material_domain", unreal.MaterialDomain.MD_DEFERRED_DECAL
        )
        material.set_editor_property(
            "blend_mode", unreal.BlendMode.BLEND_TRANSLUCENT
        )
        material.set_editor_property(
            "decal_blend_mode", unreal.DecalBlendMode.DBM_TRANSLUCENT
        )
        first = next(
            value
            for value in texture_sets.values()
            if {"BaseColor", "Normal", "RMAO"} <= set(value)
        )
        sampler = unreal.MaterialSamplerType
        base = texture_parameter(
            material,
            "BaseColor",
            first["BaseColor"],
            sampler.SAMPLERTYPE_COLOR,
            -1400,
            -300,
        )
        normal = texture_parameter(
            material,
            "Normal",
            first["Normal"],
            sampler.SAMPLERTYPE_NORMAL,
            -1400,
            200,
        )
        rmao = texture_parameter(
            material,
            "RMAO",
            first["RMAO"],
            sampler.SAMPLERTYPE_MASKS,
            -1400,
            550,
        )
        average = options.get(
            "average_color", [0.07, 0.057, 0.04]
        )
        contrast = node(
            material, unreal.MaterialExpressionLinearInterpolate, -950, -450
        )
        link(
            vector(
                material,
                "AvgColor",
                list(average) + [1.0],
                -1400,
                -750,
            ),
            "",
            contrast,
            ["A"],
        )
        link(base, "RGB", contrast, ["B"])
        link(
            scalar(
                material,
                "Contrast",
                float(options.get("default_contrast", 0.6)),
                -1100,
                -500,
            ),
            "",
            contrast,
            ["Alpha"],
        )
        tinted = multiply(
            material,
            contrast,
            "",
            vector(material, "Tint", [1, 1, 1, 1], -950, -200),
            "RGB",
            -650,
            -400,
        )
        bright = multiply(
            material,
            tinted,
            "",
            scalar(material, "Brightness", 1.0, -700, -100),
            "",
            -400,
            -300,
        )
        max_color = vector(
            material,
            "MaxColor",
            [0.25, 0.22, 0.18, 1.0],
            -400,
            -100,
        )
        final_color = minimum(material, bright, max_color, -150, -300)
        connect_property(
            final_color, "", unreal.MaterialProperty.MP_BASE_COLOR
        )
        opacity = multiply(
            material,
            base,
            "A",
            scalar(material, "Opacity", 1.0, -700, 150),
            "",
            -400,
            100,
        )
        connect_property(opacity, "", unreal.MaterialProperty.MP_OPACITY)
        normal_xy = node(
            material, unreal.MaterialExpressionComponentMask, -900, 250
        )
        for channel in ("r", "g", "b", "a"):
            normal_xy.set_editor_property(channel, channel in ("r", "g"))
        link(normal, "RGB", normal_xy, [""])
        normal_scaled = multiply(
            material,
            normal_xy,
            "",
            scalar(material, "NormalStrength", 1.0, -900, 400),
            "",
            -650,
            250,
        )
        normal_out = node(
            material, unreal.MaterialExpressionAppendVector, -400, 300
        )
        link(normal_scaled, "", normal_out, ["A"])
        link(normal, "B", normal_out, ["B"])
        connect_property(
            normal_out, "", unreal.MaterialProperty.MP_NORMAL
        )
        roughness = multiply(
            material,
            rmao,
            "R",
            scalar(material, "RoughnessMul", 1.0, -900, 700),
            "",
            -500,
            600,
        )
        connect_property(
            roughness, "", unreal.MaterialProperty.MP_ROUGHNESS
        )
        connect_property(
            rmao, "G", unreal.MaterialProperty.MP_METALLIC
        )
        mel.recompile_material(material)
        eal.save_loaded_asset(material, False)
    instances = []
    for base_name, textures in sorted(texture_sets.items()):
        if "BaseColor" not in textures:
            continue
        short = base_name.replace("T_Decal_", "").replace("T_", "")
        name = "MI_Port_" + short
        path = destination + "/" + name
        if eal.does_asset_exist(path):
            instance = unreal.load_asset(path)
            if not options.get("rebuild_existing", False):
                instances.append(name)
                continue
        else:
            instance = tools.create_asset(
                name,
                destination,
                unreal.MaterialInstanceConstant,
                unreal.MaterialInstanceConstantFactoryNew(),
            )
        mel.set_material_instance_parent(instance, material)
        for parameter, texture in textures.items():
            mel.set_material_instance_texture_parameter_value(
                instance, parameter, texture
            )
        mel.update_material_instance(instance)
        eal.save_loaded_asset(instance, False)
        instances.append(name)
    counts = {
        "textures": len(files),
        "texture_sets": len(texture_sets),
        "decal_instances": len(instances),
        "connections_failed": len(FAIL),
        "basecolor_without_alpha": len(no_alpha),
    }
    report_dir = options.get(
        "report_dir", os.path.join(source, "reports")
    )
    if not os.path.isdir(report_dir):
        os.makedirs(report_dir)
    payload = {
        "counts": counts,
        "instances": instances,
        "basecolor_without_alpha": no_alpha,
        "failures": FAIL,
    }
    with open(
        os.path.join(report_dir, "import_decals.json"),
        "w",
        encoding="utf-8",
    ) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    with open(
        os.path.join(report_dir, "import_decals.txt"),
        "w",
        encoding="utf-8",
    ) as handle:
        handle.write(
            json.dumps(counts, ensure_ascii=False, indent=2)
            + "\n\nFAILURES\n"
            + "\n".join(FAIL)
        )
    return payload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", help="Path to PortKit JSON config")
    args = parser.parse_args()
    config = load_config(args.config)
    try:
        run(config)
    except Exception:
        options = (
            config.get("ue427", {})
            .get("imports", {})
            .get("decals", {})
        )
        report_dir = options.get("report_dir") or os.getcwd()
        if not os.path.isdir(report_dir):
            os.makedirs(report_dir)
        with open(
            os.path.join(report_dir, "import_decals.txt"),
            "w",
            encoding="utf-8",
        ) as handle:
            handle.write("ERROR\n" + traceback.format_exc())
        if unreal is not None:
            unreal.log_error(
                "[PortKit] import_decals failed\n" + traceback.format_exc()
            )
        else:
            raise


if __name__ == "__main__":
    main()
