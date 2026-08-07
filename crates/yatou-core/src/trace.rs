//! Runtime recorder and strict offline replay cursor.

use thiserror::Error;
use yatou_schema::{
    ApiLedgerEvent, ReplayEvent, TraceEvent, TraceEventBody, TraceFooter, TraceHeader, TraceStream,
    TraceStreamError,
};

/// Runtime failures while recording or consuming a trace.
#[derive(Debug, Error, PartialEq)]
pub enum TraceRuntimeError {
    /// A newly recorded logical timestamp moved backwards.
    #[error("trace logical time regressed from {previous} to {actual}")]
    LogicalTimeRegression {
        /// Previous event timestamp.
        previous: u64,
        /// Rejected timestamp.
        actual: u64,
    },
    /// Causal parent does not precede the event being recorded.
    #[error("trace parent {parent} does not precede event {event}")]
    InvalidParent {
        /// Rejected parent sequence.
        parent: u64,
        /// Child sequence being appended.
        event: u64,
    },
    /// Completed trace violated its data contract.
    #[error(transparent)]
    InvalidTrace(#[from] TraceStreamError),
    /// Replay reached end-of-stream before the requested boundary.
    #[error("replay exhausted while expecting {expected}")]
    ReplayExhausted {
        /// Human-readable expected boundary.
        expected: String,
    },
    /// Next recorded L0 boundary did not match the runtime request.
    #[error("replay mismatch at L0 sequence {seq}: expected {expected}; recorded {recorded}")]
    ReplayMismatch {
        /// Original trace sequence number.
        seq: u64,
        /// Requested boundary.
        expected: String,
        /// Recorded boundary.
        recorded: String,
    },
    /// Replay stopped before consuming every L0 boundary.
    #[error("replay has {remaining} unconsumed L0 events")]
    ReplayIncomplete {
        /// Number of remaining L0 events.
        remaining: usize,
    },
}

/// Append-only recorder shared by host-boundary and generated-surface hooks.
#[derive(Clone, Debug)]
pub struct TraceRecorder {
    header: TraceHeader,
    events: Vec<TraceEvent>,
    last_logical_time_ns: Option<u64>,
}

impl TraceRecorder {
    /// Create an empty recorder for a previously validated baseline identifier.
    #[must_use]
    pub const fn new(header: TraceHeader) -> Self {
        Self {
            header,
            events: Vec::new(),
            last_logical_time_ns: None,
        }
    }

    /// Append an L0 replay-critical event.
    ///
    /// # Errors
    ///
    /// Returns [`TraceRuntimeError`] when logical time regresses or the causal
    /// parent does not precede the event.
    pub fn record_l0(
        &mut self,
        logical_time_ns: u64,
        parent_seq: Option<u64>,
        event: ReplayEvent,
    ) -> Result<u64, TraceRuntimeError> {
        self.push(logical_time_ns, parent_seq, TraceEventBody::L0(event))
    }

    /// Append an L1 get/set/call/construct ledger entry.
    ///
    /// This is the stable insertion point for generated browser-surface
    /// trampolines. It intentionally records no full stack or live object.
    ///
    /// # Errors
    ///
    /// Returns [`TraceRuntimeError`] when ordering invariants fail.
    pub fn record_l1(
        &mut self,
        logical_time_ns: u64,
        parent_seq: Option<u64>,
        event: ApiLedgerEvent,
    ) -> Result<u64, TraceRuntimeError> {
        self.push(logical_time_ns, parent_seq, TraceEventBody::L1(event))
    }

    /// Finalize and validate a complete stream with footer counts.
    ///
    /// # Errors
    ///
    /// Returns [`TraceRuntimeError::InvalidTrace`] for invalid digests or L0
    /// lifecycle pairs.
    pub fn finish(self) -> Result<TraceStream, TraceRuntimeError> {
        let l0_count = self
            .events
            .iter()
            .filter(|event| matches!(event.body, TraceEventBody::L0(_)))
            .count();
        let l1_count = self.events.len() - l0_count;
        let stream = TraceStream {
            header: self.header,
            footer: TraceFooter {
                event_count: u64::try_from(self.events.len()).unwrap_or(u64::MAX),
                l0_count: u64::try_from(l0_count).unwrap_or(u64::MAX),
                l1_count: u64::try_from(l1_count).unwrap_or(u64::MAX),
                last_seq: self.events.last().map(|event| event.seq),
                complete: true,
            },
            events: self.events,
        };
        stream.validate()?;
        Ok(stream)
    }

