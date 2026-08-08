from __future__ import annotations

import importlib.util
import pathlib
import unittest


MODULE_PATH = pathlib.Path(__file__).with_name("runner.py")
SPEC = importlib.util.spec_from_file_location("google_vm_acceptance_runner", MODULE_PATH)
assert SPEC and SPEC.loader
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


class GoogleVmAcceptanceTests(unittest.TestCase):
    def test_source_gate_recognizes_intentional_fallback(self) -> None:
        source = (
            "var g='knitsail';var sp='';var ussv='';"
            "h.knitsail||(h.knitsail={});var c=C[g];if(c){};"
            "var Z=window.sgs&&ussv&&sp?window.sgs(sp):Promise.resolve(false);"
            "Z.then(function(a){a||la()})"
        )

        evidence = runner.source_gate_evidence([source])

        self.assertTrue(evidence["sgs_gate_present"])
        self.assertFalse(evidence["sgs_gate_enabled_by_input"])
        self.assertTrue(evidence["fallback_present"])
        self.assertTrue(evidence["knitsail_initializer_present"])
        self.assertTrue(evidence["knitsail_lookup_present"])

    def test_trace_summary_does_not_treat_void_call_as_missing_api(self) -> None:
        trace = {"events": [
            {
                "level": "l1",
                "entry": {
                    "operation": "call",
                    "target": "EventTarget.prototype",
                    "member": "addEventListener",
                    "outcome": {"value": {"kind": "undefined"}},
                },
            },
            {
                "level": "l1",
                "entry": {
                    "operation": "get",
                    "target": "globalThis",
                    "member": "knitsail",
                    "outcome": {"value": {"kind": "undefined"}},
                },
            },
        ]}

        summary = runner.trace_summary(trace)

        self.assertEqual(len(summary["void_observations"]), 1)
        self.assertEqual(len(summary["undefined_gets"]), 1)

    def test_td_requires_ordered_numeric_timing(self) -> None:
        self.assertTrue(runner.valid_td('{"ns":100,"rs":104}'))
        self.assertFalse(runner.valid_td('{"ns":104,"rs":100}'))
        self.assertFalse(runner.valid_td("{}"))

    def test_pending_navigation_requires_same_entrypoint_and_sei(self) -> None:
        source_url = "https://www.google.com.hk/search?q=kiss+site:imdb.com"
        self.assertTrue(runner.valid_pending_navigation(
            {
                "from": source_url,
                "kind": "replace",
                "url": source_url + "&sei=fixture",
            },
            source_url=source_url,
        ))
        self.assertFalse(runner.valid_pending_navigation(
            {
                "from": source_url,
                "kind": "replace",
                "url": "https://example.test/search?q=fixture&sei=fixture",
            },
            source_url=source_url,
        ))
        self.assertFalse(runner.valid_pending_navigation(
            {
                "from": source_url,
                "kind": "replace",
                "url": source_url,
            },
            source_url=source_url,
        ))

    def test_cookie_record_redacts_token(self) -> None:
        record = runner.redacted_cookie_record({
            "name": "SG_SS",
            "value": "*secret-token",
            "domain": "www.google.com.hk",
            "path": "/",
        })

        self.assertNotIn("value", record)
        self.assertEqual(record["value_prefix"], "*")
        self.assertEqual(record["value_length"], 13)
        self.assertEqual(len(record["value_sha256"]), 64)

    def test_handoff_cookie_requires_challenge_host_scope(self) -> None:
        source_url = "https://www.google.com.hk/search?q=fixture"
        cookie = {
            "name": "SG_SS",
            "value": "*secret-token",
            "domain": ".www.google.com.hk",
            "path": "/",
        }

        self.assertTrue(runner.valid_sg_ss_handoff_cookie(cookie, source_url=source_url))
        cookie["domain"] = "example.test"
        self.assertFalse(runner.valid_sg_ss_handoff_cookie(cookie, source_url=source_url))


if __name__ == "__main__":
    unittest.main()
