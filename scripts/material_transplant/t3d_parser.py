# -*- coding: utf-8 -*-
"""Parse Unreal material expression dumps.

Environment:
    Plain Python 3.7+; no ``unreal`` module required.

Use:
    from material_transplant.t3d_parser import parse_dump, load_graphs

Output:
    A dictionary of expression name -> normalized node dictionary. The parser
    accepts the compact dumps written by PortKit/dump_graphs.py and the
    Begin Object / End Object text files included in the reference corpus.
"""
import glob
import os
import re


BLOCK_RE = re.compile(
    r'^Begin Object Class=/Script/Engine\.(\w+) Name="([^"]+)"[^\n]*\n'
    r"(.*?)^End Object",
    re.M | re.S,
)
LINE_RE = re.compile(r"^\s{4}(\w+)(?:\((\d+)\))?=(.*)$")
REF_RE = re.compile(
    r'Expression="/Script/Engine\.(\w+)\'[^\']*?:([^\':]+)\'"'
)
SWITCH_PARAMS = (
    "MaterialExpressionStaticSwitchParameter",
    "MaterialExpressionStaticBoolParameter",
)


def parse_ref(value):
    match = REF_RE.search(value)
    if not match:
        return None
    output = re.search(r"OutputIndex=(-?\d+)", value)
    return {
        "cls": match.group(1),
        "node": match.group(2),
        "idx": int(output.group(1)) if output else 0,
        "mask": "".join(
            channel for channel in "RGBA" if ("Mask%s=1" % channel) in value
        ),
    }


def parse_dump(path):
    with open(path, "r", encoding="utf-8") as handle:
        return parse_text(handle.read())


def parse_text(text):
    nodes = {}
    for cls, name, body in BLOCK_RE.findall(text):
        node = {
            "cls": cls,
            "name": name,
            "props": {},
            "inputs": [],
            "x": 0,
            "y": 0,
            "outputs": [],
            "func": None,
        }
        for line in body.splitlines():
            match = LINE_RE.match(line)
            if not match:
                continue
            key, index, value = match.group(1), match.group(2), match.group(3).strip()
            if key == "MaterialExpressionEditorX":
                node["x"] = int(value)
            elif key == "MaterialExpressionEditorY":
                node["y"] = int(value)
            elif key == "Outputs":
                output = re.search(r'OutputName="([^"]*)"', value)
                node["outputs"].append(output.group(1) if output else "")
            elif key == "MaterialFunction":
                function = re.search(r"MaterialFunction'([^']+)'", value)
                node["func"] = (
                    function.group(1).split(".")[0] if function else None
                )
            elif key == "FunctionInputs":
                ref = parse_ref(value)
                input_name = re.search(r'InputName="([^"]*)"', value)
                if ref:
                    node["inputs"].append(
                        (
                            "FunctionInputs",
                            int(index),
                            input_name.group(1) if input_name else "",
                            ref,
                        )
                    )
            elif key == "Declaration":
                declaration = re.search(r"'[^']*?:([^':]+)'", value)
                node["props"]["Declaration"] = (
                    declaration.group(1) if declaration else None
                )
            elif 'Expression="' in value and value.startswith("("):
                ref = parse_ref(value)
                if ref:
                    node["inputs"].append(
                        (key, int(index) if index else None, None, ref)
                    )
            elif not value.startswith("("):
                node["props"][key] = value
            elif key in ("Constant", "DefaultValue", "PreviewValue", "CommentColor"):
                node["props"][key] = value
        nodes[name] = node
    return nodes


def strip_q(value):
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        return value[1:-1]
    return value


def switch_params(nodes):
    result = {}
    for node in nodes.values():
        if node["cls"] in SWITCH_PARAMS:
            name = strip_q(node["props"].get("ParameterName", '""'))
            result[name] = node["props"].get("DefaultValue", "False") == "True"
    return result


def load_graphs(dumps_dir, pattern="*.txt"):
    graphs = {}
    for path in sorted(glob.glob(os.path.join(dumps_dir, pattern))):
        name = os.path.splitext(os.path.basename(path))[0]
        graphs[name] = parse_dump(path)
    return graphs


def first_input(node, prop):
    for input_prop, _index, _input_name, ref in node["inputs"]:
        if input_prop == prop:
            return ref
    return None
