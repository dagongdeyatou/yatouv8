//! Differential conformance and causal blocker ranking primitives.

use serde::{Deserialize, Serialize};
use yatou_schema::TraceStream;

/// High-level divergence classes ordered from substrate failure to coverage debt.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum DivergenceClass {
    /// Runtime or parser could not start the target.
    FatalRuntime,
    /// Required browser surface is missing.
    MissingSurface,
    /// Descriptor, prototype, or receiver check differs.
    Structural,
    /// Return value, exception, or state transition differs.
    Behavioral,
    /// Event-loop or asynchronous ordering differs.
    Scheduling,
    /// Timing distribution differs from the accepted envelope.
    Timing,
    /// Untouched surface lacks coverage but did not block this trace.
    Coverage,
}

/// Inputs to the first deterministic blocker score.
#[derive(Clone, Copy, Debug, Deserialize, PartialEq, Serialize)]
pub struct BlockerFactors {
    /// Severity on an implementation-defined positive scale.
    pub severity: f64,
    /// Earlier causal divergences receive larger values.
    pub causal_earliness: f64,
    /// Number or weight of independent reproductions.
    pub recurrence: f64,
    /// Number or weight of downstream failures explained by the blocker.
    pub dependency_fanout: f64,
}

impl BlockerFactors {
    /// Computes the agreed multiplicative causal score.
    #[must_use]
    pub fn score(self) -> f64 {
        self.severity * self.causal_earliness * self.recurrence * self.dependency_fanout
    }
}

/// Allowances applied while comparing Chrome and yatouv8 traces.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct TraceDiffAllowance {
    /// Maximum logical-time difference before a timing divergence is emitted.
    pub logical_time_tolerance_ns: u64,
    /// Ignore the low-overhead L1 source location while comparing API events.
    pub ignore_l1_call_site: bool,
}

impl Default for TraceDiffAllowance {
    fn default() -> Self {
        Self {
            logical_time_tolerance_ns: 1_000_000,
            ignore_l1_call_site: true,
        }
    }
}

/// One observed difference between the Chrome oracle and yatouv8 trace.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct TraceDivergence {
    /// Stable report-local divergence index.
    pub index: usize,
    /// Event position at which comparison diverged.
    pub event_position: usize,
    /// Chrome sequence number, when an oracle event exists.
    pub chrome_seq: Option<u64>,
    /// yatouv8 sequence number, when a runtime event exists.
    pub yatou_seq: Option<u64>,
    /// Semantic divergence class.
    pub class: DivergenceClass,
    /// Compared field or event key.
    pub field: String,
    /// Bounded Chrome representation.
    pub expected: String,
    /// Bounded yatouv8 representation.
    pub actual: String,
    /// Earliest divergence that causally dominates this one.
    pub causal_root: usize,
}

/// Ranked root-cause candidate derived from one divergence.
#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
pub struct RankedBlocker {
    /// Divergence represented by this blocker.
    pub divergence_index: usize,
    /// Stable signature used to group recurrences.
    pub signature: String,
    /// Ranking factors retained for auditability.
    pub factors: BlockerFactors,
    /// Multiplicative causal score.
    pub score: f64,
    /// Number of divergences causally explained by this blocker.
    pub explained_divergences: usize,
}

/// Complete deterministic trace-diff and blocker-ranking report.
#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
pub struct TraceDiffReport {
    /// Number of exactly matching leading events.
    pub matching_prefix_events: usize,
    /// Ordered divergences.
    pub divergences: Vec<TraceDivergence>,
    /// Candidates sorted by descending score and then causal position.
    pub blockers: Vec<RankedBlocker>,
    /// True only when no divergence remains.
    pub conformant: bool,
}

