//! Opt-in V8 Inspector capture for dynamically evaluated JavaScript.

use std::cell::RefCell;
use std::collections::{BTreeMap, BTreeSet};
use std::rc::Rc;

use serde_json::{Value, json};
use sha2::{Digest, Sha256};

use super::ExecutionTraceConfig;

#[derive(Default)]
struct ProtocolState {
    responses: BTreeMap<i32, Value>,
    notifications: Vec<Value>,
    decode_errors: Vec<String>,
}

#[derive(Clone)]
struct ProtocolChannel {
    state: Rc<RefCell<ProtocolState>>,
}

impl v8::inspector::ChannelImpl for ProtocolChannel {
    fn send_response(&self, call_id: i32, message: v8::UniquePtr<v8::inspector::StringBuffer>) {
        let Some(message) = message.as_ref() else {
            self.state
                .borrow_mut()
                .decode_errors
                .push(format!("Inspector response {call_id} had no payload"));
            return;
        };
        let text = message.string().to_string();
        match serde_json::from_str(&text) {
            Ok(value) => {
                self.state.borrow_mut().responses.insert(call_id, value);
            }
            Err(error) => self
                .state
                .borrow_mut()
                .decode_errors
                .push(format!("Inspector response {call_id}: {error}: {text}")),
        }
    }

    fn send_notification(&self, message: v8::UniquePtr<v8::inspector::StringBuffer>) {
        let Some(message) = message.as_ref() else {
            self.state
                .borrow_mut()
                .decode_errors
                .push("Inspector notification had no payload".to_owned());
            return;
        };
        let text = message.string().to_string();
        match serde_json::from_str(&text) {
            Ok(value) => self.state.borrow_mut().notifications.push(value),
            Err(error) => self
                .state
                .borrow_mut()
                .decode_errors
                .push(format!("Inspector notification: {error}: {text}")),
        }
    }

    fn flush_protocol_notifications(&self) {}
}

#[derive(Default)]
struct InspectorClient;

impl v8::inspector::V8InspectorClientImpl for InspectorClient {}

/// Inspector state retained on the isolate owner thread.
///
/// The session field intentionally precedes the inspector field so it is
/// destroyed first and cannot outlive the inspector it is connected to.
pub(super) struct ExecutionInspector {
    session: v8::inspector::V8InspectorSession,
    inspector: v8::inspector::V8Inspector,
    state: Rc<RefCell<ProtocolState>>,
    config: ExecutionTraceConfig,
    next_call_id: i32,
    eval_sequence: u64,
    active: bool,
    last_capture: Value,
}

impl ExecutionInspector {
    pub(super) fn new(
        isolate: &mut v8::OwnedIsolate,
        context: &v8::Global<v8::Context>,
        config: ExecutionTraceConfig,
    ) -> Result<Self, String> {
        let client = v8::inspector::V8InspectorClient::new(Box::<InspectorClient>::default());
        let inspector = v8::inspector::V8Inspector::create(isolate, client);
        {
            v8::scope!(let scope, isolate);
            let context = v8::Local::new(scope, context);
            inspector.context_created(
                context,
                1,
                v8::inspector::StringView::from(b"yatouv8".as_slice()),
                v8::inspector::StringView::from(b"{}".as_slice()),
            );
        }
        let state = Rc::new(RefCell::new(ProtocolState::default()));
        let channel = ProtocolChannel {
            state: Rc::clone(&state),
        };
        let session = inspector.connect(
            1,
            v8::inspector::Channel::new(Box::new(channel)),
            v8::inspector::StringView::from(b"{}".as_slice()),
            v8::inspector::V8InspectorClientTrustLevel::FullyTrusted,
        );
        let mut capture = Self {
            session,
            inspector,
            state,
            config,
            next_call_id: 1,
            eval_sequence: 0,
            active: false,
            last_capture: json!({
                "schema_version": 1,
                "enabled": true,
                "status": "no_eval_captured",
                "scripts": [],
            }),
        };
        capture.dispatch("Debugger.enable", None)?;
        capture.dispatch("Profiler.enable", None)?;
        capture.dispatch("Runtime.enable", None)?;
        if let Ok(script_hash) = std::env::var("YATOU_INSPECTOR_BREAK_HASH") {
            if !script_hash.is_empty() {
                let line_number = std::env::var("YATOU_INSPECTOR_BREAK_LINE")
                    .ok()
                    .and_then(|value| value.parse::<u32>().ok())
                    .unwrap_or(0);
                let column_number = std::env::var("YATOU_INSPECTOR_BREAK_COLUMN")
                    .ok()
                    .and_then(|value| value.parse::<u32>().ok())
                    .unwrap_or(0);
                let condition = std::env::var("YATOU_INSPECTOR_BREAK_CONDITION").ok();
                let mut params = json!({
                    "lineNumber": line_number,
                    "columnNumber": column_number,
                    "scriptHash": script_hash,
                });
                if let Some(condition) = condition.filter(|value| !value.is_empty()) {
                    params["condition"] = Value::String(condition);
                }
                capture.dispatch("Debugger.setBreakpointByUrl", Some(params))?;
            }
        }
        capture.reset_protocol_window();
        Ok(capture)
    }

