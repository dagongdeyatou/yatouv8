import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "generate.py"
SPEC = importlib.util.spec_from_file_location("surface_codegen", MODULE_PATH)
assert SPEC and SPEC.loader
surface_codegen = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(surface_codegen)


class SurfaceCodegenTest(unittest.TestCase):
    def fixture(self, root: Path) -> Path:
        descriptor = {
            "key": {
                "kind": "string",
                "display": "now",
                "description": None,
                "registry_key": None,
            },
            "kind": "data",
            "configurable": True,
            "enumerable": True,
            "writable": True,
            "value_type": "function",
            "callable": {
                "name": "now",
                "length": 0,
                "native_like": True,
                "source": "function now() { [native code] }",
            },
            "getter": None,
            "setter": None,
        }
        snapshot = {
            "baseline_id": "chrome150-test",
            "surfaces": [
                {
                    "available": True,
                    "path": "Performance.prototype",
                    "prototype_path": "EventTarget.prototype",
                    "value_type": "object",
                    "own_keys": [descriptor["key"]],
                    "descriptors": [descriptor],
                }
            ],
        }
        path = root / "snapshot.json"
        path.write_text(json.dumps(snapshot), encoding="utf-8")
        return path

    def test_preserves_order_flags_and_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            snapshot = self.fixture(Path(directory))
            manifest = surface_codegen.derive_manifest(snapshot)
        member = manifest["interfaces"][0]["members"][0]
        self.assertEqual(member["handler_id"], "clock.performance_now")
        self.assertTrue(member["configurable"])
        self.assertTrue(member["enumerable"])
        self.assertTrue(member["writable"])
        self.assertEqual(len(member["evidence_refs"][0]["sha256"]), 64)

    def test_generation_is_deterministic(self):
        with tempfile.TemporaryDirectory() as directory:
            snapshot = self.fixture(Path(directory))
            first = surface_codegen.derive_manifest(snapshot)
            second = surface_codegen.derive_manifest(snapshot)
        self.assertEqual(
            surface_codegen.canonical_json(first),
            surface_codegen.canonical_json(second),
        )
        self.assertEqual(
            surface_codegen.render_rust(first),
            surface_codegen.render_rust(second),
        )
        self.assertEqual(
            surface_codegen.runtime_manifest(first),
            surface_codegen.runtime_manifest(second),
        )

    def test_runtime_manifest_strips_evidence_but_keeps_callable_shape(self):
        with tempfile.TemporaryDirectory() as directory:
            snapshot = self.fixture(Path(directory))
            manifest = surface_codegen.derive_manifest(snapshot)
            runtime = surface_codegen.runtime_manifest(manifest)
        member = runtime["interfaces"][0]["members"][0]
        self.assertNotIn("evidence_refs", member)
        self.assertEqual(member["d"], "data")
        self.assertEqual(member["f"]["name"], "now")
        self.assertTrue(member["f"]["native_like"])


if __name__ == "__main__":
    unittest.main()
