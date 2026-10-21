# -*- coding: utf-8 -*-
"""Match selected material instances to a reference material's average color.

Environment:
    Unreal Engine 4.27 Editor Python 3.7, Cmd mode.

Use:
    py "PATH/TO/PortKit/scripts/tools/match_color.py" --config "PATH/TO/config.json"

Output:
    Per-instance Tint and Brightness values, plus JSON/TXT report. Set
    tools.match_color.mode to "restore" to reset Tint=1 and Brightness=1.
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


def srgb_to_linear(value):
    value /= 255.0
    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4


def tga_average(filename, step=7):
    with open(filename, "rb") as handle:
        data = handle.read()
    id_length = data[0]
    image_type = data[2]
    bytes_per_pixel = data[16] // 8
    width = data[12] | data[13] << 8
    height = data[14] | data[15] << 8
    offset = 18 + id_length
    pixels = bytearray()
    if image_type == 2:
        pixels = data[offset : offset + width * height * bytes_per_pixel]
    elif image_type == 10:
        index = offset
        needed = width * height * bytes_per_pixel
        while len(pixels) < needed:
            header = data[index]
            index += 1
            count = (header & 0x7F) + 1
            if header & 0x80:
                pixels += data[index : index + bytes_per_pixel] * count
                index += bytes_per_pixel
            else:
                pixels += data[index : index + bytes_per_pixel * count]
                index += bytes_per_pixel * count
    else:
        raise ValueError("Unsupported TGA type %d" % image_type)
    lookup = [srgb_to_linear(value) for value in range(256)]
    totals = [0.0, 0.0, 0.0]
    samples = 0
    for pixel in range(0, width * height, step):
        index = pixel * bytes_per_pixel
        totals[0] += lookup[pixels[index + 2]]
        totals[1] += lookup[pixels[index + 1]]
        totals[2] += lookup[pixels[index]]
        samples += 1
    return [value / samples for value in totals]


def export_average(texture, output):
    task = unreal.AssetExportTask()
    task.object = texture
    task.filename = output
    task.automated = True
    task.prompt = False
    task.replace_identical = True
    task.exporter = unreal.TextureExporterTGA()
    if not unreal.Exporter.run_asset_export_task(task):
        raise RuntimeError("TGA export failed: " + texture.get_name())
    return tga_average(output)


def _default_parameter(method, material, name):
    try:
        return method(material, name)
    except Exception:
        return None


def run(config):
    if unreal is None:
        raise RuntimeError("Run match_color.py inside UE 4.27 Editor Python")
    options = config.get("tools", {}).get("match_color", {})
    mode = str(options.get("mode", "apply")).lower()
    target_folder = options.get("target_folder")
    reference_path = options.get("reference_material")
    if not target_folder:
        raise ValueError("tools.match_color.target_folder is required")
    mel = unreal.MaterialEditingLibrary
    eal = unreal.EditorAssetLibrary
    temp_file = options.get(
        "temp_tga",
        report_path(config, "_match_color_tmp.tga"),
    )
    max_tint = float(options.get("max_tint", 8.0))
    darkness = options.get("darkness", {"": 0.9})
    target_averages = options.get("target_averages", {})
    sand = None
    if mode != "restore":
        if not reference_path:
            raise ValueError(
                "tools.match_color.reference_material is required"
            )
        reference = unreal.load_asset(reference_path)
        texture = _default_parameter(
            mel.get_material_default_texture_parameter_value,
            reference,
            options.get(
                "reference_texture_parameter", "BaseColor"
            ),
        )
        if texture is None:
            raise RuntimeError("Reference material texture not found")
        sand = export_average(texture, temp_file)
        for parameter, factor in options.get(
            "reference_vector_multipliers", {}
        ).items():
            color = _default_parameter(
                mel.get_material_default_vector_parameter_value,
                reference,
                parameter,
            )
            if color is not None:
                sand = [
                    sand[index] * getattr(color, "rgba"[index]) * factor
                    for index in range(3)
                ]
        for parameter, factor in options.get(
            "reference_scalar_multipliers", {}
        ).items():
            value = _default_parameter(
                mel.get_material_default_scalar_parameter_value,
                reference,
                parameter,
            )
            if value is not None:
                sand = [component * value * factor for component in sand]
    prefix = options.get("instance_prefix", "MI_")
    tint_name = options.get("tint_parameter", "Tint")
    brightness_name = options.get("brightness_parameter", "Brightness")
    texture_name = options.get("target_texture_parameter", "BaseColor")
    assets = [
        path.split(".")[0]
        for path in eal.list_assets(
            target_folder, recursive=False, include_folder=False
        )
        if path.rsplit("/", 1)[-1].split(".")[0].startswith(prefix)
    ]
    rows = []
    failures = []
    progress = unreal.ScopedSlowTask(
        max(1, len(assets)), "PortKit match color"
    )
    progress.make_dialog_visible()
    for path in assets:
        if progress.should_cancel():
            failures.append("CANCELLED")
            break
        name = path.rsplit("/", 1)[-1]
        progress.enter_progress_frame(1, name)
        instance = unreal.load_asset(path)
        if instance is None:
            failures.append("missing instance " + path)
            continue
        if mode == "restore":
            tint = (1.0, 1.0, 1.0)
        else:
            key = name[len(prefix) :] if name.startswith(prefix) else name
            average = target_averages.get(key)
            if average is None:
                texture = _default_parameter(
                    mel.get_material_instance_texture_parameter_value,
                    instance,
                    texture_name,
                )
                if texture is None:
                    failures.append("no target texture " + name)
                    continue
                average = export_average(texture, temp_file)
            dark = next(
                (
                    value
                    for token, value in darkness.items()
                    if token and token in key
                ),
                darkness.get("", 0.9),
            )
            tint = tuple(
                min(max_tint, sand[index] * dark / max(average[index], 1e-6))
                for index in range(3)
            )
        mel.set_material_instance_vector_parameter_value(
            instance,
            tint_name,
            unreal.LinearColor(tint[0], tint[1], tint[2], 1.0),
        )
        mel.set_material_instance_scalar_parameter_value(
            instance, brightness_name, 1.0
        )
        mel.update_material_instance(instance)
        eal.save_loaded_asset(instance, False)
        rows.append(
            {
                "instance": name,
                "tint": [round(value, 4) for value in tint],
            }
        )
    if os.path.isfile(temp_file):
        os.remove(temp_file)
    payload = {
        "mode": mode,
        "reference_average": sand,
        "instances": len(rows),
        "rows": rows,
        "failures": failures,
    }
    with open(
        report_path(config, "match_color.json"), "w", encoding="utf-8"
    ) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    with open(
        report_path(config, "match_color.txt"), "w", encoding="utf-8"
    ) as handle:
        handle.write(
            json.dumps(payload, ensure_ascii=False, indent=2)
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
        if unreal is not None:
            import traceback

            with open(
                report_path(config, "match_color.txt"),
                "w",
                encoding="utf-8",
            ) as handle:
                handle.write(traceback.format_exc())
        else:
            raise


if __name__ == "__main__":
    main()
