"""The parametric stages on the example lamp: parameters from a schema, the kit table, the rules stage, the stand-in render
and measure, gates with their mutants, and the trust rule for the three new adapter kinds."""
import copy
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "pipeline"))
sys.path.insert(0, str(REPO))
import adapter_config  # noqa: E402
import kit_table  # noqa: E402
import param_gates  # noqa: E402
import param_run  # noqa: E402
import rules_generate  # noqa: E402
from core import parameters  # noqa: E402

EXAMPLE = REPO / "examples" / "parametric"
SCHEMA_FILE = EXAMPLE / "schema" / "lamp.schema.json"
KIT_FILE = EXAMPLE / "parametric" / "lamp.kit.json"
SCHEMA = json.loads(SCHEMA_FILE.read_text())
KIT = json.loads(KIT_FILE.read_text())
GATES = param_gates.validate(json.loads((EXAMPLE / "parametric" / "lamp.gates.json").read_text()))
MODEL = parameters.model(SCHEMA)
CROSS = {"theme": ["modern", "rustic", "industrial"], "material": ["oak", "steel"]}


class Parameters(unittest.TestCase):
    def test_fields_carry_range_step_unit_and_variant(self):
        fields = {f["name"]: f for f in MODEL["fields"]}
        self.assertEqual((fields["height_cm"]["min"], fields["height_cm"]["max"], fields["height_cm"]["step"], fields["height_cm"]["unit"]), (30, 200, 5, "cm"))
        self.assertEqual(fields["shade"]["values"], ["drum", "cone"])
        self.assertEqual(fields["colour"]["type"], "colour")
        self.assertEqual(fields["has_arm"]["type"], "boolean")
        self.assertEqual(fields["cone_top_cm"]["builders"], ["cone"])

    def test_the_selector_and_the_switch_decide_which_fields_apply(self):
        names = lambda row: {f["name"] for f in parameters.active(MODEL, row)}  # noqa: E731
        self.assertIn("drum_radius_cm", names({"shade": "drum", "has_arm": False}))
        self.assertNotIn("cone_top_cm", names({"shade": "drum"}))
        self.assertNotIn("arm_reach_cm", names({"shade": "drum", "has_arm": False}))
        self.assertIn("arm_reach_cm", names({"shade": "cone", "has_arm": True}))

    def test_row_problems_name_the_field(self):
        row = {"shade": "drum", "height_cm": 33, "base_radius_cm": 9, "has_arm": False, "colour": "red", "drum_radius_cm": 20, "cone_top_cm": 5}
        text = "; ".join(parameters.row_problems(MODEL, row))
        self.assertIn("height_cm: 33 is not a multiple of 5", text)
        self.assertIn("colour:", text)
        self.assertIn("cone_top_cm: does not apply", text)

    def test_defaults_sit_on_the_step_grid(self):
        for f in MODEL["fields"]:
            if f["type"] in ("number", "integer"):
                self.assertIsNone(parameters.value_problem(f, f["default"]), f["name"])

    def test_a_schema_with_no_bounded_number_is_not_parametric(self):
        self.assertFalse(parameters.is_parametric(parameters.model({"properties": {"name": {"type": "string"}, "size": {"type": "string", "enum": ["a"]}}})))


    def test_a_boolean_subschema_gives_no_parameter(self):
        schema = {"x-selector": "s", "properties": {"x": True, "y": False, "h": {"type": "number", "minimum": 0, "maximum": 1}},
                  "allOf": [True, {"if": True, "then": {"properties": {"z": True}}}]}
        self.assertEqual([f["name"] for f in parameters.model(schema)["fields"]], ["h"])

    def test_infinity_and_nan_are_invalid_values_not_errors(self):
        number = {"type": "number", "min": 0, "max": 10, "step": None}
        whole = {**number, "type": "integer", "step": 1}
        for field in (number, whole):
            for bad in (float("inf"), float("-inf"), float("nan")):
                self.assertIsNotNone(parameters.value_problem(field, bad), (field["type"], bad))