/// Compare two validated trace streams and rank the earliest causal blockers.
///
/// Chrome is always the first argument and therefore the expected oracle.
///
#[must_use]
pub fn compare_traces(
    chrome: &TraceStream,
    yatou: &TraceStream,
    allowance: TraceDiffAllowance,
) -> TraceDiffReport {
    let max_events = chrome.events.len().max(yatou.events.len());
    let mut divergences = Vec::new();
    let mut matching_prefix_events = 0;
    let mut prefix_open = true;

    for position in 0..max_events {
        let expected = chrome.events.get(position);
        let actual = yatou.events.get(position);
        let matched = compare_position(&mut divergences, position, expected, actual, allowance);
        if prefix_open && matched {
            matching_prefix_events += 1;
        } else {
            prefix_open = false;
        }
    }

    let blockers = rank_blockers(&divergences, max_events);
    TraceDiffReport {
        matching_prefix_events,
        conformant: divergences.is_empty(),
        divergences,
        blockers,
    }
}

fn compare_position(
    divergences: &mut Vec<TraceDivergence>,
    position: usize,
    expected: Option<&yatou_schema::TraceEvent>,
    actual: Option<&yatou_schema::TraceEvent>,
    allowance: TraceDiffAllowance,
) -> bool {
    match (expected, actual) {
        (Some(expected), Some(actual)) => {
            compare_event_pair(divergences, position, expected, actual, allowance)
        }
        (Some(expected), None) => {
            push_divergence(
                divergences,
                position,
                Some(expected.seq),
                None,
                DivergenceDetail {
                    class: classify_missing(&expected.body),
                    field: "missing_event",
                    expected: event_key(&expected.body),
                    actual: "<missing>".to_owned(),
                },
            );
            false
        }
        (None, Some(actual)) => {
            push_divergence(
                divergences,
                position,
                None,
                Some(actual.seq),
                DivergenceDetail {
                    class: DivergenceClass::Structural,
                    field: "unexpected_event",
                    expected: "<none>".to_owned(),
                    actual: event_key(&actual.body),
                },
            );
            false
        }
        (None, None) => true,
    }
}

fn compare_event_pair(
    divergences: &mut Vec<TraceDivergence>,
    position: usize,
    expected: &yatou_schema::TraceEvent,
    actual: &yatou_schema::TraceEvent,
    allowance: TraceDiffAllowance,
) -> bool {
    let expected_key = event_key(&expected.body);
    let actual_key = event_key(&actual.body);
    if expected_key != actual_key {
        push_divergence(
            divergences,
            position,
            Some(expected.seq),
            Some(actual.seq),
            DivergenceDetail {
                class: classify_key_mismatch(&expected.body, &actual.body),
                field: "event_key",
                expected: expected_key,
                actual: actual_key,
            },
        );
        return false;
    }

    let mut matched = true;
    let expected_body = comparable_body(&expected.body, allowance);
    let actual_body = comparable_body(&actual.body, allowance);
    if expected_body != actual_body {
        push_divergence(
            divergences,
            position,
            Some(expected.seq),
            Some(actual.seq),
            DivergenceDetail {
                class: classify_body_mismatch(&expected.body),
                field: "event_body",
                expected: expected_body,
                actual: actual_body,
            },
        );
        matched = false;
    }
    if expected.logical_time_ns.abs_diff(actual.logical_time_ns)
        > allowance.logical_time_tolerance_ns
    {
        push_divergence(
            divergences,
            position,
            Some(expected.seq),
            Some(actual.seq),
            DivergenceDetail {
                class: DivergenceClass::Timing,
                field: "logical_time_ns",
                expected: expected.logical_time_ns.to_string(),
                actual: actual.logical_time_ns.to_string(),
            },
        );
        matched = false;
    }
    matched
}

struct DivergenceDetail {
    class: DivergenceClass,
    field: &'static str,
    expected: String,
    actual: String,
}

