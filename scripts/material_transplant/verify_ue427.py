# -*- coding: utf-8 -*-
"""Verify rebuilt UE 4.27 material graphs against the original UE5 dumps.

Environment:
    Unreal Engine 4.27 Editor Python 3.7, Cmd mode.

Use:
    py "PATH/TO/PortKit/scripts/material_transplant/verify_ue427.py" --config "PATH/TO/config.json"

Output:
    Full T3D exports in paths.verify_t3d, a machine-readable comparison in
    paths.reports/verify_materials.json, and a compact Markdown diff table in
    paths.reports/verify_materials.md.
"""
import argparse
import collections
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

from portkit_config import (
    load_config,
    path_value,
    report_path,
    write_json,
    write_text,
)
from material_transplant.planner import make_resolver, plan, variant_name
from material_transplant.rules_ue427 import in_name, out_name
from material_transplant.t3d_parser import load_graphs, parse_text
from ue5.dump_graphs import normalize_expression_blocks

try:
    import unreal
except ImportError:
    unreal = None


def _safe_name(asset_path):
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", asset_path.strip("/"))


def _export(asset_path, output_path):
    asset = unreal.load_asset(asset_path)
    if asset is None:
        return False
    task = unreal.AssetExportTask()
    task.object = asset
    task.filename = output_path
    task.automated = True
    task.prompt = False
    task.replace_identical = True
    return bool(unreal.Exporter.run_asset_export_task(task))


def node_type_counts(nodes):
    return collections.Counter(node["cls"] for node in nodes.values())


def connection_set(nodes, values):
    resolver = make_resolver(
        nodes, values, {name: name for name in nodes}
    )
    connections = set()
    for node in nodes.values():
        for prop, index, input_name, ref in node["inputs"]:
            resolved = resolver(ref)
            if resolved is None:
                continue
            source_name, source_index = resolver.last
            source = nodes[source_name]
            target_name = in_name(node, prop, index, input_name)
            source_out = out_name(source, source_index)
            connections.add(
                (
                    source["cls"],
                    source_out,
                    node["cls"],
                    target_name,
                )
            )
    return connections


def _values_for_combo(defaults, combo):
    values = dict(defaults)
    values.update(dict(combo))
    return values


def _asset_original(asset_path, runtime):
    name = asset_path.rsplit("/", 1)[-1]
    master_name = runtime["master_name"]
    graphs = runtime["graphs"]
    master_match = re.match(
        re.escape(master_name) + r"_C(\d+)$", name
    )
    if master_match:
        combo_index = int(master_match.group(1)) - 1
        combos = runtime["plan_data"]["combos"]
        if 0 <= combo_index < len(combos):
            return master_name, _values_for_combo(
                runtime["defaults"], combos[combo_index]
            )
        return master_name, dict(runtime["defaults"])
    base = name.split("__", 1)[0]
    if base not in graphs:
        return None, None
    for combo in runtime["plan_data"]["combos"]:
        values = _values_for_combo(runtime["defaults"], combo)
        variant, _folder = variant_name(
            base,
            values,
            runtime["plan_data"]["deps"],
            runtime["func_dir"],
            runtime["variant_dir"],
        )
        if variant == name:
            return base, values
    return base, dict(runtime["defaults"])


def _diff_counts(original, rebuilt):
    keys = sorted(set(original) | set(rebuilt))
    rows = {}
    for key in keys:
        left = original.get(key, 0)
        right = rebuilt.get(key, 0)
        if left != right:
            rows[key] = {"original": left, "rebuilt": right, "delta": right - left}
    return rows


def compare_graph(original_nodes, rebuilt_nodes, values):
    original_counts = node_type_counts(original_nodes)
    rebuilt_counts = node_type_counts(rebuilt_nodes)
    original_edges = connection_set(original_nodes, values)
    rebuilt_edges = connection_set(rebuilt_nodes, values)
    missing_edges = sorted(original_edges - rebuilt_edges)
    added_edges = sorted(rebuilt_edges - original_edges)
    return {
        "original_node_count": len(original_nodes),
        "rebuilt_node_count": len(rebuilt_nodes),
        "node_type_diff": _diff_counts(
            original_counts, rebuilt_counts
        ),
        "original_connection_count": len(original_edges),
        "rebuilt_connection_count": len(rebuilt_edges),
        "missing_connections": [list(edge) for edge in missing_edges],
        "added_connections": [list(edge) for edge in added_edges],
        "match": not missing_edges and not added_edges,
    }


