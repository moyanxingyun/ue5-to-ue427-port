# -*- coding: utf-8 -*-
import os
import sys
import unittest

SCRIPTS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SCRIPTS_ROOT not in sys.path:
    sys.path.insert(0, SCRIPTS_ROOT)

from material_transplant.rules_ue427 import (
    in_name,
    material_property_for_pin,
    positive_pow_enabled,
    world_position_offset_property,
)


class RulesTests(unittest.TestCase):
    def test_positive_pow_defaults_on_and_can_be_disabled(self):
        self.assertTrue(positive_pow_enabled({}))
        self.assertFalse(positive_pow_enabled({"native_pow": True}))

    def test_wpo_is_found_by_name(self):
        class MaterialProperty(object):
            MP_BASE_COLOR = object()
            MP_WORLD_POSITION_OFFSET = object()

        self.assertEqual(
            MaterialProperty.MP_WORLD_POSITION_OFFSET,
            world_position_offset_property(MaterialProperty),
        )
        self.assertEqual(
            MaterialProperty.MP_WORLD_POSITION_OFFSET,
            material_property_for_pin(
                MaterialProperty, "WORLD_POSITION_OFFSET"
            ),
        )

    def test_pin_translation(self):
        node = {"cls": "MaterialExpressionStaticSwitch", "inputs": []}
        self.assertEqual("True", in_name(node, "A", 0, None))
        self.assertEqual("False", in_name(node, "B", 1, None))


if __name__ == "__main__":
    unittest.main()
