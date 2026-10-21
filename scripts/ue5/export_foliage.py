# -*- coding: utf-8 -*-
"""Export foliage meshes and textures with the mesh-export pipeline.

Environment:
    Unreal Engine 5.4 Editor Python, Cmd mode.

Use:
    py "PATH/TO/PortKit/scripts/ue5/export_foliage.py" --config "PATH/TO/config.json"

Output:
    The output directory configured in ue5.exports.foliage, using the same
    manifest/material/texture layout as export_meshes.py.
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

from ue5.export_meshes import main


if __name__ == "__main__":
    main("foliage")
