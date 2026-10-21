# -*- coding: utf-8 -*-
"""Rebuild a UE5 material graph in UE 4.27 from normalized expression dumps.

Environment:
    UE 4.27 Editor Python 3.7, Cmd mode.

Use:
    py "PATH/TO/PortKit/scripts/material_transplant/build_ue427.py" --config "PATH/TO/config.json"

Output:
    Rebuilt material functions, baked switch-combination masters, material
    instances and mesh material assignments. A resumable JSON report is written
    to paths.reports/rebuild_log.json. Existing assets are skipped unless
    material.rebuild_existing is true.
"""
import argparse
import hashlib
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
from material_transplant.planner import (
    make_comps,
    needs_lerp_alpha_r,
    plan,
    report_unsupported,
    variant_name,
)
from material_transplant.rules_ue427 import (
    BYPASS,
    ROOT_PINS,
    SCALAR_ATTRS,
    SKIP_PROPS,
    VEC3_ATTRS,
    first_input,
    in_name,
    make_resolver,
    material_property_for_pin,
    positive_pow_enabled,
)
from material_transplant.t3d_parser import load_graphs, strip_q

try:
    import unreal
except ImportError:
    unreal = None


REPORT = {
    "steps": [],
    "graphs": {},
    "prop_fail": {},
    "connect_fail": [],
    "missing_textures": [],
    "errors": [],
}
HAVE_UE = unreal is not None


def _override(name, default):
    return globals().get(name, default)


def _load_runtime(config):
    material = config.get("material", {})
    runtime = {
        "dumps": path_value(config, "paths", "dumps"),
        "materials_json": path_value(config, "paths", "materials_json"),
        "materials_extra_json": path_value(
            config, "paths", "materials_extra_json"
        ),
        "manifest": path_value(config, "paths", "manifest"),
        "textures_map": path_value(config, "paths", "textures_map"),
        "textures_map_extra": path_value(
            config, "paths", "textures_map_extra"
        ),
        "textures_dir": path_value(config, "paths", "textures"),
        "textures_extra_dir": path_value(config, "paths", "textures_extra"),
        "settings": path_value(config, "paths", "settings"),
        "master_name": material.get("master_name"),
        "func_dir": material.get("func_dir"),
        "combo_dir": material.get("combo_dir"),
        "variant_dir": material.get(
            "variant_dir",
            (material.get("func_dir") or "").rstrip("/") + "/Variants",
        ),
        "struct_meshes": config.get("ue427", {}).get("struct_meshes"),
        "native_pow": bool(material.get("native_pow", False)),
        "max_combos": int(material.get("max_combos", 50)),
        "only_combos": _override("ONLY_COMBOS", material.get("only_combos")),
        "master_range": _override(
            "MASTER_RANGE", material.get("master_range")
        ),
        "rebuild_existing": bool(
            _override(
                "REBUILD_EXISTING",
                material.get("rebuild_existing", False),
            )
        ),
        "do_textures": bool(
            _override("DO_TEXTURES", material.get("do_textures", True))
        ),
        "do_meshes": bool(
            _override("DO_MESHES", material.get("do_meshes", True))
        ),
        "extra": bool(_override("EXTRA", material.get("extra", False))),
        "extra_filter": _override(
            "EXTRA_FILTER", material.get("extra_filter", "")
        ),
        "fix_functions": list(
            _override("FIX_FUNCTIONS", material.get("fix_functions", []))
        ),
        "rebuild_funcs": set(
            _override("REBUILD_FUNCS", material.get("rebuild_funcs", []))
        ),
    }
    required = ("dumps", "materials_json", "master_name", "func_dir", "combo_dir")
    missing = [name for name in required if not runtime.get(name)]
    if missing:
        raise ValueError("Missing config values: %s" % ", ".join(missing))
    return runtime


class Runtime(object):
    def __init__(self, config, values):
        self.config = config
        self.values = values
        self.graphs = {}
        self.infos = {}
        self.plan_data = None
        self.settings = {}
        self.emissive_default = 1.0
        self.built = {}
        self.progress = None

    @property
    def eal(self):
        return unreal.EditorAssetLibrary

    @property
    def mel(self):
        return unreal.MaterialEditingLibrary

    @property
    def tools(self):
        return unreal.AssetToolsHelpers.get_asset_tools()

    def tick(self, message=""):
        if self.progress is not None:
            self.progress.enter_progress_frame(1, message)
        if self.progress is not None and self.progress.should_cancel():
            raise RuntimeError("cancelled by user")


