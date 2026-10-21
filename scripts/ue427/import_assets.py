# -*- coding: utf-8 -*-
"""Import a PortKit mesh/material export into UE 4.27 with simplified materials.

Environment:
    Unreal Engine 4.27 Editor Python 3.7, Cmd mode.

Use:
    py "PATH/TO/PortKit/scripts/ue427/import_assets.py" --config "PATH/TO/config.json"

Output:
    Textures, four simplified master variants, global and per-source material
    instances, imported meshes with explicit LOD screen sizes 1/0.25/0.1/0.04,
    and JSON/TXT reports. Existing assets are skipped unless
    ue427.imports.assets.rebuild_existing is true.
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

from portkit_config import load_config

try:
    import unreal
except ImportError:
    unreal = None


LOG = []
FAIL = []


def log(message):
    LOG.append(str(message))
    if unreal is not None:
        unreal.log("[PortKit import] " + str(message))


def short(path):
    return path.split("/")[-1] if path else ""


def enum_name(value):
    match = re.search(r"\.(\w+):", value or "")
    return match.group(1) if match else None


class ImportRuntime(object):
    def __init__(self, options):
        self.eal = unreal.EditorAssetLibrary
        self.mel = unreal.MaterialEditingLibrary
        self.tools = unreal.AssetToolsHelpers.get_asset_tools()
        self.options = options
        self.input_dir = options["input"]
        self.dest = options["destination"].rstrip("/")
        self.texture_dir = self.dest + "/" + options.get(
            "texture_folder", "Textures"
        )
        self.material_dir = self.dest + "/" + options.get(
            "material_folder", "Materials"
        )
        self.mesh_dir = self.dest + "/" + options.get(
            "mesh_folder", "Meshes"
        )
        self.tex_cap = int(options.get("texture_cap", 2048))
        self.heavy = int(options.get("heavy_vertices", 250000))
        self.only = options.get("only")
        self.master_prefix = options.get("master_prefix", "M_Port_Asset")
        self.fill_marker = options.get("fill_marker", "T_L_Fill_")
        self.foliage_config = options.get("foliage_material", {})
        self.generate_collision = bool(
            options.get("generate_collision", True)
        )
        self.rebuild_existing = bool(
            options.get("rebuild_existing", False)
        )
        self.lod_screen_sizes = list(
            options.get("lod_screen_sizes", [1.0, 0.25, 0.1, 0.04])
        )
        self.role_settings = {
            "BaseColor": ("TC_DEFAULT", True, "SAMPLERTYPE_COLOR"),
            "Emissive": ("TC_DEFAULT", True, "SAMPLERTYPE_COLOR"),
            "Normal": ("TC_NORMALMAP", False, "SAMPLERTYPE_NORMAL"),
            "ORM": ("TC_MASKS", False, "SAMPLERTYPE_MASKS"),
            "OpacityMask": ("TC_MASKS", False, "SAMPLERTYPE_MASKS"),
        }

    def import_file(self, filename, destination, options=None):
        task = unreal.AssetImportTask()
        task.filename = filename
        task.destination_path = destination
        task.automated = True
        task.replace_existing = True
        task.save = False
        if options is not None:
            task.options = options
        self.tools.import_asset_tasks([task])
        paths = list(task.imported_object_paths)
        return unreal.load_asset(paths[0]) if paths else None


def spec_of(info, runtime):
    textures = info.get("textures", {})
    vectors = info.get("vectors", {})
    scalars = info.get("scalars", {})
    switches = info.get("switches", {})
    spec = {
        "textures": {},
        "uv": (1.0, 1.0),
        "controls": (1, 1, 0, 0),
        "tint": (1, 1, 1, 1),
        "normal": 1.0,
        "orms": (1, 1, 1, 0.5),
        "emissive": None,
    }
    if "00_BaseColor" in textures:
        spec["textures"]["BaseColor"] = textures.get("00_BaseColor")
        spec["textures"]["Normal"] = textures.get("00_Normal")
        spec["textures"]["ORM"] = textures.get("00_ORM")
        uv = vectors.get("00_UVTiling") or [1, 1, 0, 0]
        spec["uv"] = (uv[0], uv[1] if uv[1] else uv[0])
        spec["controls"] = tuple(
            vectors.get("00_BaseColorControls") or (1, 1, 0, 0)
        )
        spec["tint"] = tuple(
            vectors.get("00_BaseColorTint") or (1, 1, 1, 1)
        )
        spec["normal"] = scalars.get("00_NormalIntensity") or 1.0
        spec["orms"] = tuple(
            vectors.get("00_ORMS_Intensity") or (1, 1, 1, 0.5)
        )
        if switches.get("00_Emissive?"):
            emissive = textures.get("00_Emissive")
            spec["emissive"] = {
                "tint": vectors.get("00_EmissiveTint") or [1, 1, 1, 1],
                "intensity": scalars.get("00_EmissiveIntensity") or 1.0,
            }
            if emissive and runtime.fill_marker not in emissive:
                spec["textures"]["Emissive"] = emissive
    else:
        for key, texture_path in textures.items():
            if not texture_path:
                continue
            texture_name = short(texture_path).lower()
            key_lower = key.lower()
            if key_lower in (
                "bc",
                "basecolor",
                "albedo",
                "diffuse",
            ) or texture_name.endswith(
                ("_bc", "_basecolor", "_albedo", "_d")
            ):
                spec["textures"].setdefault("BaseColor", texture_path)
            elif key_lower.startswith("normal") or texture_name.endswith(
                ("_n", "_normal")
            ):
                spec["textures"].setdefault("Normal", texture_path)
            elif key_lower in ("orm", "rma") or texture_name.endswith(
                ("_orm",)
            ):
                spec["textures"].setdefault("ORM", texture_path)
        tiling = scalars.get("Tiling") or 1.0
        spec["uv"] = (tiling, tiling)
    overrides = info.get("overrides", {})
    base = info.get("base", {})
    blend = (
        overrides.get("blend_mode")
        if overrides.get("override_blend_mode")
        else base.get("blend_mode")
    )
    two_sided = (
        overrides.get("two_sided")
        if overrides.get("override_two_sided")
        else base.get("two_sided")
    )
    masked = bool(blend) and (
        "MASKED" in str(blend) or "TRANSLUCENT" in str(blend)
    )
    variant = runtime.master_prefix
    if masked:
        variant += "_Masked"
    if str(two_sided) == "True":
        variant += "_TwoSided"
    spec["variant"] = variant
    return spec


def _foliage_pick(textures, keys):
    values = {
        key.lower(): value
        for key, value in textures.items()
        if value
    }
    for key in keys:
        value = values.get(key.lower())
        if value and "Fill" not in value and "Template" not in value:
            return value
    return None


def _foliage_by_suffix(textures, suffixes, banned=()):
    for name, value in textures.items():
        if not value or not str(name).lower().startswith("used_"):
            continue
        stem = str(name)[5:].lower()
        asset_name = str(value).lower()
        if any(token in stem for token in banned):
            continue
        if "fill" in asset_name or "template" in asset_name:
            continue
        if any(stem.endswith(suffix) for suffix in suffixes):
            return value
    return None


def foliage_spec_of(info, runtime):
    config = runtime.foliage_config
    textures = info.get("textures", {})
    vectors = info.get("vectors", {})
    scalars = info.get("scalars", {})
    base = info.get("base", {})
    overrides = info.get("overrides", {})
    blend = (
        overrides.get("blend_mode")
        if overrides.get("override_blend_mode")
        else base.get("blend_mode")
    ) or ""
    shading = base.get("shading_model") or ""
    foliage = (
        "MASKED" in blend
        or "FOLIAGE" in shading
        or "SUBSURFACE" in shading
    )
    texture_keys = config.get("texture_keys", {})
    suffix_keys = config.get("texture_suffixes", {})
    spec = {"foliage": foliage, "textures": {}}
    spec["textures"]["BaseColor"] = _foliage_pick(
        textures, texture_keys.get("BaseColor", [])
    ) or _foliage_by_suffix(
        textures, suffix_keys.get("BaseColor", [])
    )
    spec["textures"]["Normal"] = _foliage_pick(
        textures, texture_keys.get("Normal", [])
    ) or _foliage_by_suffix(
        textures, suffix_keys.get("Normal", [])
    )
    spec["textures"]["ORM"] = _foliage_pick(
        textures, texture_keys.get("ORM", [])
    ) or _foliage_by_suffix(
        textures,
        suffix_keys.get("ORM", []),
        suffix_keys.get("ORMBan", []),
    )
    opacity_mask = _foliage_pick(
        textures, texture_keys.get("OpacityMask", [])
    ) or _foliage_by_suffix(
        textures, suffix_keys.get("OpacityMask", [])
    )
    if foliage and opacity_mask:
        spec["textures"]["OpacityMask"] = opacity_mask
    spec["textures"] = {
        key: value for key, value in spec["textures"].items() if value
    }
    tint = config.get("defaults", {}).get("tint", [1, 1, 1, 1])
    for key in config.get("tint_vector_keys", []):
        value = vectors.get(key)
        if value:
            tint = value
            break
    spec["tint"] = tint
    uv = vectors.get(config.get("uv_vector_key", "00_UVTiling"))
    if not uv:
        tiling = 1.0
        for key in config.get("uv_scalar_keys", []):
            if scalars.get(key):
                tiling = scalars[key]
                break
        uv = [tiling, 0, 0, 0]
    spec["uv"] = (
        uv[0] or 1.0,
        uv[1] if len(uv) > 1 and uv[1] else (uv[0] or 1.0),
    )
    normal_intensity = 1.0
    for key in config.get("normal_scalar_keys", []):
        if scalars.get(key) is not None:
            normal_intensity = scalars[key]
            break
    normal_min = float(config.get("normal_minimum", 0.05))
    spec["normal"] = (
        abs(normal_intensity)
        if abs(normal_intensity) > normal_min
        else 1.0
    )
    return spec


def import_textures(runtime, roles, texture_map):
    output = {}
    progress = unreal.ScopedSlowTask(
        max(1, len(roles)), "PortKit simplified-material textures"
    )
    progress.make_dialog_visible()
    for path, role in sorted(roles.items()):
        if progress.should_cancel():
            FAIL.append("CANCELLED during textures")
            break
        progress.enter_progress_frame(1, short(path))
        info = texture_map.get(path)
        if info is None:
            FAIL.append("texture not exported: " + path)
            continue
        name = os.path.splitext(info["file"])[0]
        asset_path = runtime.texture_dir + "/" + name
        if runtime.eal.does_asset_exist(asset_path):
            texture = unreal.load_asset(asset_path)
        else:
            texture = runtime.import_file(
                os.path.join(runtime.input_dir, "Textures", info["file"]),
                runtime.texture_dir,
            )
        if texture is None:
            FAIL.append("texture import failed: " + info["file"])
            continue
        compression, srgb, _sampler = runtime.role_settings[role]
        texture.set_editor_property(
            "compression_settings",
            getattr(unreal.TextureCompressionSettings, compression),
        )
        texture.set_editor_property("srgb", srgb)
        if role == "Normal":
            try:
                texture.set_editor_property(
                    "flip_green_channel",
                    bool(info.get("flip_green"))
                    or any(
                        token.lower() in name.lower()
                        for token in runtime.foliage_config.get(
                            "flip_green_name_tokens", []
                        )
                    ),
                )
            except Exception:
                pass
        lod_group = enum_name(info.get("lod_group"))
        if lod_group and hasattr(unreal.TextureGroup, lod_group):
            texture.set_editor_property(
                "lod_group", getattr(unreal.TextureGroup, lod_group)
            )
        if max(info.get("size") or [0]) > runtime.tex_cap:
            texture.set_editor_property("max_texture_size", runtime.tex_cap)
        runtime.eal.save_loaded_asset(texture, False)
        output[path] = texture
    return output


class Graph(object):
    def __init__(self, runtime, material):
        self.runtime = runtime
        self.material = material

    def node(self, cls, x, y):
        return self.runtime.mel.create_material_expression(
            self.material, cls, x, y
        )

    def link(self, source, source_pin, target, pins):
        candidates = pins if isinstance(pins, (list, tuple)) else [pins]
        for pin in candidates:
            try:
                if self.runtime.mel.connect_material_expressions(
                    source, source_pin, target, pin
                ):
                    return True
            except Exception:
                pass
        FAIL.append(
            "wire %s.%s -> %s.%s"
            % (source.get_name(), source_pin, target.get_name(), candidates)
        )
        return False

    def mask(self, source, output, channels, x, y):
        mask = self.node(unreal.MaterialExpressionComponentMask, x, y)
        for channel in ("r", "g", "b", "a"):
            mask.set_editor_property(channel, channel in channels)
        self.link(source, output, mask, "")
        return mask

    def multiply(self, left, left_out, right, right_out, x, y):
        node = self.node(unreal.MaterialExpressionMultiply, x, y)
        self.link(left, left_out, node, "A")
        self.link(right, right_out, node, "B")
        return node

    def scalar(self, name, value, x, y, group="PortKit"):
        node = self.node(unreal.MaterialExpressionScalarParameter, x, y)
        node.set_editor_property("parameter_name", name)
        node.set_editor_property("default_value", value)
        node.set_editor_property("group", group)
        return node

    def vector(self, name, rgba, x, y, group="PortKit"):
        node = self.node(unreal.MaterialExpressionVectorParameter, x, y)
        node.set_editor_property("parameter_name", name)
        node.set_editor_property(
            "default_value", unreal.LinearColor(*rgba)
        )
        node.set_editor_property("group", group)
        return node

    def texture(self, name, texture, sampler_type, uv, x, y):
        node = self.node(
            unreal.MaterialExpressionTextureSampleParameter2D, x, y
        )
        node.set_editor_property("parameter_name", name)
        node.set_editor_property("texture", texture)
        node.set_editor_property("sampler_type", sampler_type)
        node.set_editor_property("group", "PortKit Textures")
        self.link(uv, "", node, "UVs")
        return node

    def constant(self, value, x, y):
        node = self.node(unreal.MaterialExpressionConstant, x, y)
        node.set_editor_property("r", value)
        return node


def connect_property(runtime, source, output, prop):
    try:
        if runtime.mel.connect_material_property(source, output, prop):
            return True
    except Exception:
        pass
    FAIL.append("property %s <- %s" % (prop, source.get_name()))
    return False


def build_master(runtime, name, defaults):
    path = runtime.material_dir + "/" + name
    if runtime.eal.does_asset_exist(path):
        material = unreal.load_asset(path)
        if not runtime.rebuild_existing:
            return material
        runtime.mel.delete_all_material_expressions(material)
    else:
        material = runtime.tools.create_asset(
            name,
            runtime.material_dir,
            unreal.Material,
            unreal.MaterialFactoryNew(),
        )
    masked = "_Masked" in name
    two_sided = "_TwoSided" in name
    material.set_editor_property(
        "blend_mode",
        unreal.BlendMode.BLEND_MASKED
        if masked
        else unreal.BlendMode.BLEND_OPAQUE,
    )
    material.set_editor_property("two_sided", two_sided)
    graph = Graph(runtime, material)
    sampler = unreal.MaterialSamplerType
    uv0 = graph.node(
        unreal.MaterialExpressionTextureCoordinate, -2200, 0
    )
    tiling = graph.mask(
        graph.vector("UVTiling", (1, 1, 0, 0), -2400, 150),
        "",
        "rg",
        -2200,
        150,
    )
    uv = graph.multiply(uv0, "", tiling, "", -2000, 50)
    base = graph.texture(
        "BaseColor",
        defaults["BaseColor"],
        sampler.SAMPLERTYPE_COLOR,
        uv,
        -1700,
        -500,
    )
    normal = graph.texture(
        "Normal",
        defaults["Normal"],
        sampler.SAMPLERTYPE_NORMAL,
        uv,
        -1700,
        100,
    )
    orm = graph.texture(
        "ORM",
        defaults["ORM"],
        sampler.SAMPLERTYPE_MASKS,
        uv,
        -1700,
        500,
    )
    emissive = graph.texture(
        "Emissive",
        defaults["BaseColor"],
        sampler.SAMPLERTYPE_COLOR,
        uv,
        -1700,
        900,
    )
    controls = graph.vector(
        "BaseColorControls", (1, 1, 0, 0), -1700, -800
    )
    power = graph.node(unreal.MaterialExpressionPower, -1300, -550)
    graph.link(base, "RGB", power, ["Base"])
    graph.link(controls, "G", power, ["Exp", "Exponent"])
    bright = graph.multiply(power, "", controls, "R", -1150, -600)
    desaturate = graph.node(
        unreal.MaterialExpressionDesaturation, -950, -600
    )
    graph.link(bright, "", desaturate, "")
    graph.link(controls, "B", desaturate, "Fraction")
    tinted = graph.multiply(
        desaturate,
        "",
        graph.vector("Tint", (1, 1, 1, 1), -950, -450),
        "",
        -750,
        -600,
    )
    global_tint = graph.multiply(
        tinted,
        "",
        graph.vector("GlobalTint", (1, 1, 1, 1), -750, -450, "Global"),
        "",
        -550,
        -600,
    )
    final_color = graph.multiply(
        global_tint,
        "",
        graph.scalar("GlobalBrightness", 1.0, -550, -450, "Global"),
        "",
        -350,
        -600,
    )
    connect_property(
        runtime, final_color, "", unreal.MaterialProperty.MP_BASE_COLOR
    )
    intensity = graph.scalar("NormalIntensity", 1.0, -1450, 300)
    normal_xy = graph.multiply(
        graph.mask(normal, "RGB", "rg", -1450, 100),
        "",
        intensity,
        "",
        -1250,
        150,
    )
    normal_out = graph.node(
        unreal.MaterialExpressionAppendVector, -1050, 150
    )
    graph.link(normal_xy, "", normal_out, "A")
    graph.link(
        graph.mask(normal, "RGB", "b", -1450, 220), "", normal_out, "B"
    )
    connect_property(
        runtime, normal_out, "", unreal.MaterialProperty.MP_NORMAL
    )
    orms = graph.vector("ORMS_Intensity", (1, 1, 1, 0.5), -1700, 750)
    ao = graph.node(
        unreal.MaterialExpressionLinearInterpolate, -1200, 450
    )
    graph.link(graph.constant(1.0, -1400, 420), "", ao, "A")
    graph.link(orm, "R", ao, "B")
    graph.link(orms, "R", ao, "Alpha")
    connect_property(
        runtime,
        ao,
        "",
        unreal.MaterialProperty.MP_AMBIENT_OCCLUSION,
    )
    roughness = graph.multiply(orm, "G", orms, "G", -1200, 560)
    connect_property(
        runtime, roughness, "", unreal.MaterialProperty.MP_ROUGHNESS
    )
    metallic = graph.multiply(orm, "B", orms, "B", -1200, 640)
    connect_property(
        runtime, metallic, "", unreal.MaterialProperty.MP_METALLIC
    )
    connect_property(
        runtime, orms, "A", unreal.MaterialProperty.MP_SPECULAR
    )
    emissive_out = graph.multiply(
        emissive,
        "RGB",
        graph.vector("EmissiveTint", (1, 1, 1, 1), -1450, 1000),
        "",
        -1200,
        950,
    )
    emissive_out = graph.multiply(
        emissive_out,
        "",
        graph.scalar("EmissiveIntensity", 0.0, -1450, 1100),
        "",
        -1000,
        950,
    )
    connect_property(
        runtime,
        emissive_out,
        "",
        unreal.MaterialProperty.MP_EMISSIVE_COLOR,
    )
    if masked:
        connect_property(
            runtime,
            base,
            "A",
            unreal.MaterialProperty.MP_OPACITY_MASK,
        )
        material.set_editor_property("opacity_mask_clip_value", 0.3333)
    runtime.mel.recompile_material(material)
    runtime.eal.save_loaded_asset(material, False)
    global_name = "MI_PortGlobal" + name[len(runtime.master_prefix) :]
    global_path = runtime.material_dir + "/" + global_name
    if runtime.eal.does_asset_exist(global_path):
        global_instance = unreal.load_asset(global_path)
        if runtime.rebuild_existing:
            runtime.mel.set_material_instance_parent(
                global_instance, material
            )
    else:
        global_instance = runtime.tools.create_asset(
            global_name,
            runtime.material_dir,
            unreal.MaterialInstanceConstant,
            unreal.MaterialInstanceConstantFactoryNew(),
        )
        runtime.mel.set_material_instance_parent(global_instance, material)
        runtime.eal.save_loaded_asset(global_instance, False)
    return global_instance


def _foliage_parameter(runtime, key, default):
    return runtime.foliage_config.get("parameter_names", {}).get(
        key, default
    )


def _foliage_default(runtime, key, default):
    return runtime.foliage_config.get("defaults", {}).get(key, default)


def build_foliage_master(runtime, defaults):
    config = runtime.foliage_config
    name = config.get("master_name", "M_Port_Foliage")
    path = runtime.material_dir + "/" + name
    if runtime.eal.does_asset_exist(path):
        material = unreal.load_asset(path)
        if not runtime.rebuild_existing:
            return material
        runtime.mel.delete_all_material_expressions(material)
    else:
        material = runtime.tools.create_asset(
            name,
            runtime.material_dir,
            unreal.Material,
            unreal.MaterialFactoryNew(),
        )
    material.set_editor_property(
        "blend_mode",
        getattr(
            unreal.BlendMode,
            config.get("blend_mode", "BLEND_MASKED"),
        ),
    )
    material.set_editor_property(
        "two_sided", bool(config.get("two_sided", True))
    )
    material.set_editor_property(
        "shading_model",
        getattr(
            unreal.MaterialShadingModel,
            config.get("shading_model", "MSM_TWO_SIDED_FOLIAGE"),
        ),
    )
    material.set_editor_property(
        "opacity_mask_clip_value",
        float(config.get("opacity_mask_clip_value", 0.4)),
    )
    for flag_key, property_name in (
        (
            "used_with_instanced_static_meshes",
            "used_with_instanced_static_meshes",
        ),
        ("used_with_static_lighting", "used_with_static_lighting"),
    ):
        if config.get(flag_key, True):
            try:
                material.set_editor_property(property_name, True)
            except Exception:
                pass

    graph = Graph(runtime, material)
    sampler = unreal.MaterialSamplerType
    uv0 = graph.node(
        unreal.MaterialExpressionTextureCoordinate, -2200, 0
    )
    tiling = graph.mask(
        graph.vector(
            _foliage_parameter(runtime, "uv_tiling", "UVTiling"),
            (1, 1, 0, 0),
            -2400,
            150,
        ),
        "",
        "rg",
        -2200,
        150,
    )
    uv = graph.multiply(uv0, "", tiling, "", -2000, 50)
    base = graph.texture(
        _foliage_parameter(runtime, "base_color", "BaseColor"),
        defaults["BaseColor"],
        sampler.SAMPLERTYPE_COLOR,
        uv,
        -1700,
        -500,
    )
    normal = graph.texture(
        _foliage_parameter(runtime, "normal", "Normal"),
        defaults["Normal"],
        sampler.SAMPLERTYPE_NORMAL,
        uv,
        -1700,
        100,
    )
    orm = graph.texture(
        _foliage_parameter(runtime, "orm", "ORM"),
        defaults["ORM"],
        sampler.SAMPLERTYPE_MASKS,
        uv,
        -1700,
        500,
    )
    opacity = graph.texture(
        _foliage_parameter(runtime, "opacity_mask", "OpacityMask"),
        defaults["ORM"],
        sampler.SAMPLERTYPE_MASKS,
        uv,
        -1700,
        900,
    )

    tinted = graph.multiply(
        base,
        "RGB",
        graph.vector(
            _foliage_parameter(runtime, "tint", "Tint"),
            tuple(_foliage_default(runtime, "tint", (1, 1, 1, 1))),
            -1450,
            -650,
        ),
        "",
        -1250,
        -550,
    )
    tinted = graph.multiply(
        tinted,
        "",
        graph.vector(
            _foliage_parameter(runtime, "global_tint", "GlobalTint"),
            tuple(
                _foliage_default(
                    runtime, "global_tint", (1, 1, 1, 1)
                )
            ),
            -1250,
            -700,
            "Global",
        ),
        "",
        -1050,
        -550,
    )
    color_out = graph.multiply(
        tinted,
        "",
        graph.scalar(
            _foliage_parameter(
                runtime, "global_brightness", "GlobalBrightness"
            ),
            float(_foliage_default(runtime, "global_brightness", 1.0)),
            -1050,
            -700,
            "Global",
        ),
        "",
        -850,
        -550,
    )
    connect_property(
        runtime, color_out, "", unreal.MaterialProperty.MP_BASE_COLOR
    )
    subsurface = graph.multiply(
        color_out,
        "",
        graph.vector(
            _foliage_parameter(
                runtime, "subsurface_tint", "SubsurfaceTint"
            ),
            tuple(
                _foliage_default(
                    runtime, "subsurface_tint", (0.6, 0.6, 0.5, 1)
                )
            ),
            -850,
            -400,
        ),
        "",
        -650,
        -450,
    )
    connect_property(
        runtime,
        subsurface,
        "",
        unreal.MaterialProperty.MP_SUBSURFACE_COLOR,
    )
    intensity = graph.scalar(
        _foliage_parameter(
            runtime, "normal_intensity", "NormalIntensity"
        ),
        float(_foliage_default(runtime, "normal_intensity", 1.0)),
        -1450,
        300,
    )
    normal_xy = graph.multiply(
        graph.mask(normal, "RGB", "rg", -1450, 100),
        "",
        intensity,
        "",
        -1250,
        150,
    )
    normal_out = graph.node(
        unreal.MaterialExpressionAppendVector, -1050, 150
    )
    graph.link(normal_xy, "", normal_out, "A")
    graph.link(
        graph.mask(normal, "RGB", "b", -1450, 220), "", normal_out, "B"
    )
    connect_property(
        runtime, normal_out, "", unreal.MaterialProperty.MP_NORMAL
    )
    use_orm = graph.scalar(
        _foliage_parameter(runtime, "use_orm", "UseORM"),
        float(_foliage_default(runtime, "use_orm", 1.0)),
        -1450,
        650,
    )
    ao = graph.node(
        unreal.MaterialExpressionLinearInterpolate, -1100, 450
    )
    graph.link(graph.constant(1.0, -1300, 420), "", ao, "A")
    graph.link(orm, "R", ao, "B")
    graph.link(use_orm, "", ao, "Alpha")
    connect_property(
        runtime,
        ao,
        "",
        unreal.MaterialProperty.MP_AMBIENT_OCCLUSION,
    )
    roughness = graph.node(
        unreal.MaterialExpressionLinearInterpolate, -1100, 560
    )
    graph.link(
        graph.scalar(
            _foliage_parameter(runtime, "roughness", "Roughness"),
            float(_foliage_default(runtime, "roughness", 0.7)),
            -1300,
            600,
        ),
        "",
        roughness,
        "A",
    )
    graph.link(orm, "G", roughness, "B")
    graph.link(use_orm, "", roughness, "Alpha")
    connect_property(
        runtime,
        roughness,
        "",
        unreal.MaterialProperty.MP_ROUGHNESS,
    )
    connect_property(
        runtime,
        graph.scalar(
            _foliage_parameter(runtime, "specular", "Specular"),
            float(_foliage_default(runtime, "specular", 0.3)),
            -1100,
            700,
        ),
        "",
        unreal.MaterialProperty.MP_SPECULAR,
    )
    opacity_out = graph.node(
        unreal.MaterialExpressionLinearInterpolate, -1100, 900
    )
    graph.link(opacity, "R", opacity_out, "A")
    graph.link(base, "A", opacity_out, "B")
    graph.link(
        graph.scalar(
            _foliage_parameter(
                runtime, "opacity_from_alpha", "OpacityFromAlpha"
            ),
            float(_foliage_default(runtime, "opacity_from_alpha", 1.0)),
            -1300,
            1000,
        ),
        "",
        opacity_out,
        "Alpha",
    )
    connect_property(
        runtime,
        opacity_out,
        "",
        unreal.MaterialProperty.MP_OPACITY_MASK,
    )

    wind = config.get("wind", {})
    if wind.get("enabled", True):
        wind_function = unreal.load_asset(
            wind.get(
                "function",
                "/Engine/Functions/Engine_MaterialFunctions01/"
                "WorldPositionOffset/SimpleGrassWind",
            )
        )
        if wind_function is not None:
            wind_call = graph.node(
                unreal.MaterialExpressionMaterialFunctionCall, -900, 1200
            )
            wind_call.set_editor_property(
                "material_function", wind_function
            )
            for key, default_name in (
                ("intensity", "WindIntensity"),
                ("weight", "WindWeight"),
                ("speed", "WindSpeed"),
            ):
                settings = wind.get(key, {})
                graph.link(
                    graph.scalar(
                        settings.get("parameter", default_name),
                        float(settings.get("default", 0.0)),
                        -1200,
                        1150 + (
                            ("intensity", "weight", "speed").index(key)
                            * 70
                        ),
                        wind.get("group", "Wind"),
                    ),
                    "",
                    wind_call,
                    settings.get("input", default_name),
                )
            world_position_offset = next(
                (
                    getattr(unreal.MaterialProperty, member)
                    for member in dir(unreal.MaterialProperty)
                    if "WORLD" in member.upper()
                    and "OFFSET" in member.upper()
                ),
                None,
            )
            if world_position_offset is not None:
                connect_property(
                    runtime,
                    wind_call,
                    "",
                    world_position_offset,
                )
            else:
                log(
                    "4.27 does not expose WorldPositionOffset to Python; "
                    "SimpleGrassWind is built but left unwired"
                )
        else:
            log("SimpleGrassWind not found; wind disabled for this master")

    runtime.mel.recompile_material(material)
    runtime.eal.save_loaded_asset(material, False)
    global_name = config.get(
        "global_instance_name", "MI_PortFoliage_Global"
    )
    global_path = runtime.material_dir + "/" + global_name
    if runtime.eal.does_asset_exist(global_path):
        global_instance = unreal.load_asset(global_path)
        if runtime.rebuild_existing:
            runtime.mel.set_material_instance_parent(
                global_instance, material
            )
    else:
        global_instance = runtime.tools.create_asset(
            global_name,
            runtime.material_dir,
            unreal.MaterialInstanceConstant,
            unreal.MaterialInstanceConstantFactoryNew(),
        )
        runtime.mel.set_material_instance_parent(global_instance, material)
        runtime.eal.save_loaded_asset(global_instance, False)
    return global_instance


def build_foliage_instance(
    runtime,
    material_path,
    spec,
    parent,
    textures,
    names_used,
    is_foliage_master,
):
    base_name = short(material_path)
    if base_name.startswith("MI_"):
        base_name = base_name[3:]
    prefix = runtime.foliage_config.get(
        "instance_prefix", "MI_Port_Foliage_"
    )
    name = prefix + base_name
    if names_used.get(name, material_path) != material_path:
        suffix = 2
        while "%s__%d" % (name, suffix) in names_used:
            suffix += 1
        name = "%s__%d" % (name, suffix)
    names_used[name] = material_path
    path = runtime.material_dir + "/" + name
    if runtime.eal.does_asset_exist(path):
        instance = unreal.load_asset(path)
        if not runtime.rebuild_existing:
            return instance
    else:
        instance = runtime.tools.create_asset(
            name,
            runtime.material_dir,
            unreal.MaterialInstanceConstant,
            unreal.MaterialInstanceConstantFactoryNew(),
        )
    runtime.mel.set_material_instance_parent(instance, parent)
    for role, texture_path in spec["textures"].items():
        if (
            not is_foliage_master
            and role == "OpacityMask"
        ):
            continue
        texture = textures.get(texture_path)
        if texture is not None:
            runtime.mel.set_material_instance_texture_parameter_value(
                instance, role, texture
            )
    runtime.mel.set_material_instance_vector_parameter_value(
        instance,
        _foliage_parameter(runtime, "uv_tiling", "UVTiling"),
        unreal.LinearColor(spec["uv"][0], spec["uv"][1], 0, 0),
    )
    runtime.mel.set_material_instance_vector_parameter_value(
        instance,
        _foliage_parameter(runtime, "tint", "Tint"),
        linear_color(spec["tint"]),
    )
    runtime.mel.set_material_instance_scalar_parameter_value(
        instance,
        _foliage_parameter(
            runtime, "normal_intensity", "NormalIntensity"
        ),
        float(spec["normal"]),
    )
    if is_foliage_master:
        runtime.mel.set_material_instance_scalar_parameter_value(
            instance,
            _foliage_parameter(runtime, "use_orm", "UseORM"),
            1.0 if "ORM" in spec["textures"] else 0.0,
        )
        runtime.mel.set_material_instance_scalar_parameter_value(
            instance,
            _foliage_parameter(
                runtime, "opacity_from_alpha", "OpacityFromAlpha"
            ),
            0.0 if "OpacityMask" in spec["textures"] else 1.0,
        )
    runtime.mel.update_material_instance(instance)
    runtime.eal.save_loaded_asset(instance, False)
    return instance


def linear_color(values):
    values = list(values) + [1.0] * (4 - len(values))
    return unreal.LinearColor(*values[:4])


def build_instance(
    runtime, material_path, spec, globals_by_variant, textures, names_used
):
    base_name = short(material_path)
    if base_name.startswith("MI_"):
        base_name = base_name[3:]
    name = "MI_Port_" + base_name
    if names_used.get(name, material_path) != material_path:
        suffix = 2
        while "%s__%d" % (name, suffix) in names_used:
            suffix += 1
        name = "%s__%d" % (name, suffix)
    names_used[name] = material_path
    path = runtime.material_dir + "/" + name
    if runtime.eal.does_asset_exist(path):
        instance = unreal.load_asset(path)
        if not runtime.rebuild_existing:
            return instance
    else:
        instance = runtime.tools.create_asset(
            name,
            runtime.material_dir,
            unreal.MaterialInstanceConstant,
            unreal.MaterialInstanceConstantFactoryNew(),
        )
    parent = globals_by_variant[spec["variant"]]
    runtime.mel.set_material_instance_parent(instance, parent)
    for role, texture_path in spec["textures"].items():
        texture = textures.get(texture_path)
        if texture is not None:
            runtime.mel.set_material_instance_texture_parameter_value(
                instance, role, texture
            )
    runtime.mel.set_material_instance_vector_parameter_value(
        instance,
        "UVTiling",
        unreal.LinearColor(spec["uv"][0], spec["uv"][1], 0, 0),
    )
    runtime.mel.set_material_instance_vector_parameter_value(
        instance, "BaseColorControls", linear_color(spec["controls"])
    )
    runtime.mel.set_material_instance_vector_parameter_value(
        instance, "Tint", linear_color(spec["tint"])
    )
    runtime.mel.set_material_instance_scalar_parameter_value(
        instance, "NormalIntensity", float(spec["normal"])
    )
    runtime.mel.set_material_instance_vector_parameter_value(
        instance, "ORMS_Intensity", linear_color(spec["orms"])
    )
    if spec["emissive"]:
        runtime.mel.set_material_instance_vector_parameter_value(
            instance,
            "EmissiveTint",
            linear_color(spec["emissive"]["tint"][:3]),
        )
        runtime.mel.set_material_instance_scalar_parameter_value(
            instance,
            "EmissiveIntensity",
            float(spec["emissive"]["intensity"]),
        )
    runtime.mel.update_material_instance(instance)
    runtime.eal.save_loaded_asset(instance, False)
    return instance


def fbx_options(with_lods):
    ui = unreal.FbxImportUI()
    ui.import_mesh = True
    ui.import_materials = False
    ui.import_textures = False
    ui.import_as_skeletal = False
    ui.mesh_type_to_import = unreal.FBXImportType.FBXIT_STATIC_MESH
    data = ui.static_mesh_import_data
    data.combine_meshes = True
    data.auto_generate_collision = False
    data.generate_lightmap_u_vs = True
    for prop in ("import_mesh_lo_ds", "import_mesh_lods"):
        try:
            data.set_editor_property(prop, with_lods)
            break
        except Exception:
            pass
    return ui


def assign_slots(mesh, slots, resolve):
    by_name = {}
    for slot in slots:
        by_name[slot["slot"]] = slot
        by_name[short(slot["material"])] = slot
    materials = mesh.get_editor_property("static_materials")
    for index, static_material in enumerate(materials):
        entry = by_name.get(str(static_material.material_slot_name))
        if entry is None and index < len(slots):
            entry = slots[index]
        if entry is None or not entry["material"]:
            continue
        instance = resolve(entry["material"])
        if instance is not None:
            static_material.material_interface = instance
            materials[index] = static_material
    mesh.set_editor_property("static_materials", materials)


def make_lods(runtime, mesh, vertices):
    p0 = min(1.0, float(runtime.heavy) / vertices) if vertices > runtime.heavy else 1.0
    sizes = runtime.lod_screen_sizes
    percentages = [p0, p0 * 0.55, p0 * 0.25, p0 * 0.08]
    options = unreal.EditorScriptingMeshReductionOptions()
    reduction_settings = []
    for percentage, screen_size in zip(percentages, sizes):
        setting = unreal.EditorScriptingMeshReductionSettings()
        setting.set_editor_property("percent_triangles", percentage)
        setting.set_editor_property("screen_size", screen_size)
        reduction_settings.append(setting)
    options.set_editor_property(
        "reduction_settings", reduction_settings
    )
    options.set_editor_property("auto_compute_lod_screen_size", False)
    return unreal.EditorStaticMeshLibrary.set_lods(mesh, options)


def run(config, profile_name="assets"):
    if unreal is None:
        raise RuntimeError("Run import_assets.py inside UE 4.27 Editor Python")
    options = (
        config.get("ue427", {})
        .get("imports", {})
        .get(profile_name, {})
    )
    if not options.get("input") or not options.get("destination"):
        raise ValueError(
            "ue427.imports.%s requires input and destination"
            % profile_name
        )
    runtime = ImportRuntime(options)
    with open(
        os.path.join(runtime.input_dir, "manifest.json"),
        "r",
        encoding="utf-8",
    ) as handle:
        manifest = json.load(handle)
    with open(
        os.path.join(runtime.input_dir, "materials.json"),
        "r",
        encoding="utf-8",
    ) as handle:
        materials = json.load(handle)
    with open(
        os.path.join(runtime.input_dir, "textures_map.json"),
        "r",
        encoding="utf-8",
    ) as handle:
        texture_map = json.load(handle)
    if profile_name == "foliage":
        specs = {
            path: foliage_spec_of(info, runtime)
            for path, info in materials.items()
            if short(path) != "WorldGridMaterial"
        }
    else:
        specs = {
            path: spec_of(info, runtime)
            for path, info in materials.items()
            if short(path) != "WorldGridMaterial"
        }
    roles = {}
    for spec in specs.values():
        for role, texture_path in spec["textures"].items():
            if texture_path:
                roles.setdefault(texture_path, role)
    textures = import_textures(runtime, roles, texture_map)

    def first_texture(role, preferred):
        for path, value in roles.items():
            if (
                value == role
                and preferred in path
                and path in textures
            ):
                return textures[path]
        for path, value in roles.items():
            if value == role and path in textures:
                return textures[path]
        return None

    defaults = {
        "BaseColor": unreal.load_asset(
            "/Engine/EngineResources/DefaultTexture"
        ),
        "Normal": unreal.load_asset(
            "/Engine/EngineMaterials/FlatNormal"
        ),
        "ORM": first_texture("ORM", runtime.fill_marker),
    }
    if profile_name == "foliage":
        if defaults["ORM"] is None:
            defaults["ORM"] = first_texture(
                "OpacityMask", runtime.fill_marker
            )
        if defaults["ORM"] is None:
            defaults["ORM"] = defaults["BaseColor"]
        foliage_master = build_foliage_master(runtime, defaults)
        opaque_path = runtime.foliage_config.get(
            "opaque_global_instance", ""
        )
        opaque_global = (
            unreal.load_asset(opaque_path)
            if opaque_path
            and runtime.eal.does_asset_exist(opaque_path)
            else None
        )
        if not opaque_global:
            log(
                "opaque foliage parts use the foliage master because "
                "opaque_global_instance is not configured"
            )
        variants = [runtime.foliage_config.get(
            "master_name", "M_Port_Foliage"
        )]
        globals_by_variant = {}
    else:
        variants = sorted({spec["variant"] for spec in specs.values()})
        globals_by_variant = {
            variant: build_master(runtime, variant, defaults)
            for variant in variants
        }
        foliage_master = None
        opaque_global = None
    instances = {}
    names_used = {}
    progress = unreal.ScopedSlowTask(
        max(1, len(specs)), "PortKit material instances"
    )
    progress.make_dialog_visible()
    for path, spec in specs.items():
        if progress.should_cancel():
            FAIL.append("CANCELLED during instances")
            break
        progress.enter_progress_frame(1, short(path))
        if profile_name == "foliage":
            use_opaque = bool(
                not spec["foliage"] and opaque_global is not None
            )
            instances[path] = build_foliage_instance(
                runtime,
                path,
                spec,
                opaque_global if use_opaque else foliage_master,
                textures,
                names_used,
                not use_opaque,
            )
        else:
            instances[path] = build_instance(
                runtime,
                path,
                spec,
                globals_by_variant,
                textures,
                names_used,
            )
    grid = unreal.load_asset(
        "/Engine/EngineMaterials/WorldGridMaterial"
    )

    def resolve(material_path):
        if material_path in instances:
            return instances[material_path]
        if short(material_path) == "WorldGridMaterial":
            return grid
        return None

    items = [
        (path, info)
        for path, info in manifest.items()
        if not runtime.only
        or any(
            value.lower() in info["folder"].lower()
            for value in runtime.only
        )
    ]
    imported = skipped = lod_count = 0
    progress = unreal.ScopedSlowTask(
        max(1, len(items)), "PortKit mesh import"
    )
    progress.make_dialog_visible()
    for _path, info in items:
        if progress.should_cancel():
            FAIL.append("CANCELLED during meshes")
            break
        progress.enter_progress_frame(
            1, "%s (%s verts)" % (info["name"], info["verts"])
        )
        destination = runtime.mesh_dir
        if info["folder"]:
            destination += "/" + info["folder"]
        if runtime.eal.does_asset_exist(
            destination + "/" + info["name"]
        ):
            skipped += 1
            continue
        fbx_path = os.path.join(runtime.input_dir, info["fbx"])
        mesh = (
            runtime.import_file(
                fbx_path,
                destination,
                fbx_options(info["lods"] > 1),
            )
            if os.path.isfile(fbx_path)
            else None
        )
        if not isinstance(mesh, unreal.StaticMesh):
            FAIL.append("mesh " + info["name"])
            continue
        assign_slots(mesh, info["slots"], resolve)
        if runtime.generate_collision:
            try:
                mesh.get_editor_property(
                    "body_setup"
                ).set_editor_property(
                    "collision_trace_flag",
                    unreal.CollisionTraceFlag.CTF_USE_COMPLEX_AS_SIMPLE,
                )
            except Exception:
                pass
        if info["lods"] <= 1 or info["verts"] > runtime.heavy:
            try:
                make_lods(runtime, mesh, info["verts"])
                lod_count += 1
            except Exception as exc:
                FAIL.append("LODs %s: %r" % (info["name"], exc))
        runtime.eal.save_loaded_asset(mesh, False)
        imported += 1
    counts = {
        "textures": len(textures),
        "masters": len(globals_by_variant),
        "instances": len(instances),
        "meshes_imported": imported,
        "meshes_skipped": skipped,
        "lod_meshes": lod_count,
        "failures": len(FAIL),
    }
    if profile_name == "foliage":
        counts["foliage_instances"] = sum(
            1 for spec in specs.values() if spec["foliage"]
        )
        counts["solid_instances"] = len(specs) - counts["foliage_instances"]
    report_dir = options.get(
        "report_dir", os.path.join(runtime.input_dir, "reports")
    )
    if not os.path.isdir(report_dir):
        os.makedirs(report_dir)
    payload = {"counts": counts, "notes": LOG, "failures": FAIL}
    with open(
            os.path.join(report_dir, profile_name + ".json"),
        "w",
        encoding="utf-8",
    ) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    with open(
        os.path.join(report_dir, "import_assets.txt"),
        "w",
        encoding="utf-8",
    ) as handle:
        handle.write(
            json.dumps(counts, ensure_ascii=False, indent=2)
            + "\n\n"
            + "\n".join(LOG)
            + "\n\nFAILURES\n"
            + "\n".join(FAIL)
        )
    return payload


def main(profile_name="assets"):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", help="Path to PortKit JSON config")
    args = parser.parse_args()
    config = load_config(args.config)
    try:
        run(config, profile_name)
    except Exception:
        options = (
            config.get("ue427", {})
            .get("imports", {})
            .get(profile_name, {})
        )
        report_dir = options.get("report_dir") or os.getcwd()
        if not os.path.isdir(report_dir):
            os.makedirs(report_dir)
        with open(
            os.path.join(report_dir, profile_name + ".txt"),
            "w",
            encoding="utf-8",
        ) as handle:
            handle.write("ERROR\n" + traceback.format_exc())
        if unreal is not None:
            unreal.log_error(
                "[PortKit] import_assets failed; see report"
            )
        else:
            raise


if __name__ == "__main__":
    main()
