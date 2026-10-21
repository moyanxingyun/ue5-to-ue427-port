# -*- coding: utf-8 -*-
"""Shared read-only UE5 export helpers used by PortKit scripts."""
import json
import os
import traceback

try:
    import unreal
except ImportError:
    unreal = None


def safe(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except Exception:
        return None


def asset_path(asset):
    return asset.get_path_name().split(".")[0] if asset else ""


def class_name(asset_data):
    try:
        return str(asset_data.asset_class_path.asset_name)
    except Exception:
        return str(asset_data.asset_class)


def str_prop(obj, name):
    value = safe(obj.get_editor_property, name)
    if isinstance(value, (bool, int, float, str)):
        return value
    return str(value) if value is not None else None


def run_export(obj, filename, options=None):
    task = unreal.AssetExportTask()
    task.object = obj
    task.filename = filename
    task.automated = True
    task.prompt = False
    task.replace_identical = True
    if options is not None:
        task.options = options
    return bool(unreal.Exporter.run_asset_export_task(task))


def material_info(mat):
    mel = unreal.MaterialEditingLibrary
    info = {
        "path": asset_path(mat),
        "parents": [],
        "base": {},
        "overrides": {},
        "scalars": {},
        "vectors": {},
        "textures": {},
        "switches": {},
    }
    parent = mat
    while isinstance(parent, unreal.MaterialInstance):
        parent = safe(parent.get_editor_property, "parent")
        if parent is None:
            break
        info["parents"].append(asset_path(parent))
    base = (
        safe(mat.get_base_material)
        if isinstance(mat, unreal.MaterialInstance)
        else mat
    )
    if base is not None:
        for prop in (
            "blend_mode",
            "shading_model",
            "two_sided",
            "opacity_mask_clip_value",
            "use_material_attributes",
            "material_domain",
        ):
            info["base"][prop] = str_prop(base, prop)
    if isinstance(mat, unreal.MaterialInstance):
        overrides = safe(mat.get_editor_property, "base_property_overrides")
        if overrides is not None:
            for prop in (
                "override_blend_mode",
                "blend_mode",
                "override_two_sided",
                "two_sided",
                "override_opacity_mask_clip_value",
                "opacity_mask_clip_value",
            ):
                info["overrides"][prop] = str_prop(overrides, prop)
        for name in safe(mel.get_scalar_parameter_names, mat) or []:
            info["scalars"][str(name)] = safe(
                mel.get_material_instance_scalar_parameter_value, mat, name
            )
        for name in safe(mel.get_vector_parameter_names, mat) or []:
            color = safe(
                mel.get_material_instance_vector_parameter_value, mat, name
            )
            info["vectors"][str(name)] = (
                [color.r, color.g, color.b, color.a]
                if color is not None
                else None
            )
        for name in safe(mel.get_texture_parameter_names, mat) or []:
            texture = safe(
                mel.get_material_instance_texture_parameter_value, mat, name
            )
            info["textures"][str(name)] = asset_path(texture)
        for name in safe(mel.get_static_switch_parameter_names, mat) or []:
            info["switches"][str(name)] = safe(
                mel.get_material_instance_static_switch_parameter_value,
                mat,
                name,
            )
    if not info["textures"] and base is not None:
        for texture in safe(mel.get_used_textures, base) or []:
            if texture is not None:
                info["textures"]["used_" + texture.get_name()] = asset_path(
                    texture
                )
    return info


def texture_record(texture, filename):
    return {
        "file": filename,
        "srgb": bool(texture.get_editor_property("srgb")),
        "compression": str(
            texture.get_editor_property("compression_settings")
        ),
        "lod_group": str(texture.get_editor_property("lod_group")),
        "flip_green": bool(
            safe(texture.get_editor_property, "flip_green_channel")
        ),
        "size": [
            safe(texture.blueprint_get_size_x) or 0,
            safe(texture.blueprint_get_size_y) or 0,
        ],
    }


def export_texture(texture, texture_dir, used_names, manual_texture_map=None):
    name = texture.get_name()
    path = asset_path(texture)
    if name in used_names and used_names[name] != path:
        suffix = 2
        while "%s__%d" % (name, suffix) in used_names:
            suffix += 1
        name = "%s__%d" % (name, suffix)
    used_names[name] = path
    for extension in (".png", ".tga", ".exr"):
        filename = name + extension
        output = os.path.join(texture_dir, filename)
        if os.path.isfile(output) or (
            run_export(texture, output) and os.path.isfile(output)
        ):
            if manual_texture_map is not None:
                manual_texture_map[path] = texture_record(
                    texture, filename
                )
            return filename
    return None


def write_json(path, payload):
    directory = os.path.dirname(os.path.abspath(path))
    if not os.path.isdir(directory):
        os.makedirs(directory)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)


def write_text(path, text):
    directory = os.path.dirname(os.path.abspath(path))
    if not os.path.isdir(directory):
        os.makedirs(directory)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


def export_summary(name, output_dir, counts, failures, errors=None):
    payload = {
        "script": name,
        "output_dir": output_dir,
        "counts": counts,
        "failures": list(failures),
        "errors": list(errors or []),
    }
    write_json(os.path.join(output_dir, name + "_report.json"), payload)
    lines = ["%s: %s" % (key, value) for key, value in sorted(counts.items())]
    lines.extend(["", "FAILURES"])
    lines.extend(list(failures) or ["none"])
    if errors:
        lines.extend(["", "ERRORS"])
        lines.extend(errors)
    write_text(os.path.join(output_dir, name + "_report.txt"), "\n".join(lines))
    return payload


def exception_text():
    return traceback.format_exc()