def snake(key):
    if key.startswith("b") and len(key) > 1 and key[1].isupper():
        key = key[1:]
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", key).lower()


def num_list(value):
    return [float(number) for number in re.findall(r"=(-?[\d.eE+-]+)", value)]


def enum_value(current, raw):
    enum_type = type(current)
    wanted = re.sub(r"[^A-Z0-9]", "", raw.upper())
    for member in dir(enum_type):
        if member.isupper() and re.sub(r"[^A-Z0-9]", "", member) == wanted:
            return getattr(enum_type, member)
    return None


def load_texture(runtime, raw):
    match = re.search(r"Texture2D'([^']+)'", raw)
    if not match:
        return None
    asset_path = match.group(1).split(".")[0]
    if runtime.eal.does_asset_exist(asset_path):
        return unreal.load_asset(asset_path)
    REPORT["missing_textures"].append(asset_path)
    return None


def set_prop(runtime, obj, key, raw, graph_name):
    python_name = snake(key)
    try:
        if key == "Texture":
            texture = load_texture(runtime, raw)
            if texture is not None:
                obj.set_editor_property("texture", texture)
            return
        current = obj.get_editor_property(python_name)
        if isinstance(current, bool):
            value = raw == "True"
        elif isinstance(current, unreal.EnumBase):
            value = enum_value(current, raw)
            if value is None:
                raise ValueError("enum not found: " + raw)
        elif isinstance(current, int):
            value = int(float(raw))
        elif isinstance(current, float):
            value = float(raw)
        elif isinstance(current, unreal.LinearColor):
            numbers = num_list(raw)
            padded = (numbers + [1.0] * 4)[:4]
            value = unreal.LinearColor(*padded)
        elif isinstance(current, unreal.Vector4):
            numbers = num_list(raw)
            padded = (numbers + [0.0] * 4)[:4]
            value = unreal.Vector4(*padded)
        else:
            value = strip_q(raw)
        obj.set_editor_property(python_name, value)
    except Exception as exc:
        report_key = "%s.%s" % (type(obj).__name__, key)
        REPORT["prop_fail"].setdefault(report_key, repr(exc)[:240])
        if graph_name:
            REPORT["prop_fail"].setdefault(
                "graph:" + graph_name, "one or more properties failed"
            )


def connect(runtime, source, source_pin, target, target_pin, label):
    try:
        succeeded = bool(
            runtime.mel.connect_material_expressions(
                source, source_pin, target, target_pin
            )
        )
    except Exception as exc:
        succeeded = False
        REPORT["connect_fail"].append(
            "%s exception=%r" % (label, exc)
        )
    if not succeeded:
        REPORT["connect_fail"].append(label)
    return succeeded


def connect_property(runtime, source, source_pin, property_value, label):
    try:
        succeeded = bool(
            runtime.mel.connect_material_property(
                source, source_pin, property_value
            )
        )
    except Exception as exc:
        succeeded = False
        REPORT["connect_fail"].append(
            "%s exception=%r" % (label, exc)
        )
    if not succeeded:
        REPORT["connect_fail"].append(label)
    return succeeded


def positive_pow_output_type_name(component_count):
    """Return the Custom output enum name for 1-4 channels, or None for unknown."""
    if component_count < 1 or component_count > 4:
        return None
    return "CMOT_FLOAT%d" % component_count


def positive_pow_base_components(nodes, values, node):
    base_ref = first_input(node, "Base")
    if base_ref is None:
        return 0
    comps = make_comps(nodes, values)
    return comps(base_ref["node"], base_ref["idx"])