fn push_divergence(
    divergences: &mut Vec<TraceDivergence>,
    event_position: usize,
    chrome_seq: Option<u64>,
    yatou_seq: Option<u64>,
    detail: DivergenceDetail,
) {
    let index = divergences.len();
    divergences.push(TraceDivergence {
        index,
        event_position,
        chrome_seq,
        yatou_seq,
        class: detail.class,
        field: detail.field.to_owned(),
        expected: bounded(detail.expected),
        actual: bounded(detail.actual),
        causal_root: 0,
    });
}

fn rank_blockers(divergences: &[TraceDivergence], event_count: usize) -> Vec<RankedBlocker> {
    if divergences.is_empty() {
        return Vec::new();
    }
    let mut counts = std::collections::BTreeMap::<String, usize>::new();
    for divergence in divergences {
        *counts.entry(divergence_signature(divergence)).or_default() += 1;
    }
    let root_index = divergences[0].index;
    let mut blockers = divergences
        .iter()
        .map(|divergence| {
            let signature = divergence_signature(divergence);
            let explained = if divergence.index == root_index {
                divergences.len()
            } else {
                1
            };
            let factors = BlockerFactors {
                severity: severity(divergence.class),
                causal_earliness: if event_count == 0 {
                    1.0
                } else {
                    usize_as_f64(event_count.saturating_sub(divergence.event_position))
                        / usize_as_f64(event_count)
                },
                recurrence: usize_as_f64(*counts.get(&signature).unwrap_or(&1)),
                dependency_fanout: usize_as_f64(explained),
            };
            RankedBlocker {
                divergence_index: divergence.index,
                signature,
                factors,
                score: factors.score(),
                explained_divergences: explained,
            }
        })
        .collect::<Vec<_>>();
    blockers.sort_by(|left, right| {
        right
            .score
            .total_cmp(&left.score)
            .then_with(|| left.divergence_index.cmp(&right.divergence_index))
    });
    blockers
}

fn usize_as_f64(value: usize) -> f64 {
    f64::from(u32::try_from(value).unwrap_or(u32::MAX))
}

fn divergence_signature(divergence: &TraceDivergence) -> String {
    format!(
        "{:?}:{}:{}",
        divergence.class, divergence.field, divergence.expected
    )
}

const fn severity(class: DivergenceClass) -> f64 {
    match class {
        DivergenceClass::FatalRuntime => 10.0,
        DivergenceClass::MissingSurface => 8.0,
        DivergenceClass::Structural => 7.0,
        DivergenceClass::Behavioral => 6.0,
        DivergenceClass::Scheduling => 5.0,
        DivergenceClass::Timing => 4.0,
        DivergenceClass::Coverage => 1.0,
    }
}

fn event_key(body: &yatou_schema::TraceEventBody) -> String {
    use yatou_schema::{ReplayEvent, TraceEventBody};
    match body {
        TraceEventBody::L0(event) => match event {
            ReplayEvent::EvalStart { eval_id, .. } => format!("l0:eval_start:{eval_id}"),
            ReplayEvent::EvalEnd { eval_id, .. } => format!("l0:eval_end:{eval_id}"),
            ReplayEvent::ResourceRequest { request_id, .. } => {
                format!("l0:resource_request:{request_id}")
            }
            ReplayEvent::ResourceResponse { request_id, .. } => {
                format!("l0:resource_response:{request_id}")
            }
            ReplayEvent::TimerSchedule { timer_id, .. } => {
                format!("l0:timer_schedule:{timer_id}")
            }
            ReplayEvent::TimerFire { timer_id } => format!("l0:timer_fire:{timer_id}"),
            ReplayEvent::Input { input_type, .. } => format!("l0:input:{input_type}"),
            ReplayEvent::Exception { exception } => format!("l0:exception:{}", exception.name),
            ReplayEvent::Checkpoint { name, .. } => format!("l0:checkpoint:{name}"),
        },
        TraceEventBody::L1(event) => format!(
            "l1:{:?}:{}:{}",
            event.operation,
            event.target,
            event.member.as_deref().unwrap_or("")
        ),
    }
}

