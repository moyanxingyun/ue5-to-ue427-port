# -*- coding: utf-8 -*-
"""Export a UE5 material and its recursive /Game function graph dumps.

Environment:
    Unreal Engine 5.4 Editor Python, Cmd mode.

Use:
    py "PATH/TO/PortKit/scripts/ue5/dump_graphs.py" --config "PATH/TO/config.json"

Output:
    One compact .txt dump per material/function in paths.dumps. Each dump uses
    the same Begin Object / 4-space properties / End Object format as the
    reference corpus. Resumable JSON report: paths.reports/dump_graphs.json.
"""
import argparse
import importlib
import json
import os
import re
import sys
import traceback

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_ROOT = os.path.dirname(SCRIPT_DIR)
if SCRIPTS_ROOT not in sys.path:
    sys.path.insert(0, SCRIPTS_ROOT)

import portkit_config

importlib.reload(portkit_config)
portkit_config.reload_shared_modules()

from portkit_config import load_config, path_value, report_path, write_json
from material_transplant.t3d_parser import parse_dump

try:
    import unreal
except ImportError:
    unreal = None


BLOCK_RE = re.compile(
    r'^(?P<indent>[ \t]*)Begin Object(?P<header>[^\n]*)\n'
    r'.*?^[ \t]*End Object[ \t]*$',
    re.M | re.S,
)
FUNCTION_RE = re.compile(
    r"MaterialFunction(?:\"|')?([^\"']+)(?:\"|')?"
)
CLASS_RE = re.compile(r"Class=/Script/Engine\.(\w+)")
NAME_RE = re.compile(r'Name="([^"]+)"')


def normalize_expression_blocks(t3d_text):
    classes = {}
    properties = {}
    order = []
    stack = []
    blocks = []
    for line in t3d_text.splitlines():
        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        if stripped.startswith("Begin Object"):
            stack.append(
                {
                    "indent": indent,
                    "header": stripped[len("Begin Object") :],
                    "body": [],
                }
            )
            continue
        if stripped.startswith("End Object") and stack:
            block = stack.pop()
            blocks.append(block)
            continue
        for block in stack:
            block["body"].append(line)
    for block in blocks:
        header = block["header"]
        class_match = CLASS_RE.search(header)
        name_match = NAME_RE.search(header)
        if not name_match:
            continue
        name = name_match.group(1)
        if class_match:
            cls = class_match.group(1)
            if cls.startswith("MaterialExpression"):
                classes[name] = cls
                if name not in order:
                    order.append(name)
            continue
        body_lines = []
        for line in block["body"]:
            stripped = line.strip()
            if stripped:
                body_lines.append("    " + stripped)
        if body_lines:
            properties.setdefault(name, []).extend(body_lines)
    output = []
    for name in order:
        cls = classes[name]
        output.append(
            'Begin Object Class=/Script/Engine.%s Name="%s"'
            % (cls, name)
        )
        output.extend(properties.get(name, []))
        output.append("End Object")
    return "\n".join(output) + ("\n" if output else "")


def function_paths_from_t3d(t3d_text, game_root="/Game"):
    paths = set()
    for raw_path in FUNCTION_RE.findall(t3d_text):
        asset_path = raw_path.split(".")[0]
        if asset_path.startswith(game_root + "/"):
            paths.add(asset_path)
    return sorted(paths)


def _export_t3d(asset, output_path):
    task = unreal.AssetExportTask()
    task.object = asset
    task.filename = output_path
    task.automated = True
    task.prompt = False
    task.replace_identical = True
    return bool(unreal.Exporter.run_asset_export_task(task))


def _dump_name(asset_path):
    return asset_path.rsplit("/", 1)[-1]


def run(config):
    if unreal is None:
        raise RuntimeError("Run dump_graphs.py inside UE 5.4 Editor Python")
    dumps_dir = path_value(config, "paths", "dumps")
    work_dir = path_value(
        config,
        "paths",
        "graph_work",
        default=os.path.join(os.path.dirname(dumps_dir), "_graph_work"),
    )
    if not os.path.isdir(dumps_dir):
        os.makedirs(dumps_dir)
    if not os.path.isdir(work_dir):
        os.makedirs(work_dir)
    game_root = config.get("ue5", {}).get("game_root", "/Game")
    seed_assets = list(config.get("ue5", {}).get("master_assets", []))
    if not seed_assets:
        raise ValueError("ue5.master_assets must contain at least one asset path")
    report = {
        "project": config.get("project", {}).get("name", ""),
        "assets": [],
        "written": [],
        "skipped": [],
        "missing": [],
        "errors": [],
    }
    progress = unreal.ScopedSlowTask(100, "PortKit graph dump")
    progress.make_dialog_visible()
    queue = list(seed_assets)
    seen = set()
    while queue:
        if progress.should_cancel():
            report["errors"].append("cancelled by user")
            break
        progress.enter_progress_frame(1)
        asset_path = queue.pop(0).split(".")[0]
        if asset_path in seen:
            continue
        seen.add(asset_path)
        asset = unreal.load_asset(asset_path)
        if asset is None:
            report["missing"].append(asset_path)
            continue
        name = _dump_name(asset_path)
        work_path = os.path.join(work_dir, name + ".t3d")
        if not _export_t3d(asset, work_path):
            report["errors"].append("T3D export failed: " + asset_path)
            continue
        with open(work_path, "r", encoding="utf-8") as handle:
            full_t3d = handle.read()
        queue.extend(
            path
            for path in function_paths_from_t3d(full_t3d, game_root)
            if path not in seen
        )
        output_path = os.path.join(dumps_dir, name + ".txt")
        if os.path.isfile(output_path) and os.path.getsize(output_path) > 0:
            report["skipped"].append(output_path)
            continue
        compact = normalize_expression_blocks(full_t3d)
        if not compact:
            report["errors"].append(
                "no material expression blocks: " + asset_path
            )
            continue
        with open(output_path, "w", encoding="utf-8") as handle:
            handle.write(compact)
        try:
            parsed = parse_dump(output_path)
            if not parsed:
                raise ValueError("parser produced zero nodes")
            report["written"].append(
                {"path": output_path, "nodes": len(parsed)}
            )
        except Exception as exc:
            report["errors"].append(
                "parser validation %s: %r" % (output_path, exc)
            )
        report["assets"].append(asset_path)
    write_json(report_path(config, "dump_graphs.json"), report)
    unreal.log(
        "[PortKit] graphs written=%d skipped=%d missing=%d errors=%d"
        % (
            len(report["written"]),
            len(report["skipped"]),
            len(report["missing"]),
            len(report["errors"]),
        )
    )
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", help="Path to PortKit JSON config")
    args = parser.parse_args()
    config = load_config(args.config)
    try:
        run(config)
    except Exception:
        if unreal is not None:
            fallback = {
                "errors": [traceback.format_exc()],
                "written": [],
                "skipped": [],
                "missing": [],
            }
            write_json(report_path(config, "dump_graphs.json"), fallback)
            unreal.log_error("[PortKit] dump_graphs failed; see report")
        else:
            raise


if __name__ == "__main__":
    main()
