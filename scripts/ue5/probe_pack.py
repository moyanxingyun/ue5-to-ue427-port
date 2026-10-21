# -*- coding: utf-8 -*-
"""Inspect a UE5 resource pack before choosing a 4.27 port strategy.

Environment:
    Unreal Engine 5.4 Editor Python, Cmd mode.

Use:
    py "PATH/TO/PortKit/scripts/ue5/probe_pack.py" --config "PATH/TO/config.json"

Output:
    paths.reports/summary.json and summary.txt with asset classes, material
    node-type counts, Custom nodes, UE5-only candidates and static-switch
    combination counts.
"""
import argparse
import collections
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

from portkit_config import load_config, path_value, report_path, write_json, write_text
from material_transplant.planner import plan
from material_transplant.t3d_parser import load_graphs, switch_params
from ue5.export_common import class_name, material_info

try:
    import unreal
except ImportError:
    unreal = None


UE5_ONLY_TOKENS = (
    "Substrate",
    "MaterialLayer",
    "VirtualTexture",
    "Nanite",
    "RuntimeVirtualTexture",
)


def _asset_class_counts(root):
    eal = unreal.EditorAssetLibrary
    counts = collections.Counter()
    for path in eal.list_assets(root, recursive=True, include_folder=False):
        counts[class_name(eal.find_asset_data(path))] += 1
    return dict(sorted(counts.items()))


def _instance_infos(root, master_name):
    eal = unreal.EditorAssetLibrary
    infos = {}
    for path in eal.list_assets(root, recursive=True, include_folder=False):
        if class_name(eal.find_asset_data(path)) != "MaterialInstanceConstant":
            continue
        instance = unreal.load_asset(path)
        if instance is None:
            continue
        info = material_info(instance)
        parents = info.get("parents") or []
        if parents and master_name in parents[-1]:
            infos[path.split(".")[0]] = info
    return infos


def run(config):
    if unreal is None:
        raise RuntimeError("Run probe_pack.py inside UE 5.4 Editor Python")
    ue5 = config.get("ue5", {})
    probe_options = ue5.get("probe", {})
    roots = probe_options.get("asset_roots", [ue5.get("asset_root")])
    roots = [root for root in roots if root]
    if not roots:
        raise ValueError("ue5.asset_root or ue5.probe.asset_roots is required")
    material = config.get("material", {})
    master_name = material.get("master_name")
    func_dir = material.get("func_dir")
    dumps_dir = path_value(config, "paths", "dumps")
    summary = {
        "project": config.get("project", {}).get("name", ""),
        "asset_roots": roots,
        "asset_classes": {},
        "materials": {},
        "errors": [],
    }
    for root in roots:
        summary["asset_classes"][root] = _asset_class_counts(root)
    try:
        # Probe imports dump_graphs lazily to keep the standalone parser usable
        # outside UE when this module is inspected.
        from ue5.dump_graphs import run as dump_run

        dump_report = dump_run(config)
        summary["dump_graphs"] = {
            "written": len(dump_report.get("written", [])),
            "skipped": len(dump_report.get("skipped", [])),
            "missing": dump_report.get("missing", []),
            "errors": dump_report.get("errors", []),
        }
        graphs = load_graphs(dumps_dir)
        node_counts = {
            name: dict(
                sorted(
                    collections.Counter(
                        node["cls"] for node in nodes.values()
                    ).items()
                )
            )
            for name, nodes in graphs.items()
        }
        custom_nodes = [
            "%s:%s" % (graph_name, node["name"])
            for graph_name, nodes in graphs.items()
            for node in nodes.values()
            if node["cls"] == "MaterialExpressionCustom"
        ]
        ue5_only = sorted(
            {
                node["cls"]
                for nodes in graphs.values()
                for node in nodes.values()
                if any(token in node["cls"] for token in UE5_ONLY_TOKENS)
            }
        )
        switch_defaults = {
            name: switch_params(nodes) for name, nodes in graphs.items()
        }
        infos = _instance_infos(roots[0], master_name)
        combos = []
        if master_name in graphs and func_dir:
            combos = plan(
                graphs, infos, master_name, func_dir
            )["combos"]
        summary["materials"] = {
            "graph_count": len(graphs),
            "node_type_counts": node_counts,
            "custom_nodes": custom_nodes,
            "ue5_only_candidates": ue5_only,
            "static_switch_defaults": switch_defaults,
            "material_instances": len(infos),
            "switch_combinations": len(combos),
        }
    except Exception:
        summary["errors"].append(traceback.format_exc())
    write_json(report_path(config, "summary.json"), summary)
    lines = [
        "PortKit pack summary",
        "",
        "project: %s" % summary["project"],
        "asset classes:",
    ]
    for root, counts in summary["asset_classes"].items():
        lines.append("  %s" % root)
        for key, value in counts.items():
            lines.append("    %s: %d" % (key, value))
    materials = summary.get("materials", {})
    lines.extend(
        [
            "",
            "material graphs: %d" % materials.get("graph_count", 0),
            "material instances: %d" % materials.get("material_instances", 0),
            "switch combinations: %d"
            % materials.get("switch_combinations", 0),
            "custom nodes: %d" % len(materials.get("custom_nodes", [])),
            "UE5-only candidates: %s"
            % (", ".join(materials.get("ue5_only_candidates", [])) or "none"),
        ]
    )
    if summary["errors"]:
        lines.extend(["", "ERRORS"] + summary["errors"])
    write_text(report_path(config, "summary.txt"), "\n".join(lines))
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", help="Path to PortKit JSON config")
    args = parser.parse_args()
    config = load_config(args.config)
    try:
        run(config)
    except Exception:
        if unreal is not None:
            write_json(
                report_path(config, "summary.json"),
                {"errors": [traceback.format_exc()]},
            )
            unreal.log_error("[PortKit] probe_pack failed")
        else:
            raise


if __name__ == "__main__":
    main()
