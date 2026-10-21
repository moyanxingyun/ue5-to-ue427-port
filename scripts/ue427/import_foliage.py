# -*- coding: utf-8 -*-
"""Import a foliage mesh export into UE 4.27 using the simplified pipeline.

Environment:
    Unreal Engine 4.27 Editor Python 3.7, Cmd mode.

Use:
    py "PATH/TO/PortKit/scripts/ue427/import_foliage.py" --config "PATH/TO/config.json"

Output:
    Foliage meshes, materials and textures under the configured destination,
    with LOD screen sizes 1/0.25/0.1/0.04 and JSON/TXT reports.
"""
import importlib
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_ROOT = os.path.dirname(SCRIPT_DIR)
if SCRIPTS_ROOT not in sys.path:
    sys.path.insert(0, SCRIPTS_ROOT)

import portkit_config

importlib.reload(portkit_config)
portkit_config.reload_shared_modules()

import ue427.import_assets

importlib.reload(ue427.import_assets)
assets_main = ue427.import_assets.main


if __name__ == "__main__":
    assets_main("foliage")