fn comparable_body(body: &yatou_schema::TraceEventBody, allowance: TraceDiffAllowance) -> String {
    use yatou_schema::TraceEventBody;
    let mut body = body.clone();
    if allowance.ignore_l1_call_site
        && let TraceEventBody::L1(event) = &mut body
    {
        event.call_site = None;
    }
    serde_json::to_string(&body).unwrap_or_else(|_| "<serialization-error>".to_owned())
}

const fn classify_key_mismatch(
    expected: &yatou_schema::TraceEventBody,
    actual: &yatou_schema::TraceEventBody,
) -> DivergenceClass {
    use yatou_schema::TraceEventBody;
    match (expected, actual) {
        (TraceEventBody::L1(_), _) | (_, TraceEventBody::L1(_)) => DivergenceClass::MissingSurface,
        _ => DivergenceClass::Scheduling,
    }
}

const fn classify_body_mismatch(body: &yatou_schema::TraceEventBody) -> DivergenceClass {
    use yatou_schema::{ReplayEvent, TraceEventBody};
    match body {
        TraceEventBody::L0(ReplayEvent::TimerSchedule { .. } | ReplayEvent::TimerFire { .. }) => {
            DivergenceClass::Timing
        }
        _ => DivergenceClass::Behavioral,
    }
}

const fn classify_missing(body: &yatou_schema::TraceEventBody) -> DivergenceClass {
    use yatou_schema::TraceEventBody;
    match body {
        TraceEventBody::L1(_) => DivergenceClass::MissingSurface,
        TraceEventBody::L0(_) => DivergenceClass::Scheduling,
    }
}

