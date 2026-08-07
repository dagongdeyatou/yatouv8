"""Unit tests for deterministic collector helpers."""

from __future__ import annotations

import importlib.util
import json
import pathlib
import tempfile
import unittest


COLLECTOR_PATH = pathlib.Path(__file__).parents[1] / "collector.py"
SPEC = importlib.util.spec_from_file_location("yatouv8_chrome_collector", COLLECTOR_PATH)
assert SPEC is not None and SPEC.loader is not None
collector = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(collector)

DIFF_PATH = pathlib.Path(__file__).parents[1] / "snapshot_diff.py"
DIFF_SPEC = importlib.util.spec_from_file_location("yatouv8_snapshot_diff", DIFF_PATH)
assert DIFF_SPEC is not None and DIFF_SPEC.loader is not None
snapshot_diff = importlib.util.module_from_spec(DIFF_SPEC)
DIFF_SPEC.loader.exec_module(snapshot_diff)


class CollectorHelpersTest(unittest.TestCase):
    """Verify content addressing and pollution helper invariants."""

    def test_canonical_json_preserves_array_order(self) -> None:
        self.assertEqual(collector.canonical_json_bytes({"b": [2, 1], "a": 3}), b'{"a":3,"b":[2,1]}\n')

    def test_sanitize_flags_only_redacts_ephemeral_profile(self) -> None:
        flags = ["--remote-debugging-port=43123", r"--user-data-dir=C:\Temp\profile", "about:blank"]
        self.assertEqual(
            collector.sanitize_flags(flags),
            [
                "--remote-debugging-port=<ephemeral-nonzero>",
                "--user-data-dir=<ephemeral>",
                "about:blank",
            ],
        )

    def test_pollution_delta_counts_duplicate_symbols(self) -> None:
        added, removed = collector.pollution_delta(["symbol:x", "symbol:x"], ["symbol:x"])
        self.assertEqual(added, [])
        self.assertEqual(removed, ["symbol:x"])

    def test_content_store_uses_sha256_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            digest, relative = collector.store_object(root, b"yatouv8")
            self.assertEqual(digest, collector.sha256_bytes(b"yatouv8"))
            self.assertEqual((root / relative).read_bytes(), b"yatouv8")

    def test_snapshot_diff_ignores_run_identity_and_clock_values(self) -> None:
        left = {
            "baseline_id": "chrome150",
            "run_id": "left",
            "captured_at": "first",
            "environment": {
                "clock_sample": {"date_now_ms": 1},
                "clock_profile": {
                    "tight_loop_samples": 1,
                    "delayed_samples": 1,
                    "samples": [{"date_now_ms": 1}],
                    "summary": {"sample_count": 2},
                },
            },
            "surfaces": ["Object"],
        }
        right = json.loads(json.dumps(left))
        right["run_id"] = "right"
        right["captured_at"] = "second"
        right["environment"]["clock_sample"]["date_now_ms"] = 2
        right["environment"]["clock_profile"]["samples"] = [{"date_now_ms": 2}]
        self.assertTrue(snapshot_diff.compare(left, right)["stable_equal"])


if __name__ == "__main__":
    unittest.main()
