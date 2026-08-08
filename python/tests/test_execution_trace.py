from __future__ import annotations

import unittest

from yatouv8.execution_trace import analyze_execution_trace


class ExecutionTraceAnalysisTests(unittest.TestCase):
    def test_symbol_in_zero_count_range_is_ranked_first(self) -> None:
        source = "const emoji='😀';if(check){globalThis.knitsail={}}else{reject()}"
        start = len("const emoji='😀';if(check){".encode("utf-16-le")) // 2
        end = len("const emoji='😀';if(check){globalThis.knitsail={}}".encode("utf-16-le")) // 2
        capture = {
            "scripts": [{
                "script_id": "9",
                "role": "nested_dynamic_script",
                "source": source,
                "functions": [{
                    "functionName": "",
                    "ranges": [
                        {"startOffset": 0, "endOffset": len(source), "count": 1},
                        {"startOffset": start, "endOffset": end, "count": 0},
                    ],
                }],
                "missed_range_snippets": [{
                    "function_name": "",
                    "start_offset": start,
                    "end_offset": end,
                    "context_start_offset": 0,
                    "context_end_offset": len(source),
                    "context": source,
                }],
            }],
        }

        report = analyze_execution_trace(capture, ("knitsail",))

        self.assertEqual(report["summary"]["missed_symbol_occurrences"], 1)
        self.assertEqual(report["ranked_blockers"][0]["rank_class"], 0)
        self.assertEqual(report["ranked_blockers"][0]["symbol"], "knitsail")
        self.assertIn("if(check)", report["ranked_blockers"][0]["context"])


if __name__ == "__main__":
    unittest.main()