    pub(super) fn begin_eval(&mut self) -> Result<u64, String> {
        if self.active {
            return Err("execution coverage capture is already active".to_owned());
        }
        self.eval_sequence = self.eval_sequence.saturating_add(1);
        self.reset_protocol_window();
        self.dispatch(
            "Profiler.startPreciseCoverage",
            Some(json!({
                "callCount": true,
                "detailed": true,
                "allowTriggeredUpdates": false,
            })),
        )?;
        self.active = true;
        Ok(self.eval_sequence)
    }

    pub(super) fn finish_eval(&mut self, eval_sequence: u64) -> Result<(), String> {
        if !self.active {
            return Err("execution coverage capture is not active".to_owned());
        }
        let coverage = self.dispatch("Profiler.takePreciseCoverage", None);
        let stop = self.dispatch("Profiler.stopPreciseCoverage", None);
        self.active = false;
        let coverage = coverage?;
        stop?;
        self.last_capture = self.build_capture(eval_sequence, &coverage);
        Ok(())
    }

    pub(super) fn abort_eval(&mut self, eval_sequence: u64, reason: &str) {
        if self.active {
            let _ = self.dispatch("Profiler.stopPreciseCoverage", None);
            self.active = false;
        }
        self.last_capture = json!({
            "schema_version": 1,
            "enabled": true,
            "status": "capture_failed",
            "eval_sequence": eval_sequence,
            "error": reason,
            "scripts": [],
        });
    }

    pub(super) fn snapshot(&self) -> Value {
        self.last_capture.clone()
    }

    fn dispatch(&mut self, method: &str, params: Option<Value>) -> Result<Value, String> {
        let call_id = self.next_call_id;
        self.next_call_id = self.next_call_id.saturating_add(1);
        let mut request = json!({"id": call_id, "method": method});
        if let Some(params) = params {
            request["params"] = params;
        }
        let request = serde_json::to_vec(&request).map_err(|error| error.to_string())?;
        self.session
            .dispatch_protocol_message(v8::inspector::StringView::from(request.as_slice()));
        let response = self
            .state
            .borrow_mut()
            .responses
            .remove(&call_id)
            .ok_or_else(|| format!("Inspector method {method} returned no response"))?;
        if let Some(error) = response.get("error") {
            return Err(format!("Inspector method {method} failed: {error}"));
        }
        Ok(response)
    }

    fn reset_protocol_window(&self) {
        let mut state = self.state.borrow_mut();
        state.notifications.clear();
        state.decode_errors.clear();
    }

    fn build_capture(&mut self, eval_sequence: u64, coverage: &Value) -> Value {
        let (notifications, decode_errors) = {
            let state = self.state.borrow();
            (state.notifications.clone(), state.decode_errors.clone())
        };
        let parsed = parsed_scripts(notifications);
        let console_events = inspector_console_events(&self.state.borrow().notifications);
        let coverage_by_script = coverage_by_script(coverage);
        let mut scripts = Vec::new();
        let mut omitted_scripts = 0_u64;
        let mut target_script_order = 0_u64;
        for (index, (script_id, metadata)) in parsed.into_iter().enumerate() {
            if index >= self.config.max_scripts as usize {
                omitted_scripts = omitted_scripts.saturating_add(1);
                continue;
            }
            let source = self.capture_source(&script_id);
            let role = script_role(source.full.as_deref(), target_script_order);
            if matches!(role, "entry_eval" | "nested_dynamic_script") {
                target_script_order = target_script_order.saturating_add(1);
            }
            let coverage = coverage_by_script.get(&script_id).cloned();
            let missed_range_snippets =
                missed_range_snippets(source.full.as_deref(), coverage.as_ref());
            scripts.push(json!({
                "script_id": script_id,
                "parse_order": index,
                "role": role,
                "url": metadata.get("url").cloned().unwrap_or(Value::String(String::new())),
                "embedder_name": metadata.get("embedderName").cloned().unwrap_or(Value::String(String::new())),
                "hash": metadata.get("hash").cloned().unwrap_or(Value::Null),
                "start_line": metadata.get("startLine").cloned().unwrap_or(Value::Null),
                "start_column": metadata.get("startColumn").cloned().unwrap_or(Value::Null),
                "end_line": metadata.get("endLine").cloned().unwrap_or(Value::Null),
                "end_column": metadata.get("endColumn").cloned().unwrap_or(Value::Null),
                "source_length_bytes": source.full_bytes,
                "source_sha256": source.sha256,
                "source": source.retained,
                "source_truncated": source.truncated,
                "source_error": source.error,
                "missed_range_snippets": missed_range_snippets,
                "functions": coverage
                    .as_ref()
                    .and_then(|value| value.get("functions"))
                    .cloned()
                    .unwrap_or_else(|| Value::Array(Vec::new())),
            }));
        }
        let (summary, captured_script_ids) = summarize_scripts(&scripts, omitted_scripts);
        json!({
            "schema_version": 1,
            "enabled": true,
            "status": "captured",
            "eval_sequence": eval_sequence,
            "summary": summary,
            "script_ids": captured_script_ids,
            "protocol_decode_errors": decode_errors,
            "console_events": console_events,
            "scripts": scripts,
        })
    }