class Kit(unittest.TestCase):
    def problems(self, change):
        kit = copy.deepcopy(KIT)
        change(kit)
        return kit_table.validate(kit, MODEL, SCHEMA["properties"])

    def test_a_field_of_the_wrong_type_is_named_not_raised(self):
        for rule_change, text in (
            (lambda r: r.update(when=["theme"]), "/rules/0/when"),
            (lambda r: r.update(ranges=[1, 2]), "/rules/0/ranges"),
            (lambda r: r.update(choices="x"), "/rules/0/choices"),
            (lambda r: r.update(colours=5), "/rules/0/colours"),
            (lambda r: r.update(builder=3), "/rules/0/builder"),
            (lambda r: r.update(about=3), "/rules/0/about"),
        ):
            found = self.problems(lambda kit: rule_change(kit["rules"][0]))
            self.assertTrue(any(text in p for p in found), (text, found))
        self.assertTrue(any("/rules:" in p for p in self.problems(lambda k: k.update(rules={"a": 1}))))
        self.assertTrue(any("/defaults:" in p for p in self.problems(lambda k: k.update(defaults=["a"]))))
        self.assertTrue(any("/forbidden:" in p for p in self.problems(lambda k: k.update(forbidden={"a": 1}))))

    def test_the_example_kit_is_sound(self):
        self.assertEqual(kit_table.validate(KIT, MODEL, SCHEMA["properties"]), [])

    def test_each_kind_of_mistake_is_named(self):
        cases = [
            (lambda k: k["rules"][1]["ranges"].update(height_cm=[10, 500]), "/rules/1/ranges/height_cm"),
            (lambda k: k["rules"][1]["ranges"].update(sparkle=[1, 2]), "not a parameter"),
            (lambda k: k["rules"][1].update(builder="dome"), "/rules/1/builder"),
            (lambda k: k["rules"][1]["when"].update(colour="x"), "not in subject_fields"),
            (lambda k: k["rules"][1]["colours"].update(colour=["red"]), "colours"),
            (lambda k: k["forbidden"].append({"nope": 1}), "/forbidden/1/nope"),
            (lambda k: k.update(extra=1), "/extra"),
        ]
        for change, text in cases:
            with self.subTest(text):
                self.assertTrue(any(text in p for p in self.problems(change)), self.problems(change))


class Rules(unittest.TestCase):
    def make(self, seed=3, count=4, cross=CROSS):
        return rules_generate.generate(SCHEMA, KIT, {"subject": {}, "cross": cross}, seed, count)

    def test_every_row_is_valid_and_follows_its_cell(self):
        made = self.make()
        self.assertEqual(len(made["rows"]), 24)
        for entry in made["rows"]:
            row = entry["row"]
            self.assertEqual(parameters.row_problems(MODEL, row), [], row)
            self.assertEqual(row["theme"], entry["cell"]["theme"])
            if row["theme"] == "modern":
                self.assertEqual(row["shade"], "drum")
                self.assertTrue(60 <= row["height_cm"] <= 140 and row["base_radius_cm"] <= 14)
            if row["theme"] == "industrial":
                self.assertTrue(row["has_arm"] and 20 <= row["arm_reach_cm"] <= 60)
            if row["theme"] == "rustic":
                self.assertEqual(row["shade"], "drum")  # the forbidden combination was dropped
                self.assertNotIn("arm_reach_cm", row)
            if row["material"] == "oak":
                self.assertGreaterEqual(row["base_radius_cm"], 12)

    def test_same_inputs_same_rows_and_another_seed_differs(self):
        self.assertEqual(self.make(), self.make())
        self.assertNotEqual(self.make(seed=4)["rows"], self.make(seed=3)["rows"])

    def test_a_cross_of_three_fields_or_too_many_rows_is_refused(self):
        with self.assertRaises(ValueError):
            self.make(cross={**CROSS, "shade": ["drum"]})
        with self.assertRaises(ValueError):
            self.make(count=200)

    def test_rules_that_leave_nothing_are_an_error(self):
        kit = copy.deepcopy(KIT)
        kit["rules"].append({"when": {"theme": "modern"}, "ranges": {"height_cm": [150, 160]}})
        with self.assertRaises(kit_table.KitError):
            rules_generate.generate(SCHEMA, kit, {"cross": {"theme": ["modern"]}}, 1, 1)

    def test_twenty_rows_in_milliseconds(self):
        started = time.monotonic()
        self.make(count=20, cross={"theme": ["modern"]})
        self.assertLess(time.monotonic() - started, 0.5)


