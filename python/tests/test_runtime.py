from __future__ import annotations

import concurrent.futures
import unittest

import yatouv8


class RuntimeTests(unittest.TestCase):
    def test_persistent_dom_timer_resource_and_trace(self) -> None:
        with yatouv8.Runtime() as runtime:
            self.assertEqual(runtime.eval("globalThis.answer = 41; answer + 1"), 42)
            self.assertEqual(runtime.eval("answer"), 41)
            self.assertEqual(
                runtime.eval(
                    "const node=document.createElement('div');"
                    "node.id='probe';document.body.appendChild(node);"
                    "document.querySelector('#probe').id"
                ),
                "probe",
            )

            runtime.add_resource(
                "https://fixture.invalid/data.json",
                '{"answer":42}',
                headers={"content-type": "application/json"},
            )
            runtime.eval(
                "globalThis.fetched=null;"
                "fetch('https://fixture.invalid/data.json')"
                ".then(r=>r.json()).then(v=>{globalThis.fetched=v.answer});"
                "'scheduled'"
            )
            self.assertEqual(runtime.eval("fetched"), 42)

            runtime.eval("globalThis.timerValue=0;setTimeout(()=>timerValue=7,5);'timer'")
            self.assertEqual(runtime.drain()["pendingTimers"], 0)
            self.assertEqual(runtime.eval("timerValue"), 7)

            trace = runtime.trace
            self.assertTrue(trace["footer"]["complete"])
            self.assertGreater(trace["footer"]["event_count"], 0)
            self.assertFalse(runtime.environment["networkFallback"])

    def test_js_exception_does_not_destroy_context(self) -> None:
        with yatouv8.Runtime() as runtime:
            with self.assertRaises(yatouv8.JSException):
                runtime.eval("throw new TypeError('expected')")
            self.assertEqual(runtime.eval("6 * 7"), 42)

    def test_concurrent_callers_are_serialized_on_owner_thread(self) -> None:
        with yatouv8.Runtime() as runtime:
            runtime.eval("globalThis.concurrentCounter=0")
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                list(pool.map(lambda _: runtime.eval("++concurrentCounter"), range(32)))
            self.assertEqual(runtime.eval("concurrentCounter"), 32)


if __name__ == "__main__":
    unittest.main()
