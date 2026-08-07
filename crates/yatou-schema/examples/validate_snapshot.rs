//! Validates one Chrome snapshot against the current Rust data contract.
#![allow(clippy::print_stdout)]

use std::{env, fs};

use yatou_schema::ChromeSnapshot;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let path = env::args().nth(1).ok_or("usage: validate_snapshot PATH")?;
    let bytes = fs::read(&path)?;
    let snapshot: ChromeSnapshot = serde_json::from_slice(&bytes)?;
    snapshot.validate()?;
    println!(
        "validated baseline={} run={} surfaces={}",
        snapshot.baseline_id,
        snapshot.run_id,
        snapshot.surfaces.len()
    );
    Ok(())
}