def build_graph(
    runtime,
    graph_name,
    nodes,
    owner,
    is_function,
    values,
    func_for_path,
    emissive_default,
):
    if is_function:
        runtime.mel.delete_all_material_expressions_in_function(owner)
    else:
        runtime.mel.delete_all_material_expressions(owner)

    def create(class_name, x, y):
        cls = getattr(unreal, class_name)
        if is_function:
            return runtime.mel.create_material_expression_in_function(
                owner, cls, x, y
            )
        return runtime.mel.create_material_expression(owner, cls, x, y)

    created = {}
    comps = make_comps(nodes, values)
    stats = {
        "nodes": 0,
        "wires": 0,
        "connect_fail": 0,
        "skipped": 0,
    }
    for node in nodes.values():
        runtime.tick("Create %s" % node["name"])
        cls = node["cls"]
        if cls in BYPASS:
            continue
        try:
            if cls == "MaterialExpressionStaticBoolParameter":
                obj = create(
                    "MaterialExpressionStaticBool", node["x"], node["y"]
                )
                obj.set_editor_property(
                    "value",
                    values.get(
                        strip_q(node["props"].get("ParameterName", '""')),
                        False,
                    ),
                )
            elif cls == "MaterialExpressionDistanceFieldApproxAO":
                obj = create(
                    "MaterialExpressionConstant", node["x"], node["y"]
                )
                obj.set_editor_property("r", 1.0)
            elif (
                cls == "MaterialExpressionPower"
                and positive_pow_enabled(runtime.values)
            ):
                base_components = positive_pow_base_components(
                    nodes, values, node
                )
                output_type_name = positive_pow_output_type_name(
                    base_components
                )
                if output_type_name is None:
                    obj = create(cls, node["x"], node["y"])
                    for key, raw in node["props"].items():
                        if key not in SKIP_PROPS:
                            set_prop(runtime, obj, key, raw, graph_name)
                    stats["pow_skipped"] = stats.get("pow_skipped", 0) + 1
                else:
                    obj = create(
                        "MaterialExpressionCustom", node["x"], node["y"]
                    )
                    wired_exp = any(
                        prop == "Exponent"
                        for prop, _index, _name, _ref in node["inputs"]
                    )
                    pins = ["Base", "Exp"] if wired_exp else ["Base"]
                    exponent = (
                        "Exp"
                        if wired_exp
                        else repr(
                            float(
                                node["props"].get("ConstExponent", "2.0")
                            )
                        )
                    )
                    custom_inputs = []
                    for pin in pins:
                        custom_input = unreal.CustomInput()
                        custom_input.set_editor_property("input_name", pin)
                        custom_inputs.append(custom_input)
                    obj.set_editor_property("inputs", custom_inputs)
                    obj.set_editor_property(
                        "output_type",
                        getattr(
                            unreal.CustomMaterialOutputType,
                            output_type_name,
                        ),
                    )
                    obj.set_editor_property(
                        "description", "PortKit PositiveClampedPow"
                    )
                    obj.set_editor_property(
                        "code",
                        "return pow(max(Base, 0.0), %s);" % exponent,
                    )
                    stats["pow_fixed"] = stats.get("pow_fixed", 0) + 1
            elif cls == "MaterialExpressionCollectionParameter":
                obj = create(
                    "MaterialExpressionScalarParameter",
                    node["x"],
                    node["y"],
                )
                obj.set_editor_property(
                    "parameter_name",
                    strip_q(node["props"].get("ParameterName", '"MPC"')),
                )
                obj.set_editor_property("default_value", emissive_default)
            else:
                obj = create(cls, node["x"], node["y"])
                if (
                    cls == "MaterialExpressionMaterialFunctionCall"
                    and node["func"]
                ):
                    function = func_for_path(node["func"])
                    if function is None:
                        REPORT["connect_fail"].append(
                            "missing function %s in %s"
                            % (node["func"], graph_name)
                        )
                    else:
                        obj.set_editor_property(
                            "material_function", function
                        )
                if cls == "MaterialExpressionComponentMask":
                    for channel in ("r", "g", "b", "a"):
                        obj.set_editor_property(channel, False)
                for key, raw in node["props"].items():
                    if key not in SKIP_PROPS:
                        set_prop(runtime, obj, key, raw, graph_name)
            created[node["name"]] = obj
            stats["nodes"] += 1
        except Exception as exc:
            stats["skipped"] += 1
            REPORT["errors"].append(
                "create %s %s: %r" % (cls, node["name"], exc)
            )

    resolve = make_resolver(nodes, values, created)
    for node in nodes.values():
        if node["name"] not in created or node["cls"] in (
            "MaterialExpressionStaticBoolParameter",
        ):
            continue
        runtime.tick("Connect %s" % node["name"])
        destination = created[node["name"]]
        for prop, index, input_name, ref in node["inputs"]:
            source = resolve(ref)
            if source is None:
                continue
            source_obj, source_pin = source
            target_pin = in_name(node, prop, index, input_name)
            if target_pin.startswith("CustomizedUV"):
                continue
            raw_source = resolve.last
            label = "%s.%s <- %s[%s]" % (
                node["name"],
                target_pin or prop,
                ref["node"],
                source_pin,
            )
            if (
                node["cls"] == "MaterialExpressionLinearInterpolate"
                and prop == "Alpha"
                and needs_lerp_alpha_r(nodes, values, node)
            ):
                mask = create(
                    "MaterialExpressionComponentMask",
                    node["x"] - 150,
                    node["y"] + 60,
                )
                for channel, enabled in (
                    ("r", True),
                    ("g", False),
                    ("b", False),
                    ("a", False),
                ):
                    mask.set_editor_property(channel, enabled)
                connect(
                    runtime,
                    source_obj,
                    source_pin,
                    mask,
                    "",
                    label + " -> alpha mask",
                )
                source_obj, source_pin = mask, ""
            need_rgb = False
            if raw_source and comps(raw_source[0], raw_source[1]) == 4:
                if (
                    node["cls"] == "MaterialExpressionMakeMaterialAttributes"
                    and target_pin in VEC3_ATTRS
                ):
                    need_rgb = True
                elif node["cls"] == "MaterialExpressionMaterialFunctionCall":
                    function_types = runtime.values.get(
                        "function_input_types", {}
                    )
                    short = (node["func"] or "").split("/")[-1]
                    if (
                        function_types.get(short, {}).get(target_pin)
                        == "FunctionInput_Vector3"
                    ):
                        need_rgb = True
            if need_rgb:
                mask = create(
                    "MaterialExpressionComponentMask",
                    node["x"] - 150,
                    node["y"] + 40,
                )
                for channel, enabled in (
                    ("r", True),
                    ("g", True),
                    ("b", True),
                    ("a", False),
                ):
                    mask.set_editor_property(channel, enabled)
                connect(
                    runtime,
                    source_obj,
                    source_pin,
                    mask,
                    "",
                    label + " -> RGB mask",
                )
                source_obj, source_pin = mask, ""
                stats["rgb_masks"] = stats.get("rgb_masks", 0) + 1
            if (
                node["cls"] == "MaterialExpressionMakeMaterialAttributes"
                and target_pin in SCALAR_ATTRS
            ):
                mask = create(
                    "MaterialExpressionComponentMask",
                    node["x"] - 150,
                    node["y"],
                )
                for channel, enabled in (
                    ("r", True),
                    ("g", False),
                    ("b", False),
                    ("a", False),
                ):
                    mask.set_editor_property(channel, enabled)
                connect(
                    runtime,
                    source_obj,
                    source_pin,
                    mask,
                    "",
                    label + " -> scalar mask",
                )
                source_obj, source_pin = mask, ""
            if connect(
                runtime,
                source_obj,
                source_pin,
                destination,
                target_pin,
                label,
            ):
                stats["wires"] += 1

    if not is_function:
        consumed = set()
        for node in nodes.values():
            for _prop, _index, _name, ref in node["inputs"]:
                consumed.add(ref["node"])
        roots = [
            name
            for name, node in nodes.items()
            if node["cls"] == "MaterialExpressionMakeMaterialAttributes"
            and name not in consumed
            and name in created
        ]
        if roots:
            root = roots[0]
            attributes = create(
                "MaterialExpressionBreakMaterialAttributes",
                nodes[root]["x"] + 400,
                nodes[root]["y"],
            )
            connect(
                runtime,
                created[root],
                "",
                attributes,
                "",
                "root attributes -> break",
            )
            wired = []
            for output_name, property_name in ROOT_PINS:
                property_value = material_property_for_pin(
                    unreal.MaterialProperty, property_name
                )
                if property_value is not None and connect_property(
                    runtime,
                    attributes,
                    output_name,
                    property_value,
                    "root %s" % output_name,
                ):
                    wired.append(output_name)
            stats["root_pins"] = wired
        stats["root"] = roots[:1]
    stats["connect_fail"] = len(REPORT["connect_fail"])
    return stats


