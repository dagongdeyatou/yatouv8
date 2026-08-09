from __future__ import annotations

import importlib.util
import pathlib
import sys
import unittest


MODULE_PATH = pathlib.Path(__file__).with_name("session_matrix_runner.py")
sys.path.insert(0, str(MODULE_PATH.parent))
SPEC = importlib.util.spec_from_file_location("google_vm_session_matrix_runner", MODULE_PATH)
assert SPEC and SPEC.loader
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


class GoogleVmSessionMatrixRunnerTests(unittest.TestCase):
    def test_cookie_inventory_never_exposes_values(self) -> None:
        inventory = runner.cookie_inventory(
            [
                {
                    "name": "SG_SS",
                    "value": "*secret",
                    "domain": "www.google.com",
                    "path": "/",
                },
                {
                    "name": "NID",
                    "value": "also-secret",
                    "domain": ".google.com",
                    "path": "/",
                },
            ]
        )

        self.assertEqual(inventory["count"], 2)
        self.assertEqual(inventory["names"], ["NID", "SG_SS"])
        self.assertNotIn("secret", repr(inventory))

    def test_accepted_response_requires_all_result_markers(self) -> None:
        valid = {"status": 200, "sorry": False, "result_dom": True}
        self.assertTrue(runner.accepted_response(valid))
        self.assertFalse(runner.accepted_response({**valid, "status": 429}))
        self.assertFalse(runner.accepted_response({**valid, "sorry": True}))
        self.assertFalse(runner.accepted_response({**valid, "result_dom": False}))


if __name__ == "__main__":
    unittest.main()