fn bounded(value: String) -> String {
    const LIMIT: usize = 1024;
    if value.len() <= LIMIT {
        value
    } else {
        let mut boundary = LIMIT;
        while !value.is_char_boundary(boundary) {
            boundary -= 1;
        }
        format!("{}…", &value[..boundary])
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use yatou_schema::{
        ApiLedgerEvent, ApiOperation, ApiOutcome, BaselineId, CURRENT_SCHEMA_VERSION, EvalOutcome,
        JsValueKind, ReplayEvent, TraceEvent, TraceEventBody, TraceFooter, TraceHeader,
        TraceSource, ValueSummary,
    };

    fn fixture_stream(source: TraceSource) -> TraceStream {
        let value = ValueSummary {
            kind: JsValueKind::Number,
            preview: Some("1".to_owned()),
            sha256: None,
        };
        let events = vec![
            TraceEvent {
                seq: 0,
                logical_time_ns: 0,
                parent_seq: None,
                body: TraceEventBody::L0(ReplayEvent::EvalStart {
                    eval_id: "eval-1".to_owned(),
                    source_sha256: "a".repeat(64),
                }),
            },
            TraceEvent {
                seq: 1,
                logical_time_ns: 10,
                parent_seq: Some(0),
                body: TraceEventBody::L1(ApiLedgerEvent {
                    operation: ApiOperation::Call,
                    target: "Performance".to_owned(),
                    member: Some("now".to_owned()),
                    arguments: Vec::new(),
                    outcome: ApiOutcome::Return { value },
                    call_site: None,
                }),
            },
            TraceEvent {
                seq: 2,
                logical_time_ns: 20,
                parent_seq: Some(0),
                body: TraceEventBody::L0(ReplayEvent::Checkpoint {
                    name: "token-shape".to_owned(),
                    state_sha256: "b".repeat(64),
                }),
            },
            TraceEvent {
                seq: 3,
                logical_time_ns: 30,
                parent_seq: Some(0),
                body: TraceEventBody::L0(ReplayEvent::EvalEnd {
                    eval_id: "eval-1".to_owned(),
                    outcome: EvalOutcome::Return,
                }),
            },
        ];
        TraceStream {
            header: TraceHeader {
                schema_version: CURRENT_SCHEMA_VERSION,
                trace_id: "m4-fixture".to_owned(),
                baseline_id: BaselineId::parse("chrome150").expect("baseline"),
                source,
                created_at: "2026-08-07T00:00:00Z".to_owned(),
                producer: "yatou-harness-test".to_owned(),
            },
            events,
            footer: TraceFooter {
                event_count: 4,
                l0_count: 3,
                l1_count: 1,
                last_seq: Some(3),
                complete: true,
            },
        }
    }

    fn resequence(stream: &mut TraceStream) {
        for (index, event) in stream.events.iter_mut().enumerate() {
            event.seq = u64::try_from(index).expect("small fixture");
            event.parent_seq = None;
        }
        stream.footer.event_count = u64::try_from(stream.events.len()).expect("small fixture");
        stream.footer.l0_count = u64::try_from(
            stream
                .events
                .iter()
                .filter(|event| matches!(event.body, TraceEventBody::L0(_)))
                .count(),
        )
        .expect("small fixture");
        stream.footer.l1_count = stream.footer.event_count - stream.footer.l0_count;
        stream.footer.last_seq = stream.events.last().map(|event| event.seq);
    }

    #[test]
    fn causal_score_is_multiplicative() {
        let factors = BlockerFactors {
            severity: 4.0,
            causal_earliness: 3.0,
            recurrence: 2.0,
            dependency_fanout: 5.0,
        };
        assert!((factors.score() - 120.0).abs() < f64::EPSILON);
    }

    #[test]
    fn identical_traces_are_conformant() {
        let chrome = fixture_stream(TraceSource::Chrome);
        let yatou = fixture_stream(TraceSource::Yatouv8);
        let report = compare_traces(&chrome, &yatou, TraceDiffAllowance::default());
        assert!(report.conformant);
        assert_eq!(report.matching_prefix_events, 4);
        assert!(report.blockers.is_empty());
    }

    #[test]
    fn earliest_missing_l1_is_the_top_causal_blocker() {
        let chrome = fixture_stream(TraceSource::Chrome);
        let mut yatou = fixture_stream(TraceSource::Yatouv8);
        yatou.events.remove(1);
        resequence(&mut yatou);

        let report = compare_traces(&chrome, &yatou, TraceDiffAllowance::default());
        assert!(!report.conformant);
        assert_eq!(report.divergences[0].class, DivergenceClass::MissingSurface);
        assert_eq!(report.blockers[0].divergence_index, 0);
        assert_eq!(
            report.blockers[0].explained_divergences,
            report.divergences.len()
        );
    }

    #[test]
    fn checkpoint_digest_difference_is_behavioral() {
        let chrome = fixture_stream(TraceSource::Chrome);
        let mut yatou = fixture_stream(TraceSource::Yatouv8);
        if let TraceEventBody::L0(ReplayEvent::Checkpoint { state_sha256, .. }) =
            &mut yatou.events[2].body
        {
            *state_sha256 = "c".repeat(64);
        }

        let report = compare_traces(&chrome, &yatou, TraceDiffAllowance::default());
        assert_eq!(report.divergences.len(), 1);
        assert_eq!(report.divergences[0].class, DivergenceClass::Behavioral);
        assert_eq!(report.divergences[0].field, "event_body");
    }

    #[test]
    fn logical_time_allowance_is_enforced() {
        let chrome = fixture_stream(TraceSource::Chrome);
        let mut yatou = fixture_stream(TraceSource::Yatouv8);
        yatou.events[1].logical_time_ns += 5;

        let accepted = compare_traces(
            &chrome,
            &yatou,
            TraceDiffAllowance {
                logical_time_tolerance_ns: 5,
                ignore_l1_call_site: true,
            },
        );
        assert!(accepted.conformant);

        let rejected = compare_traces(
            &chrome,
            &yatou,
            TraceDiffAllowance {
                logical_time_tolerance_ns: 4,
                ignore_l1_call_site: true,
            },
        );
        assert_eq!(rejected.divergences[0].class, DivergenceClass::Timing);
    }
}
