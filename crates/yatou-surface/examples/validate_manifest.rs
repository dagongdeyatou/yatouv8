//! Decode and validate an evidence-derived Surface Manifest.

use std::path::PathBuf;

use yatou_surface::SurfaceManifest;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let path = PathBuf::from(std::env::args_os().nth(1).ok_or("missing manifest path")?);
    let input = std::fs::read_to_string(path)?;
    let manifest = serde_json::from_str::<SurfaceManifest>(&input)?;
    manifest.validate()?;
    let member_count = manifest
        .interfaces
        .iter()
        .map(|interface| interface.members.len())
        .sum::<usize>();
    println!(
        "validated surface manifest baseline={} interfaces={} members={} snapshot_sha256={}",
        manifest.baseline_id,
        manifest.interfaces.len(),
        member_count,
        manifest.source_snapshot.sha256,
    );
    Ok(())
}