def run(config):
    if unreal is None:
        raise RuntimeError("Run verify_ue427.py inside UE 4.27 Editor Python")
    material = config.get("material", {})
    dumps_dir = path_value(config, "paths", "dumps")
    materials_json = path_value(config, "paths", "materials_json")
    master_name = material.get("master_name")
    func_dir = material.get("func_dir")
    variant_dir = material.get(
        "variant_dir", func_dir.rstrip("/") + "/Variants"
    )
    combo_dir = material.get("combo_dir")
    output_dir = path_value(config, "paths", "verify_t3d")
    if not os.path.isdir(output_dir):
        os.makedirs(output_dir)
    graphs = load_graphs(dumps_dir)
    with open(materials_json, "r", encoding="utf-8") as handle:
        infos = json.load(handle)
    plan_data = plan(graphs, infos, master_name, func_dir)
    runtime = {
        "graphs": graphs,
        "plan_data": plan_data,
        "defaults": plan_data["defaults"],
        "master_name": master_name,
        "func_dir": func_dir,
        "variant_dir": variant_dir,
    }
    asset_paths = list(material.get("verify_assets", []))
    for directory in (combo_dir, variant_dir):
        if directory and unreal.EditorAssetLibrary.does_directory_exist(directory):
            asset_paths.extend(
                str(path)
                for path in unreal.EditorAssetLibrary.list_assets(
                    directory, recursive=True
                )
            )
    asset_paths = sorted(set(asset_paths))
    report = {
        "assets": {},
        "export_failures": [],
        "parse_failures": [],
        "unmatched_assets": [],
        "errors": [],
    }
    progress = unreal.ScopedSlowTask(
        max(1, len(asset_paths)), "PortKit material verification"
    )
    progress.make_dialog_visible()
    for asset_path in asset_paths:
        if progress.should_cancel():
            report["errors"].append("cancelled by user")
            break
        progress.enter_progress_frame(1, asset_path)
        original_name, values = _asset_original(asset_path, runtime)
        if original_name is None or original_name not in graphs:
            report["unmatched_assets"].append(asset_path)
            continue
        t3d_path = os.path.join(
            output_dir, _safe_name(asset_path) + ".t3d"
        )
        if not _export(asset_path, t3d_path):
            report["export_failures"].append(asset_path)
            continue
        try:
            with open(t3d_path, "r", encoding="utf-8") as handle:
                full_t3d = handle.read()
            compact = normalize_expression_blocks(full_t3d)
            rebuilt_nodes = parse_text(compact)
            if not rebuilt_nodes:
                raise ValueError("zero parsed expression nodes")
        except Exception as exc:
            report["parse_failures"].append(
                {"asset": asset_path, "error": repr(exc)}
            )
            continue
        result = compare_graph(
            graphs[original_name], rebuilt_nodes, values
        )
        result["original_graph"] = original_name
        result["t3d"] = t3d_path
        report["assets"][asset_path] = result
    write_json(report_path(config, "verify_materials.json"), report)
    lines = [
        "# PortKit material verification",
        "",
        "| asset | original graph | nodes | connections | missing | added | match |",
        "|---|---|---:|---:|---:|---:|---|",
    ]
    for asset_path, result in sorted(report["assets"].items()):
        lines.append(
            "| `%s` | `%s` | %d -> %d | %d -> %d | %d | %d | %s |"
            % (
                asset_path,
                result["original_graph"],
                result["original_node_count"],
                result["rebuilt_node_count"],
                result["original_connection_count"],
                result["rebuilt_connection_count"],
                len(result["missing_connections"]),
                len(result["added_connections"]),
                "yes" if result["match"] else "no",
            )
        )
    lines.extend(
        [
            "",
            "Export failures: %d" % len(report["export_failures"]),
            "",
            "Parse failures: %d" % len(report["parse_failures"]),
            "",
        ]
    )
    write_text(report_path(config, "verify_materials.md"), "\n".join(lines))
    unreal.log(
        "[PortKit] verified=%d export_fail=%d parse_fail=%d report=%s"
        % (
            len(report["assets"]),
            len(report["export_failures"]),
            len(report["parse_failures"]),
            report_path(config, "verify_materials.json"),
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
        failure = {"errors": [traceback.format_exc()], "assets": {}}
        write_json(report_path(config, "verify_materials.json"), failure)
        if unreal is not None:
            unreal.log_error("[PortKit] verification failed; see report")
        else:
            raise


if __name__ == "__main__":
    main()
