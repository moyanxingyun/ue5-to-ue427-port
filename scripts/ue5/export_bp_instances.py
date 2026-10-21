# -*- coding: utf-8 -*-
"""Export world transforms and meshes from a selected placed Blueprint actor.

Environment:
    Unreal Engine 5.4 Editor Python, Cmd mode with the source level open.

Use:
    py "PATH/TO/PortKit/scripts/ue5/export_bp_instances.py" --config "PATH/TO/config.json"

Output:
    ue5.exports.bp_instances.output/instances.json and a JSON report. Transforms
    include both rotators and quaternions; child actors and spline meshes are
    recorded when present.
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

from portkit_config import load_config
from ue5.export_common import asset_path, safe, write_json

try:
    import unreal
except ImportError:
    unreal = None


def transform_dict(transform):
    if transform is None:
        return None
    location = transform.translation
    scale = transform.scale3d
    quaternion = transform.rotation
    try:
        rotator = transform.rotator()
        rotation = [rotator.pitch, rotator.yaw, rotator.roll]
    except Exception:
        rotation = [
            quaternion.x,
            quaternion.y,
            quaternion.z,
            quaternion.w,
        ]
    return {
        "loc": [location.x, location.y, location.z],
        "rot": rotation,
        "quat": [quaternion.x, quaternion.y, quaternion.z, quaternion.w],
        "scale": [scale.x, scale.y, scale.z],
    }


def instance_world(component, index):
    result = safe(component.get_instance_transform, index, True)
    if isinstance(result, tuple):
        result = result[-1]
    if result is not None and not isinstance(result, bool):
        value = transform_dict(result)
        if value:
            return value
    local = safe(component.get_instance_transform, index)
    if isinstance(local, tuple):
        local = local[-1]
    if local is None or isinstance(local, bool):
        return None
    component_world = safe(component.get_world_transform)
    if component_world is not None:
        try:
            return transform_dict(component_world * local)
        except Exception:
            pass
    return transform_dict(local)


def component_materials(component):
    result = []
    for index in range(safe(component.get_num_materials) or 0):
        material = safe(component.get_material, index)
        result.append(material.get_name() if material else "")
    return result


def actors_with_children(actor):
    result = []
    pending = [actor]
    while pending:
        current = pending.pop()
        result.append(current)
        for child_component in (
            safe(current.get_components_by_class, unreal.ChildActorComponent)
            or []
        ):
            child = safe(child_component.get_editor_property, "child_actor")
            if child is not None:
                pending.append(child)
    return result


def _find_actor(blueprint_hint):
    selected = safe(
        unreal.EditorLevelLibrary.get_selected_level_actors
    ) or []
    if selected:
        return selected[0], "selected"
    for actor in (
        safe(unreal.EditorLevelLibrary.get_all_level_actors) or []
    ):
        cls = safe(actor.get_class)
        class_name = safe(cls.get_name) if cls else ""
        if blueprint_hint.lower() in str(class_name).lower():
            return actor, "class"
    return None, "missing"


def run(config):
    if unreal is None:
        raise RuntimeError(
            "Run export_bp_instances.py inside UE 5.4 Editor Python"
        )
    options = (
        config.get("ue5", {})
        .get("exports", {})
        .get("bp_instances", {})
    )
    output = options.get("output")
    hint = options.get("blueprint_hint", "")
    if not output or not hint:
        raise ValueError(
            "ue5.exports.bp_instances requires output and blueprint_hint"
        )
    actor, selection_mode = _find_actor(hint)
    if actor is None:
        raise RuntimeError(
            "No selected or matching actor found for hint " + hint
        )
    actors = actors_with_children(actor)
    components = []
    for current in actors:
        components.extend(
            safe(
                current.get_components_by_class,
                unreal.InstancedStaticMeshComponent,
            )
            or []
        )
    static_components = []
    for current in actors:
        static_components.extend(
            safe(
                current.get_components_by_class,
                unreal.StaticMeshComponent,
            )
            or []
        )
    data = {
        "blueprint_hint": hint,
        "selection_mode": selection_mode,
        "actor_label": str(safe(actor.get_actor_label) or ""),
        "actor_transform": transform_dict(
            safe(actor.get_actor_transform)
        ),
        "components": [],
    }
    total_instances = 0
    progress = unreal.ScopedSlowTask(
        max(1, len(components) + len(static_components)),
        "PortKit Blueprint placement export",
    )
    progress.make_dialog_visible()
    for component in components:
        if progress.should_cancel():
            raise RuntimeError("cancelled by user")
        mesh = safe(component.get_editor_property, "static_mesh")
        if mesh is None:
            continue
        instances = []
        for index in range(safe(component.get_instance_count) or 0):
            value = instance_world(component, index)
            if value:
                instances.append(value)
        if not instances:
            continue
        data["components"].append(
            {
                "name": str(safe(component.get_name)),
                "mesh": asset_path(mesh),
                "mesh_name": mesh.get_name(),
                "materials": component_materials(component),
                "instances": instances,
            }
        )
        total_instances += len(instances)
        progress.enter_progress_frame(1, mesh.get_name())
    for component in static_components:
        if isinstance(component, unreal.InstancedStaticMeshComponent):
            continue
        if progress.should_cancel():
            raise RuntimeError("cancelled by user")
        mesh = safe(component.get_editor_property, "static_mesh")
        if mesh is None:
            continue
        value = transform_dict(safe(component.get_world_transform))
        if value is None:
            continue
        data["components"].append(
            {
                "name": str(safe(component.get_name)),
                "mesh": asset_path(mesh),
                "mesh_name": mesh.get_name(),
                "materials": component_materials(component),
                "spline": isinstance(component, unreal.SplineMeshComponent),
                "instances": [value],
            }
        )
        total_instances += 1
        progress.enter_progress_frame(1, mesh.get_name())
    data["totals"] = {
        "components": len(data["components"]),
        "instances": total_instances,
        "unique_meshes": len(
            {entry["mesh"] for entry in data["components"]}
        ),
    }
    write_json(os.path.join(output, "instances.json"), data)
    write_json(
        os.path.join(output, "export_bp_instances_report.json"),
        data["totals"],
    )
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", help="Path to PortKit JSON config")
    args = parser.parse_args()
    config = load_config(args.config)
    try:
        run(config)
    except Exception:
        output = (
            config.get("ue5", {})
            .get("exports", {})
            .get("bp_instances", {})
            .get("output")
            or os.getcwd()
        )
        if unreal is not None:
            import traceback

            write_json(
                os.path.join(output, "export_bp_instances_report.json"),
                {"errors": [traceback.format_exc()]},
            )
            unreal.log_error(
                "[PortKit] Blueprint placement export failed"
            )
        else:
            raise


if __name__ == "__main__":
    main()
