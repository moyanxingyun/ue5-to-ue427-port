# -*- coding: utf-8 -*-
"""Export selected UE5 static meshes, material parameters and textures.

Environment:
    Unreal Engine 5.4 Editor Python, Cmd mode.

Use:
    py "PATH/TO/PortKit/scripts/ue5/export_meshes.py" --config "PATH/TO/config.json"

Output:
    FBX files, manifest.json, materials.json, textures_map.json and report files
    under ue5.exports.meshes.output. Existing files are skipped, so interrupted
    exports can resume.
"""
import argparse
import importlib
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_ROOT = os.path.dirname(SCRIPT_DIR)
if SCRIPTS_ROOT not in sys.path:
    sys.path.insert(0, SCRIPTS_ROOT)

import portkit_config

importlib.reload(portkit_config)
portkit_config.reload_shared_modules()

from portkit_config import load_config, path_value
from ue5.export_common import (
    asset_path,
    class_name,
    exception_text,
    export_summary,
    export_texture,
    material_info,
    run_export,
    safe,
    write_json,
)

try:
    import unreal
except ImportError:
    unreal = None


def _profile(config, name):
    profiles = config.get("ue5", {}).get("exports", {})
    profile = profiles.get(name, {})
    if not profile:
        raise ValueError("ue5.exports.%s is missing" % name)
    return profile


def _number_vertices(mesh):
    subsystem_class = getattr(unreal, "StaticMeshEditorSubsystem", None)
    subsystem = (
        safe(unreal.get_editor_subsystem, subsystem_class)
        if subsystem_class
        else None
    )
    if subsystem:
        count = safe(subsystem.get_number_verts, mesh, 0)
        if count:
            return count
    return safe(unreal.EditorStaticMeshLibrary.get_number_verts, mesh, 0) or 0


def _wanted(path, profile):
    exact = profile.get("exact", [])
    if path in exact:
        return True
    probe = path + "/"
    include = profile.get("include", [])
    exclude = profile.get("exclude", [])
    return any(value.lower() in probe.lower() for value in include) and not any(
        value.lower() in probe.lower() for value in exclude
    )


