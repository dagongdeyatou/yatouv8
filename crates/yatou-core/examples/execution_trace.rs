//! Capture dynamic `eval` source and precise V8 block coverage.

use std::fs;

use yatou_core::{BrowserRuntime, ExecutionTraceConfig, RuntimeConfig};

fn main() {
    let mut arguments = std::env::args().skip(1);
    let source_path = arguments.next();
    let output_path = arguments
        .next()
        .unwrap_or_else(|| "execution-trace.json".to_owned());
    let source = source_path.map_or_else(
        || {
            r"
                eval(`
                    globalThis.__coverageProbe = true;
                    if (globalThis.addEventListener) {
                        globalThis.__coverageHit = 1;
                    } else {
                        globalThis.__coverageMiss = 1;
                    }
                `);
                globalThis.__coverageHit;
            "
            .to_owned()
        },
        |path| fs::read_to_string(path).expect("read JavaScript source"),
    );
    let config = RuntimeConfig {
        execution_trace: ExecutionTraceConfig {
            enabled: true,
            ..ExecutionTraceConfig::default()
        },
        ..RuntimeConfig::default()
    };
    let runtime = BrowserRuntime::new(config).expect("runtime");
    let result = runtime.eval(source).expect("eval");
    let capture = runtime.execution_trace().expect("execution trace");
    fs::write(
        &output_path,
        serde_json::to_vec_pretty(&serde_json::json!({
            "eval_result": result,
            "execution_trace": capture,
        }))
        .expect("serialize trace"),
    )
    .expect("write trace");
    println!("{output_path}");
}