    fn capture_source(&mut self, script_id: &str) -> CapturedSource {
        let response = self.dispatch(
            "Debugger.getScriptSource",
            Some(json!({"scriptId": script_id})),
        );
        let (full, error) = match response {
            Ok(response) => (
                response
                    .pointer("/result/scriptSource")
                    .and_then(Value::as_str)
                    .map(str::to_owned),
                None,
            ),
            Err(error) => (None, Some(error)),
        };
        CapturedSource::new(full, error, self.config)
    }
}

fn inspector_console_events(notifications: &[Value]) -> Vec<Value> {
    notifications
        .iter()
        .filter(|notification| {
            notification.get("method").and_then(Value::as_str) == Some("Runtime.consoleAPICalled")
        })
        .filter_map(|notification| notification.get("params"))
        .filter(|params| {
            params
                .get("args")
                .and_then(Value::as_array)
                .and_then(|args| args.first())
                .and_then(|argument| argument.get("value"))
                .and_then(Value::as_str)
                .is_some_and(|value| value.starts_with("__YATOU_BP__"))
        })
        .cloned()
        .collect()
}

struct CapturedSource {
    full: Option<String>,
    retained: Option<String>,
    full_bytes: usize,
    sha256: Option<String>,
    truncated: bool,
    error: Option<String>,
}

impl CapturedSource {
    fn new(full: Option<String>, error: Option<String>, config: ExecutionTraceConfig) -> Self {
        let full_bytes = full.as_deref().map_or(0, str::len);
        let sha256 = full
            .as_deref()
            .map(|value| format!("{:x}", Sha256::digest(value.as_bytes())));
        let (retained, truncated) = retained_source(full.as_deref(), config);
        Self {
            full,
            retained,
            full_bytes,
            sha256,
            truncated,
            error,
        }
    }
}

fn retained_source(source: Option<&str>, config: ExecutionTraceConfig) -> (Option<String>, bool) {
    if !config.capture_source {
        return (None, false);
    }
    source.map_or((None, false), |source| {
        if source.len() <= config.max_source_bytes as usize {
            return (Some(source.to_owned()), false);
        }
        let mut end = config.max_source_bytes as usize;
        while !source.is_char_boundary(end) {
            end = end.saturating_sub(1);
        }
        (Some(source[..end].to_owned()), true)
    })
}

fn parsed_scripts(notifications: Vec<Value>) -> Vec<(String, Value)> {
    let mut parsed = Vec::new();
    let mut seen = BTreeSet::new();
    for notification in notifications {
        if notification.get("method").and_then(Value::as_str) != Some("Debugger.scriptParsed") {
            continue;
        }
        let Some(params) = notification.get("params") else {
            continue;
        };
        let Some(script_id) = params.get("scriptId").and_then(Value::as_str) else {
            continue;
        };
        if seen.insert(script_id.to_owned()) {
            parsed.push((script_id.to_owned(), params.clone()));
        }
    }
    parsed
}

fn coverage_by_script(coverage: &Value) -> BTreeMap<String, Value> {
    coverage
        .pointer("/result/result")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(|row| {
            let script_id = row.get("scriptId")?.as_str()?.to_owned();
            Some((script_id, row.clone()))
        })
        .collect()
}

fn script_role(source: Option<&str>, target_order: u64) -> &'static str {
    source.map_or("source_unavailable", |source| {
        if source.starts_with("(function (setGetTraceActive, source) {") {
            "yatouv8_eval_wrapper"
        } else if target_order == 0 {
            "entry_eval"
        } else {
            "nested_dynamic_script"
        }
    })
}