    fn push(
        &mut self,
        logical_time_ns: u64,
        parent_seq: Option<u64>,
        body: TraceEventBody,
    ) -> Result<u64, TraceRuntimeError> {
        if let Some(previous) = self.last_logical_time_ns
            && logical_time_ns < previous
        {
            return Err(TraceRuntimeError::LogicalTimeRegression {
                previous,
                actual: logical_time_ns,
            });
        }
        let seq = u64::try_from(self.events.len()).unwrap_or(u64::MAX);
        if let Some(parent) = parent_seq
            && parent >= seq
        {
            return Err(TraceRuntimeError::InvalidParent { parent, event: seq });
        }
        self.events.push(TraceEvent {
            seq,
            logical_time_ns,
            parent_seq,
            body,
        });
        self.last_logical_time_ns = Some(logical_time_ns);
        Ok(seq)
    }
}

/// Resource response returned exclusively from a recorded L0 trace.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ReplayedResource {
    /// Recorded status code.
    pub status: u16,
    /// Recorded canonical headers.
    pub headers: std::collections::BTreeMap<String, String>,
    /// Recorded base64 body.
    pub body_base64: String,
    /// Recorded decoded-body digest.
    pub body_sha256: String,
}

/// Strict cursor over L0 events. It has no network adapter and cannot fall back online.
#[derive(Clone, Debug)]
pub struct ReplayTape {
    events: Vec<(u64, ReplayEvent)>,
    cursor: usize,
}

impl ReplayTape {
    /// Build a replay cursor from a validated stream while retaining L0 order.
    ///
    /// # Errors
    ///
    /// Returns [`TraceRuntimeError::InvalidTrace`] if the source stream is invalid.
    pub fn new(stream: &TraceStream) -> Result<Self, TraceRuntimeError> {
        stream.validate()?;
        let events = stream
            .events
            .iter()
            .filter_map(|event| match &event.body {
                TraceEventBody::L0(entry) => Some((event.seq, entry.clone())),
                TraceEventBody::L1(_) => None,
            })
            .collect();
        Ok(Self { events, cursor: 0 })
    }

    /// Consume an exact L0 boundary event.
    ///
    /// # Errors
    ///
    /// Returns a mismatch or exhaustion error rather than consulting real host services.
    pub fn expect_event(&mut self, expected: &ReplayEvent) -> Result<u64, TraceRuntimeError> {
        let (seq, recorded) = self.next(format!("{expected:?}"))?;
        if recorded != *expected {
            return Err(TraceRuntimeError::ReplayMismatch {
                seq,
                expected: format!("{expected:?}"),
                recorded: format!("{recorded:?}"),
            });
        }
        Ok(seq)
    }

    /// Consume a request and return its immediately recorded response.
    ///
    /// # Errors
    ///
    /// Returns a strict replay error for any method, URL, ordering, or request-id mismatch.
    /// No live network fallback exists on this type.
    pub fn resource(
        &mut self,
        method: &str,
        url: &str,
    ) -> Result<ReplayedResource, TraceRuntimeError> {
        let expected = format!("resource request {method} {url}");
        let (request_seq, request) = self.next(expected.clone())?;
        let request_id = match request {
            ReplayEvent::ResourceRequest {
                request_id,
                method: recorded_method,
                url: recorded_url,
            } if recorded_method == method && recorded_url == url => request_id,
            recorded => {
                return Err(TraceRuntimeError::ReplayMismatch {
                    seq: request_seq,
                    expected,
                    recorded: format!("{recorded:?}"),
                });
            }
        };
        let response_expected = format!("resource response {request_id}");
        let (response_seq, response) = self.next(response_expected.clone())?;
        match response {
            ReplayEvent::ResourceResponse {
                request_id: response_id,
                status,
                headers,
                body_base64,
                body_sha256,
            } if response_id == request_id => Ok(ReplayedResource {
                status,
                headers,
                body_base64,
                body_sha256,
            }),
            recorded => Err(TraceRuntimeError::ReplayMismatch {
                seq: response_seq,
                expected: response_expected,
                recorded: format!("{recorded:?}"),
            }),
        }
    }

    /// Verify that every replay-critical event was consumed.
    ///
    /// # Errors
    ///
    /// Returns [`TraceRuntimeError::ReplayIncomplete`] when boundaries remain.
    pub fn finish(self) -> Result<(), TraceRuntimeError> {
        let remaining = self.events.len().saturating_sub(self.cursor);
        if remaining == 0 {
            Ok(())
        } else {
            Err(TraceRuntimeError::ReplayIncomplete { remaining })
        }
    }

    /// Number of L0 events not yet consumed.
    #[must_use]
    pub fn remaining(&self) -> usize {
        self.events.len().saturating_sub(self.cursor)
    }

