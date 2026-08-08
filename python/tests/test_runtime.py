from __future__ import annotations

import concurrent.futures
import unittest

import yatouv8


class RuntimeTests(unittest.TestCase):
    GET_TRACE_SOURCE = """
        (() => {
            const canvas = document.createElement("canvas");
            const event = new Event("probe");
            const locationDescriptor = Object.getOwnPropertyDescriptor(
                globalThis,
                "location",
            );
            return {
                userAgent: navigator.userAgent,
                screenWidth: screen.width,
                cookie: document.cookie,
                locationHref: location.href,
                performanceOrigin: performance.timeOrigin,
                canvasContext: canvas.getContext("2d"),
                canvasWidth: canvas.clientWidth,
                stableNavigator: navigator === navigator,
                stableDocument: document === document,
                windowIdentity: window === self,
                eventIsEvent: event instanceof Event,
                locationIsDataDescriptor: "value" in locationDescriptor,
                dynamicNavigator: globalThis["navigator"] === navigator,
                missingGlobal: globalThis.DefinitelyMissingChromeSurface,
            };
        })()
    """

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

    def test_td_candidate_api_semantics_match_chrome150(self) -> None:
        with yatouv8.Runtime() as runtime:
            result = runtime.eval(
                """
                (() => {
                    const canvas = document.createElement("canvas");
                    const context = canvas.getContext("2d");
                    const media = matchMedia(
                        "(min-width: 1px) and (orientation: landscape)",
                    );
                    const indexDescriptor = Object.getOwnPropertyDescriptor(
                        navigator.plugins,
                        "0",
                    );
                    const nameDescriptor = Object.getOwnPropertyDescriptor(
                        navigator.plugins,
                        "PDF Viewer",
                    );
                    return {
                        chromeKeys: Reflect.ownKeys(chrome),
                        chromeRuntime: typeof chrome.runtime,
                        userAgentData: typeof navigator.userAgentData,
                        navigatorOwnKeys: Reflect.ownKeys(navigator),
                        screenOwnKeys: Reflect.ownKeys(screen),
                        pluginTag: Object.prototype.toString.call(navigator.plugins),
                        pluginLength: navigator.plugins.length,
                        pluginName: navigator.plugins[0].name,
                        pluginMime: navigator.plugins[0][0].type,
                        pluginItemStable: navigator.plugins.item(0) === navigator.plugins[0],
                        pluginNamedStable: navigator.plugins.namedItem("PDF Viewer") === navigator.plugins[0],
                        indexDescriptor: [indexDescriptor.enumerable, indexDescriptor.configurable, indexDescriptor.writable],
                        nameDescriptor: [nameDescriptor.enumerable, nameDescriptor.configurable, nameDescriptor.writable],
                        mimeTag: Object.prototype.toString.call(navigator.mimeTypes),
                        mimeLength: navigator.mimeTypes.length,
                        permissionsTag: Object.prototype.toString.call(navigator.permissions),
                        connectionTag: Object.prototype.toString.call(navigator.connection),
                        connection: [
                            navigator.connection.effectiveType,
                            navigator.connection.rtt,
                            navigator.connection.downlink,
                            navigator.connection.saveData,
                        ],
                        orientationTag: Object.prototype.toString.call(screen.orientation),
                        orientation: [screen.orientation.type, screen.orientation.angle],
                        hasFocus: document.hasFocus(),
                        timingTag: Object.prototype.toString.call(performance.timing),
                        timingKeys: Object.keys(performance.timing.toJSON()).length,
                        navigationTag: Object.prototype.toString.call(performance.navigation),
                        navigation: performance.navigation.toJSON(),
                        memoryTag: Object.prototype.toString.call(performance.memory),
                        entryTag: Object.prototype.toString.call(
                            performance.getEntriesByType("navigation")[0],
                        ),
                        mediaTag: Object.prototype.toString.call(media),
                        mediaMatches: media.matches,
                        viewportTag: Object.prototype.toString.call(visualViewport),
                        viewport: [visualViewport.width, visualViewport.height, visualViewport.scale],
                        canvas: [
                            canvas.width,
                            canvas.height,
                            Object.prototype.toString.call(context),
                            canvas.getContext("webgl"),
                            canvas.toDataURL().startsWith("data:image/png;base64,"),
                        ],
                        nativeQuery: Function.prototype.toString.call(
                            navigator.permissions.query,
                        ).includes("[native code]"),
                    };
                })()
                """
            )
            self.assertEqual(result["chromeKeys"], ["loadTimes", "csi", "app"])
            self.assertEqual(result["chromeRuntime"], "undefined")
            self.assertEqual(result["userAgentData"], "undefined")
            self.assertEqual(result["navigatorOwnKeys"], [])
            self.assertEqual(result["screenOwnKeys"], [])
            self.assertEqual(result["pluginTag"], "[object PluginArray]")
            self.assertEqual(result["pluginLength"], 5)
            self.assertEqual(result["pluginName"], "PDF Viewer")
            self.assertEqual(result["pluginMime"], "application/pdf")
            self.assertTrue(result["pluginItemStable"])
            self.assertTrue(result["pluginNamedStable"])
            self.assertEqual(result["indexDescriptor"], [True, True, False])
            self.assertEqual(result["nameDescriptor"], [False, True, False])
            self.assertEqual(result["mimeTag"], "[object MimeTypeArray]")
            self.assertEqual(result["mimeLength"], 2)
            self.assertEqual(result["permissionsTag"], "[object Permissions]")
            self.assertEqual(result["connectionTag"], "[object NetworkInformation]")
            self.assertEqual(result["connection"], ["4g", 150, 1.75, False])
            self.assertEqual(result["orientationTag"], "[object ScreenOrientation]")
            self.assertEqual(result["orientation"], ["landscape-primary", 0])
            self.assertTrue(result["hasFocus"])
            self.assertEqual(result["timingTag"], "[object PerformanceTiming]")
            self.assertEqual(result["timingKeys"], 21)
            self.assertEqual(result["navigationTag"], "[object PerformanceNavigation]")
            self.assertEqual(result["navigation"], {"type": 0, "redirectCount": 0})
            self.assertEqual(result["memoryTag"], "[object MemoryInfo]")
            self.assertEqual(result["entryTag"], "[object PerformanceNavigationTiming]")
            self.assertEqual(result["mediaTag"], "[object MediaQueryList]")
            self.assertTrue(result["mediaMatches"])
            self.assertEqual(result["viewportTag"], "[object VisualViewport]")
            self.assertEqual(result["viewport"], [1280, 720, 1])
            self.assertEqual(
                result["canvas"],
                [300, 150, "[object CanvasRenderingContext2D]", None, True],
            )
            self.assertTrue(result["nativeQuery"])

            runtime.eval(
                "globalThis.permissionProbe=null;"
                "navigator.permissions.query({name:'geolocation'}).then(value=>{"
                "permissionProbe=[Object.prototype.toString.call(value),value.name,value.state]"
                "});'queued'"
            )
            runtime.drain()
            self.assertEqual(
                runtime.eval("permissionProbe"),
                ["[object PermissionStatus]", "geolocation", "prompt"],
            )

    def test_performance_timing_exposes_and_traces_all_chrome_fields(self) -> None:
        keys = [
            "navigationStart",
            "unloadEventStart",
            "unloadEventEnd",
            "redirectStart",
            "redirectEnd",
            "fetchStart",
            "domainLookupStart",
            "domainLookupEnd",
            "connectStart",
            "connectEnd",
            "secureConnectionStart",
            "requestStart",
            "responseStart",
            "responseEnd",
            "domLoading",
            "domInteractive",
            "domContentLoadedEventStart",
            "domContentLoadedEventEnd",
            "domComplete",
            "loadEventStart",
            "loadEventEnd",
        ]
        config = yatouv8.RuntimeConfig(
            get_trace=yatouv8.GetTraceConfig(enabled=True, max_events=1_000)
        )
        with yatouv8.Runtime(config) as runtime:
            values = runtime.eval(
                f"Object.fromEntries({keys!r}.map(key=>[key,performance.timing[key]]))"
            )
            timing_reads = [
                event["entry"]["member"]
                for event in runtime.trace["events"]
                if event["level"] == "l1"
                and event["entry"].get("target") == "PerformanceTiming.prototype"
                and event["entry"].get("operation") == "get"
            ]

        self.assertEqual(timing_reads, keys)
        start = values["navigationStart"]
        self.assertEqual(values["fetchStart"], start + 3)
        self.assertEqual(values["requestStart"], start + 3)
        self.assertEqual(values["responseStart"], start + 4)
        self.assertEqual(values["responseEnd"], start + 4)
        self.assertEqual(values["domLoading"], start + 14)
        self.assertEqual(values["domInteractive"], start + 17)
        self.assertEqual(values["domComplete"], start + 18)
        self.assertEqual(values["loadEventEnd"], start + 18)
        self.assertEqual(values["redirectStart"], 0)
        self.assertEqual(values["unloadEventStart"], 0)

    def test_get_trace_names_dynamic_knitsail_namespace(self) -> None:
        config = yatouv8.RuntimeConfig(
            get_trace=yatouv8.GetTraceConfig(enabled=True, max_events=100)
        )
        with yatouv8.Runtime(config) as runtime:
            self.assertEqual(
                runtime.eval(
                    "globalThis.knitsail={createSnapshot(){return 'snapshot'}};"
                    "knitsail.createSnapshot()"
                ),
                "snapshot",
            )
            reads = {
                (event["entry"].get("target"), event["entry"].get("member"))
                for event in runtime.trace["events"]
                if event["level"] == "l1"
                and event["entry"].get("operation") == "get"
            }

        self.assertIn(("knitsail", "createSnapshot"), reads)
        self.assertNotIn(("Object.prototype", "createSnapshot"), reads)

    def test_get_trace_is_opt_in_and_semantics_preserving(self) -> None:
        with yatouv8.Runtime() as runtime:
            oracle = runtime.eval(self.GET_TRACE_SOURCE)
            self.assertFalse(runtime.environment["getTrace"]["enabled"])
            self.assertEqual(
                [
                    event
                    for event in runtime.trace["events"]
                    if event["level"] == "l1"
                    and event["entry"]["operation"] == "get"
                ],
                [],
            )

        config = yatouv8.RuntimeConfig(
            get_trace=yatouv8.GetTraceConfig(enabled=True, max_events=100)
        )
        with yatouv8.Runtime(config) as runtime:
            observed = runtime.eval(self.GET_TRACE_SOURCE)
            self.assertEqual(observed, oracle)
            self.assertTrue(runtime.environment["getTrace"]["enabled"])
            gets = [
                (event["entry"]["target"], event["entry"]["member"])
                for event in runtime.trace["events"]
                if event["level"] == "l1"
                and event["entry"]["operation"] == "get"
            ]
            self.assertTrue(
                {
                    ("globalThis", "navigator"),
                    ("Navigator.prototype", "userAgent"),
                    ("globalThis", "screen"),
                    ("Screen.prototype", "width"),
                    ("globalThis", "document"),
                    ("Document.prototype", "cookie"),
                    ("Location.prototype", "href"),
                    ("Performance.prototype", "timeOrigin"),
                    ("HTMLCanvasElement.prototype", "getContext"),
                    ("Element.prototype", "clientWidth"),
                    ("globalThis", "DefinitelyMissingChromeSurface"),
                }.issubset(set(gets))
            )

    def test_get_trace_preserves_native_and_host_causal_order(self) -> None:
        config = yatouv8.RuntimeConfig(
            get_trace=yatouv8.GetTraceConfig(enabled=True, max_events=100)
        )
        with yatouv8.Runtime(config) as runtime:
            runtime.eval("navigator.userAgent; performance.now(); screen.width; 'ok'")
            observations = [
                (
                    event["entry"]["operation"],
                    event["entry"]["target"],
                    event["entry"]["member"],
                )
                for event in runtime.trace["events"]
                if event["level"] == "l1"
            ]
            self.assertEqual(
                observations,
                [
                    ("get", "globalThis", "navigator"),
                    ("get", "Navigator.prototype", "userAgent"),
                    ("get", "globalThis", "performance"),
                    ("get", "Performance.prototype", "now"),
                    ("call", "Performance.prototype", "now"),
                    ("get", "globalThis", "screen"),
                    ("get", "Screen.prototype", "width"),
                ],
            )

    def test_get_trace_wraps_native_trusted_types_surfaces(self) -> None:
        config = yatouv8.RuntimeConfig(
            get_trace=yatouv8.GetTraceConfig(enabled=True, max_events=100)
        )
        with yatouv8.Runtime(config) as runtime:
            self.assertEqual(
                runtime.eval(
                    "const policy=trustedTypes.createPolicy('trace-tt',{"
                    "createScript:value=>`S:${value}`});"
                    "policy.createScript('x');'ok'"
                ),
                "ok",
            )
            observations = [
                (
                    event["entry"]["operation"],
                    event["entry"]["target"],
                    event["entry"]["member"],
                )
                for event in runtime.trace["events"]
                if event["level"] == "l1"
            ]
            self.assertEqual(
                observations,
                [
                    ("get", "globalThis", "trustedTypes"),
                    ("get", "TrustedTypePolicyFactory.prototype", "createPolicy"),
                    ("call", "TrustedTypePolicyFactory.prototype", "createPolicy"),
                    ("get", "TrustedTypePolicy.prototype", "createScript"),
                    ("call", "TrustedTypePolicy.prototype", "createScript"),
                ],
            )

    def test_get_trace_covers_microtasks_and_drained_timers(self) -> None:
        config = yatouv8.RuntimeConfig(
            get_trace=yatouv8.GetTraceConfig(enabled=True, max_events=100)
        )
        with yatouv8.Runtime(config) as runtime:
            runtime.eval(
                "globalThis.callbackReads=[];"
                "Promise.resolve().then(()=>callbackReads.push(navigator.language));"
                "setTimeout(()=>callbackReads.push(screen.height),0);"
                "'queued'"
            )
            runtime.drain()
            self.assertEqual(runtime.eval("callbackReads.slice()"), ["zh-CN", 1080])
            gets = {
                (event["entry"]["target"], event["entry"]["member"])
                for event in runtime.trace["events"]
                if event["level"] == "l1"
                and event["entry"]["operation"] == "get"
            }
            self.assertTrue(
                {
                    ("Navigator.prototype", "language"),
                    ("Screen.prototype", "height"),
                }.issubset(gets)
            )

    def test_get_trace_budget_is_hard_bounded(self) -> None:
        config = yatouv8.RuntimeConfig(
            get_trace=yatouv8.GetTraceConfig(enabled=True, max_events=3)
        )
        with yatouv8.Runtime(config) as runtime:
            runtime.eval(
                "navigator.userAgent; screen.width; document.cookie; location.href"
            )
            stats = runtime.get_trace_stats
            gets = [
                event
                for event in runtime.trace["events"]
                if event["level"] == "l1"
                and event["entry"]["operation"] == "get"
            ]
            self.assertEqual(len(gets), 3)
            self.assertEqual(stats["events"], 3)
            self.assertGreater(stats["dropped"], 0)

    def test_concurrent_callers_are_serialized_on_owner_thread(self) -> None:
        with yatouv8.Runtime() as runtime:
            runtime.eval("globalThis.concurrentCounter=0")
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                list(pool.map(lambda _: runtime.eval("++concurrentCounter"), range(32)))
            self.assertEqual(runtime.eval("concurrentCounter"), 32)

    def test_generated_chrome_surface_is_installed_without_internal_leaks(self) -> None:
        with yatouv8.Runtime() as runtime:
            result = runtime.eval(
                """
                (() => {
                    const globals = Object.getOwnPropertyNames(globalThis);
                    return {
                        count: globals.length,
                        internals: globals.filter(key =>
                            key.startsWith("__yatou") || key === "_listeners"
                        ),
                        navigatorKeys: Reflect.ownKeys(Navigator.prototype).length,
                        brands: [navigator, screen, location, performance, document]
                            .map(value => Object.prototype.toString.call(value)),
                        nativeNode: Function.prototype.toString.call(Node)
                            .includes("[native code]"),
                        nativeAppend: Function.prototype.toString.call(
                            Node.prototype.appendChild,
                        ).includes("[native code]"),
                    };
                })()
                """
            )
            self.assertEqual(result["count"], 981)
            self.assertEqual(result["internals"], [])
            self.assertEqual(result["navigatorKeys"], 37)
            self.assertEqual(
                result["brands"],
                [
                    "[object Navigator]",
                    "[object Screen]",
                    "[object Location]",
                    "[object Performance]",
                    "[object Document]",
                ],
            )
            self.assertTrue(result["nativeNode"])
            self.assertTrue(result["nativeAppend"])

    def test_reflection_trace_records_structure_operations(self) -> None:
        config = yatouv8.RuntimeConfig(
            get_trace=yatouv8.GetTraceConfig(enabled=True, max_events=10_000)
        )
        with yatouv8.Runtime(config) as runtime:
            runtime.eval(
                "Object.getOwnPropertyNames(globalThis);"
                "Reflect.ownKeys(Navigator.prototype);"
                "Object.getOwnPropertyDescriptors(Navigator.prototype);"
                "Object.getPrototypeOf(navigator);"
                "Reflect.has(navigator, 'webdriver');"
                "'ok'"
            )
            operations = {
                event["entry"]["operation"]
                for event in runtime.trace["events"]
                if event["level"] == "l1"
            }
            self.assertTrue(
                {
                    "own_keys",
                    "get_own_property_descriptor",
                    "get_prototype_of",
                    "has",
                }.issubset(operations)
            )
            self.assertEqual(runtime.get_trace_stats["dropped"], 0)

    def test_trace_names_intrinsic_namespaces_instead_of_object_prototype(self) -> None:
        config = yatouv8.RuntimeConfig(
            get_trace=yatouv8.GetTraceConfig(enabled=True, max_events=100)
        )
        with yatouv8.Runtime(config) as runtime:
            runtime.eval(
                "Math.random();"
                "JSON.stringify({answer:42});"
                "Reflect.ownKeys({x:1})"
            )
            reads = {
                (event["entry"].get("target"), event["entry"].get("member"))
                for event in runtime.trace["events"]
                if event["level"] == "l1"
                and event["entry"].get("operation") == "get"
            }

        self.assertIn(("Math", "random"), reads)
        self.assertIn(("JSON", "stringify"), reads)
        self.assertNotIn(("Object.prototype", "random"), reads)

    def test_recorded_clock_cookie_navigation_and_challenge_handoff(self) -> None:
        config = yatouv8.RuntimeConfig(
            url="https://www.google.com/search?q=yatouv8",
            get_trace=yatouv8.GetTraceConfig(enabled=True, max_events=20_000),
        )
        with yatouv8.Runtime(config) as runtime:
            runtime.import_cookies({"seed": "one"})
            result = runtime.eval_challenge(
                "const samples=Array.from({length:800},()=>performance.now());"
                "document.cookie='SG_SS=fixture-token; Path=/; Secure; SameSite=None';"
                "location.replace('/search?q=yatouv8&sei=fixture-sei');"
                "({unique:new Set(samples).size,repeated:samples.some((v,i)=>i&&v===samples[i-1])})"
            )
            self.assertTrue(result.value["repeated"])
            self.assertLess(result.value["unique"], 100)
            self.assertTrue(any(cookie["name"] == "SG_SS" for cookie in result.cookies))
            self.assertEqual(result.pending_navigation["kind"], "replace")
            self.assertEqual(
                result.pending_navigation["url"],
                "https://www.google.com/search?q=yatouv8&sei=fixture-sei",
            )
            self.assertEqual(runtime.take_navigation(), result.pending_navigation)
            self.assertIsNone(runtime.pending_navigation)


if __name__ == "__main__":
    unittest.main()
