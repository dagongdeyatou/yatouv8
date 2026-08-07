//! Executable smoke test for the pinned V8 source build.
#![allow(linker_messages)]

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let source = "JSON.stringify({ engine: 'v8', answer: 6 * 7, traceSpine: false })";
    let value = yatou_core::evaluate_to_string(source)?;

    println!("yatouv8 V8 smoke: {value}");
    if value != r#"{"engine":"v8","answer":42,"traceSpine":false}"# {
        return Err(format!("unexpected V8 result: {value}").into());
    }
    Ok(())
}
