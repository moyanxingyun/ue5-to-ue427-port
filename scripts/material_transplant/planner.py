# -*- coding: utf-8 -*-
"""Plan 4.27 switch combinations and report unsupported material nodes.

Environment:
    Plain Python 3.7+; no ``unreal`` module required.

Use:
    python planner.py --config config.json --check

Output:
    Console summary and JSON report at paths.reports/offline_check.json.
"""
import argparse
import hashlib
import json
import os
import sys

try:
    from .t3d_parser import load_graphs, strip_q, switch_params
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from material_transplant.t3d_parser import load_graphs, strip_q, switch_params

try:
    from portkit_config import load_config, path_value, report_path, write_json
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from portkit_config import load_config, path_value, report_path, write_json


BREAK_UE5 = [
    "BaseColor",
    "Metallic",
    "Specular",
    "Roughness",
    "Anisotropy",
    "EmissiveColor",
    "Opacity",
    "OpacityMask",
    "Normal",
    "Tangent",
    "WorldPositionOffset",
    "SubsurfaceColor",
    "ClearCoat",
    "ClearCoatRoughness",
    "AmbientOcclusion",
    "Refraction",
] + ["CustomizedUV%d" % index for index in range(8)] + [
    "PixelDepthOffset",
    "ShadingModel",
]
TS_OUT = ["RGB", "R", "G", "B", "A", "RGBA"]
V_OUT = ["", "R", "G", "B", "A", "RGBA"]
BYPASS = {
    "MaterialExpressionReroute",
    "MaterialExpressionNamedRerouteDeclaration",
    "MaterialExpressionNamedRerouteUsage",
    "MaterialExpressionStaticSwitchParameter",
}
WA_FUNCS = ("WorldAlignedTexture", "WorldAlignedNormal2", "WorldAlignedNormal")


def plan(graphs, infos, master_name, func_dir):
    """Return switch dependencies and the exact baked-material combinations."""
    own = {name: switch_params(nodes) for name, nodes in graphs.items()}
    defaults = {}
    for values in own.values():
        defaults.update(values)
    calls = {
        name: sorted(
            {
                node["func"].split("/")[-1]
                for node in nodes.values()
                if node["cls"] == "MaterialExpressionMaterialFunctionCall"
                and node["func"]
                and node["func"].startswith(func_dir)
            }
        )
        for name, nodes in graphs.items()
    }
    deps = {}

    def dependency(name, stack=()):
        if name in deps:
            return deps[name]
        values = set(own.get(name, {}))
        for called in calls.get(name, []):
            if called in graphs and called not in stack:
                values |= dependency(called, stack + (name,))
        deps[name] = values
        return values

    for graph_name in graphs:
        dependency(graph_name)

    combos = []
    mi_combo = {}
    for mi_name, info in sorted(infos.items()):
        parents = info.get("parents") or []
        if not parents or master_name not in parents[-1]:
            continue
        values = dict(defaults)
        for key, value in info.get("switches", {}).items():
            if key in values and value is not None:
                values[key] = bool(value)
        key = tuple(
            sorted((name, values[name]) for name in deps.get(master_name, set()))
        )
        if key not in combos:
            combos.append(key)
        mi_combo[mi_name] = combos.index(key)
    return {
        "defaults": defaults,
        "deps": deps,
        "calls": calls,
        "combos": combos,
        "mi_combo": mi_combo,
    }


def variant_name(graph, values, deps, func_dir, variant_dir=None):
    keys = sorted(deps[graph])
    if not keys:
        return graph, func_dir
    signature = "|".join("%s=%d" % (key, int(values[key])) for key in keys)
    digest = hashlib.md5(signature.encode("utf-8")).hexdigest()[:6]
    return (
        "%s__%s" % (graph, digest),
        variant_dir or (func_dir.rstrip("/") + "/Variants"),
    )


def out_name(node, index):
    cls = node["cls"]
    if cls == "MaterialExpressionMaterialFunctionCall":
        if index < len(node["outputs"]):
            return node["outputs"][index]
        return ""
    if cls == "MaterialExpressionBreakMaterialAttributes":
        return BREAK_UE5[index] if index < len(BREAK_UE5) else ""
    if cls in (
        "MaterialExpressionTextureSample",
        "MaterialExpressionTextureSampleParameter2D",
    ):
        return TS_OUT[index] if index < len(TS_OUT) else ""
    return V_OUT[index] if 0 < index < len(V_OUT) else ""


