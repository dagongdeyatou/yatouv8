//! Compare Chrome and yatouv8 NDJSON traces and emit ranked blockers.
#![allow(clippy::print_stdout)]

use std::{env, fs};

use yatou_harness::{TraceDiffAllowance, compare_traces};
use yatou_schema::TraceStream;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let mut arguments = env::args().skip(1);
    let chrome_path = arguments.next().ok_or("usage: diff_trace CHROME YATOU")?;
    let yatou_path = arguments.next().ok_or("usage: diff_trace CHROME YATOU")?;
    let chrome = TraceStream::from_ndjson(&fs::read_to_string(chrome_path)?)?;
    let yatou = TraceStream::from_ndjson(&fs::read_to_string(yatou_path)?)?;
    let report = compare_traces(&chrome, &yatou, TraceDiffAllowance::default());
    println!("{}", serde_json::to_string_pretty(&report)?);
    Ok(())
}
