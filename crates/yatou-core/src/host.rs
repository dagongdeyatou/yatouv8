//! Deterministic host-side resources shared by the V8 runtime and replay tools.

use std::collections::BTreeMap;

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use thiserror::Error;

/// A caller-provided response that may be consumed by the offline `fetch` host service.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct Resource {
    /// Exact URL used as the resource-store key.
    pub url: String,
    /// HTTP-like status exposed to JavaScript.
    pub status: u16,
    /// Canonically ordered response headers.
    pub headers: BTreeMap<String, String>,
    /// Response body bytes.
    pub body: Vec<u8>,
    /// SHA-256 digest of `body`.
    pub body_sha256: String,
}

impl Resource {
    /// Construct a validated resource and derive its content digest.
    ///
    /// # Errors
    ///
    /// Returns [`ResourceError`] when the URL is empty, the status is outside the
    /// HTTP range, or a header name is empty.
    pub fn new(
        url: impl Into<String>,
        status: u16,
        headers: BTreeMap<String, String>,
        body: Vec<u8>,
    ) -> Result<Self, ResourceError> {
        let resource = Self {
            url: url.into(),
            status,
            headers,
            body_sha256: format!("{:x}", Sha256::digest(&body)),
            body,
        };
        resource.validate()?;
        Ok(resource)
    }

    /// Validate the externally observable resource contract.
    ///
    /// # Errors
    ///
    /// Returns [`ResourceError`] for malformed fields or a stale body digest.
    pub fn validate(&self) -> Result<(), ResourceError> {
        if self.url.is_empty() {
            return Err(ResourceError::EmptyUrl);
        }
        if !(100..=599).contains(&self.status) {
            return Err(ResourceError::InvalidStatus(self.status));
        }
        if self.headers.keys().any(String::is_empty) {
            return Err(ResourceError::EmptyHeaderName);
        }
        let actual = format!("{:x}", Sha256::digest(&self.body));
        if self.body_sha256 != actual {
            return Err(ResourceError::DigestMismatch {
                expected: self.body_sha256.clone(),
                actual,
            });
        }
        Ok(())
    }
}

/// In-memory resource registry with no network fallback.
#[derive(Clone, Debug, Default)]
pub struct ResourceStore {
    entries: BTreeMap<String, Resource>,
}

impl ResourceStore {
    /// Insert or replace one exact URL.
    ///
    /// # Errors
    ///
    /// Returns [`ResourceError`] when the resource fails validation.
    pub fn insert(&mut self, resource: Resource) -> Result<Option<Resource>, ResourceError> {
        resource.validate()?;
        Ok(self.entries.insert(resource.url.clone(), resource))
    }

    /// Retrieve an exact URL without consulting the network.
    #[must_use]
    pub fn get(&self, url: &str) -> Option<&Resource> {
        self.entries.get(url)
    }

    /// Number of registered resources.
    #[must_use]
    pub fn len(&self) -> usize {
        self.entries.len()
    }

    /// Whether no resources have been registered.
    #[must_use]
    pub fn is_empty(&self) -> bool {
        self.entries.is_empty()
    }
}

/// Resource validation failures.
#[derive(Clone, Debug, Error, Eq, PartialEq)]
pub enum ResourceError {
    /// URL keys must not be empty.
    #[error("resource URL is empty")]
    EmptyUrl,
    /// Status must fit the HTTP status-code range.
    #[error("invalid resource status {0}")]
    InvalidStatus(u16),
    /// Empty header names cannot be represented consistently.
    #[error("resource header name is empty")]
    EmptyHeaderName,
    /// Body content changed without updating its digest.
    #[error("resource body digest mismatch: expected {expected}, actual {actual}")]
    DigestMismatch {
        /// Digest stored with the resource.
        expected: String,
        /// Digest derived from current body bytes.
        actual: String,
    },
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn resource_store_is_exact_and_offline() {
        let resource = Resource::new(
            "https://fixture.invalid/data.json",
            200,
            BTreeMap::from([("content-type".to_owned(), "application/json".to_owned())]),
            br#"{"answer":42}"#.to_vec(),
        )
        .expect("resource");
        let mut store = ResourceStore::default();
        store.insert(resource).expect("insert");
        assert_eq!(store.len(), 1);
        assert!(store.get("https://fixture.invalid/data.json").is_some());
        assert!(store.get("https://fixture.invalid/missing.json").is_none());
    }

    #[test]
    fn stale_digest_is_rejected() {
        let mut resource =
            Resource::new("https://fixture.invalid/a", 200, BTreeMap::new(), vec![1])
                .expect("resource");
        resource.body.push(2);
        assert!(matches!(
            resource.validate(),
            Err(ResourceError::DigestMismatch { .. })
        ));
    }
}
