# -*- coding: utf-8 -*-
"""Rebuild a placed Blueprint from instances.json in UE 4.27.

Environment:
    Unreal Engine 4.27 Editor Python 3.7, Cmd mode with the target level open.

Use:
    py "PATH/TO/PortKit/scripts/ue427/rebuild_from_instances.py" --config "PATH/TO/config.json"

Output:
    Static-mesh actors under the configured Outliner folder, one actor per
    exported instance. Missing *_LOD1 meshes fall back to *_LOD0 and Cube falls
    back to the engine Cube. JSON/TXT reports include missing meshes/materials.
"""
import argparse
import importlib
import json
import os
import sys
import time
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


LOG = []


def safe(function, *args):
    try:
        return function(*args)
    except Exception:
        return None


def log(message):
    LOG.append(str(message))
    if unreal is not None:
        unreal.log("[PortKit rebuild] " + str(message))


def index_assets(roots, class_name):
    eal = unreal.EditorAssetLibrary
    result = {}
    for root in roots:
        if not (
            eal.does_asset_exist(root)
            or eal.does_directory_exist(root)
        ):
            continue
        for path in eal.list_assets(root, True, False):
            data = eal.find_asset_data(path)
            if class_name not in str(data.asset_class):
                continue
            clean = path.split(".")[0]
            result.setdefault(clean.rsplit("/", 1)[-1].lower(), clean)
    return result


def transform_of(instance):
    location = instance.get("loc") or [0, 0, 0]
    scale = instance.get("scale") or [1, 1, 1]
    quaternion = instance.get("quat")
    if quaternion:
        rotation = unreal.Quat(
            quaternion[0],
            quaternion[1],
            quaternion[2],
            quaternion[3],
        )
    else:
        rotation_values = instance.get("rot") or [0, 0, 0]
        rotation = unreal.Rotator(
            roll=rotation_values[2],
            pitch=rotation_values[0],
            yaw=rotation_values[1],
        ).quaternion()
    return unreal.Transform(
        unreal.Vector(*location),
        rotation.rotator(),
        unreal.Vector(*scale),
    )


def run(config):
    if unreal is None:
        raise RuntimeError(
            "Run rebuild_from_instances.py inside UE 4.27 Editor Python"
        )
    options = (
        config.get("ue427", {})
        .get("rebuild_instances", {})
    )
    source = options.get("instances_json")
    mesh_roots = options.get("mesh_roots", [])
    material_roots = options.get("material_roots", [])
    folder = options.get("outliner_folder", "PortKitRebuilt")
    report_dir = options.get("report_dir") or os.getcwd()
    max_instances = int(options.get("max_instances", 0))
    only = {
        value.lower() for value in options.get("only_meshes", [])
    }
    if not source or not os.path.isfile(source):
        raise IOError("instances_json not found: %s" % source)
    with open(source, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    components = data.get("components") or []
    if only:
        components = [
            component
            for component in components
            if str(component.get("mesh_name") or "").lower() in only
        ]
    total = sum(len(component.get("instances") or []) for component in components)
    eal = unreal.EditorAssetLibrary
    level_library = unreal.EditorLevelLibrary
    existing = [
        actor
        for actor in (safe(level_library.get_all_level_actors) or [])
        if str(safe(actor.get_folder_path) or "") == folder
    ]
    if existing and not options.get("rebuild_existing", False):
        raise RuntimeError(
            "Outliner folder %s already contains %d actors"
            % (folder, len(existing))
        )
    meshes = index_assets(mesh_roots, "StaticMesh")
    materials = index_assets(
        material_roots, "MaterialInstanceConstant"
    )
    engine_cube = options.get(
        "engine_cube", "/Engine/BasicShapes/Cube"
    )
    if eal.does_asset_exist(engine_cube):
        meshes["cube"] = engine_cube
    for name in list(meshes):
        if name.endswith("_lod1") and name[:-1] + "0" in meshes:
            meshes[name] = meshes[name[:-1] + "0"]
    prefix = options.get("instance_prefix", "MI_Port_")
    spawned = failed = skipped = 0
    missing_meshes = set()
    missing_materials = set()
    started = time.time()
    progress = unreal.ScopedSlowTask(
        max(1, total), "PortKit placed-instance rebuild"
    )
    progress.make_dialog_visible()
    for component in components:
        if progress.should_cancel():
            LOG.append("cancelled; spawned actors were kept")
            break
        instances = component.get("instances") or []
        mesh_name = str(component.get("mesh_name") or "").lower()
        mesh_path = meshes.get(mesh_name)
        mesh = safe(eal.load_asset, mesh_path) if mesh_path else None
        if not isinstance(mesh, unreal.StaticMesh):
            missing_meshes.add(component.get("mesh_name"))
            skipped += len(instances)
            progress.enter_progress_frame(len(instances))
            continue
        overrides = []
        for material_name in component.get("materials") or []:
            base_name = (
                material_name[3:]
                if material_name.startswith("MI_")
                else material_name
            )
            material_path = materials.get(
                (prefix + base_name).lower()
            )
            if material_name and not material_path:
                missing_materials.add(material_name)
            overrides.append(
                safe(eal.load_asset, material_path)
                if material_path
                else None
            )
        for instance in instances:
            progress.enter_progress_frame(
                1, component.get("mesh_name", "")
            )
            if max_instances and spawned >= max_instances:
                break
            actor = safe(
                level_library.spawn_actor_from_object,
                mesh,
                unreal.Vector(0, 0, 0),
                unreal.Rotator(0, 0, 0),
            )
            if actor is None:
                failed += 1
                continue
            safe(
                actor.set_actor_transform,
                transform_of(instance),
                False,
                False,
            )
            component_system = safe(
                actor.get_component_by_class,
                unreal.StaticMeshComponent,
            )
            if component_system is not None:
                safe(
                    component_system.set_mobility,
                    unreal.ComponentMobility.STATIC,
                )
                for index, material in enumerate(overrides):
                    if material is not None:
                        safe(component_system.set_material, index, material)
            safe(actor.set_folder_path, folder)
            spawned += 1
        if max_instances and spawned >= max_instances:
            break
    payload = {
        "components": len(components),
        "instances_requested": total,
        "actors_spawned": spawned,
        "instances_skipped": skipped,
        "failed": failed,
        "missing_meshes": sorted(str(value) for value in missing_meshes),
        "missing_materials": sorted(missing_materials),
        "seconds": round(time.time() - started, 1),
        "notes": LOG,
    }
    if not os.path.isdir(report_dir):
        os.makedirs(report_dir)
    with open(
        os.path.join(report_dir, "rebuild_from_instances.json"),
        "w",
        encoding="utf-8",
    ) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    with open(
        os.path.join(report_dir, "rebuild_from_instances.txt"),
        "w",
        encoding="utf-8",
    ) as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, indent=2))
    return payload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", help="Path to PortKit JSON config")
    args = parser.parse_args()
    config = load_config(args.config)
    try:
        run(config)
    except Exception:
        options = config.get("ue427", {}).get("rebuild_instances", {})
        report_dir = options.get("report_dir") or os.getcwd()
        if not os.path.isdir(report_dir):
            os.makedirs(report_dir)
        with open(
            os.path.join(report_dir, "rebuild_from_instances.txt"),
            "w",
            encoding="utf-8",
        ) as handle:
            handle.write("ERROR\n" + traceback.format_exc())
        if unreal is not None:
            unreal.log_error(
                "[PortKit] rebuild_from_instances failed; see report"
            )
        else:
            raise


if __name__ == "__main__":
    main()
