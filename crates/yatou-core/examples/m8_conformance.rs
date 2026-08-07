//! Exercise the M7 owner-thread API and M8 browser host as one deterministic slice.
#![allow(linker_messages)]

use std::collections::BTreeMap;
use std::sync::Arc;

use serde_json::json;
use yatou_core::{BrowserRuntime, Resource, RuntimeConfig};

fn eval_json(runtime: &BrowserRuntime, source: &str) -> serde_json::Value {
    let result = runtime.eval(source).expect("runtime eval");
    assert!(
        result.ok,
        "JavaScript exception: {:?}: {:?}",
        result.exception_name, result.exception_message
    );
    result
        .json
        .as_deref()
        .map(serde_json::from_str)
        .transpose()
        .expect("JSON result")
        .unwrap_or(serde_json::Value::Null)
}

#[allow(clippy::too_many_lines)]
fn main() {
    let runtime = Arc::new(BrowserRuntime::new(RuntimeConfig::default()).expect("runtime start"));
    runtime
        .add_resource(
            Resource::new(
                "https://fixture.invalid/data.json",
                200,
                BTreeMap::from([("content-type".to_owned(), "application/json".to_owned())]),
                br#"{"answer":42}"#.to_vec(),
            )
            .expect("resource"),
        )
        .expect("add resource");

    assert_eq!(
        eval_json(&runtime, "globalThis.counter = 40; counter + 2"),
        json!(42)
    );
    assert_eq!(eval_json(&runtime, "counter"), json!(40));

    let dom = eval_json(
        &runtime,
        r#"(() => {
            const article = document.createElement("article");
            article.id = "probe";
            article.classList.add("ready", "m8");
            article.style.cssText = "color: rgb(1, 2, 3); width: 12px";
            article.appendChild(document.createTextNode("yatou"));
            document.body.appendChild(article);
            return {
                found: document.querySelector("article#probe.ready") === article,
                text: article.textContent,
                connected: article.isConnected,
                childCount: document.body.childElementCount,
                color: getComputedStyle(article).color,
                width: getComputedStyle(article).width,
                display: getComputedStyle(article).display
            };
        })()"#,
    );
    assert_eq!(dom["found"], true);
    assert_eq!(dom["text"], "yatou");
    assert_eq!(dom["connected"], true);
    assert_eq!(dom["color"], "rgb(1, 2, 3)");
    assert_eq!(dom["width"], "12px");
    assert_eq!(dom["display"], "block");

    let state = eval_json(
        &runtime,
        r#"(() => {
            localStorage.setItem("answer", 42);
            sessionStorage.setItem("mode", "m8");
            document.cookie = "session=yatou; Path=/";
            const target = document.createElement("button");
            let events = 0;
            target.addEventListener("click", () => events++, { once: true });
            target.dispatchEvent(new MouseEvent("click"));
            target.dispatchEvent(new MouseEvent("click"));
            return {
                local: localStorage.getItem("answer"),
                session: sessionStorage.getItem("mode"),
                cookie: document.cookie,
                events
            };
        })()"#,
    );
    assert_eq!(state["local"], "42");
    assert_eq!(state["session"], "m8");
    assert_eq!(state["cookie"], "session=yatou");
    assert_eq!(state["events"], 1);

    eval_json(
        &runtime,
        r#"globalThis.timerResult = [];
           queueMicrotask(() => timerResult.push("microtask"));
           setTimeout(() => timerResult.push("timer"), 5);
           "scheduled""#,
    );
    let drain = runtime.drain(10).expect("drain");
    assert_eq!(drain["pendingTimers"], 0);
    assert_eq!(
        eval_json(&runtime, "timerResult"),
        json!(["microtask", "timer"])
    );

    eval_json(
        &runtime,
        r#"globalThis.fetchResult = null;
           fetch("https://fixture.invalid/data.json")
             .then(response => response.json())
             .then(value => { globalThis.fetchResult = value.answer; });
           "fetch-started""#,
    );
    assert_eq!(eval_json(&runtime, "fetchResult"), json!(42));
    eval_json(
        &runtime,
        r#"globalThis.resourceMiss = null;
           fetch("https://fixture.invalid/missing.json")
             .catch(error => { globalThis.resourceMiss = error.message; });
           "miss-started""#,
    );
    assert!(
        eval_json(&runtime, "resourceMiss")
            .as_str()
            .is_some_and(|value| value.contains("offline resource not found"))
    );

    eval_json(&runtime, "globalThis.concurrentCounter = 0");
    let workers = (0..8)
        .map(|_| {
            let runtime = Arc::clone(&runtime);
            std::thread::spawn(move || {
                let result = runtime
                    .eval("globalThis.concurrentCounter += 1")
                    .expect("concurrent eval");
                assert!(result.ok);
            })
        })
        .collect::<Vec<_>>();
    for worker in workers {
        worker.join().expect("caller thread");
    }
    assert_eq!(eval_json(&runtime, "concurrentCounter"), json!(8));

    let trace = runtime.trace().expect("validated trace");
    let environment = runtime.environment().expect("environment");
    let report = json!({
        "milestone": "m8",
        "persistent_realm": true,
        "owner_thread_serialization": true,
        "dom_cssom_storage_events": true,
        "timers_drained": drain["pendingTimers"] == 0,
        "offline_resource": true,
        "network_fallback": environment["networkFallback"],
        "trace": {
            "events": trace.footer.event_count,
            "l0": trace.footer.l0_count,
            "l1": trace.footer.l1_count,
            "complete": trace.footer.complete,
        },
        "environment": environment,
    });
    println!("{}", serde_json::to_string_pretty(&report).expect("report"));
    runtime.close().expect("close");
}
