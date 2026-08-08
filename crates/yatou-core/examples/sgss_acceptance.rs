//! Local final gate for the SG_SS-oriented Chrome-structure compatibility slice.
#![allow(linker_messages, clippy::too_many_lines)]

use serde_json::{Value, json};
use yatou_core::{BrowserRuntime, GetTraceConfig, RuntimeConfig};
use yatou_schema::{ApiOperation, TraceEventBody};

fn main() {
    let config = RuntimeConfig {
        url: "https://www.google.com/search?q=yatouv8".to_owned(),
        trace_id: "sgss-local-acceptance".to_owned(),
        get_trace: GetTraceConfig {
            enabled: true,
            max_events: 50_000,
        },
        ..RuntimeConfig::default()
    };
    let runtime = BrowserRuntime::new(config).expect("runtime");
    let result = runtime
        .eval(
            r#"(() => {
                const globals = Object.getOwnPropertyNames(globalThis);
                const navigatorKeys = Reflect.ownKeys(Navigator.prototype);
                const navigatorDescriptors = Object.getOwnPropertyDescriptors(Navigator.prototype);
                const navigatorPrototype = Object.getPrototypeOf(navigator);
                const hasWebdriver = Reflect.has(navigator, "webdriver");
                const policy = trustedTypes.createPolicy("sgss-acceptance", {
                    createScript: value => value
                });
                policy.createScript("bootstrap");
                atob("U0dfU1M=");
                const samples = Array.from({ length: 800 }, () => performance.now());
                document.cookie = "SG_SS=fixture-token; Path=/; Secure; SameSite=None";
                location.replace("/search?q=yatouv8&sei=fixture-sei");
                return {
                    globalCount: globals.length,
                    internals: globals.filter(key => key.startsWith("__yatou") || key === "_listeners"),
                    brands: [navigator, screen, location, performance, document]
                        .map(value => Object.prototype.toString.call(value)),
                    navigatorKeyCount: navigatorKeys.length,
                    navigatorDescriptorCount: Reflect.ownKeys(navigatorDescriptors).length,
                    navigatorPrototype: navigatorPrototype === Navigator.prototype,
                    hasWebdriver,
                    clockUnique: new Set(samples).size,
                    clockRepeated: samples.some((value, index) => index > 0 && value === samples[index - 1]),
                    cookie: document.cookie
                };
            })()"#,
        )
        .expect("eval transport");
    assert!(result.ok, "JavaScript exception: {result:?}");
    let value: Value =
        serde_json::from_str(result.json.as_deref().expect("JSON result")).expect("decode result");
    assert_eq!(value["globalCount"], 981);
    assert_eq!(value["internals"], json!([]));
    assert_eq!(
        value["brands"],
        json!([
            "[object Navigator]",
            "[object Screen]",
            "[object Location]",
            "[object Performance]",
            "[object Document]"
        ])
    );
    assert_eq!(value["navigatorKeyCount"], 37);
    assert_eq!(value["navigatorDescriptorCount"], 37);
    assert_eq!(value["navigatorPrototype"], true);
    assert_eq!(value["hasWebdriver"], true);
    assert_eq!(value["clockRepeated"], true);
    assert!(
        value["clockUnique"]
            .as_u64()
            .is_some_and(|count| count < 100)
    );
    assert!(
        value["cookie"]
            .as_str()
            .is_some_and(|value| value.contains("SG_SS=fixture-token"))
    );

    let cookies = runtime.export_cookies().expect("cookies");
    assert!(cookies.as_array().is_some_and(|cookies| {
        cookies
            .iter()
            .any(|cookie| cookie["name"] == "SG_SS" && cookie["value"] == "fixture-token")
    }));
    let navigation = runtime.navigation(true).expect("navigation");
    assert_eq!(navigation["kind"], "replace");
    assert_eq!(
        navigation["url"],
        "https://www.google.com/search?q=yatouv8&sei=fixture-sei"
    );

    let trace = runtime.trace().expect("trace");
    let operations = trace
        .events
        .iter()
        .filter_map(|event| match &event.body {
            TraceEventBody::L1(entry) => Some(entry.operation),
            TraceEventBody::L0(_) => None,
        })
        .collect::<Vec<_>>();
    for required in [
        ApiOperation::Get,
        ApiOperation::OwnKeys,
        ApiOperation::GetOwnPropertyDescriptor,
        ApiOperation::GetPrototypeOf,
        ApiOperation::Has,
        ApiOperation::Call,
        ApiOperation::Set,
    ] {
        assert!(
            operations.contains(&required),
            "missing trace operation: {required:?}"
        );
    }
    let stats = runtime.trace_stats().expect("trace stats");
    assert!(stats["events"].as_u64().is_some_and(|events| events > 0));
    assert_eq!(stats["dropped"], 0);

    println!(
        "{}",
        serde_json::to_string_pretty(&json!({
            "accepted": true,
            "global_count": value["globalCount"],
            "clock_unique_800": value["clockUnique"],
            "cookie": cookies,
            "navigation": navigation,
            "trace_events": trace.footer.event_count,
            "trace_stats": stats,
        }))
        .expect("report")
    );
    runtime.close().expect("close");
}