def run_export_meshes(config, name="export_meshes"):
    if unreal is None:
        raise RuntimeError("Run export_meshes.py inside UE 5.4 Editor Python")
    profile = _profile(config, name)
    asset_root = profile.get("asset_root") or config.get("ue5", {}).get(
        "asset_root"
    )
    mesh_root = profile.get("mesh_root") or asset_root
    output = profile.get("output")
    if not asset_root or not mesh_root or not output:
        raise ValueError(
            "mesh profile requires asset_root, mesh_root and output"
        )
    mesh_dir = os.path.join(output, "Meshes")
    texture_dir = os.path.join(output, "Textures")
    if not os.path.isdir(mesh_dir):
        os.makedirs(mesh_dir)
    if not os.path.isdir(texture_dir):
        os.makedirs(texture_dir)
    eal = unreal.EditorAssetLibrary
    selected = []
    folders = {}
    for path in eal.list_assets(asset_root, recursive=True, include_folder=False):
        data = eal.find_asset_data(path)
        if class_name(data) != "StaticMesh":
            continue
        clean_path = path.split(".")[0]
        folder = clean_path.rsplit("/", 1)[0]
        folder_info = folders.setdefault(
            folder, {"meshes": 0, "included": _wanted(folder, profile)}
        )
        folder_info["meshes"] += 1
        if folder_info["included"]:
            selected.append(clean_path)
    write_json(os.path.join(output, "folders.json"), folders)
    fbx_options = unreal.FbxExportOption()
    fbx_options.collision = False
    fbx_options.vertex_color = True
    fbx_options.level_of_detail = True
    source_ok = False
    try:
        fbx_options.set_editor_property("export_source_mesh", True)
        source_ok = True
    except Exception:
        pass
    manifest = {}
    materials = {}
    texture_map = {}
    texture_queue = set()
    failures = []
    used_names = {}
    progress = unreal.ScopedSlowTask(
        max(1, len(selected)), "PortKit mesh export"
    )
    progress.make_dialog_visible()
    for path in selected:
        if progress.should_cancel():
            failures.append("CANCELLED - rerun to continue")
            break
        progress.enter_progress_frame(1, path.rsplit("/", 1)[-1])
        mesh = unreal.load_asset(path)
        if not isinstance(mesh, unreal.StaticMesh):
            continue
        folder = path.rsplit("/", 1)[0]
        if folder == mesh_root:
            relative = ""
        elif folder.startswith(mesh_root.rstrip("/") + "/"):
            relative = folder[len(mesh_root.rstrip("/")) + 1 :]
        else:
            relative = "_Other/" + folder[len(asset_root.rstrip("/")) + 1 :]
        target_dir = (
            os.path.join(mesh_dir, *relative.split("/"))
            if relative
            else mesh_dir
        )
        if not os.path.isdir(target_dir):
            os.makedirs(target_dir)
        fbx_path = os.path.join(
            target_dir, path.rsplit("/", 1)[-1] + ".fbx"
        )
        if not os.path.isfile(fbx_path) and not (
            safe(run_export, mesh, fbx_path, fbx_options)
            and os.path.isfile(fbx_path)
        ):
            failures.append("mesh " + path)
            continue
        slots = []
        for slot in mesh.static_materials:
            material = slot.material_interface
            material_path = asset_path(material)
            slots.append(
                {
                    "slot": str(slot.material_slot_name),
                    "material": material_path,
                }
            )
            if material and material_path not in materials:
                materials[material_path] = material_info(material)
                for texture_path in materials[material_path][
                    "textures"
                ].values():
                    if texture_path and texture_path.startswith("/Game/"):
                        texture_queue.add(texture_path)
        nanite = safe(mesh.get_editor_property, "nanite_settings")
        box = mesh.get_bounding_box()
        size = box.max - box.min
        manifest[path] = {
            "name": path.rsplit("/", 1)[-1],
            "folder": relative,
            "fbx": os.path.relpath(fbx_path, output),
            "slots": slots,
            "nanite": bool(
                nanite
                and safe(nanite.get_editor_property, "enabled")
            ),
            "verts": _number_vertices(mesh),
            "lods": safe(mesh.get_num_lods) or 1,
            "size_cm": [
                round(size.x, 1),
                round(size.y, 1),
                round(size.z, 1),
            ],
        }
    textures = sorted(texture_queue)
    texture_progress = unreal.ScopedSlowTask(
        max(1, len(textures)), "PortKit texture export"
    )
    texture_progress.make_dialog_visible()
    for path in textures:
        if texture_progress.should_cancel():
            failures.append("CANCELLED during textures - rerun to continue")
            break
        texture_progress.enter_progress_frame(1, path.rsplit("/", 1)[-1])
        texture = unreal.load_asset(path)
        if not isinstance(texture, unreal.Texture2D):
            failures.append("not a Texture2D: " + path)
            continue
        if export_texture(texture, texture_dir, used_names, texture_map) is None:
            failures.append("texture " + path)
    write_json(os.path.join(output, "manifest.json"), manifest)
    write_json(os.path.join(output, "materials.json"), materials)
    write_json(os.path.join(output, "textures_map.json"), texture_map)
    counts = {
        "meshes": len(manifest),
        "materials": len(materials),
        "textures": len(texture_map),
        "nanite_meshes": sum(
            1 for entry in manifest.values() if entry["nanite"]
        ),
        "export_source_mesh": bool(source_ok),
    }
    export_summary(name, output, counts, failures)
    if counts["meshes"] == 0:
        unreal.log_error(
            "[PortKit] mesh export produced zero meshes; check project and profile"
        )
    return counts


def main(profile_name="export_meshes"):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", help="Path to PortKit JSON config")
    args = parser.parse_args()
    config = load_config(args.config)
    try:
        run_export_meshes(config, profile_name)
    except Exception:
        profile = config.get("ue5", {}).get("exports", {}).get(
            profile_name, {}
        )
        output = profile.get("output") or os.getcwd()
        if unreal is not None:
            export_summary(
                profile_name,
                output,
                {},
                ["fatal"],
                [exception_text()],
            )
            unreal.log_error(
                "[PortKit] mesh export failed; see report in " + output
            )
        else:
            raise


if __name__ == "__main__":
    main()