def pinfo(name):
    info = unreal.MaterialParameterInfo()
    info.set_editor_property("name", name)
    return info


def get_or_create(runtime, name, folder, cls, factory):
    path = folder + "/" + name
    if runtime.eal.does_asset_exist(path):
        return unreal.load_asset(path)
    return runtime.tools.create_asset(name, folder, cls, factory)


def import_texture_map(runtime, map_path, texture_dir, wanted=None):
    if not map_path or not os.path.isfile(map_path):
        REPORT["errors"].append("texture map missing: %s" % map_path)
        return
    with open(map_path, "r", encoding="utf-8") as handle:
        texture_map = json.load(handle)
    if not texture_dir or not os.path.isdir(texture_dir):
        REPORT["errors"].append("texture folder missing: %s" % texture_dir)
        return
    files = {
        os.path.splitext(name)[0]: os.path.join(texture_dir, name)
        for name in os.listdir(texture_dir)
    }
    done = skipped = failed = 0
    for stem, info in sorted(texture_map.items()):
        if wanted and stem not in wanted:
            continue
        runtime.tick("Texture %s" % stem)
        destination = info["path"]
        if runtime.eal.does_asset_exist(destination):
            skipped += 1
            continue
        if stem not in files:
            REPORT["missing_textures"].append(destination)
            failed += 1
            continue
        folder, name = destination.rsplit("/", 1)
        task = unreal.AssetImportTask()
        task.filename = files[stem]
        task.destination_path = folder
        task.destination_name = name
        task.automated = True
        task.replace_existing = True
        task.save = False
        runtime.tools.import_asset_tasks([task])
        imported = list(task.imported_object_paths)
        texture = unreal.load_asset(imported[0]) if imported else None
        if texture is None:
            REPORT["missing_textures"].append(destination)
            failed += 1
            continue
        compression = re.search(
            r"TC_\w+", str(info.get("compression", ""))
        )
        if compression:
            value = enum_value(
                texture.get_editor_property("compression_settings"),
                compression.group(0),
            )
            if value is not None:
                texture.set_editor_property("compression_settings", value)
        texture.set_editor_property("srgb", bool(info.get("srgb", True)))
        runtime.eal.save_loaded_asset(texture, False)
        done += 1
    REPORT["steps"].append(
        "textures imported=%d existing=%d failed=%d"
        % (done, skipped, failed)
    )