class Stages(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        config = self.folder / "machine.json"
        config.write_text("{}")
        self.adapters = adapter_config.from_machine({"GENSTAGE_MACHINE_CONFIG": str(config)})

    def test_a_batch_of_twenty_runs_through_the_adapters(self):
        started = time.monotonic()
        batch = param_run.run_batch(self.adapters, None, SCHEMA_FILE, KIT_FILE, GATES,
                                    {"subject": {}, "cross": {"theme": ["modern", "industrial"]}}, 5, 10, self.folder / "batch")
        self.assertLess(time.monotonic() - started, 20)
        self.assertEqual(len(batch["tiles"]), 20)
        self.assertTrue(all((self.folder / "batch" / "tiles" / t["id"] / "still.png").is_file() for t in batch["tiles"]))
        self.assertEqual(batch["adapters"], {"rules": "rules-kit", "render": "standin-render", "measure": "standin-measure"})
        verdicts = {t["verdict"] for t in batch["tiles"]}
        self.assertTrue(verdicts <= {"pass", "review", "fail"} and "fail" in verdicts, verdicts)  # the wide industrial lamps trip not_a_blob

    def test_the_same_row_gives_the_same_picture(self):
        row = rules_generate.generate(SCHEMA, KIT, {"cross": {"theme": ["modern"]}}, 1, 1)["rows"][0]["row"]
        one = param_run.render_one(self.adapters, None, SCHEMA_FILE, row, 1, self.folder / "a")
        two = param_run.render_one(self.adapters, None, SCHEMA_FILE, row, 1, self.folder / "b")
        self.assertEqual((self.folder / "a" / "still.png").read_bytes(), (self.folder / "b" / "still.png").read_bytes())
        self.assertEqual(one["numbers"], two["numbers"])

    def test_every_gate_fails_on_its_mutant_and_a_good_row_passes(self):
        def measured(row):
            return param_run.render_one(self.adapters, None, SCHEMA_FILE, row, 0, self.folder / "m")["numbers"]
        self.assertEqual(param_gates.check_mutants(GATES, measured), [])
        for gate in GATES:
            self.assertEqual(parameters.row_problems(MODEL, gate["mutant"]["row"]), [], gate["id"])
        good = {"name": "x", "shade": "drum", "height_cm": 100, "base_radius_cm": 12, "has_arm": False, "colour": "#a0714f", "drum_radius_cm": 20}
        self.assertEqual(param_run.render_one(self.adapters, None, SCHEMA_FILE, good, 0, self.folder / "g", GATES)["verdict"], "pass")

    def test_a_gate_without_a_mutant_that_fails_it_is_reported(self):
        lax = [{**GATES[0], "min": 0.0}]
        problems = param_gates.check_mutants(lax, lambda row: {"ink_ratio": 0.5})
        self.assertEqual(len(problems), 1)
        with self.assertRaises(param_gates.GateError):
            param_gates.validate({"gates": [{"id": "a", "measure": "m", "min": 1, "verdict": "fail"}]})

    def test_a_measure_file_of_the_wrong_shape_is_refused(self):
        entry = {"id": "bad-measure", "kind": "measure", "argv": ["{python}", "-I", "-c", "import sys; open(sys.argv[1], 'w').write('[1]')", "{output}"],
                 "sandbox": {"network": "allow"}, "licence": "test"}
        config = self.folder / "m2.json"
        config.write_text(json.dumps({"adapters": [entry]}))
        adapters = adapter_config.from_machine({"GENSTAGE_MACHINE_CONFIG": str(config)})
        with self.assertRaises(Exception) as caught:
            param_run.render_one(adapters, {"measure": "bad-measure"}, SCHEMA_FILE, {"shade": "drum"}, 0, self.folder / "x")
        self.assertIn("measure.json", str(caught.exception))


class Trust(unittest.TestCase):
    def entry(self, kind, argv):
        return {"id": "t", "kind": kind, "argv": argv, "sandbox": {"network": "deny"}, "licence": "test"}

    def test_the_new_kinds_take_only_their_own_placeholders(self):
        adapter_config.parse_entry(self.entry("render", ["/bin/true", "{row}", "{schema}", "{output}", "{out_dir}", "{seed}"]), "t")
        adapter_config.parse_entry(self.entry("measure", ["/bin/true", "{row}", "{image}", "{output}"]), "t")
        adapter_config.parse_entry(self.entry("rules", ["/bin/true", "{schema}", "{kit}", "{subject}", "{count}", "{output}"]), "t")
        for kind, bad in (("render", "{prompt}"), ("measure", "{mesh}"), ("rules", "{image}")):
            with self.subTest(kind), self.assertRaises(adapter_config.AdapterError):
                adapter_config.parse_entry(self.entry(kind, ["/bin/true", bad]), "t")

    def test_a_request_cannot_choose_a_command_only_an_id_of_the_right_kind(self):
        config = self.tmp_adapters()
        for chosen in ("standin-image", "../x", "rm -rf /", 5):
            with self.subTest(chosen), self.assertRaises(adapter_config.AdapterError):
                config.pick(chosen, "render")
        self.assertEqual(config.pick("standin-render", "render").id, "standin-render")

    def tmp_adapters(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "m.json"
            path.write_text("{}")
            return adapter_config.from_machine({"GENSTAGE_MACHINE_CONFIG": str(path)})

    def test_a_row_value_stays_one_argument(self):
        argv, _, _ = adapter_config.command(self.tmp_adapters().entries["standin-render"], {"row": "a b; rm -rf ~", "schema": "s", "output": "o", "out_dir": "d", "seed": 1})
        self.assertIn("a b; rm -rf ~", argv)


if __name__ == "__main__":
    unittest.main()
