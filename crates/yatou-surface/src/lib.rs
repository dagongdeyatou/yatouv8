//! Evidence-backed browser-surface manifest, generated descriptors, and L1 trampoline.

use std::collections::BTreeSet;

use serde::{Deserialize, Serialize};
use thiserror::Error;
use yatou_schema::{ApiOperation, ApiOutcome, EvidenceRef, ValueSummary};

/// Current Surface Manifest schema version.
pub const SURFACE_MANIFEST_VERSION: u32 = 1;

/// Placement of an interface member in the JavaScript object graph.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum MemberOwner {
    /// Property installed on the global object.
    Global,
    /// Property installed on a constructor.
    Constructor,
    /// Property installed on a prototype.
    Prototype,
    /// Property installed directly on each instance.
    Instance,
}

/// Kind of property key retained by the manifest.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ManifestKeyKind {
    /// Ordinary string key.
    String,
    /// Symbol key identified by display and optional registry name.
    Symbol,
}

/// Property key in exact Chrome own-key order.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct ManifestKey {
    /// String or symbol.
    pub kind: ManifestKeyKind,
    /// Stable human-readable representation.
    pub display: String,
    /// Symbol description when present.
    pub description: Option<String>,
    /// `Symbol.for` registry key when present.
    pub registry_key: Option<String>,
}

/// Data or accessor descriptor kind.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ManifestDescriptorKind {
    /// Value descriptor.
    Data,
    /// Getter/setter descriptor.
    Accessor,
}

/// Evidence-observed native callable metadata.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct CallableSpec {
    /// JavaScript function name.
    pub name: String,
    /// JavaScript function length.
    pub length: u32,
    /// Whether Chrome rendered a native-code-shaped source.
    pub native_like: bool,
}

/// One evidence-backed member declaration consumed by code generation.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct SurfaceMember {
    /// Exact property key.
    pub key: ManifestKey,
    /// Property owner.
    pub owner: MemberOwner,
    /// Data or accessor descriptor.
    pub descriptor_kind: ManifestDescriptorKind,
    /// Configurable flag observed in Chrome.
    pub configurable: bool,
    /// Enumerable flag observed in Chrome.
    pub enumerable: bool,
    /// Writable flag for data descriptors.
    pub writable: Option<bool>,
    /// Observed JavaScript value type for data descriptors.
    pub value_type: Option<String>,
    /// Callable metadata for data functions.
    pub callable: Option<CallableSpec>,
    /// Getter metadata for accessor descriptors.
    pub getter: Option<CallableSpec>,
    /// Setter metadata for accessor descriptors.
    pub setter: Option<CallableSpec>,
    /// Stable handler identifier consumed by the shared trampoline.
    pub handler_id: String,
    /// Evidence that justified this declaration.
    pub evidence_refs: Vec<EvidenceRef>,
}

impl SurfaceMember {
    /// Returns true when the declaration can be considered for code generation.
    #[must_use]
    pub fn has_evidence(&self) -> bool {
        !self.evidence_refs.is_empty()
    }
}

/// One object, constructor, or prototype captured from Chrome.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct SurfaceInterface {
    /// Stable JavaScript path, such as `Performance.prototype`.
    pub path: String,
    /// Prototype path observed by Chrome.
    pub prototype_path: Option<String>,
    /// Observed JavaScript value type.
    pub value_type: String,
    /// Exact own-key order used as a generator invariant.
    pub own_key_order: Vec<ManifestKey>,
    /// Members in the same order as `own_key_order`.
    pub members: Vec<SurfaceMember>,
}

/// Deterministic manifest derived from one accepted Chrome snapshot.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct SurfaceManifest {
    /// Manifest data-contract version.
    pub schema_version: u32,
    /// Accepted Chrome baseline identifier.
    pub baseline_id: String,
    /// Snapshot used as the direct parent evidence.
    pub source_snapshot: EvidenceRef,
    /// Interfaces in Chrome capture order.
    pub interfaces: Vec<SurfaceInterface>,
}

/// Surface Manifest validation error.
#[derive(Debug, Error, Eq, PartialEq)]
pub enum SurfaceManifestError {
    /// Manifest schema version is not supported.
    #[error("unsupported surface manifest version: {0}")]
    UnsupportedVersion(u32),
    /// Baseline identifier is missing.
    #[error("surface manifest baseline id is empty")]
    EmptyBaseline,
    /// An interface path occurs more than once.
    #[error("duplicate surface interface: {0}")]
    DuplicateInterface(String),
    /// Member order does not exactly match the interface key order.
    #[error("surface member order mismatch: {0}")]
    MemberOrderMismatch(String),
    /// A generated member has no parent evidence.
    #[error("surface member lacks evidence: {0}")]
    MissingEvidence(String),
    /// An evidence reference is malformed.
    #[error("invalid surface evidence: {0}")]
    InvalidEvidence(String),
    /// A handler identifier is empty.
    #[error("surface member has empty handler id: {0}")]
    EmptyHandler(String),
}