fn missed_range_snippets(source: Option<&str>, coverage: Option<&Value>) -> Vec<Value> {
    let Some(source) = source else {
        return Vec::new();
    };
    coverage
        .and_then(|value| value.get("functions"))
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .flat_map(missed_function_ranges)
        .take(1_024)
        .map(|(function_name, range)| range_snippet(source, &function_name, range))
        .collect()
}

fn missed_function_ranges(function: &Value) -> Vec<(String, &Value)> {
    let function_name = function
        .get("functionName")
        .and_then(Value::as_str)
        .unwrap_or_default()
        .to_owned();
    function
        .get("ranges")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter(|range| {
            range
                .get("count")
                .and_then(Value::as_u64)
                .unwrap_or_default()
                == 0
        })
        .map(|range| (function_name.clone(), range))
        .collect()
}

fn range_snippet(source: &str, function_name: &str, range: &Value) -> Value {
    let start = range
        .get("startOffset")
        .and_then(Value::as_u64)
        .unwrap_or_default();
    let end = range
        .get("endOffset")
        .and_then(Value::as_u64)
        .unwrap_or(start);
    let (context_start, context_end, context) = source_context(source, start, end, 180);
    json!({
        "function_name": function_name,
        "start_offset": start,
        "end_offset": end,
        "context_start_offset": context_start,
        "context_end_offset": context_end,
        "context": context,
    })
}

fn summarize_scripts(scripts: &[Value], omitted: u64) -> (Value, BTreeSet<&str>) {
    let mut function_count = 0_u64;
    let mut range_count = 0_u64;
    let mut hit_ranges = 0_u64;
    let mut missed_ranges = 0_u64;
    let mut source_bytes = 0_u64;
    let mut script_ids = BTreeSet::new();
    for script in scripts {
        if let Some(script_id) = script.get("script_id").and_then(Value::as_str) {
            script_ids.insert(script_id);
        }
        source_bytes = source_bytes.saturating_add(
            script
                .get("source_length_bytes")
                .and_then(Value::as_u64)
                .unwrap_or_default(),
        );
        let functions = script
            .get("functions")
            .and_then(Value::as_array)
            .map(Vec::as_slice)
            .unwrap_or_default();
        function_count = function_count.saturating_add(functions.len() as u64);
        for range in functions.iter().flat_map(function_ranges) {
            range_count = range_count.saturating_add(1);
            if range
                .get("count")
                .and_then(Value::as_u64)
                .unwrap_or_default()
                == 0
            {
                missed_ranges = missed_ranges.saturating_add(1);
            } else {
                hit_ranges = hit_ranges.saturating_add(1);
            }
        }
    }
    (
        json!({
            "scripts": scripts.len(),
            "omitted_scripts": omitted,
            "source_bytes": source_bytes,
            "functions": function_count,
            "ranges": range_count,
            "hit_ranges": hit_ranges,
            "missed_ranges": missed_ranges,
        }),
        script_ids,
    )
}

fn function_ranges(function: &Value) -> impl Iterator<Item = &Value> {
    function
        .get("ranges")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
}

fn utf16_offset_to_byte(source: &str, offset: u64) -> usize {
    let target = usize::try_from(offset).unwrap_or(usize::MAX);
    let mut utf16_offset = 0_usize;
    for (byte_offset, character) in source.char_indices() {
        if utf16_offset >= target {
            return byte_offset;
        }
        utf16_offset = utf16_offset.saturating_add(character.len_utf16());
        if utf16_offset > target {
            return byte_offset;
        }
    }
    source.len()
}

fn source_context(source: &str, start: u64, end: u64, radius: usize) -> (u64, u64, String) {
    let start_byte = utf16_offset_to_byte(source, start);
    let end_byte = utf16_offset_to_byte(source, end).max(start_byte);
    let context_start_byte = source[..start_byte]
        .char_indices()
        .rev()
        .nth(radius)
        .map_or(0, |(offset, _)| offset);
    let context_end_byte = source[end_byte..]
        .char_indices()
        .nth(radius)
        .map_or(source.len(), |(offset, _)| end_byte.saturating_add(offset));
    let context_start_offset = source[..context_start_byte].encode_utf16().count() as u64;
    let context_end_offset = source[..context_end_byte].encode_utf16().count() as u64;
    (
        context_start_offset,
        context_end_offset,
        source[context_start_byte..context_end_byte].to_owned(),
    )
}

impl Drop for ExecutionInspector {
    fn drop(&mut self) {
        // Keep the inspector field observably used and make the ownership
        // relationship explicit; field order performs the actual safe teardown.
        let _ = &self.inspector;
    }
}
