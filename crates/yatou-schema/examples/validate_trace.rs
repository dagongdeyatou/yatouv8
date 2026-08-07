//! Validates one complete L0/L1 NDJSON trace against the Rust data contract.
#![allow(clippy::print_stdout)]

use std::{env, fs};

use yatou_schema::TraceStream;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let path = env::args()
        .nth(1)
        .ok_or("usage: validate_trace TRACE.ndjson")?;
    let stream = TraceStream::from_ndjson(&fs::read_to_string(&path)?)?;
    println!(
        "validated trace={} baseline={} events={} l0={} l1={}",
        stream.header.trace_id,
        stream.header.baseline_id,
        stream.footer.event_count,
        stream.footer.l0_count,
        stream.footer.l1_count
    );
    Ok(())
}