def apply_material_settings(runtime, material_asset, settings):
    for key, raw in settings.items():
        try:
            current = material_asset.get_editor_property(key)
            if isinstance(current, bool):
                value = raw in (True, "True")
            elif isinstance(current, float):
                value = float(raw)
            elif isinstance(current, unreal.EnumBase):
                match = re.search(r"\.(\w+)", str(raw))
                value = enum_value(
                    current, match.group(1) if match else str(raw)
                )
                if value is None:
                    continue
            elif isinstance(current, int):
                value = int(raw)
            else:
                continue
            material_asset.set_editor_property(key, value)
        except Exception as exc:
            REPORT["prop_fail"].setdefault(
                "material." + key, repr(exc)[:240]
            )
    material_asset.set_editor_property("use_material_attributes", False)


def load_func_input_types(graphs):
    result = {}
    for graph_name, nodes in graphs.items():
        values = {}
        for node in nodes.values():
            if node["cls"] == "MaterialExpressionFunctionInput":
                input_name = strip_q(
                    node["props"].get("InputName", '"In"')
                )
                values[input_name] = node["props"].get(
                    "InputType", "FunctionInput_Vector3"
                )
        result[graph_name] = values
    return result


def run_build(config):
    settings_values = _load_runtime(config)
    runtime = Runtime(config, settings_values)
    runtime.graphs = load_graphs(settings_values["dumps"])
    runtime.values["function_input_types"] = load_func_input_types(
        runtime.graphs
    )
    with open(settings_values["materials_json"], "r", encoding="utf-8") as handle:
        runtime.infos = json.load(handle)
    if settings_values["settings"] and os.path.isfile(
        settings_values["settings"]
    ):
        with open(
            settings_values["settings"], "r", encoding="utf-8"
        ) as handle:
            runtime.settings = json.load(handle)
    else:
        REPORT["errors"].append(
            "settings file missing; using material defaults"
        )
    for scalar in (
        runtime.settings.get("mpc", {}).get("scalars", [])
    ):
        if scalar.get("name") == "Global Emissive Intensity":
            runtime.emissive_default = float(scalar.get("default", 1.0))

    runtime.progress = unreal.ScopedSlowTask(
        max(100, len(runtime.graphs) * 4),
        "PortKit material reconstruction",
    )
    runtime.progress.make_dialog_visible()

    if settings_values["fix_functions"]:
        for graph_name in settings_values["fix_functions"]:
            runtime.tick("Fix %s" % graph_name)
            func = unreal.load_asset(
                settings_values["func_dir"] + "/" + graph_name
            )
            if func is None or graph_name not in runtime.graphs:
                REPORT["errors"].append("cannot fix " + graph_name)
                continue
            stats = build_graph(
                runtime,
                graph_name,
                runtime.graphs[graph_name],
                func,
                True,
                {},
                lambda path: (
                    unreal.load_asset(path)
                    if runtime.eal.does_asset_exist(path)
                    else None
                ),
                runtime.emissive_default,
            )
            runtime.mel.update_material_function(func)
            runtime.eal.save_loaded_asset(func, False)
            REPORT["graphs"][
                settings_values["func_dir"] + "/" + graph_name
            ] = stats
        return

    if settings_values["do_textures"]:
        extra = {}
        if settings_values["extra"]:
            with open(
                settings_values["materials_extra_json"],
                "r",
                encoding="utf-8",
            ) as handle:
                extra = {
                    key: value
                    for key, value in json.load(handle).items()
                    if key not in runtime.infos
                    and settings_values["extra_filter"]
                    in value.get("path", "")
                }
            wanted = {
                texture.split(".")[-1]
                for info in extra.values()
                for texture in info.get("textures", {}).values()
                if texture
            }
            import_texture_map(
                runtime,
                settings_values["textures_map_extra"],
                settings_values["textures_extra_dir"],
                wanted,
            )
        else:
            import_texture_map(
                runtime,
                settings_values["textures_map"],
                settings_values["textures_dir"],
            )

    runtime.plan_data = plan(
        runtime.graphs,
        runtime.infos,
        settings_values["master_name"],
        settings_values["func_dir"],
    )
    probe_path = path_value(config, "paths", "probe_427")
    probe = None
    if probe_path and os.path.isfile(probe_path):
        with open(probe_path, "r", encoding="utf-8") as handle:
            probe = json.load(handle)
    unsupported = report_unsupported(
        runtime.graphs,
        probe,
        len(runtime.plan_data["combos"]),
        settings_values["max_combos"],
    )
    REPORT["unsupported"] = unsupported
    if unsupported["needs_confirm"] and not runtime.values["only_combos"]:
        REPORT["errors"].append(
            "unsupported nodes/custom nodes/combination cap require confirmation"
        )
        return

    extra_infos = {}
    if settings_values["extra"]:
        with open(
            settings_values["materials_extra_json"], "r", encoding="utf-8"
        ) as handle:
            extra_infos = {
                key: value
                for key, value in json.load(handle).items()
                if key not in runtime.infos
                and settings_values["extra_filter"] in value.get("path", "")
            }
        for instance_name, info in sorted(extra_infos.items()):
            parents = info.get("parents") or []
            if not parents or settings_values["master_name"] not in parents[-1]:
                continue
            values = dict(runtime.plan_data["defaults"])
            for key, value in info.get("switches", {}).items():
                if key in values and value is not None:
                    values[key] = bool(value)
            combo = tuple(
                sorted(
                    (name, values[name])
                    for name in runtime.plan_data["deps"][
                        settings_values["master_name"]
                    ]
                )
            )
            if combo not in runtime.plan_data["combos"]:
                runtime.plan_data["combos"].append(combo)
            runtime.plan_data["mi_combo"][instance_name] = (
                runtime.plan_data["combos"].index(combo)
            )
        runtime.infos.update(extra_infos)

    combos = runtime.plan_data["combos"]
    if settings_values["only_combos"] is not None:
        combos = combos[: int(settings_values["only_combos"])]
    REPORT["steps"].append(
        "combinations to build=%d total=%d"
        % (len(combos), len(runtime.plan_data["combos"]))
    )

    def func_for_variant(function_path, values):
        short = function_path.split("/")[-1]
        if (
            function_path.startswith(settings_values["func_dir"])
            and short in runtime.graphs
        ):
            return build_function(short, values)
        if runtime.eal.does_asset_exist(function_path):
            return unreal.load_asset(function_path)
        return None

    def build_function(graph_name, values):
        name, folder = variant_name(
            graph_name,
            values,
            runtime.plan_data["deps"],
            settings_values["func_dir"],
            settings_values["variant_dir"],
        )
        path = folder + "/" + name
        if path in runtime.built:
            return runtime.built[path]
        for called in runtime.plan_data["calls"].get(graph_name, []):
            if called in runtime.graphs:
                build_function(called, values)
        function = get_or_create(
            runtime,
            name,
            folder,
            unreal.MaterialFunction,
            unreal.MaterialFunctionFactoryNew(),
        )
        runtime.built[path] = function
        needs_rebuild = bool(
            graph_name in settings_values["rebuild_funcs"]
            or settings_values["rebuild_existing"]
        )
        if (
            not needs_rebuild
            and runtime.mel.get_num_material_expressions_in_function(
                function
            )
            > 0
        ):
            REPORT["graphs"][path] = {
                "nodes": 0,
                "wires": 0,
                "connect_fail": 0,
                "skipped": 0,
                "kept": True,
            }
            return function
        runtime.tick("Function %s" % name)
        stats = build_graph(
            runtime,
            name,
            runtime.graphs[graph_name],
            function,
            True,
            values,
            lambda function_path: func_for_variant(
                function_path, values
            ),
            runtime.emissive_default,
        )
        runtime.mel.update_material_function(function)
        runtime.eal.save_loaded_asset(function, False)
        REPORT["graphs"][path] = stats
        return function

    masters = []
    master_parameter_names = []
    master_range = settings_values["master_range"]
    for combo_index, combo in enumerate(combos):
        combo_number = combo_index + 1
        if master_range is not None and not (
            int(master_range[0]) <= combo_number <= int(master_range[1])
        ):
            continue
        values = dict(runtime.plan_data["defaults"])
        values.update(dict(combo))
        name = "%s_C%02d" % (settings_values["master_name"], combo_number)
        material = get_or_create(
            runtime,
            name,
            settings_values["combo_dir"],
            unreal.Material,
            unreal.MaterialFactoryNew(),
        )
        if (
            not settings_values["rebuild_existing"]
            and runtime.mel.get_num_material_expressions(material) > 0
        ):
            REPORT.setdefault("kept_masters", []).append(name)
        else:
            apply_material_settings(
                runtime,
                material,
                runtime.settings.get("master", {}),
            )
            runtime.tick("Master %s" % name)
            stats = build_graph(
                runtime,
                name,
                runtime.graphs[settings_values["master_name"]],
                material,
                False,
                values,
                lambda function_path: func_for_variant(
                    function_path, values
                ),
                runtime.emissive_default,
            )
            runtime.mel.recompile_material(material)
            runtime.eal.save_loaded_asset(material, False)
            REPORT["graphs"][
                settings_values["combo_dir"] + "/" + name
            ] = stats
        masters.append(material)
        names = set()
        for getter in (
            runtime.mel.get_scalar_parameter_names,
            runtime.mel.get_vector_parameter_names,
            runtime.mel.get_texture_parameter_names,
        ):
            try:
                names |= {str(item) for item in getter(material)}
            except Exception:
                pass
        master_parameter_names.append(names)

    REPORT["steps"].append(
        "functions=%d masters=%d" % (len(runtime.built), len(masters))
    )
    if master_range is not None:
        return

    made = {}
    for instance_name, combo_index in sorted(
        runtime.plan_data["mi_combo"].items()
    ):
        if settings_values["extra"] and instance_name not in extra_infos:
            continue
        if combo_index >= len(masters):
            continue
        info = runtime.infos[instance_name]
        asset_path = info["path"].split(".")[0]
        folder, name = asset_path.rsplit("/", 1)
        instance = get_or_create(
            runtime,
            name,
            folder,
            unreal.MaterialInstanceConstant,
            unreal.MaterialInstanceConstantFactoryNew(),
        )
        runtime.mel.set_material_instance_parent(
            instance, masters[combo_index]
        )
        master_parameters = master_parameter_names[combo_index]
        scalar_values = []
        vector_values = []
        texture_values = []
        for key, value in info.get("scalars", {}).items():
            if value is None or (
                master_parameters and key not in master_parameters
            ):
                continue
            scalar_values.append(
                unreal.ScalarParameterValue(
                    parameter_info=pinfo(key),
                    parameter_value=float(value),
                )
            )
        for key, value in info.get("vectors", {}).items():
            if value is None or (
                master_parameters and key not in master_parameters
            ):
                continue
            vector_values.append(
                unreal.VectorParameterValue(
                    parameter_info=pinfo(key),
                    parameter_value=unreal.LinearColor(*value),
                )
            )
        for key, value in info.get("textures", {}).items():
            if not value or (
                master_parameters and key not in master_parameters
            ):
                continue
            texture_path = value.split(".")[0]
            if runtime.eal.does_asset_exist(texture_path):
                texture_values.append(
                    unreal.TextureParameterValue(
                        parameter_info=pinfo(key),
                        parameter_value=unreal.load_asset(texture_path),
                    )
                )
            else:
                REPORT["missing_textures"].append(texture_path)
        instance.set_editor_property(
            "scalar_parameter_values", scalar_values
        )
        instance.set_editor_property(
            "vector_parameter_values", vector_values
        )
        instance.set_editor_property(
            "texture_parameter_values", texture_values
        )
        runtime.mel.update_material_instance(instance)
        runtime.eal.save_loaded_asset(instance, False)
        made[instance_name] = instance
        runtime.tick("Instance %s" % instance_name)

    REPORT["steps"].append("instances=%d" % len(made))
    if (
        settings_values["do_meshes"]
        and settings_values["manifest"]
        and os.path.isfile(settings_values["manifest"])
        and settings_values["struct_meshes"]
    ):
        with open(
            settings_values["manifest"], "r", encoding="utf-8"
        ) as handle:
            manifest = json.load(handle)
        changed = 0
        for mesh_name, entry in manifest.items():
            mesh_path = (
                settings_values["struct_meshes"].rstrip("/")
                + "/"
                + mesh_name
            )
            if not runtime.eal.does_asset_exist(mesh_path):
                continue
            mesh = unreal.load_asset(mesh_path)
            slots = entry.get("slots", [])
            by_name = {}
            for slot in slots:
                by_name[slot["slot"]] = slot
                by_name[slot["material"]] = slot
            materials = mesh.get_editor_property("static_materials")
            touched = False
            for index, static_material in enumerate(materials):
                entry_slot = by_name.get(
                    str(static_material.material_slot_name)
                )
                if entry_slot is None and index < len(slots):
                    entry_slot = slots[index]
                if (
                    entry_slot
                    and entry_slot["material"] in made
                ):
                    static_material.material_interface = made[
                        entry_slot["material"]
                    ]
                    materials[index] = static_material
                    touched = True
            if touched:
                mesh.set_editor_property("static_materials", materials)
                runtime.eal.save_loaded_asset(mesh, False)
                changed += 1
        REPORT["steps"].append("mesh material assignments=%d" % changed)


def _write_report(config):
    REPORT["missing_textures"] = sorted(
        set(REPORT["missing_textures"])
    )
    REPORT["connect_fail"] = sorted(set(REPORT["connect_fail"]))
    write_json(report_path(config, "rebuild_log.json"), REPORT)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", help="Path to PortKit JSON config")
    args = parser.parse_args()
    config = load_config(args.config)
    try:
        if not HAVE_UE:
            raise RuntimeError(
                "Run this script inside UE 4.27 Editor Python"
            )
        run_build(config)
    except Exception:
        REPORT["errors"].append(traceback.format_exc())
    finally:
        _write_report(config)
        if HAVE_UE:
            unreal.log(
                "[PortKit] errors=%d connect_fail=%d missing_textures=%d report=%s"
                % (
                    len(REPORT["errors"]),
                    len(REPORT["connect_fail"]),
                    len(REPORT["missing_textures"]),
                    report_path(config, "rebuild_log.json"),
                )
            )


if __name__ == "__main__":
    main()
