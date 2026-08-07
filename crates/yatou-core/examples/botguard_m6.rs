//! Execute the archived Google `BotGuard` M6 fixture and optionally retain its trace.

use std::path::PathBuf;

use yatou_core::{BrowserProfile, run_botguard};

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let mut arguments = std::env::args_os().skip(1);
    let model_path = PathBuf::from(arguments.next().ok_or("missing model.js path")?);
    let bytecode_path = PathBuf::from(arguments.next().ok_or("missing enc path")?);
    let trace_path = arguments.next().map(PathBuf::from);
    let result_path = arguments.next().map(PathBuf::from);
    let model = std::fs::read_to_string(&model_path)?;
    let bytecode = std::fs::read(&bytecode_path)?;
    let run = run_botguard(&model, &bytecode, &BrowserProfile::default())?;
    if let Some(path) = trace_path {
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent)?;
        }
        std::fs::write(path, run.trace.to_ndjson()?)?;
    }
    if let Some(path) = result_path {
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent)?;
        }
        std::fs::write(
            path,
            serde_json::to_vec_pretty(&serde_json::json!({
                "api_call_count": run.api_call_count,
                "error": run.error,
                "token": run.token,
                "starts_with_bang": run.starts_with_bang,
                "token_length": run.token_length,
                "token_shape_sha256": run.token_shape_sha256,
                "diagnostic_trace": run.diagnostic_trace,
            }))?,
        )?;
    }
    println!(
        "{}",
        serde_json::to_string_pretty(&serde_json::json!({
            "api_call_count": run.api_call_count,
            "error": run.error,
            "starts_with_bang": run.starts_with_bang,
            "token_length": run.token_length,
            "token_shape_sha256": run.token_shape_sha256,
            "trace_event_count": run.trace.footer.event_count,
        }))?
    );
    Ok(())
}
