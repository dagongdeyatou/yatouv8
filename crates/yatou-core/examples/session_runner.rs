//! Execute caller-provided source in the persistent browser runtime and emit JSON.
#![allow(linker_messages)]

use std::fs;
use std::path::PathBuf;

use serde::Deserialize;
use serde_json::json;
use yatou_core::{BrowserRuntime, Resource, RuntimeConfig};

#[derive(Debug, Deserialize)]
struct ResourceManifest {
    resources: Vec<Resource>,
}

fn argument(name: &str) -> Option<String> {
    let mut arguments = std::env::args().skip(1);
    while let Some(argument) = arguments.next() {
        if argument == name {
            return arguments.next();
        }
    }
    None
}

fn main() {
    let script_path = argument("--script").map_or_else(
        || {
            eprintln!(
                "usage: session_runner --script PATH [--resources PATH] [--config PATH] [--drain N]"
            );
            std::process::exit(2);
        },
        PathBuf::from,
    );
    let source = fs::read_to_string(&script_path).expect("read script");
    let config = argument("--config").map_or_else(RuntimeConfig::default, |path| {
        serde_json::from_slice(&fs::read(path).expect("read config")).expect("parse config")
    });
    let runtime = BrowserRuntime::new(config).expect("runtime");
    if let Some(path) = argument("--resources") {
        let manifest = serde_json::from_slice::<ResourceManifest>(
            &fs::read(path).expect("read resource manifest"),
        )
        .expect("parse resource manifest");
        for resource in manifest.resources {
            runtime.add_resource(resource).expect("add resource");
        }
    }
    let result = runtime.eval(source).expect("eval");
    let drain = argument("--drain").map_or(serde_json::Value::Null, |value| {
        runtime
            .drain(value.parse().expect("drain limit"))
            .expect("drain")
    });
    let trace = runtime.trace().expect("trace");
    let report = json!({
        "result": result,
        "drain": drain,
        "environment": runtime.environment().expect("environment"),
        "trace": {
            "header": trace.header,
            "events": trace.events,
            "footer": trace.footer,
        },
    });
    println!("{}", serde_json::to_string_pretty(&report).expect("report"));
    runtime.close().expect("close");
}
