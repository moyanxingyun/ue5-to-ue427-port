# -*- coding: utf-8 -*-
"""PortKit configuration and report helpers.

Environment:
    Python 3.7+ including UE 4.27 Editor Python.

Use:
    from portkit_config import load_config, section, write_json

The configuration path is taken from ``--config PATH`` when present, then from
the PORTKIT_CONFIG environment variable, then from config.json beside this
file. All filesystem paths and Unreal paths come from the selected JSON file.
"""
import argparse
import importlib
import json
import os
import sys


def _config_from_argv():
    if "--config" in sys.argv:
        index = sys.argv.index("--config")
        if index + 1 < len(sys.argv):
            return sys.argv[index + 1]
    for index, value in enumerate(sys.argv):
        if value.startswith("--config="):
            return value.split("=", 1)[1]
    return None


def find_config(explicit=None):
    candidate = explicit or _config_from_argv() or os.environ.get("PORTKIT_CONFIG")
    if candidate:
        candidate = os.path.abspath(os.path.expanduser(candidate))
        if not os.path.isfile(candidate):
            raise IOError("PortKit config not found: %s" % candidate)
        return candidate
    local = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
    if os.path.isfile(local):
        return local
    raise IOError(
        "PortKit config missing. Copy config_example.json to config.json or "
        "set PORTKIT_CONFIG."
    )


def load_config(explicit=None):
    path = find_config(explicit)
    with open(path, "r", encoding="utf-8") as handle:
        config = json.load(handle)
    config["_config_path"] = path
    config["_config_dir"] = os.path.dirname(path)
    return config


def section(config, name):
    value = config.get(name, {})
    if not isinstance(value, dict):
        raise ValueError("config section %s must be an object" % name)
    return value


def path_value(config, *keys, **kwargs):
    default = kwargs.get("default")
    current = config
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    if current is None:
        return default
    if isinstance(current, str):
        current = os.path.expandvars(os.path.expanduser(current))
        if not os.path.isabs(current) and keys and keys[0] == "paths":
            current = os.path.join(config["_config_dir"], current)
        return os.path.abspath(current)
    return current


def asset_root(config):
    value = path_value(config, "ue427", "target_root", default="/Game")
    return str(value).rstrip("/")


def write_json(path, payload):
    parent = os.path.dirname(os.path.abspath(path))
    if parent and not os.path.isdir(parent):
        os.makedirs(parent)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
    return path


def write_text(path, text):
    parent = os.path.dirname(os.path.abspath(path))
    if parent and not os.path.isdir(parent):
        os.makedirs(parent)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    return path


def report_path(config, name):
    report_dir = path_value(config, "paths", "reports", default=os.getcwd())
    return os.path.join(report_dir, name)


def cli_parser(description):
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--config", help="Path to the PortKit JSON config")
    return parser


def reload_shared_modules():
    """Reload shared modules so edits take effect without restarting UE."""
    names = (
        "material_transplant.t3d_parser",
        "material_transplant.planner",
        "material_transplant.rules_ue427",
        "ue5.export_common",
    )
    for name in names:
        module = importlib.import_module(name)
        importlib.reload(module)
