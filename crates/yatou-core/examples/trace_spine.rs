//! Produce, decode, validate, and strictly replay an M3 trace fixture.
#![allow(clippy::print_stdout, clippy::too_many_lines)]

use std::{collections::BTreeMap, env, fs};

use yatou_core::{ReplayTape, TraceRecorder};
use yatou_schema::{
    ApiLedgerEvent, ApiOperation, ApiOutcome, BaselineId, CURRENT_SCHEMA_VERSION, CallSite,
    EvalOutcome, JsValueKind, ReplayEvent, TraceHeader, TraceSource, TraceStream, ValueSummary,
};

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let output = env::args()
        .nth(1)
        .ok_or("usage: trace_spine OUTPUT.ndjson")?;
    let mut recorder = TraceRecorder::new(TraceHeader {
        schema_version: CURRENT_SCHEMA_VERSION,
        trace_id: "m3-trace-spine-v1".to_owned(),
        baseline_id: BaselineId::parse("win11-chrome150.0.7871.188-headful-m2-v2")?,
        source: TraceSource::Fixture,
        created_at: "2026-08-07T00:00:00.000Z".to_owned(),
        producer: "yatou-core/0.1.0-alpha.0".to_owned(),
    });

    let eval = recorder.record_l0(
        0,
        None,
        ReplayEvent::EvalStart {
            eval_id: "eval-google-vm-fixture".to_owned(),
            source_sha256: "1".repeat(64),
        },
    )?;
    recorder.record_l1(
        100,
        Some(eval),
        ApiLedgerEvent {
            operation: ApiOperation::Get,
            target: "Navigator.prototype".to_owned(),
            member: Some("userAgent".to_owned()),
            arguments: vec![],
            outcome: ApiOutcome::Return {
                value: ValueSummary {
                    kind: JsValueKind::String,
                    preview: Some("Mozilla/5.0 ... Chrome/150.0.0.0".to_owned()),
                    sha256: None,
                },
            },
            call_site: Some(CallSite {
                script: "fixture://google-vm.js".to_owned(),
                line: 0,
                column: 12,
            }),
        },
    )?;
    recorder.record_l0(
        200,
        Some(eval),
        ReplayEvent::ResourceRequest {
            request_id: "resource-1".to_owned(),
            method: "GET".to_owned(),
            url: "https://fixture.invalid/challenge.js".to_owned(),
        },
    )?;
    recorder.record_l0(
        300,
        Some(eval),
        ReplayEvent::ResourceResponse {
            request_id: "resource-1".to_owned(),
            status: 200,
            headers: BTreeMap::from([(
                "content-type".to_owned(),
                "text/javascript; charset=utf-8".to_owned(),
            )]),
            body_base64: "Y29uc29sZS5sb2coNDIpOw==".to_owned(),
            body_sha256: "2".repeat(64),
        },
    )?;
    recorder.record_l0(
        400,
        Some(eval),
        ReplayEvent::TimerSchedule {
            timer_id: 1,
            delay_ms: 10.0,
            repeating: false,
        },
    )?;
    recorder.record_l0(10_400, Some(eval), ReplayEvent::TimerFire { timer_id: 1 })?;
    recorder.record_l1(
        10_500,
        Some(eval),
        ApiLedgerEvent {
            operation: ApiOperation::Call,
            target: "Performance.prototype".to_owned(),
            member: Some("now".to_owned()),
            arguments: vec![],
            outcome: ApiOutcome::Return {
                value: ValueSummary {
                    kind: JsValueKind::Number,
                    preview: Some("10.5".to_owned()),
                    sha256: None,
                },
            },
            call_site: Some(CallSite {
                script: "fixture://google-vm.js".to_owned(),
                line: 1,
                column: 4,
            }),
        },
    )?;
    recorder.record_l0(
        10_600,
        Some(eval),
        ReplayEvent::Checkpoint {
            name: "after-timer".to_owned(),
            state_sha256: "3".repeat(64),
        },
    )?;
    recorder.record_l0(
        10_700,
        Some(eval),
        ReplayEvent::EvalEnd {
            eval_id: "eval-google-vm-fixture".to_owned(),
            outcome: EvalOutcome::Return,
        },
    )?;

    let stream = recorder.finish()?;
    let encoded = stream.to_ndjson()?;
    if let Some(parent) = std::path::Path::new(&output).parent() {
        fs::create_dir_all(parent)?;
    }
    fs::write(&output, encoded.as_bytes())?;
    let decoded = TraceStream::from_ndjson(&fs::read_to_string(&output)?)?;

    let mut replay = ReplayTape::new(&decoded)?;
    replay.expect_event(&ReplayEvent::EvalStart {
        eval_id: "eval-google-vm-fixture".to_owned(),
        source_sha256: "1".repeat(64),
    })?;
    let resource = replay.resource("GET", "https://fixture.invalid/challenge.js")?;
    replay.expect_event(&ReplayEvent::TimerSchedule {
        timer_id: 1,
        delay_ms: 10.0,
        repeating: false,
    })?;
    replay.expect_event(&ReplayEvent::TimerFire { timer_id: 1 })?;
    replay.expect_event(&ReplayEvent::Checkpoint {
        name: "after-timer".to_owned(),
        state_sha256: "3".repeat(64),
    })?;
    replay.expect_event(&ReplayEvent::EvalEnd {
        eval_id: "eval-google-vm-fixture".to_owned(),
        outcome: EvalOutcome::Return,
    })?;
    replay.finish()?;

    println!(
        "{}",
        serde_json::json!({
            "trace": output,
            "events": decoded.footer.event_count,
            "l0": decoded.footer.l0_count,
            "l1": decoded.footer.l1_count,
            "resource_status": resource.status,
            "replay_complete": true,
            "network_fallback": false
        })
    );
    Ok(())
}
