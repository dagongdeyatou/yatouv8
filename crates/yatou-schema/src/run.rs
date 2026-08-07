//! Collector run manifests.

use serde::{Deserialize, Serialize};

use crate::{BaselineId, EvidenceArtifact, SchemaError, SchemaVersion};

/// Metadata identifying the collector and exact probe source.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct CollectorMetadata {
    /// Collector implementation name.
    pub name: String,
    /// Collector implementation version.
    pub version: String,
    /// SHA-256 digest of the JavaScript probe source.
    pub probe_sha256: String,
    /// Chrome flags with ephemeral paths removed.
    pub command_line_flags: Vec<String>,
}

/// Terminal status of a collector run.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum RunStatus {
    /// Every required artifact was captured and validated.
    Complete,
    /// The run stopped before producing a valid baseline.
    Failed,
}

/// Lineage manifest for one Chrome collection run.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct RunManifest {
    /// Data-contract version.
    pub schema_version: SchemaVersion,
    /// Normative baseline family identifier.
    pub baseline_id: BaselineId,
    /// Unique identifier for this concrete capture.
    pub run_id: String,
    /// UTC RFC 3339 start timestamp.
    pub started_at: String,
    /// UTC RFC 3339 finish timestamp.
    pub finished_at: String,
    /// Run result.
    pub status: RunStatus,
    /// Whether all launched Chrome processes and the temporary profile were removed.
    pub cleanup_verified: bool,
    /// Captured evidence artifacts and their direct parents.
    pub artifacts: Vec<EvidenceArtifact>,
}

impl RunManifest {
    /// Validates artifact content addresses.
    ///
    /// # Errors
    ///
    /// Returns [`SchemaError`] when an artifact reference is malformed.
    pub fn validate(&self) -> Result<(), SchemaError> {
        for artifact in &self.artifacts {
            artifact.evidence.validate()?;
        }
        Ok(())
    }
}