def make_resolver(nodes, values, created):
    declarations = {
        node["name"]: node
        for node in nodes.values()
        if node["cls"] == "MaterialExpressionNamedRerouteDeclaration"
    }

    def resolve(ref, depth=0):
        if ref is None or depth > 64 or ref["node"] not in nodes:
            return None
        node = nodes[ref["node"]]
        cls = node["cls"]
        if cls in (
            "MaterialExpressionReroute",
            "MaterialExpressionNamedRerouteDeclaration",
        ):
            return resolve(_first_input(node, "Input"), depth + 1)
        if cls == "MaterialExpressionNamedRerouteUsage":
            declaration = declarations.get(node["props"].get("Declaration"))
            if declaration:
                return resolve(
                    _first_input(declaration, "Input"), depth + 1
                )
            return None
        if cls == "MaterialExpressionStaticSwitchParameter":
            enabled = values.get(
                strip_q(node["props"].get("ParameterName", '""')), False
            )
            return resolve(
                _first_input(node, "A" if enabled else "B"), depth + 1
            )
        if node["name"] not in created:
            return None
        resolve.last = (node["name"], ref["idx"])
        return created[node["name"]], out_name(node, ref["idx"])

    resolve.last = None
    return resolve


def _first_input(node, prop):
    for input_prop, _index, _name, ref in node["inputs"]:
        if input_prop == prop:
            return ref
    return None


def make_comps(nodes, values, func_input_types=None):
    """Infer a raw output's component count; 4 is only returned when certain."""
    del func_input_types
    memo = {}
    resolve_raw = make_resolver(
        nodes, values, {name: name for name in nodes}
    )

    def comps_ref(ref, depth=0):
        if ref is None or depth > 40 or resolve_raw(ref) is None:
            return 0
        name, index = resolve_raw.last
        return comps(name, index, depth + 1)

    def comps(name, index, depth=0):
        key = (name, index)
        if key in memo:
            return memo[key]
        memo[key] = 0
        node = nodes[name]
        cls = node["cls"]
        count = 0
        if cls == "MaterialExpressionMaterialFunctionCall":
            short = (node["func"] or "").split("/")[-1]
            output = (
                node["outputs"][index] if index < len(node["outputs"]) else ""
            )
            if short in WA_FUNCS and output in (
                "XYZ Texture",
                "XY Texture",
                "Z Texture",
            ):
                count = 4
        elif cls in (
            "MaterialExpressionTextureSample",
            "MaterialExpressionTextureSampleParameter2D",
        ):
            count = [3, 1, 1, 1, 1, 4][index] if index < 6 else 0
        elif cls == "MaterialExpressionConstant4Vector":
            count = 4 if index == 0 else 1
        elif cls in (
            "MaterialExpressionVectorParameter",
            "MaterialExpressionConstant3Vector",
            "MaterialExpressionConstant2Vector",
        ):
            if index == 0:
                count = 4 if cls == "MaterialExpressionVectorParameter" else (
                    3
                    if cls == "MaterialExpressionConstant3Vector"
                    else 2
                )
            elif 1 <= index <= 4:
                count = 1
        elif cls == "MaterialExpressionScalarParameter":
            count = 1
        elif cls in (
            "MaterialExpressionPower",
            "MaterialExpressionSaturate",
            "MaterialExpressionOneMinus",
            "MaterialExpressionClamp",
            "MaterialExpressionFrac",
            "MaterialExpressionSine",
        ):
            source = node["inputs"][0][3] if node["inputs"] else None
            for prop, _index, _input_name, ref in node["inputs"]:
                if prop in ("Base", "Input"):
                    source = ref
            count = comps_ref(source, depth)
        elif cls in (
            "MaterialExpressionMultiply",
            "MaterialExpressionAdd",
            "MaterialExpressionSubtract",
            "MaterialExpressionDivide",
            "MaterialExpressionLinearInterpolate",
            "MaterialExpressionStaticSwitch",
        ):
            count = max(
                [
                    comps_ref(ref, depth)
                    for prop, _index, _input_name, ref in node["inputs"]
                    if prop in ("A", "B")
                ]
                or [0]
            )
        memo[key] = count
        return count

    return comps


def needs_lerp_alpha_r(nodes, values, node):
    """Return True when a Lerp alpha is inferred to carry more than one channel."""
    if node["cls"] != "MaterialExpressionLinearInterpolate":
        return False
    alpha = _first_input(node, "Alpha")
    if alpha is None:
        return False
    return make_comps(nodes, values)(
        alpha["node"], alpha["idx"]
    ) > 1