impl SurfaceManifest {
    /// Validate version, lineage, uniqueness, and exact member order.
    ///
    /// # Errors
    ///
    /// Returns [`SurfaceManifestError`] when generated bindings cannot safely use
    /// the manifest.
    pub fn validate(&self) -> Result<(), SurfaceManifestError> {
        if self.schema_version != SURFACE_MANIFEST_VERSION {
            return Err(SurfaceManifestError::UnsupportedVersion(
                self.schema_version,
            ));
        }
        if self.baseline_id.is_empty() {
            return Err(SurfaceManifestError::EmptyBaseline);
        }
        self.source_snapshot
            .validate()
            .map_err(|error| SurfaceManifestError::InvalidEvidence(error.to_string()))?;
        let mut paths = BTreeSet::new();
        for interface in &self.interfaces {
            if !paths.insert(interface.path.as_str()) {
                return Err(SurfaceManifestError::DuplicateInterface(
                    interface.path.clone(),
                ));
            }
            let member_keys = interface
                .members
                .iter()
                .map(|member| &member.key)
                .collect::<Vec<_>>();
            let own_keys = interface.own_key_order.iter().collect::<Vec<_>>();
            if member_keys != own_keys {
                return Err(SurfaceManifestError::MemberOrderMismatch(
                    interface.path.clone(),
                ));
            }
            for member in &interface.members {
                let path = format!("{}.{}", interface.path, member.key.display);
                if member.handler_id.is_empty() {
                    return Err(SurfaceManifestError::EmptyHandler(path));
                }
                if !member.has_evidence() {
                    return Err(SurfaceManifestError::MissingEvidence(path));
                }
                for evidence in &member.evidence_refs {
                    evidence.validate().map_err(|error| {
                        SurfaceManifestError::InvalidEvidence(error.to_string())
                    })?;
                }
            }
        }
        Ok(())
    }
}

/// Compact descriptor emitted as Rust by `surface-codegen`.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct GeneratedMemberSpec {
    /// Interface path.
    pub interface: &'static str,
    /// Property display name.
    pub key: &'static str,
    /// Descriptor kind.
    pub kind: ManifestDescriptorKind,
    /// Configurable flag.
    pub configurable: bool,
    /// Enumerable flag.
    pub enumerable: bool,
    /// Writable flag for data descriptors.
    pub writable: Option<bool>,
    /// Stable shared-trampoline handler ID.
    pub handler_id: &'static str,
}

/// Generated interface index into [`GENERATED_MEMBERS`].
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct GeneratedInterfaceSpec {
    /// Interface path.
    pub path: &'static str,
    /// Prototype path, if any.
    pub prototype_path: Option<&'static str>,
    /// Start index in [`GENERATED_MEMBERS`].
    pub member_start: usize,
    /// Number of generated members.
    pub member_len: usize,
}

/// Invocation passed from generated V8 glue to one shared semantic dispatcher.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SurfaceInvocation {
    /// Handler selected by generated glue.
    pub handler_id: String,
    /// Get, set, call, or construct.
    pub operation: ApiOperation,
    /// Stable receiver path.
    pub target: String,
    /// Optional member display name.
    pub member: Option<String>,
    /// Bounded argument summaries.
    pub arguments: Vec<ValueSummary>,
}

/// Handwritten semantics behind generated descriptors.
pub trait SurfaceHandler {
    /// Dispatch one generated invocation and return its JavaScript outcome.
    fn dispatch(&mut self, invocation: &SurfaceInvocation) -> ApiOutcome;
}

include!("generated/chrome150.rs");

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn generated_surface_has_expected_baseline_shape() {
        assert_eq!(
            GENERATED_BASELINE_ID,
            "win11-chrome150.0.7871.129-headful-secure-m2-v1"
        );
        assert_eq!(GENERATED_INTERFACES.len(), 1_935);
        assert_eq!(GENERATED_MEMBERS.len(), 15_473);
        assert_eq!(GENERATED_INTERFACES[0].path, "globalThis");
        assert_eq!(GENERATED_INTERFACES[0].member_len, 1_233);
    }
}
