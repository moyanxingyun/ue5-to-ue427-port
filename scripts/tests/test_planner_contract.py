# -*- coding: utf-8 -*-
import importlib.util
import json
import os
import sys
import tempfile
import unittest

SCRIPTS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SCRIPTS_ROOT not in sys.path:
    sys.path.insert(0, SCRIPTS_ROOT)

from material_transplant.planner import (
    report_unsupported,
    plan,
    variant_name,
)
from material_transplant.t3d_parser import load_graphs


DUMPS = os.environ.get("PORTKIT_TEST_DUMPS", "")
MATERIALS = os.environ.get("PORTKIT_TEST_MATERIALS", "")
V13 = os.environ.get("PORTKIT_TEST_V13", "")
MASTER = os.environ.get("PORTKIT_TEST_MASTER", "")
PROBE = os.environ.get(
    "PORTKIT_TEST_PROBE",
    os.path.join(DUMPS, "probe_427.json") if DUMPS else "",
)


@unittest.skipUnless(
    bool(DUMPS)
    and os.path.isdir(DUMPS)
    and os.path.isfile(MATERIALS)
    and os.path.isfile(V13),
    "reference corpus is unavailable",
)
class PlannerContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.graphs = load_graphs(DUMPS)
        with open(MATERIALS, "r", encoding="utf-8") as handle:
            cls.infos = json.load(handle)
        spec = importlib.util.spec_from_file_location("portkit_v13", V13)
        cls.v13 = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.v13)

    @unittest.skipUnless(
        bool(MASTER), "PORTKIT_TEST_MASTER is not set"
    )
    def test_reference_corpus_and_combinations(self):
        self.assertEqual(23, len(self.graphs))
        result = plan(
            self.graphs,
            self.infos,
            MASTER,
            self.v13.FUNC_DIR,
        )
        self.assertEqual(31, len(result["combos"]))
        self.assertEqual(172, len(result["mi_combo"]))

    @unittest.skipUnless(
        bool(MASTER), "PORTKIT_TEST_MASTER is not set"
    )
    def test_plan_matches_v13_json_contract(self):
        new = plan(
            self.graphs,
            self.infos,
            MASTER,
            self.v13.FUNC_DIR,
        )
        old = self.v13.plan(self.graphs, self.infos)
        fields = ("combos", "deps", "calls", "mi_combo", "defaults")
        self.assertEqual(
            json.dumps(old, sort_keys=True, default=list),
            json.dumps(new, sort_keys=True, default=list),
        )
        with tempfile.TemporaryDirectory() as directory:
            for name, payload in (("old", old), ("new", new)):
                with open(
                    os.path.join(directory, name + ".json"),
                    "w",
                    encoding="utf-8",
                ) as handle:
                    json.dump(
                        payload,
                        handle,
                        sort_keys=True,
                        default=list,
                    )
            with open(
                os.path.join(directory, "old.json"),
                "r",
                encoding="utf-8",
            ) as handle:
                first = json.load(handle)
            with open(
                os.path.join(directory, "new.json"),
                "r",
                encoding="utf-8",
            ) as handle:
                second = json.load(handle)
        for field in fields:
            self.assertEqual(first[field], second[field])

    def test_variant_name_is_deterministic(self):
        old = self.v13.plan(self.graphs, self.infos)
        values = dict(old["defaults"])
        values.update(dict(old["combos"][0]))
        graph = "MF_Wetness"
        old_name, _ = self.v13.variant_name(
            graph, values, old["deps"]
        )
        new_name, _ = variant_name(
            graph, values, old["deps"], self.v13.FUNC_DIR
        )
        self.assertEqual(old_name, new_name)

    def test_unsupported_report_flags_custom_and_cap(self):
        report = report_unsupported(
            {
                "MF_Test": {
                    "Node": {
                        "cls": "MaterialExpressionCustom",
                        "name": "Node",
                    }
                }
            },
            {"createable_classes": []},
            combo_count=51,
            max_combos=50,
        )
        self.assertTrue(report["needs_confirm"])
        self.assertEqual(["MF_Test:Node"], report["custom_nodes"])


if __name__ == "__main__":
    unittest.main()
