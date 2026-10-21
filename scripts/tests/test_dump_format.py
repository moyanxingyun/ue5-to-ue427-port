# -*- coding: utf-8 -*-
import os
import sys
import tempfile
import unittest

SCRIPTS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SCRIPTS_ROOT not in sys.path:
    sys.path.insert(0, SCRIPTS_ROOT)

from material_transplant.t3d_parser import parse_text
from ue5.dump_graphs import normalize_expression_blocks


T3D = """Begin Object Class=/Script/Engine.MaterialFunction Name="MF_Test"
   Begin Object Class=/Script/Engine.MaterialExpressionConstant Name="MaterialExpressionConstant_0"
   End Object
   Begin Object Class=/Script/Engine.MaterialExpressionFunctionOutput Name="MaterialExpressionFunctionOutput_0"
   End Object
   Begin Object Name="MaterialExpressionConstant_0"
      R=0.500000
      MaterialExpressionEditorX=-100
      MaterialExpressionEditorY=50
   End Object
   Begin Object Name="MaterialExpressionFunctionOutput_0"
      A=(Expression="/Script/Engine.MaterialExpressionConstant'MF_Test:MaterialExpressionConstant_0'")
      OutputName="Result"
   End Object
End Object
"""


class DumpFormatTests(unittest.TestCase):
    def test_t3d_headers_and_property_blocks_are_merged(self):
        compact = normalize_expression_blocks(T3D)
        self.assertIn(
            'Begin Object Class=/Script/Engine.MaterialExpressionConstant '
            'Name="MaterialExpressionConstant_0"',
            compact,
        )
        self.assertIn("    R=0.500000", compact)
        self.assertNotIn("      R=0.500000", compact)
        nodes = parse_text(compact)
        self.assertEqual(2, len(nodes))
        self.assertEqual(
            "MaterialExpressionConstant",
            nodes["MaterialExpressionFunctionOutput_0"]["inputs"][0][3]["cls"],
        )

    def test_reference_t3d_material_produces_nodes(self):
        source = os.environ.get(
            "PORTKIT_TEST_T3D",
            "",
        )
        if not os.path.isfile(source):
            self.skipTest("reference T3D is unavailable")
        with open(source, "r", encoding="utf-8") as handle:
            compact = normalize_expression_blocks(handle.read())
        nodes = parse_text(compact)
        self.assertGreater(len(nodes), 10)


if __name__ == "__main__":
    unittest.main()
