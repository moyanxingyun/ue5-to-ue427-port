# -*- coding: utf-8 -*-
"""Cap texture maximum sizes and restore their original values from backup.

Environment:
    Unreal Engine 4.27 Editor Python 3.7, Cmd mode.

Use:
    py "PATH/TO/PortKit/scripts/tools/tex_cap2048.py" --config "PATH/TO/config.json"

Output:
    Modified Maximum Texture Size settings, an undo JSON backup and JSON/TXT
    reports. Set tools.texture_cap.mode to "restore" to undo.
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


def run(config):
    if unreal is None:
        raise RuntimeError("Run tex_cap2048.py inside UE 4.27 Editor Python")
    options = config.get("tools", {}).get("texture_cap", {})
    roots = options.get("roots", ["/Game"])
    excludes = options.get("exclude", ["/Engine/", "/UI/", "/HUD/"])
    cap = int(options.get("cap", 2048))
    mode = str(options.get("mode", "apply")).lower()
    backup_path = options.get("backup") or report_path(
        config, "texture_cap_backup.json"
    )
    eal = unreal.EditorAssetLibrary
    backup = {}
    if os.path.isfile(backup_path):
        with open(backup_path, "r", encoding="utf-8") as handle:
            backup = json.load(handle)
    lines = []
    if mode == "restore":
        items = list(backup.items())
        progress = unreal.ScopedSlowTask(
            max(1, len(items)), "Restore texture sizes"
        )
        progress.make_dialog_visible()
        restored = 0
        for path, old_size in items:
            if progress.should_cancel():
                break
            progress.enter_progress_frame(1, path.rsplit("/", 1)[-1])
            texture = unreal.load_asset(path)
            if texture is None:
                continue
            texture.set_editor_property(
                "max_texture_size", int(old_size)
            )
            eal.save_loaded_asset(texture, False)
            restored += 1
        backup = {}
        counts = {"restored": restored}
        lines.append("restored textures: %d" % restored)
    else:
        paths = []
        for root in roots:
            paths.extend(
                path.split(".")[0]
                for path in eal.list_assets(
                    root, recursive=True, include_folder=False
                )
                if "Texture2D"
                in str(eal.find_asset_data(path).asset_class)
            )
        paths = [
            path
            for path in paths
            if not any(
                excluded.lower() in (path + "/").lower()
                for excluded in excludes
            )
        ]
        capped = small = ui = 0
        saved_megabytes = 0.0
        progress = unreal.ScopedSlowTask(
            max(1, len(paths)), "Cap textures to %d" % cap
        )
        progress.make_dialog_visible()
        for path in paths:
            if progress.should_cancel():
                lines.append("CANCELLED - completed textures are saved")
                break
            progress.enter_progress_frame(1, path.rsplit("/", 1)[-1])
            texture = unreal.load_asset(path)
            if texture is None:
                continue
            if "UI" in str(texture.get_editor_property("lod_group")):
                ui += 1
                continue
            try:
                width = int(texture.blueprint_get_size_x())
                height = int(texture.blueprint_get_size_y())
            except Exception:
                width = height = 0
            current = int(texture.get_editor_property("max_texture_size"))
            if max(width, height) <= cap or 0 < current <= cap:
                small += 1
                continue
            if path not in backup:
                backup[path] = current
            texture.set_editor_property("max_texture_size", cap)
            eal.save_loaded_asset(texture, False)
            capped += 1
            scale = (float(cap) / max(width, height)) ** 2
            saved_megabytes += (
                width * height * 1.33 * (1.0 - scale) / (1024.0 * 1024.0)
            )
            lines.append(
                "%s %dx%d -> max %d" % (path, width, height, cap)
            )
        counts = {
            "scanned": len(paths),
            "capped": capped,
            "already_small": small,
            "ui_skipped": ui,
            "estimated_megabytes_saved": round(saved_megabytes),
        }
        lines.insert(
            0,
            "scanned %d, capped %d, already small %d, UI skipped %d"
            % (len(paths), capped, small, ui),
        )
    with open(backup_path, "w", encoding="utf-8") as handle:
        json.dump(backup, handle, ensure_ascii=False, indent=2)
    with open(
        report_path(config, "texture_cap.json"), "w", encoding="utf-8"
    ) as handle:
        json.dump(counts, handle, ensure_ascii=False, indent=2)
    with open(
        report_path(config, "texture_cap.txt"), "w", encoding="utf-8"
    ) as handle:
        handle.write("\n".join(lines))
    return counts


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
                report_path(config, "texture_cap.txt"),
                "w",
                encoding="utf-8",
            ) as handle:
                handle.write(traceback.format_exc())
        else:
            raise


if __name__ == "__main__":
    main()