def _probe_classes(probe):
    if not isinstance(probe, dict):
        return None
    for key in ("createable_classes", "creatable_classes"):
        value = probe.get(key)
        if isinstance(value, list) and value:
            return set(value)
    # Compatibility with older probes: every successfully tested expression
    # class appears as a prefix in the input-pin map.
    classes = set()
    for key in (probe.get("inputs") or {}):
        if key.startswith("MaterialExpression") and "." in key:
            classes.add(key.split(".", 1)[0])
    for key in (probe.get("outputs") or {}):
        classes.add("MaterialExpression" + key)
    return classes or None


def report_unsupported(
    graphs,
    probe_427=None,
    combo_count=0,
    max_combos=50,
    bypass=None,
):
    bypass = set(bypass or BYPASS)
    createable = _probe_classes(probe_427)
    counts = {}
    custom = []
    unsupported = []
    for graph_name, nodes in graphs.items():
        for node in nodes.values():
            cls = node["cls"]
            own_count = counts.setdefault(
                graph_name, {"nodes": {}, "custom": 0}
            )
            own_count["nodes"][cls] = own_count["nodes"].get(cls, 0) + 1
            if cls == "MaterialExpressionCustom":
                own_count["custom"] += 1
                custom.append("%s:%s" % (graph_name, node["name"]))
            elif createable is not None and cls not in createable and cls not in bypass:
                unsupported.append("%s:%s" % (graph_name, node["name"]))
    return {
        "graph_counts": counts,
        "unsupported_nodes": sorted(unsupported),
        "custom_nodes": sorted(custom),
        "combination_count": int(combo_count),
        "max_combos": int(max_combos),
        "needs_confirm": bool(custom or unsupported or combo_count > max_combos),
        "createable_classes_available": createable is not None,
    }


def external_dependency_paths(graphs, dumps_dir):
    found = {}
    known = set(graphs)
    for graph_name, nodes in graphs.items():
        for node in nodes.values():
            func = node.get("func")
            if (
                node["cls"] == "MaterialExpressionMaterialFunctionCall"
                and func
                and func.split("/")[-1] not in known
            ):
                found.setdefault(func, set()).add(graph_name)
    return {key: sorted(value) for key, value in sorted(found.items())}


def offline_plan(config, write_report=True):
    material = config.get("material", {})
    dumps_dir = path_value(config, "paths", "dumps")
    materials_json = path_value(config, "paths", "materials_json")
    probe_json = path_value(config, "paths", "probe_427")
    master_name = material.get("master_name")
    func_dir = material.get("func_dir")
    if not dumps_dir or not materials_json or not master_name or not func_dir:
        raise ValueError(
            "config requires paths.dumps, paths.materials_json, "
            "material.master_name and material.func_dir"
        )
    graphs = load_graphs(dumps_dir)
    with open(materials_json, "r", encoding="utf-8") as handle:
        infos = json.load(handle)
    plan_data = plan(graphs, infos, master_name, func_dir)
    probe = None
    if probe_json and os.path.isfile(probe_json):
        with open(probe_json, "r", encoding="utf-8") as handle:
            probe = json.load(handle)
    unsupported = report_unsupported(
        graphs,
        probe,
        len(plan_data["combos"]),
        int(material.get("max_combos", 50)),
    )
    external = external_dependency_paths(graphs, dumps_dir)
    result = {
        "master_name": master_name,
        "graph_count": len(graphs),
        "instance_count": len(plan_data["mi_combo"]),
        "combination_count": len(plan_data["combos"]),
        "dependencies": {
            key: sorted(value) for key, value in plan_data["deps"].items()
        },
        "calls": plan_data["calls"],
        "external_function_paths": external,
        "unsupported": unsupported,
        "combos": [
            [{"name": name, "value": value} for name, value in combo]
            for combo in plan_data["combos"]
        ],
        "instance_combo": plan_data["mi_combo"],
    }
    if write_report:
        write_json(report_path(config, "offline_check.json"), result)
    return result, plan_data, graphs, infos


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", help="Path to PortKit JSON config")
    parser.add_argument(
        "--check", action="store_true", help="Write an offline plan report"
    )
    args = parser.parse_args()
    config = load_config(args.config)
    result, _plan_data, _graphs, _infos = offline_plan(config)
    print(
        "graphs=%d instances=%d combinations=%d unsupported=%d custom=%d needs_confirm=%s"
        % (
            result["graph_count"],
            result["instance_count"],
            result["combination_count"],
            len(result["unsupported"]["unsupported_nodes"]),
            len(result["unsupported"]["custom_nodes"]),
            result["unsupported"]["needs_confirm"],
        )
    )
    if result["external_function_paths"]:
        print(
            "WARNING external material functions: %d"
            % len(result["external_function_paths"])
        )
    print("report=%s" % report_path(config, "offline_check.json"))


if __name__ == "__main__":
    main()
