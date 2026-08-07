//! Versioned data contracts shared by the collector, harness, generator, and runtime.

use std::fmt;

use serde::{Deserialize, Deserializer, Serialize};
use thiserror::Error;

mod evidence;
mod run;
mod snapshot;
mod trace;

pub use evidence::{EvidenceArtifact, EvidenceRef};
pub use run::{CollectorMetadata, RunManifest, RunStatus};
pub use snapshot::{
    BrowserMetadata, CallableSnapshot, CaptureMode, ChromeEnvironment, ChromeSnapshot,
    ClockProfile, ClockProfileSummary, ClockSample, DescriptorKind, HostMetadata,
    NavigatorSnapshot, PollutionCheck, PropertyDescriptorSnapshot, PropertyKeyKind,
    PropertyKeySnapshot, ScreenSnapshot, SurfaceSnapshot,
};
pub use trace::{
    ApiLedgerEvent, ApiOperation, ApiOutcome, CallSite, EvalOutcome, ExceptionSummary, JsValueKind,
    ReplayEvent, TraceEvent, TraceEventBody, TraceFooter, TraceHeader, TraceRecord, TraceSource,
    TraceStream, TraceStreamError, ValueSummary,
};

/// Current schema version for newly emitted substrate records.
pub const CURRENT_SCHEMA_VERSION: SchemaVersion = SchemaVersion(1);

/// Monotonically increasing schema version.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(transparent)]
pub struct SchemaVersion(pub u32);

/// Stable identifier for a normative Chrome baseline.
#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(transparent)]
pub struct BaselineId(String);

impl BaselineId {
    /// Constructs a validated baseline identifier.
    ///
    /// # Errors
    ///
    /// Returns [`SchemaError::InvalidBaselineId`] when the value is empty or
    /// contains characters outside ASCII alphanumeric, `-`, `_`, and `.`.
    pub fn parse(value: impl Into<String>) -> Result<Self, SchemaError> {
        let value = value.into();
        let valid = !value.is_empty()
            && value
                .bytes()
                .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_' | b'.'));
        if !valid {
            return Err(SchemaError::InvalidBaselineId(value));
        }
        Ok(Self(value))
    }

    /// Returns the validated identifier.
    #[must_use]
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl<'de> Deserialize<'de> for BaselineId {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let value = String::deserialize(deserializer)?;
        Self::parse(value).map_err(serde::de::Error::custom)
    }
}

impl fmt::Display for BaselineId {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        self.0.fmt(formatter)
    }
}

/// Validation errors emitted by schema constructors.
#[derive(Debug, Error, Eq, PartialEq)]
pub enum SchemaError {
    /// Baseline identifier contains unsupported characters.
    #[error("invalid baseline id: {0}")]
    InvalidBaselineId(String),
    /// Evidence digest is not 64 lowercase hexadecimal characters.
    #[error("invalid SHA-256 digest: {0}")]
    InvalidSha256(String),
    /// Evidence media type is empty or contains control characters.
    #[error("invalid evidence media type: {0}")]
    InvalidMediaType(String),
    /// Snapshot schema version is not supported by this build.
    #[error("unsupported schema version: {0}")]
    UnsupportedSchemaVersion(u32),
    /// A surface descriptor list does not match its own-key list.
    #[error("surface descriptor mismatch: {0}")]
    SurfaceDescriptorMismatch(String),
    /// Collector mutated the JavaScript global surface while probing it.
    #[error("collector pollution detected")]
    CollectorPollution,
    /// Clock profile counts do not match the captured sample array.
    #[error("clock profile sample count mismatch")]
    ClockProfileSampleCount,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn accepts_versioned_baseline_id() {
        let id = BaselineId::parse("win11-chrome150-v1").expect("valid baseline id");
        assert_eq!(id.as_str(), "win11-chrome150-v1");
    }

    #[test]
    fn rejects_path_like_baseline_id() {
        let error = BaselineId::parse("../chrome150").expect_err("path-like id must fail");
        assert!(matches!(error, SchemaError::InvalidBaselineId(_)));
    }

    #[test]
    fn rejects_invalid_baseline_id_during_deserialization() {
        let error = serde_json::from_str::<BaselineId>(r#""../chrome150""#)
            .expect_err("deserialization must preserve the identifier invariant");
        assert!(error.to_string().contains("invalid baseline id"));
    }
}
