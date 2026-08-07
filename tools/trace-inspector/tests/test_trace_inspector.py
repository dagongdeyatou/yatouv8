"""Tests for the independent trace-inspector stream checks."""

from __future__ import annotations

import importlib.util
import json
import pathlib
import tempfile
import unittest


INSPECTOR_PATH = pathlib.Path(__file__).parents[1] / "trace_inspector.py"
SPEC = importlib.util.spec_from_file_location("yatouv8_trace_inspector", INSPECTOR_PATH)
assert SPEC is not None and SPEC.loader is not None
inspector = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(inspector)


def record(record_type: str, value: dict[str, object]) -> str:
    """Encode one test record."""
    return json.dumps({"record_type": record_type, "record": value})


class TraceInspectorTest(unittest.TestCase):
    """Exercise event and footer ordering checks."""

    def write_fixture(self, event_seq: int = 0) -> pathlib.Path:
        """Write one tiny complete trace and return its path."""
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = pathlib.Path(directory.name) / "trace.ndjson"
        lines = [
            record("header", {"trace_id": "test", "baseline_id": "chrome150", "source": "fixture"}),
            record(
                "event",
                {
                    "seq": event_seq,
                    "logical_time_ns": 0,
                    "parent_seq": None,
                    "level": "l1",
                    "entry": {
                        "operation": "get",
                        "target": "Navigator.prototype",
                        "member": "userAgent",
                        "arguments": [],
                        "outcome": {"kind": "return"},
                        "call_site": None,
                    },
                },
            ),
            record(
                "footer",
                {
                    "event_count": 1,
                    "l0_count": 0,
                    "l1_count": 1,
                    "last_seq": 0,
                    "complete": True,
                },
            ),
        ]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def test_summarizes_l1_ledger(self) -> None:
        summary = inspector.inspect_trace(self.write_fixture())
        self.assertEqual(summary["l1_operations"], {"get": 1})
        self.assertEqual(summary["api_ledger"][0]["api"], "Navigator.prototype.userAgent")

    def test_rejects_sequence_gap(self) -> None:
        with self.assertRaises(inspector.TraceInspectionError):
            inspector.inspect_trace(self.write_fixture(event_seq=1))


if __name__ == "__main__":
    unittest.main()