    fn next(&mut self, expected: String) -> Result<(u64, ReplayEvent), TraceRuntimeError> {
        let (seq, event) = self
            .events
            .get(self.cursor)
            .cloned()
            .ok_or(TraceRuntimeError::ReplayExhausted { expected })?;
        self.cursor += 1;
        Ok((seq, event))
    }
}

#[cfg(test)]
mod tests {
    use std::collections::BTreeMap;

    use yatou_schema::{
        ApiOperation, ApiOutcome, BaselineId, CURRENT_SCHEMA_VERSION, EvalOutcome, JsValueKind,
        TraceSource, ValueSummary,
    };

    use super::*;

    fn header() -> TraceHeader {
        TraceHeader {
            schema_version: CURRENT_SCHEMA_VERSION,
            trace_id: "runtime-test-v1".to_owned(),
            baseline_id: BaselineId::parse("chrome150").expect("baseline"),
            source: TraceSource::Fixture,
            created_at: "2026-08-07T00:00:00Z".to_owned(),
            producer: "yatou-core-test".to_owned(),
        }
    }

    #[test]
    fn records_interleaved_l0_l1_and_replays_offline() {
        let mut recorder = TraceRecorder::new(header());
        let eval_seq = recorder
            .record_l0(
                0,
                None,
                ReplayEvent::EvalStart {
                    eval_id: "eval-1".to_owned(),
                    source_sha256: "a".repeat(64),
                },
            )
            .expect("eval start");
        recorder
            .record_l1(
                1,
                Some(eval_seq),
                ApiLedgerEvent {
                    operation: ApiOperation::Get,
                    target: "Navigator.prototype".to_owned(),
                    member: Some("userAgent".to_owned()),
                    arguments: vec![],
                    outcome: ApiOutcome::Return {
                        value: ValueSummary {
                            kind: JsValueKind::String,
                            preview: Some("Chrome/150".to_owned()),
                            sha256: None,
                        },
                    },
                    call_site: None,
                },
            )
            .expect("ledger");
        recorder
            .record_l0(
                2,
                Some(eval_seq),
                ReplayEvent::ResourceRequest {
                    request_id: "request-1".to_owned(),
                    method: "GET".to_owned(),
                    url: "https://fixture.invalid/vm.js".to_owned(),
                },
            )
            .expect("request");
        recorder
            .record_l0(
                3,
                Some(eval_seq),
                ReplayEvent::ResourceResponse {
                    request_id: "request-1".to_owned(),
                    status: 200,
                    headers: BTreeMap::new(),
                    body_base64: "NDI=".to_owned(),
                    body_sha256: "b".repeat(64),
                },
            )
            .expect("response");
        recorder
            .record_l0(
                4,
                Some(eval_seq),
                ReplayEvent::EvalEnd {
                    eval_id: "eval-1".to_owned(),
                    outcome: EvalOutcome::Return,
                },
            )
            .expect("eval end");
        let stream = recorder.finish().expect("trace");

        let mut replay = ReplayTape::new(&stream).expect("replay tape");
        replay
            .expect_event(&ReplayEvent::EvalStart {
                eval_id: "eval-1".to_owned(),
                source_sha256: "a".repeat(64),
            })
            .expect("start");
        assert_eq!(
            replay
                .resource("GET", "https://fixture.invalid/vm.js")
                .expect("resource")
                .status,
            200
        );
        replay
            .expect_event(&ReplayEvent::EvalEnd {
                eval_id: "eval-1".to_owned(),
                outcome: EvalOutcome::Return,
            })
            .expect("end");
        replay.finish().expect("fully consumed");
    }

    #[test]
    fn resource_miss_fails_without_fallback() {
        let mut recorder = TraceRecorder::new(header());
        recorder
            .record_l0(
                0,
                None,
                ReplayEvent::ResourceRequest {
                    request_id: "request-1".to_owned(),
                    method: "GET".to_owned(),
                    url: "https://fixture.invalid/only.js".to_owned(),
                },
            )
            .expect("request");
        recorder
            .record_l0(
                1,
                Some(0),
                ReplayEvent::ResourceResponse {
                    request_id: "request-1".to_owned(),
                    status: 200,
                    headers: BTreeMap::new(),
                    body_base64: String::new(),
                    body_sha256: "c".repeat(64),
                },
            )
            .expect("response");
        let stream = recorder.finish().expect("trace");
        let mut replay = ReplayTape::new(&stream).expect("replay tape");
        assert!(matches!(
            replay.resource("GET", "https://fixture.invalid/missing.js"),
            Err(TraceRuntimeError::ReplayMismatch { .. })
        ));
    }
}
