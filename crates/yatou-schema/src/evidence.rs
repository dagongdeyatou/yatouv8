//! Content-addressed evidence references and lineage edges.

use serde::{Deserialize, Serialize};

use crate::SchemaError;

/// Content-addressed reference to raw or derived evidence.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct EvidenceRef {
    /// SHA-256 digest in lowercase hexadecimal form.
    pub sha256: String,
    /// Logical media type, for example `application/x-ndjson`.
    pub media_type: String,
}

impl EvidenceRef {
    /// Constructs and validates an evidence reference.
    ///
    /// # Errors
    ///
    /// Returns [`SchemaError`] for malformed digests or media types.
    pub fn new(
        sha256: impl Into<String>,
        media_type: impl Into<String>,
    ) -> Result<Self, SchemaError> {
        let reference = Self {
            sha256: sha256.into(),
            media_type: media_type.into(),
        };
        reference.validate()?;
        Ok(reference)
    }

    /// Validates the digest and media type.
    ///
    /// # Errors
    ///
    /// Returns [`SchemaError`] when either field violates the evidence contract.
    pub fn validate(&self) -> Result<(), SchemaError> {
        let valid_hash = self.sha256.len() == 64
            && self
                .sha256
                .bytes()
                .all(|byte| byte.is_ascii_digit() || matches!(byte, b'a'..=b'f'));
        if !valid_hash {
            return Err(SchemaError::InvalidSha256(self.sha256.clone()));
        }
        let valid_media_type = !self.media_type.is_empty()
            && self
                .media_type
                .chars()
                .all(|character| !character.is_control());
        if !valid_media_type {
            return Err(SchemaError::InvalidMediaType(self.media_type.clone()));
        }
        Ok(())
    }
}

/// An artifact in the evidence graph.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct EvidenceArtifact {
    /// Stable logical name within one run manifest.
    pub logical_name: String,
    /// Relative path inside the local evidence store.
    pub relative_path: String,
    /// Artifact byte length.
    pub size_bytes: u64,
    /// Content address and media type.
    pub evidence: EvidenceRef,
    /// Logical names of direct parent artifacts.
    #[serde(default)]
    pub parents: Vec<String>,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn accepts_lowercase_sha256() {
        let digest = "a".repeat(64);
        EvidenceRef::new(digest, "application/json").expect("valid evidence reference");
    }

    #[test]
    fn rejects_uppercase_sha256() {
        let error = EvidenceRef::new("A".repeat(64), "application/json")
            .expect_err("uppercase digest must fail");
        assert!(matches!(error, SchemaError::InvalidSha256(_)));
    }
}
