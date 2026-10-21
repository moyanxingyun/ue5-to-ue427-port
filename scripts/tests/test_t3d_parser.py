# -*- coding: utf-8 -*-
import os
import sys
import tempfile
import unittest

SCRIPTS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SCRIPTS_ROOT not in sys.path:
    sys.path.insert(0, SCRIPTS_ROOT)

from material_transplant.planner import make_comps, needs_lerp_alpha_r
from material_transplant.t3d_parser import parse_dump, parse_ref


SAMPLE = '''Begin Object Class=/Script/Engine.MaterialExpressionVectorParameter Name="MaterialExpressionVectorParameter_0" ExportPath="/Game/M.M:MaterialExpressionVectorParameter_0"
    ParameterName="Color"
    DefaultValue=(R=1.0,G=0.5,B=0.25,A=1.0)
End Object
Begin Object Class=/Script/Engine.MaterialExpressionLinearInterpolate Name="MaterialExpressionLinearInterpolate_0"
    A=(Expression="/Script/Engine.MaterialExpressionVectorParameter'Material_0:MaterialExpressionVectorParameter_0'",OutputIndex=0)
    B=(Expression="/Script/Engine.MaterialExpressionConstant3Vector'Material_0:MaterialExpressionConstant3Vector_0'",OutputIndex=0)
    Alpha=(Expression="/Script/Engine.MaterialExpressionVectorParameter'Material_0:MaterialExpressionVectorParameter_0'",OutputIndex=0,Mask=1,MaskR=1)
    MaterialExpressionEditorX=10
    MaterialExpressionEditorY=20
End Object
'''


class ParserTests(unittest.TestCase):
    def test_parse_and_transform_alpha_component_mask(self):
        handle, path = tempfile.mkstemp(suffix=".txt")
        os.close(handle)
        try:
            with open(path, "w", encoding="utf-8") as stream:
                stream.write(SAMPLE)
            nodes = parse_dump(path)
        finally:
            os.remove(path)
        self.assertEqual(2, len(nodes))
        lerp = nodes["MaterialExpressionLinearInterpolate_0"]
        self.assertEqual(10, lerp["x"])
        self.assertEqual(20, lerp["y"])
        self.assertEqual(3, len(lerp["inputs"]))
        self.assertEqual("R", lerp["inputs"][2][3]["mask"])
        comps = make_comps(nodes, {})
        self.assertEqual(
            4,
            comps("MaterialExpressionVectorParameter_0", 0),
        )
        self.assertTrue(
            needs_lerp_alpha_r(
                nodes, {}, nodes["MaterialExpressionLinearInterpolate_0"]
            )
        )

    def test_parse_ref_output_index(self):
        ref = parse_ref(
            "Expression=\"/Script/Engine.MaterialExpressionTextureSample"
            "'M:T_0'\",OutputIndex=5,Mask=1,MaskA=1"
        )
        self.assertEqual("T_0", ref["node"])
        self.assertEqual(5, ref["idx"])
        self.assertEqual("A", ref["mask"])


if __name__ == "__main__":
    unittest.main()
