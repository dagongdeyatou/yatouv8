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

    def test_trusted_types_chrome150_contract(self) -> None:
        with yatouv8.Runtime() as runtime:
            result = runtime.eval(
                """
                (() => {
                    const descriptor = Object.getOwnPropertyDescriptor(
                        globalThis,
                        "trustedTypes",
                    );
                    const policy = trustedTypes.createPolicy("python-regression", {
                        createHTML: value => `H:${value}`,
                        createScript: value => `S:${value}`,
                        createScriptURL: value => `U:${value}`,
                    });
                    const script = policy.createScript("x");
                    let constructorError = null;
                    try {
                        new TrustedScript();
                    } catch (error) {
                        constructorError = `${error.name}: ${error.message}`;
                    }
                    return {
                        factoryTag: Object.prototype.toString.call(trustedTypes),
                        policyTag: Object.prototype.toString.call(policy),
                        scriptTag: Object.prototype.toString.call(script),
                        scriptValue: String(script),
                        scriptJSON: JSON.stringify(script),
                        scriptName: policy.createScript.name,
                        scriptLength: policy.createScript.length,
                        scriptNative: Function.prototype.toString
                            .call(policy.createScript)
                            .includes("[native code]"),
                        isScript: trustedTypes.isScript(script),
                        isStringScript: trustedTypes.isScript("S:x"),
                        globalEnumerable: descriptor.enumerable,
                        globalAccessor: typeof descriptor.get === "function",
                        constructorError,
                    };
                })()
                """
            )
            self.assertEqual(
                result,
                {
                    "factoryTag": "[object TrustedTypePolicyFactory]",
                    "policyTag": "[object TrustedTypePolicy]",
                    "scriptTag": "[object TrustedScript]",
                    "scriptValue": "S:x",
                    "scriptJSON": '"S:x"',
                    "scriptName": "createScript",
                    "scriptLength": 1,
                    "scriptNative": True,
                    "isScript": True,
                    "isStringScript": False,
                    "globalEnumerable": True,
                    "globalAccessor": True,
                    "constructorError": (
                        "TypeError: Failed to construct 'TrustedScript': "
                        "Illegal constructor"
                    ),
                },
            )

            calls = [
                event["entry"]["member"]
                for event in runtime.trace["events"]
                if event["level"] == "l1"
                and event["entry"].get("target")
                in {
                    "TrustedTypePolicyFactory.prototype",
                    "TrustedTypePolicy.prototype",
                }
            ]
            self.assertEqual(calls, ["createPolicy", "createScript", "isScript", "isScript"])

    def test_concurrent_callers_are_serialized_on_owner_thread(self) -> None:
        with yatouv8.Runtime() as runtime:
            runtime.eval("globalThis.concurrentCounter=0")
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                list(pool.map(lambda _: runtime.eval("++concurrentCounter"), range(32)))
            self.assertEqual(runtime.eval("concurrentCounter"), 32)


if __name__ == "__main__":
    unittest.main()
