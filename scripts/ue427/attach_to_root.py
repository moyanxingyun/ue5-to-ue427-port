# -*- coding: utf-8 -*-
"""Attach actors in an Outliner folder to one movable root, or detach them.

Environment:
    Unreal Engine 4.27 Editor Python 3.7. Click empty viewport space first.

Use:
    py "PATH/TO/PortKit/scripts/ue427/attach_to_root.py" --config "PATH/TO/config.json"

Output:
    A configured root actor with static mobility and world-preserving KEEP_WORLD
    attachment. mode="detach" restores loose actors. JSON report records counts.
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


def run(config):
    if unreal is None:
        raise RuntimeError("Run attach_to_root.py inside UE 4.27 Editor Python")
    options = config.get("ue427", {}).get("attach_root", {})
    folder = options.get("outliner_folder", "PortKitRebuilt")
    root_label = options.get("root_label", "PortKit_Root")
    mode = str(options.get("mode", "attach")).lower()
    report_dir = options.get("report_dir") or os.getcwd()
    library = unreal.EditorLevelLibrary
    library.select_nothing()
    all_actors = list(library.get_all_level_actors())
    actors = [
        actor
        for actor in all_actors
        if str(actor.get_folder_path()) == folder
    ]
    root = next(
        (
            actor
            for actor in all_actors
            if actor.get_actor_label() == root_label
        ),
        None,
    )
    parts = [actor for actor in actors if actor != root]
    done = 0
    if mode == "detach":
        progress = unreal.ScopedSlowTask(
            max(1, len(parts)), "Detaching " + folder
        )
        progress.make_dialog_visible()
        for actor in parts:
            if progress.should_cancel():
                break
            progress.enter_progress_frame(1)
            actor.detach_from_actor(
                unreal.DetachmentRule.KEEP_WORLD,
                unreal.DetachmentRule.KEEP_WORLD,
                unreal.DetachmentRule.KEEP_WORLD,
            )
            done += 1
    else:
        if not parts:
            raise RuntimeError("No actors found in folder " + folder)
        if root is None:
            locations = [actor.get_actor_location() for actor in parts]
            low = [
                min(location.x for location in locations),
                min(location.y for location in locations),
                min(location.z for location in locations),
            ]
            high = [
                max(location.x for location in locations),
                max(location.y for location in locations),
            ]
            centre = unreal.Vector(
                (low[0] + high[0]) / 2,
                (low[1] + high[1]) / 2,
                low[2],
            )
            root = library.spawn_actor_from_class(
                unreal.StaticMeshActor,
                centre,
                unreal.Rotator(0, 0, 0),
            )
            root.set_actor_label(root_label)
            root.set_folder_path(folder)
        root_component = root.get_editor_property("root_component")
        root_component.set_mobility(unreal.ComponentMobility.STATIC)
        progress = unreal.ScopedSlowTask(
            max(1, len(parts)), "Attaching " + folder
        )
        progress.make_dialog_visible()
        for actor in parts:
            if progress.should_cancel():
                break
            progress.enter_progress_frame(1)
            if actor.get_attach_parent_actor() == root:
                done += 1
                continue
            actor.attach_to_actor(
                root,
                "",
                unreal.AttachmentRule.KEEP_WORLD,
                unreal.AttachmentRule.KEEP_WORLD,
                unreal.AttachmentRule.KEEP_WORLD,
                False,
            )
            if actor.get_attach_parent_actor() == root:
                done += 1
        library.set_selected_level_actors([root])
    payload = {
        "mode": mode,
        "folder": folder,
        "root_label": root_label,
        "parts": len(parts),
        "processed": done,
    }
    if not os.path.isdir(report_dir):
        os.makedirs(report_dir)
    with open(
        os.path.join(report_dir, "attach_to_root.json"),
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
        options = config.get("ue427", {}).get("attach_root", {})
        report_dir = options.get("report_dir") or os.getcwd()
        if not os.path.isdir(report_dir):
            os.makedirs(report_dir)
        with open(
            os.path.join(report_dir, "attach_to_root.txt"),
            "w",
            encoding="utf-8",
        ) as handle:
            handle.write("ERROR\n" + traceback.format_exc())
        if unreal is not None:
            unreal.log_error("[PortKit] attach_to_root failed; see report")
        else:
            raise


if __name__ == "__main__":
    main()
