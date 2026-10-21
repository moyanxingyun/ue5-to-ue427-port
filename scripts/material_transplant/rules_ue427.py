# -*- coding: utf-8 -*-
"""UE5-to-UE4.27 material graph translation rules.

Environment:
    Plain Python 3.7+ for table lookups. The optional WPO helper accepts an
    Unreal MaterialProperty type and therefore runs inside UE Editor Python.

Use:
    from material_transplant.rules_ue427 import in_name, out_name, root_pins

No asset paths are stored here.
"""
from .planner import make_resolver, out_name as planner_out_name


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
INPUT_MAP = {
    "Input": "",
    "Coordinates": "UVs",
    "TextureObject": "Tex",
    "Exponent": "Exp",
    "VectorInput": "",
    "MaterialAttributes": "",
}
SWITCH_IN = {"A": "True", "B": "False"}
ROOT_PINS = [
    ("BaseColor", "MP_BASE_COLOR"),
    ("Metallic", "MP_METALLIC"),
    ("Specular", "MP_SPECULAR"),
    ("Roughness", "MP_ROUGHNESS"),
    ("EmissiveColor", "MP_EMISSIVE_COLOR"),
    ("Opacity", "MP_OPACITY"),
    ("OpacityMask", "MP_OPACITY_MASK"),
    ("Normal", "MP_NORMAL"),
    ("WorldPositionOffset", "WORLD_POSITION_OFFSET"),
    ("SubsurfaceColor", "MP_SUBSURFACE_COLOR"),
    ("ClearCoat", "MP_CUSTOM_DATA0"),
    ("ClearCoatRoughness", "MP_CUSTOM_DATA1"),
    ("AmbientOcclusion", "MP_AMBIENT_OCCLUSION"),
    ("PixelDepthOffset", "MP_PIXEL_DEPTH_OFFSET"),
]
SCALAR_ATTRS = {
    "Metallic",
    "Specular",
    "Roughness",
    "Opacity",
    "OpacityMask",
    "ClearCoat",
    "ClearCoatRoughness",
    "AmbientOcclusion",
    "PixelDepthOffset",
    "Anisotropy",
}
SKIP_PROPS = {
    "MaterialExpressionEditorX",
    "MaterialExpressionEditorY",
    "MaterialExpressionGuid",
    "Function",
    "Material",
    "ExpressionGUID",
    "Id",
    "ParameterId",
    "VariableGuid",
    "DeclarationGuid",
    "Outputs",
    "FunctionOutputs",
    "bCollapsed",
    "bCommentBubbleVisible",
    "bShowOutputNameOnPin",
    "bLastPreviewed",
    "ChannelNames",
    "NodeColor",
    "Declaration",
    "Collection",
    "MaterialFunction",
    "FunctionInputs",
    "bRealtimePreview",
    "bHidePreviewWindow",
    "bIsParameterExpression",
}
VEC3_ATTRS = {
    "BaseColor",
    "EmissiveColor",
    "Normal",
    "SubsurfaceColor",
    "WorldPositionOffset",
}


def out_name(node, index):
    return planner_out_name(node, index)


def in_name(node, prop, index, input_name):
    cls = node["cls"]
    if prop == "FunctionInputs":
        return input_name
    if (
        cls == "MaterialExpressionMakeMaterialAttributes"
        and prop == "CustomizedUVs"
    ):
        return "CustomizedUV%d" % (index or 0)
    if (
        cls
        in (
            "MaterialExpressionStaticSwitch",
            "MaterialExpressionStaticSwitchParameter",
        )
        and prop in SWITCH_IN
    ):
        return SWITCH_IN[prop]
    if cls == "MaterialExpressionFunctionOutput" and prop == "A":
        return ""
    return INPUT_MAP.get(prop, prop)


def first_input(node, prop):
    for input_prop, _index, _input_name, ref in node["inputs"]:
        if input_prop == prop:
            return ref
    return None


def positive_pow_enabled(config):
    """Power is clamped for every graph unless explicitly disabled."""
    return not bool(config.get("native_pow", False))


def material_property_by_name(material_property_type, name):
    """Find an enum member by normalized name, including WPO spelling changes."""
    wanted = name.replace("MP_", "").replace(" ", "").lower()
    for member_name in dir(material_property_type):
        normalized = member_name.replace("MP_", "").replace("_", "").lower()
        if normalized == wanted:
            return getattr(material_property_type, member_name)
    return None


def world_position_offset_property(material_property_type):
    for member_name in dir(material_property_type):
        upper = member_name.upper()
        if "WORLD" in upper and "OFFSET" in upper:
            return getattr(material_property_type, member_name)
    return None


def material_property_for_pin(material_property_type, unreal_name):
    if unreal_name == "WORLD_POSITION_OFFSET":
        return world_position_offset_property(material_property_type)
    return material_property_by_name(material_property_type, unreal_name)


__all__ = [
    "BYPASS",
    "BREAK_UE5",
    "INPUT_MAP",
    "ROOT_PINS",
    "SCALAR_ATTRS",
    "SKIP_PROPS",
    "VEC3_ATTRS",
    "first_input",
    "in_name",
    "make_resolver",
    "material_property_for_pin",
    "material_property_by_name",
    "out_name",
    "positive_pow_enabled",
    "world_position_offset_property",
]
