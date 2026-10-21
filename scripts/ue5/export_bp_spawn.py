# -*- coding: utf-8 -*-
"""Record what Actor Blueprints construct by spawning them temporarily in UE5.

Environment:
    Unreal Engine 5.4 Editor Python, Cmd mode. Do not save the level after
    running: spawned actors exist only for the duration of this script.

Use:
    py "PATH/TO/PortKit/scripts/ue5/export_bp_spawn.py" --config "PATH/TO/config.json"

Output:
    ue5.exports.bp_spawn.output/blueprints.json, newly needed FBX meshes and a
    JSON report with skipped blueprints and errors.
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

from portkit_config import load_config
from ue5.export_common import (
    asset_path,
    class_name,
    run_export,
    safe,
    write_json,
)

try:
    import unreal
except ImportError:
    unreal = None


def _transform(value):
    if value is None:
        return None
    rotator = value.rotation.rotator()
    return {
        "loc": [
            value.translation.x,
            value.translation.y,
            value.translation.z,
        ],
        "rot": [rotator.roll, rotator.pitch, rotator.yaw],
        "scale": [
            value.scale3d.x,
            value.scale3d.y,
            value.scale3d.z,
        ],
    }


def _color(value):
    return [value.r, value.g, value.b, value.a] if hasattr(value, "r") else None


def _instance_world(component, index):
    result = component.get_instance_transform(index, True)
    if isinstance(result, tuple):
        for value in result:
            if isinstance(value, unreal.Transform):
                return value
        return None
    return result


def run(config):
    if unreal is None:
        raise RuntimeError(
            "Run export_bp_spawn.py inside UE 5.4 Editor Python"
        )
    options = (
        config.get("ue5", {}).get("exports", {}).get("bp_spawn", {})
    )
    search_roots = options.get("search_roots", [])
    output = options.get("output")
    known_manifests = options.get("known_manifests", [])
    spawn_z = float(options.get("spawn_z", -200000.0))
    if not search_roots or not output:
        raise ValueError(
            "ue5.exports.bp_spawn requires search_roots and output"
        )
    eal = unreal.EditorAssetLibrary
    actor_subsystem = unreal.get_editor_subsystem(
        unreal.EditorActorSubsystem
    )
    math_library = unreal.MathLibrary
    known = set()
    for manifest_path in known_manifests:
        if os.path.isfile(manifest_path):
            with open(manifest_path, "r", encoding="utf-8") as handle:
                known.update(json.load(handle).keys())
    blueprints = []
    for root in search_roots:
        blueprints.extend(
            path.split(".")[0]
            for path in eal.list_assets(
                root, recursive=True, include_folder=False
            )
            if class_name(eal.find_asset_data(path)) == "Blueprint"
        )
    blueprints = sorted(set(blueprints))
    result = {}
    skipped = []
    needed_meshes = {}
    errors = []
    progress = unreal.ScopedSlowTask(
        max(1, len(blueprints)), "PortKit Blueprint spawn recording"
    )
    progress.make_dialog_visible()
    spawn_at = unreal.Vector(0.0, 0.0, spawn_z)
    for path in blueprints:
        if progress.should_cancel():
            errors.append("cancelled by user")
            break
        progress.enter_progress_frame(1, path.rsplit("/", 1)[-1])
        blueprint = unreal.load_asset(path)
        actor = None
        try:
            generated_class = blueprint.generated_class()
            actor = actor_subsystem.spawn_actor_from_class(
                generated_class,
                spawn_at,
                unreal.Rotator(0, 0, 0),
            )
        except Exception as exc:
            skipped.append(
                "%s (%s)" % (path.rsplit("/", 1)[-1], exc)
            )
            continue
        if actor is None:
            skipped.append(
                path.rsplit("/", 1)[-1] + " (not an actor)"
            )
            continue
        try:
            root_world = actor.get_actor_transform()
            parts = []
            other = {}
            for component in actor.get_components_by_class(
                unreal.SceneComponent
            ):
                cls = component.get_class().get_name()
                relative = math_library.make_relative_transform(
                    component.get_world_transform(), root_world
                )
                if isinstance(component, unreal.StaticMeshComponent):
                    mesh = component.get_editor_property("static_mesh")
                    if mesh is None:
                        continue
                    entry = {
                        "type": "mesh",
                        "class": cls,
                        "name": component.get_name(),
                        "mesh": component.static_mesh.get_path_name(),
                        "materials": [
                            material.get_path_name() if material else None
                            for material in component.get_materials()
                        ],
                        "visible": bool(component.is_visible()),
                    }
                    if isinstance(
                        component, unreal.InstancedStaticMeshComponent
                    ):
                        entry["instances"] = []
                        for index in range(component.get_instance_count()):
                            world = _instance_world(component, index)
                            if world is not None:
                                entry["instances"].append(
                                    _transform(
                                        math_library.make_relative_transform(
                                            world, root_world
                                        )
                                    )
                                )
                    else:
                        entry["transform"] = _transform(relative)
                    parts.append(entry)
                    if mesh.get_name() not in known:
                        needed_meshes[mesh.get_name()] = mesh
                elif isinstance(component, unreal.LightComponent):
                    entry = {
                        "type": "light",
                        "class": cls,
                        "name": component.get_name(),
                        "transform": _transform(relative),
                        "intensity": component.get_editor_property(
                            "intensity"
                        ),
                        "color": _color(
                            component.get_editor_property("light_color")
                        ),
                    }
                    for prop in (
                        "attenuation_radius",
                        "source_radius",
                        "inner_cone_angle",
                        "outer_cone_angle",
                        "intensity_units",
                        "cast_shadows",
                    ):
                        value = safe(component.get_editor_property, prop)
                        if isinstance(value, (bool, int, float)):
                            entry[prop] = value
                        elif value is not None:
                            entry[prop] = str(value)
                    parts.append(entry)
                elif isinstance(component, unreal.DecalComponent):
                    material = component.get_editor_property(
                        "decal_material"
                    )
                    size = component.get_editor_property("decal_size")
                    parts.append(
                        {
                            "type": "decal",
                            "class": cls,
                            "name": component.get_name(),
                            "transform": _transform(relative),
                            "material": asset_path(material),
                            "size": [size.x, size.y, size.z],
                        }
                    )
                else:
                    other[cls] = other.get(cls, 0) + 1
            result[path.rsplit("/", 1)[-1]] = {
                "path": path,
                "parent_class": generated_class.get_name(),
                "parts": parts,
                "other_components": other,
            }
        except Exception as exc:
            errors.append("%s: %r" % (path, exc))
        finally:
            actor_subsystem.destroy_actor(actor)
    mesh_dir = os.path.join(output, "Meshes")
    if not os.path.isdir(mesh_dir):
        os.makedirs(mesh_dir)
    exported = []
    failures = []
    for name, mesh in sorted(needed_meshes.items()):
        destination = os.path.join(mesh_dir, name + ".fbx")
        if os.path.isfile(destination) or run_export(mesh, destination):
            exported.append(name)
        else:
            failures.append("mesh " + asset_path(mesh))
    payload = {
        "summary": {
            "blueprints": len(result),
            "skipped": skipped,
            "new_meshes_exported": exported,
            "failures": failures,
            "errors": errors,
        },
        "blueprints": result,
    }
    write_json(os.path.join(output, "blueprints.json"), payload)
    write_json(
        os.path.join(output, "export_bp_spawn_report.json"),
        payload["summary"],
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

            output = (
                config.get("ue5", {})
                .get("exports", {})
                .get("bp_spawn", {})
                .get("output")
                or os.getcwd()
            )
            write_json(
                os.path.join(output, "export_bp_spawn_report.json"),
                {"errors": [traceback.format_exc()]},
            )
            unreal.log_error("[PortKit] Blueprint spawn export failed")
        else:
            raise


if __name__ == "__main__":
    main()
