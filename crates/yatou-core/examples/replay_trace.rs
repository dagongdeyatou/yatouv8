//! Verify that every L0 event in a trace is consumed by the strict offline replay tape.

use std::path::PathBuf;

use yatou_core::ReplayTape;
use yatou_schema::{TraceEventBody, TraceStream};

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let path = PathBuf::from(std::env::args_os().nth(1).ok_or("missing trace path")?);
    let input = std::fs::read_to_string(path)?;
    let stream = TraceStream::from_ndjson(&input)?;
    let expected = stream
        .events
        .iter()
        .filter_map(|event| match &event.body {
            TraceEventBody::L0(entry) => Some(entry.clone()),
            TraceEventBody::L1(_) => None,
        })
        .collect::<Vec<_>>();
    let mut tape = ReplayTape::new(&stream)?;
    for event in &expected {
        tape.expect_event(event)?;
    }
    tape.finish()?;
    println!(
        "{}",
        serde_json::to_string_pretty(&serde_json::json!({
            "fully_consumed": true,
            "l0_events": expected.len(),
            "network_fallback": false,
            "trace_id": stream.header.trace_id,
        }))?
    );
    Ok(())
}
