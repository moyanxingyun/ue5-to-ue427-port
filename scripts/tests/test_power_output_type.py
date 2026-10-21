# -*- coding: utf-8 -*-
import os
import sys
import unittest

SCRIPTS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SCRIPTS_ROOT not in sys.path:
    sys.path.insert(0, SCRIPTS_ROOT)

from material_transplant.build_ue427 import (
    positive_pow_base_components,
    positive_pow_output_type_name,
)


class PositivePowOutputTypeTests(unittest.TestCase):
    def test_output_type_follows_base_component_count(self):
        self.assertIsNone(positive_pow_output_type_name(0))
        self.assertEqual(
            "CMOT_FLOAT1", positive_pow_output_type_name(1)
        )
        self.assertEqual(
            "CMOT_FLOAT2", positive_pow_output_type_name(2)
        )
        self.assertEqual(
            "CMOT_FLOAT3", positive_pow_output_type_name(3)
        )
        self.assertEqual(
            "CMOT_FLOAT4", positive_pow_output_type_name(4)
        )

    def test_base_component_count_controls_output_type(self):
        nodes = {
            "Texture": {
                "cls": "MaterialExpressionTextureSample",
                "name": "Texture",
                "inputs": [],
                "outputs": [],
                "props": {},
            },
            "Unknown": {
                "cls": "MaterialExpressionCustom",
                "name": "Unknown",
                "inputs": [],
                "outputs": [],
                "props": {},
            },
            "Power": {
                "cls": "MaterialExpressionPower",
                "name": "Power",
                "inputs": [
                    (
                        "Base",
                        0,
                        None,
                        {
                            "cls": "MaterialExpressionTextureSample",
                            "node": "Texture",
                            "idx": 0,
                            "mask": "",
                        },
                    )
                ],
                "outputs": [],
                "props": {},
            },
            "SkippedPower": {
                "cls": "MaterialExpressionPower",
                "name": "SkippedPower",
                "inputs": [
                    (
                        "Base",
                        0,
                        None,
                        {
                            "cls": "MaterialExpressionCustom",
                            "node": "Unknown",
                            "idx": 0,
                            "mask": "",
                        },
                    )
                ],
                "outputs": [],
                "props": {},
            },
        }
        self.assertEqual(
            3, positive_pow_base_components(nodes, {}, nodes["Power"])
        )
        self.assertEqual(
            "CMOT_FLOAT3",
            positive_pow_output_type_name(
                positive_pow_base_components(nodes, {}, nodes["Power"])
            ),
        )
        self.assertEqual(
            0,
            positive_pow_base_components(
                nodes, {}, nodes["SkippedPower"]
            ),
        )
        self.assertIsNone(
            positive_pow_output_type_name(
                positive_pow_base_components(
                    nodes, {}, nodes["SkippedPower"]
                )
            )
        )


if __name__ == "__main__":
    unittest.main()
