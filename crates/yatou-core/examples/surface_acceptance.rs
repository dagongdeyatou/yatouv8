//! Verify the installed realm against every descriptor in the generated runtime manifest.
#![allow(linker_messages)]

use serde_json::{Value, json};
use yatou_core::{BrowserRuntime, RuntimeConfig};

fn main() {
    let source = include_str!("surface_probe.js").replace(
        "__YATOU_RUNTIME_SURFACE__",
        include_str!("../../../manifests/chrome150.runtime-surface.json"),
    );
    let runtime = BrowserRuntime::new(RuntimeConfig::default()).expect("runtime");
    let result = runtime.eval(source).expect("eval transport");
    assert!(result.ok, "JavaScript exception: {result:?}");
    let report: Value =
        serde_json::from_str(result.json.as_deref().expect("JSON result")).expect("decode report");
    let expected_members = u64::try_from(yatou_surface::GENERATED_MEMBERS.len())
        .expect("generated member count fits u64");
    assert_eq!(report["expected"].as_u64(), Some(expected_members));
    assert_eq!(report["present"].as_u64(), Some(expected_members));
    assert_eq!(report["descriptorExact"].as_u64(), Some(expected_members));
    assert_eq!(report["callableExpected"], report["callableExact"]);
    assert_eq!(report["failureCount"], 0);
    println!(
        "{}",
        serde_json::to_string_pretty(&json!({
            "accepted": true,
            "baseline": yatou_surface::GENERATED_BASELINE_ID,
            "interfaces": yatou_surface::GENERATED_INTERFACES.len(),
            "members": report["expected"],
            "descriptors_exact": report["descriptorExact"],
            "callables_exact": report["callableExact"],
            "failures": report["failureCount"],
        }))
        .expect("report")
    );
    runtime.close().expect("close");
}
