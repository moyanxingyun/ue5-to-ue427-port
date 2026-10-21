# -*- coding: utf-8 -*-
import json
import os
import sys
import types
import unittest

SCRIPTS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SCRIPTS_ROOT not in sys.path:
    sys.path.insert(0, SCRIPTS_ROOT)

from ue427.import_assets import foliage_spec_of


class FoliageSpecTests(unittest.TestCase):
    def test_masked_plant_extracts_texture_roles_and_values(self):
        config_path = os.path.join(
            SCRIPTS_ROOT, "config_example.json"
        )
        with open(config_path, "r", encoding="utf-8") as handle:
            config = json.load(handle)
        runtime = types.SimpleNamespace(
            foliage_config=config["ue427"]["imports"]["foliage"][
                "foliage_material"
            ],
            fill_marker="T_L_Fill_",
        )
        info = {
            "textures": {
                "00_BaseColor": "/Game/T_Grass_BC",
                "00_Normal": "/Game/T_Grass_N",
                "00_ORM": "/Game/T_Grass_ORM",
                "00_OpacityMask": "/Game/T_Grass_Mask",
            },
            "vectors": {
                "00_BaseColorTint": [0.8, 0.9, 0.7, 1.0],
                "00_UVTiling": [2.0, 2.0, 0, 0],
            },
            "scalars": {"00_NormalIntensity": -0.8},
            "base": {"blend_mode": "BLEND_MASKED"},
            "overrides": {},
        }
        spec = foliage_spec_of(info, runtime)
        self.assertTrue(spec["foliage"])
        self.assertEqual(
            "/Game/T_Grass_Mask", spec["textures"]["OpacityMask"]
        )
        self.assertEqual((2.0, 2.0), spec["uv"])
        self.assertEqual(0.8, spec["normal"])
        self.assertEqual([0.8, 0.9, 0.7, 1.0], spec["tint"])


if __name__ == "__main__":
    unittest.main()
