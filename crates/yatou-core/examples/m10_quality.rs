//! M10 startup, latency, concurrency, exception-recovery, and lifecycle gate.
#![allow(linker_messages)]

use std::sync::Arc;
use std::time::{Duration, Instant};

use serde_json::json;
use yatou_core::{BrowserRuntime, RuntimeConfig};

fn percentile(values: &mut [Duration], numerator: usize, denominator: usize) -> Duration {
    values.sort_unstable();
    let index = (values.len().saturating_sub(1) * numerator) / denominator;
    values[index]
}

fn main() {
    let startup_begin = Instant::now();
    let runtime = Arc::new(BrowserRuntime::new(RuntimeConfig::default()).expect("runtime"));
    let startup = startup_begin.elapsed();

    let mut latencies = Vec::with_capacity(200);
    for value in 0..200_u32 {
        let begin = Instant::now();
        let result = runtime
            .eval(format!(
                "globalThis.qualityCounter = {value}; qualityCounter + 1"
            ))
            .expect("latency eval");
        assert!(result.ok);
        latencies.push(begin.elapsed());
    }
    let p50 = percentile(&mut latencies.clone(), 50, 100);
    let p95 = percentile(&mut latencies, 95, 100);

    runtime
        .eval("globalThis.concurrentQualityCounter = 0")
        .expect("counter");
    let threads = (0..64)
        .map(|_| {
            let runtime = Arc::clone(&runtime);
            std::thread::spawn(move || {
                let result = runtime
                    .eval("++globalThis.concurrentQualityCounter")
                    .expect("concurrent eval");
                assert!(result.ok);
            })
        })
        .collect::<Vec<_>>();
    for thread in threads {
        thread.join().expect("caller");
    }
    let concurrent_value = runtime
        .eval("concurrentQualityCounter")
        .expect("counter result");
    assert_eq!(concurrent_value.json.as_deref(), Some("64"));

    for _ in 0..100 {
        let failure = runtime
            .eval("throw new Error('recoverable')")
            .expect("structured JS error");
        assert!(!failure.ok);
        let recovery = runtime.eval("6 * 7").expect("recovery");
        assert!(recovery.ok);
        assert_eq!(recovery.json.as_deref(), Some("42"));
    }

    let trace = runtime.trace().expect("trace");
    runtime.close().expect("close");
    runtime.close().expect("idempotent close");

    let thresholds = json!({
        "startup_ms_max": 10_000,
        "eval_p95_ms_max": 100,
    });
    let startup_ms = startup.as_secs_f64() * 1000.0;
    let p50_ms = p50.as_secs_f64() * 1000.0;
    let p95_ms = p95.as_secs_f64() * 1000.0;
    let accepted = startup_ms < 10_000.0 && p95_ms < 100.0 && trace.footer.complete;
    let report = json!({
        "milestone": "m10",
        "accepted": accepted,
        "startup_ms": startup_ms,
        "eval_samples": 200,
        "eval_p50_ms": p50_ms,
        "eval_p95_ms": p95_ms,
        "concurrent_callers": 64,
        "concurrent_result": 64,
        "exception_recovery_cycles": 100,
        "close_idempotent": true,
        "trace_complete": trace.footer.complete,
        "trace_events": trace.footer.event_count,
        "thresholds": thresholds,
    });
    println!("{}", serde_json::to_string_pretty(&report).expect("report"));
    if !accepted {
        std::process::exit(1);
    }
}
