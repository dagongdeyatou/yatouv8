from __future__ import annotations

import concurrent.futures
from collections.abc import Iterator, Mapping
import datetime
from enum import Enum
import json
import time
import unittest

import yatouv8


class RuntimeTests(unittest.TestCase):
    def test_cookiejar_precedes_mapping_for_duplicate_cookie_names(self) -> None:
        class Cookie:
            def __init__(self, domain: str) -> None:
                self.name = "__Secure-STRP"
                self.value = domain
                self.domain = domain
                self.path = "/"
                self.secure = True
                self.expires = None
                self.rest = {}

        class CurlCookies(Mapping[str, str]):
            jar = [Cookie(".google.com"), Cookie(".google.com.hk")]

            def __getitem__(self, _key: str) -> str:
                raise AssertionError("name-only lookup would lose cookie domain")

            def __iter__(self) -> Iterator[str]:
                return iter(["__Secure-STRP"])

            def __len__(self) -> int:
                return 1

        with yatouv8.Runtime(
            yatouv8.RuntimeConfig(url="https://www.google.com/search?q=yatouv8")
        ) as runtime:
            imported = runtime.import_cookies(CurlCookies())
            exported = runtime.export_cookies()

        self.assertEqual(imported, 1)
        self.assertEqual(len(exported), 1)
        self.assertEqual(exported[0]["domain"], "google.com")

    def test_curl_response_builds_causal_navigation_and_system_clock(self) -> None:
        class Info(Enum):
            NAMELOOKUP_TIME = 1
            CONNECT_TIME = 2
            APPCONNECT_TIME = 3
            PRETRANSFER_TIME = 4
            STARTTRANSFER_TIME = 5
            TOTAL_TIME = 6
            HTTP_VERSION = 7
            SIZE_DOWNLOAD_T = 8
            HEADER_SIZE = 9

        class Response:
            url = "https://www.google.com/search?q=yatouv8"
            status_code = 200
            content = b"decoded-body"
            elapsed = datetime.timedelta(milliseconds=421)
            infos = {
                Info.NAMELOOKUP_TIME: 0.002,
                Info.CONNECT_TIME: 0.018,
                Info.APPCONNECT_TIME: 0.120,
                Info.PRETRANSFER_TIME: 0.121,
                Info.STARTTRANSFER_TIME: 0.390,
                Info.TOTAL_TIME: 0.421,
                Info.HTTP_VERSION: 3,
                Info.SIZE_DOWNLOAD_T: 8,
                Info.HEADER_SIZE: 120,
            }

        config = yatouv8.RuntimeConfig.from_curl_response(
            Response(),
            navigation_start_ms=1_786_210_000_000.25,
        )

        self.assertEqual(config.profile.clock["mode"], "system_monotonic")
        self.assertEqual(config.profile.clock["start_ms"], 421.0)
        self.assertEqual(config.profile.navigation_timing["response_start"], 390)
        self.assertEqual(config.profile.navigation_timing["response_end"], 421)
        self.assertIsNone(config.profile.navigation_timing["load_event_end"])
        with yatouv8.Runtime(config) as runtime:
            first = runtime.eval("performance.now()")
            time.sleep(0.02)
            second = runtime.eval("performance.now()")
            timing = runtime.eval(
                "({start:performance.timing.navigationStart,"
                "response:performance.timing.responseStart,"
                "complete:performance.timing.domComplete})"
            )
            navigation = runtime.eval(
                "performance.getEntriesByType('navigation')[0].toJSON()"
            )

        self.assertGreaterEqual(first, 421.0)
        self.assertGreaterEqual(second - first, 10.0)
        self.assertEqual(timing["response"] - timing["start"], 390)
        self.assertEqual(timing["complete"], 0)
        self.assertEqual(navigation["responseStart"], 390)
        self.assertEqual(navigation["responseEnd"], 421)
        self.assertEqual(navigation["nextHopProtocol"], "h2")
        self.assertEqual(navigation["responseStatus"], 200)
        self.assertEqual(navigation["transferSize"], 128)
        self.assertEqual(navigation["decodedBodySize"], 12)

    def test_curl_response_accepts_legacy_float_elapsed(self) -> None:
        class Response:
            elapsed = 0.421
            infos = {}

        timing = yatouv8.HttpNavigationTiming.from_curl_response(
            Response(),
            navigation_start_ms=1_786_210_000_000.25,
        )

        self.assertEqual(timing.response_start_ms, 421.0)
        self.assertEqual(timing.response_end_ms, 421.0)

    def test_execution_trace_captures_nested_eval_source_and_missed_branch(self) -> None:
        config = yatouv8.RuntimeConfig(
            execution_trace=yatouv8.ExecutionTraceConfig(
                enabled=True,
                max_scripts=16,
                max_source_bytes=100_000,
            )
        )
        with yatouv8.Runtime(config) as runtime:
            self.assertEqual(
                runtime.eval(
                    "eval(`globalThis.knitsailReady=true;"
                    "if(globalThis.addEventListener){globalThis.knitsail={ready:true}}"
                    "else{globalThis.knitsail={ready:false}}`);"
                    "globalThis.knitsail.ready"
                ),
                True,
            )
            capture = runtime.execution_trace

        self.assertEqual(capture["status"], "captured")
        nested = next(
            script
            for script in capture["scripts"]
            if script["role"] == "nested_dynamic_script"
        )
        self.assertIn("globalThis.knitsail", nested["source"])
        self.assertGreaterEqual(len(nested["missed_range_snippets"]), 1)
        report = yatouv8.analyze_execution_trace(capture, ("knitsail",))
        self.assertGreaterEqual(report["summary"]["symbol_occurrences"], 1)
        self.assertTrue(report["ranked_blockers"])

    def test_execution_trace_is_disabled_by_default(self) -> None:
        with yatouv8.Runtime() as runtime:
            runtime.eval("1")
            capture = runtime.execution_trace
        self.assertFalse(capture["enabled"])
        self.assertEqual(capture["status"], "disabled")

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

    def test_window_inherits_chrome_event_target_surface(self) -> None:
        config = yatouv8.RuntimeConfig(
            get_trace=yatouv8.GetTraceConfig(enabled=True, max_events=200)
        )
        with yatouv8.Runtime(config) as runtime:
            result = runtime.eval(
                """
                (() => {
                    let calls = 0;
                    const listener = event => {
                        calls += event.type === "yatou-window-event" ? 1 : 100;
                    };
                    addEventListener("yatou-window-event", listener);
                    const dispatched = dispatchEvent(new Event("yatou-window-event"));
                    removeEventListener("yatou-window-event", listener);
                    dispatchEvent(new Event("yatou-window-event"));
                    const extractedAdd = globalThis.addEventListener;
                    const extractedDispatch = globalThis.dispatchEvent;
                    const extractedRemove = globalThis.removeEventListener;
                    extractedAdd("yatou-window-extracted", listener);
                    extractedDispatch(new Event("yatou-window-extracted"));
                    extractedRemove("yatou-window-extracted", listener);
                    let plainReceiverError = null;
                    try {
                        EventTarget.prototype.addEventListener.call(
                            {},
                            "yatou-illegal",
                            listener,
                        );
                    } catch (error) {
                        plainReceiverError = `${error.name}: ${error.message}`;
                    }
                    const windowProperties = Object.getPrototypeOf(Window.prototype);
                    return {
                        addType: typeof globalThis.addEventListener,
                        removeType: typeof globalThis.removeEventListener,
                        dispatchType: typeof globalThis.dispatchEvent,
                        globalAliasType: typeof globalThis.global,
                        ownAdd: Object.getOwnPropertyDescriptor(
                            globalThis,
                            "addEventListener",
                        ) === undefined,
                        sameFunction: globalThis.addEventListener
                            === EventTarget.prototype.addEventListener,
                        eventTargetPrototype: EventTarget.prototype.isPrototypeOf(window),
                        windowPropertiesTag: Object.prototype.toString.call(
                            windowProperties,
                        ),
                        windowPropertiesKeys: Reflect.ownKeys(windowProperties).map(String),
                        windowPropertiesParent: Object.getPrototypeOf(windowProperties)
                            === EventTarget.prototype,
                        calls,
                        dispatched,
                        plainReceiverError,
                    };
                })()
                """
            )
            l1 = [
                event["entry"]
                for event in runtime.trace["events"]
                if event["level"] == "l1"
            ]

        self.assertEqual(
            result,
            {
                "addType": "function",
                "removeType": "function",
                "dispatchType": "function",
                "globalAliasType": "undefined",
                "ownAdd": True,
                "sameFunction": True,
                "eventTargetPrototype": True,
                "windowPropertiesTag": "[object WindowProperties]",
                "windowPropertiesKeys": ["Symbol(Symbol.toStringTag)"],
                "windowPropertiesParent": True,
                "calls": 101,
                "dispatched": True,
                "plainReceiverError": "TypeError: Illegal invocation",
            },
        )
        self.assertTrue(
            any(
                entry.get("operation") == "get"
                and entry.get("target") == "globalThis"
                and entry.get("member") == "addEventListener"
                and entry["outcome"]["value"]["kind"] == "function"
                for entry in l1
            )
        )
        self.assertTrue(
            any(
                entry.get("operation") == "call"
                and entry.get("target") == "EventTarget.prototype"
                and entry.get("member") == "addEventListener"
                for entry in l1
            )
        )

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

    def test_trusted_script_is_accepted_by_eval(self) -> None:
        with yatouv8.Runtime() as runtime:
            result = runtime.eval(
                """
                (() => {
                    const policy = trustedTypes.createPolicy(
                        "python-eval-regression",
                        {createScript: value => value},
                    );
                    const script = policy.createScript("40 + 2");
                    const evaluated = globalThis.eval(script);
                    return {
                        evaluated,
                        evalNative: Function.prototype.toString
                            .call(eval)
                            .includes("[native code]"),
                        evalOwnKeys: Reflect.ownKeys(eval).map(String),
                    };
                })()
                """
            )
        self.assertEqual(
            result,
            {
                "evaluated": 42,
                "evalNative": True,
                "evalOwnKeys": ["length", "name"],
            },
        )

    def test_event_listener_observes_passive_option(self) -> None:
        with yatouv8.Runtime() as runtime:
            result = runtime.eval(
                """
                (() => {
                    const reads = [];
                    const options = {
                        get capture() { reads.push("capture"); return false; },
                        get once() { reads.push("once"); return false; },
                        get passive() { reads.push("passive"); return false; },
                        get signal() { reads.push("signal"); return undefined; },
                    };
                    addEventListener("yatou-options", () => {}, options);
                    return reads;
                })()
                """
            )
        self.assertEqual(result, ["capture", "once", "passive", "signal"])

    def test_event_instance_matches_chrome_ownership_and_legacy_state(self) -> None:
        with yatouv8.Runtime() as runtime:
            result = runtime.eval(
                """
                (() => {
                    const event = new Event("", {cancelable: true});
                    const legacy = document.createEvent("Event");
                    const trusted = Object.getOwnPropertyDescriptor(
                        event,
                        "isTrusted",
                    );
                    const before = [
                        event.isTrusted,
                        event.returnValue,
                        event.cancelBubble,
                        event.defaultPrevented,
                    ];
                    event.returnValue = false;
                    event.cancelBubble = true;
                    return {
                        ownKeys: Reflect.ownKeys(event).map(String),
                        legacy: {
                            tag: Object.prototype.toString.call(legacy),
                            type: legacy.type,
                            preventDefault: Function.prototype.toString.call(
                                legacy.preventDefault,
                            ),
                        },
                        trusted: {
                            own: Object.prototype.hasOwnProperty.call(
                                event,
                                "isTrusted",
                            ),
                            getter: typeof trusted.get,
                            enumerable: trusted.enumerable,
                            configurable: trusted.configurable,
                            source: Function.prototype.toString.call(trusted.get),
                        },
                        before,
                        after: [
                            event.returnValue,
                            event.cancelBubble,
                            event.defaultPrevented,
                        ],
                        constants: [
                            Event.NONE,
                            Event.CAPTURING_PHASE,
                            Event.AT_TARGET,
                            Event.BUBBLING_PHASE,
                            event.NONE,
                            event.CAPTURING_PHASE,
                            event.AT_TARGET,
                            event.BUBBLING_PHASE,
                        ],
                    };
                })()
                """
            )
        self.assertEqual(result["ownKeys"], ["isTrusted"])
        self.assertEqual(
            result["legacy"],
            {
                "tag": "[object Event]",
                "type": "",
                "preventDefault": "function preventDefault() { [native code] }",
            },
        )
        self.assertEqual(
            result["trusted"],
            {
                "own": True,
                "getter": "function",
                "enumerable": True,
                "configurable": False,
                "source": "function get isTrusted() { [native code] }",
            },
        )
        self.assertEqual(result["before"], [False, True, False, False])
        self.assertEqual(result["after"], [False, True, True])
        self.assertEqual(result["constants"], [0, 1, 2, 3, 0, 1, 2, 3])

    def test_generated_elements_window_strings_and_dimensions_match_chrome150(self) -> None:
        with yatouv8.Runtime() as runtime:
            result = runtime.eval(
                """
                (() => {
                    const image = document.createElement("img");
                    const div = document.createElement("div");
                    return {
                        name: window.name,
                        status: window.status,
                        defaultStatusType: typeof window.defaultStatus,
                        dimensions: [
                            innerWidth,
                            innerHeight,
                            outerWidth,
                            outerHeight,
                            screen.width,
                            screen.height,
                        ],
                        image: [
                            Object.prototype.toString.call(image),
                            image.constructor.name,
                            image.src,
                            image.alt,
                            image.title,
                        ],
                        div: [
                            Object.prototype.toString.call(div),
                            div.constructor.name,
                            div.align,
                        ],
                    };
                })()
                """
            )
        self.assertEqual(result["name"], "")
        self.assertEqual(result["status"], "")
        self.assertEqual(result["defaultStatusType"], "undefined")
        self.assertEqual(result["dimensions"], [1280, 633, 1280, 720, 1920, 1080])
        self.assertEqual(
            result["image"],
            ["[object HTMLImageElement]", "HTMLImageElement", "", "", ""],
        )
        self.assertEqual(result["div"], ["[object HTMLDivElement]", "HTMLDivElement", ""])

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
                        callablePrototypes: [
                            Object.prototype.hasOwnProperty.call(NodeFilter, "prototype"),
                            Object.prototype.hasOwnProperty.call(atob, "prototype"),
                            Object.prototype.hasOwnProperty.call(
                                Object.getOwnPropertyDescriptor(window, "history").get,
                                "prototype",
                            ),
                            Object.prototype.hasOwnProperty.call(
                                Object.getOwnPropertyDescriptor(window, "trustedTypes").get,
                                "prototype",
                            ),
                            Object.prototype.hasOwnProperty.call(Navigator, "prototype"),
                        ],
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
                        deprecatedStorage: [
                            navigator.webkitTemporaryStorage === navigator.webkitPersistentStorage,
                            Object.prototype.toString.call(navigator.webkitTemporaryStorage),
                            navigator.webkitTemporaryStorage.constructor.name,
                            Reflect.ownKeys(Object.getPrototypeOf(navigator.webkitTemporaryStorage)).map(String),
                            Function.prototype.toString.call(
                                navigator.webkitTemporaryStorage.queryUsageAndQuota,
                            ),
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
            self.assertEqual(result["userAgentData"], "object")
            self.assertEqual(result["callablePrototypes"], [False, False, False, False, True])
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
            self.assertEqual(
                result["deprecatedStorage"],
                [
                    True,
                    "[object DeprecatedStorageQuota]",
                    "Object",
                    ["queryUsageAndQuota", "requestQuota", "Symbol(Symbol.toStringTag)"],
                    "function queryUsageAndQuota() { [native code] }",
                ],
            )
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
            self.assertEqual(result["viewport"], [1280, 633, 1])
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
        with yatouv8.Runtime(
            yatouv8.RuntimeConfig(url="https://www.google.com.hk/search?q=yatouv8")
        ) as runtime:
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
            self.assertEqual(result["count"], 1233)
            self.assertEqual(result["internals"], [])
            self.assertEqual(result["navigatorKeys"], 85)
            self.assertEqual(
                result["brands"],
                [
                    "[object Navigator]",
                    "[object Screen]",
                    "[object Location]",
                    "[object Performance]",
                    "[object HTMLDocument]",
                ],
            )
            self.assertTrue(result["nativeNode"])
            self.assertTrue(result["nativeAppend"])

    def test_chrome150_node_constants_have_exact_values_and_descriptors(self) -> None:
        expected = {
            "ELEMENT_NODE": 1,
            "ATTRIBUTE_NODE": 2,
            "TEXT_NODE": 3,
            "CDATA_SECTION_NODE": 4,
            "ENTITY_REFERENCE_NODE": 5,
            "ENTITY_NODE": 6,
            "PROCESSING_INSTRUCTION_NODE": 7,
            "COMMENT_NODE": 8,
            "DOCUMENT_NODE": 9,
            "DOCUMENT_TYPE_NODE": 10,
            "DOCUMENT_FRAGMENT_NODE": 11,
            "NOTATION_NODE": 12,
            "DOCUMENT_POSITION_DISCONNECTED": 1,
            "DOCUMENT_POSITION_PRECEDING": 2,
            "DOCUMENT_POSITION_FOLLOWING": 4,
            "DOCUMENT_POSITION_CONTAINS": 8,
            "DOCUMENT_POSITION_CONTAINED_BY": 16,
            "DOCUMENT_POSITION_IMPLEMENTATION_SPECIFIC": 32,
        }
        with yatouv8.Runtime() as runtime:
            observed = runtime.eval(
                """
                (() => {
                    const names = Object.keys(%s);
                    const inspect = owner => Object.fromEntries(names.map(name => {
                        const descriptor = Object.getOwnPropertyDescriptor(owner, name);
                        return [name, {
                            value: owner[name],
                            writable: descriptor.writable,
                            enumerable: descriptor.enumerable,
                            configurable: descriptor.configurable,
                        }];
                    }));
                    return {
                        static: inspect(Node),
                        prototype: inspect(Node.prototype),
                        inherited: Object.fromEntries(names.map(name => [name, document[name]])),
                    };
                })()
                """
                % json.dumps(expected)
            )

        exact_descriptor = {
            name: {
                "value": value,
                "writable": False,
                "enumerable": True,
                "configurable": False,
            }
            for name, value in expected.items()
        }
        self.assertEqual(observed["static"], exact_descriptor)
        self.assertEqual(observed["prototype"], exact_descriptor)
        self.assertEqual(observed["inherited"], expected)

    def test_recorded_clock_preserves_chrome_f64_exactly(self) -> None:
        # This Chrome timer value sits on a decimal-to-binary rounding boundary.
        # Losing one ULP here is sufficient to change BotGuard's sampled index.
        chrome_value = 91.59999990463257
        profile = yatouv8.BrowserProfile(
            clock={
                "mode": "recorded",
                "buckets": [{"value_ms": chrome_value, "repeat": 2}],
                "fallback_quantum_ms": 0.1,
                "fallback_repeats": 1,
            }
        )
        with yatouv8.Runtime(yatouv8.RuntimeConfig(profile=profile)) as runtime:
            first = runtime.eval("performance.now()")
            second = runtime.eval("performance.now()")

        self.assertEqual(first, chrome_value)
        self.assertEqual(second, chrome_value)
        self.assertEqual(first.hex(), chrome_value.hex())

    def test_navigator_webdriver_getter_enforces_webidl_brand(self) -> None:
        with yatouv8.Runtime(yatouv8.RuntimeConfig()) as runtime:
            observed = runtime.eval(
                """
                (() => {
                    const getter = Object.getOwnPropertyDescriptor(
                        Navigator.prototype,
                        "webdriver",
                    ).get;
                    const invoke = receiver => {
                        try {
                            return {ok: true, value: getter.call(receiver)};
                        } catch (error) {
                            return {ok: false, name: error.name, message: error.message};
                        }
                    };
                    return {
                        navigator: invoke(navigator),
                        window: invoke(window),
                        inheritedOnly: invoke(Object.create(Navigator.prototype)),
                    };
                })()
                """
            )

        self.assertEqual(observed["navigator"], {"ok": True, "value": False})
        self.assertEqual(
            observed["window"],
            {"ok": False, "name": "TypeError", "message": "Illegal invocation"},
        )
        self.assertEqual(
            observed["inheritedOnly"],
            {"ok": False, "name": "TypeError", "message": "Illegal invocation"},
        )

    def test_get_trace_preserves_nested_native_function_to_string(self) -> None:
        config = yatouv8.RuntimeConfig(
            get_trace=yatouv8.GetTraceConfig(enabled=True, max_events=1_000)
        )
        with yatouv8.Runtime(config) as runtime:
            observed = runtime.eval(
                """
                (() => {
                    const element = document.createElement('div');
                    return Object.fromEntries([
                        ['pseudo', element.pseudo],
                        ['when', element.when],
                        ['removeChild', element.removeChild],
                    ].map(([key, value]) => [key, {
                        name: value.name,
                        source: Function.prototype.toString.call(value),
                    }]));
                })()
                """
            )

        self.assertEqual(
            observed,
            {
                name: {"name": name, "source": f"function {name}() {{ [native code] }}"}
                for name in ("pseudo", "when", "removeChild")
            },
        )

    def test_iframe_creates_chrome_window_index_and_length(self) -> None:
        config = yatouv8.RuntimeConfig(
            get_trace=yatouv8.GetTraceConfig(enabled=True, max_events=5_000)
        )
        with yatouv8.Runtime(config) as runtime:
            observed = runtime.eval(
                """
                (() => {
                    const iframe = document.createElement('iframe');
                    document.body.appendChild(iframe);
                    const descriptor = Object.getOwnPropertyDescriptor(window, '0');
                    const beforeRemoval = {
                        length: window.length,
                        firstKey: Object.getOwnPropertyNames(window)[0],
                        tag: Object.prototype.toString.call(window[0]),
                        sameWindow: iframe.contentWindow === window[0],
                        domain: document.domain,
                        childDomain: iframe.contentWindow.document.domain,
                        independentDocument:
                            iframe.contentDocument !== document &&
                            iframe.contentWindow.document === iframe.contentDocument,
                        independentLocation:
                            iframe.contentWindow.location !== location &&
                            iframe.contentDocument.location === iframe.contentWindow.location,
                        childHref: iframe.contentWindow.location.href,
                        childURL: iframe.contentDocument.URL,
                        childBaseURI: iframe.contentDocument.baseURI,
                        childReferrer: iframe.contentDocument.referrer,
                        frameElement: iframe.contentWindow.frameElement === iframe,
                        descriptor: {
                            writable: descriptor.writable,
                            enumerable: descriptor.enumerable,
                            configurable: descriptor.configurable,
                        },
                    };
                    iframe.remove();
                    return {
                        beforeRemoval,
                        afterRemoval: {
                            length: window.length,
                            zero: typeof window[0],
                            hasZero: Object.getOwnPropertyNames(window).includes('0'),
                        },
                    };
                })()
                """
            )

        self.assertEqual(
            observed,
            {
                "beforeRemoval": {
                    "length": 1,
                    "firstKey": "0",
                    "tag": "[object Window]",
                    "sameWindow": True,
                    "domain": "fixture.invalid",
                    "childDomain": "fixture.invalid",
                    "independentDocument": True,
                    "independentLocation": True,
                    "childHref": "about:blank",
                    "childURL": "about:blank",
                    "childBaseURI": "https://fixture.invalid/",
                    "childReferrer": "https://fixture.invalid/",
                    "frameElement": True,
                    "descriptor": {
                        "writable": False,
                        "enumerable": True,
                        "configurable": True,
                    },
                },
                "afterRemoval": {
                    "length": 0,
                    "zero": "undefined",
                    "hasZero": False,
                },
            },
        )

    def test_text_html_document_uses_html_document_brand(self) -> None:
        with yatouv8.Runtime() as runtime:
            observed = runtime.eval(
                """
                (() => ({
                    tag: Object.prototype.toString.call(document),
                    constructor: document.constructor.name,
                    htmlPrototype: Object.getPrototypeOf(document) === HTMLDocument.prototype,
                    documentPrototype:
                        Object.getPrototypeOf(HTMLDocument.prototype) === Document.prototype,
                }))()
                """
            )

        self.assertEqual(
            observed,
            {
                "tag": "[object HTMLDocument]",
                "constructor": "HTMLDocument",
                "htmlPrototype": True,
                "documentPrototype": True,
            },
        )

    def test_document_exposes_chrome_unforgeable_location_and_serialized_base_uri(
        self,
    ) -> None:
        config = yatouv8.RuntimeConfig(
            url="https://www.google.com.hk/search?q=%E4%BA%9A%E9%9D%9E"
        )
        with yatouv8.Runtime(config) as runtime:
            observed = runtime.eval(
                """
                (() => {
                    const descriptor = Object.getOwnPropertyDescriptor(
                        document, 'location'
                    );
                    return {
                        sameLocation: document.location === globalThis.location,
                        ownNames: Object.getOwnPropertyNames(document),
                        href: document.location.href,
                        baseURI: document.baseURI,
                        descriptor: {
                            enumerable: descriptor.enumerable,
                            configurable: descriptor.configurable,
                            get: [descriptor.get.name, descriptor.get.length,
                                Function.prototype.toString.call(descriptor.get)],
                            set: [descriptor.set.name, descriptor.set.length,
                                Function.prototype.toString.call(descriptor.set)],
                        },
                    };
                })()
                """
            )

        self.assertEqual(
            observed,
            {
                "sameLocation": True,
                "ownNames": ["location"],
                "href": "https://www.google.com.hk/search?q=%E4%BA%9A%E9%9D%9E",
                "baseURI": "https://www.google.com.hk/search?q=%E4%BA%9A%E9%9D%9E",
                "descriptor": {
                    "enumerable": True,
                    "configurable": False,
                    "get": [
                        "get location", 0,
                        "function get location() { [native code] }",
                    ],
                    "set": [
                        "set location", 1,
                        "function set location() { [native code] }",
                    ],
                },
            },
        )

    def test_location_matches_chrome_unforgeable_shape_and_url_serialization(self) -> None:
        config = yatouv8.RuntimeConfig(
            url="https://www.google.com.hk/search?q=亚非"
        )
        with yatouv8.Runtime(config) as runtime:
            observed = runtime.eval(
                """
                (() => {
                    const descriptor = key => {
                        const value = Object.getOwnPropertyDescriptor(location, key);
                        return {
                            writable: value.writable,
                            enumerable: value.enumerable,
                            configurable: value.configurable,
                            get: value.get && [value.get.name, value.get.length,
                                Function.prototype.toString.call(value.get)],
                            set: value.set && [value.set.name, value.set.length,
                                Function.prototype.toString.call(value.set)],
                            fn: typeof value.value === 'function' && [
                                value.value.name, value.value.length,
                                Function.prototype.toString.call(value.value),
                            ],
                        };
                    };
                    return {
                        href: location.href,
                        string: String(location),
                        names: Object.getOwnPropertyNames(location),
                        hrefDescriptor: descriptor('href'),
                        assignDescriptor: descriptor('assign'),
                        ancestor: {
                            tag: Object.prototype.toString.call(location.ancestorOrigins),
                            length: location.ancestorOrigins.length,
                            item: location.ancestorOrigins.item(0),
                        },
                        illegalInvocation: (() => {
                            try {
                                location.toString.call({});
                                return null;
                            } catch (error) {
                                return [error.name, error.message];
                            }
                        })(),
                    };
                })()
                """
            )

        self.assertEqual(observed["href"],
                         "https://www.google.com.hk/search?q=%E4%BA%9A%E9%9D%9E")
        self.assertEqual(observed["string"], observed["href"])
        self.assertEqual(
            observed["names"],
            [
                "valueOf", "ancestorOrigins", "href", "origin", "protocol",
                "host", "hostname", "port", "pathname", "search", "hash",
                "assign", "reload", "replace", "toString",
            ],
        )
        self.assertEqual(
            observed["hrefDescriptor"],
            {
                "enumerable": True,
                "configurable": False,
                "get": ["get href", 0, "function get href() { [native code] }"],
                "set": ["set href", 1, "function set href() { [native code] }"],
                "fn": False,
            },
        )
        self.assertEqual(
            observed["assignDescriptor"],
            {
                "writable": False,
                "enumerable": True,
                "configurable": False,
                "fn": ["assign", 1, "function assign() { [native code] }"],
            },
        )
        self.assertEqual(
            observed["ancestor"],
            {"tag": "[object DOMStringList]", "length": 0, "item": None},
        )
        self.assertEqual(
            observed["illegalInvocation"], ["TypeError", "Illegal invocation"]
        )

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

    def test_reflection_tracing_preserves_intrinsic_instance_key_order(self) -> None:
        for enabled in (False, True):
            config = yatouv8.RuntimeConfig(
                get_trace=yatouv8.GetTraceConfig(
                    enabled=enabled, max_events=1_000
                )
            )
            with yatouv8.Runtime(config) as runtime:
                observed = runtime.eval(
                    """
                    ({
                        array: Reflect.ownKeys([1, 2]).map(String),
                        regexp: Object.getOwnPropertyNames(/probe/),
                    })
                    """
                )

            self.assertEqual(
                observed,
                {
                    "array": ["0", "1", "length"],
                    "regexp": ["lastIndex"],
                },
            )

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
