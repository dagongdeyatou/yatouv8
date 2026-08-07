//! Chrome surface and environment snapshots.

use serde::{Deserialize, Serialize};
use serde_json::Value;

use crate::{BaselineId, CURRENT_SCHEMA_VERSION, CollectorMetadata, SchemaError, SchemaVersion};

/// Chrome launch mode used for a capture.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum CaptureMode {
    /// Chrome was launched with the modern headless implementation.
    Headless,
    /// Chrome was launched with a visible top-level window.
    Headful,
}

/// Browser identity returned by `Browser.getVersion`.
#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
pub struct BrowserMetadata {
    /// CDP protocol version.
    pub protocol_version: String,
    /// Product name and four-part version.
    pub product: String,
    /// Chromium source revision.
    pub revision: String,
    /// Browser-level user agent.
    pub user_agent: String,
    /// JavaScript engine version.
    pub js_version: String,
}

/// Host facts needed to reproduce a collection run.
#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
pub struct HostMetadata {
    /// Operating-system family.
    pub os: String,
    /// Operating-system release.
    pub os_release: String,
    /// Operating-system build string.
    pub os_version: String,
    /// Native machine architecture.
    pub architecture: String,
    /// Absolute path to the captured Chrome executable.
    pub chrome_executable: String,
    /// SHA-256 digest of the Chrome executable.
    pub chrome_executable_sha256: String,
}

/// Navigator values captured without invoking arbitrary page code.
#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
pub struct NavigatorSnapshot {
    /// Renderer user agent.
    pub user_agent: String,
    /// Legacy application-version string.
    pub app_version: String,
    /// Reported platform.
    pub platform: String,
    /// Primary language.
    pub language: String,
    /// Ordered preferred languages.
    pub languages: Vec<String>,
    /// Reported logical processors.
    pub hardware_concurrency: u32,
    /// Reported memory in GiB, when exposed.
    pub device_memory: Option<f64>,
    /// Automation exposure flag.
    pub webdriver: bool,
    /// Structured user-agent client hints, when available.
    pub user_agent_data: Option<Value>,
}

/// Screen facts returned by the renderer.
#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
pub struct ScreenSnapshot {
    /// Screen width in CSS pixels.
    pub width: i64,
    /// Screen height in CSS pixels.
    pub height: i64,
    /// Available width in CSS pixels.
    pub avail_width: i64,
    /// Available height in CSS pixels.
    pub avail_height: i64,
    /// Color depth in bits.
    pub color_depth: i64,
    /// Pixel depth in bits.
    pub pixel_depth: i64,
    /// Screen orientation type, when exposed.
    pub orientation_type: Option<String>,
    /// Screen orientation angle, when exposed.
    pub orientation_angle: Option<i64>,
}

/// One correlated wall-clock and monotonic-clock observation.
#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
pub struct ClockSample {
    /// `Date.now()` result in milliseconds.
    pub date_now_ms: f64,
    /// `performance.now()` result in milliseconds.
    pub performance_now_ms: f64,
    /// `performance.timeOrigin` in milliseconds since Unix epoch.
    pub performance_time_origin_ms: f64,
}

/// Derived statistics for one Chrome clock sampling pass.
#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
pub struct ClockProfileSummary {
    /// Total number of samples used by this summary.
    pub sample_count: u32,
    /// Smallest observed positive `Date.now()` delta.
    pub date_now_min_positive_delta_ms: Option<f64>,
    /// Smallest observed positive `performance.now()` delta.
    pub performance_now_min_positive_delta_ms: Option<f64>,
    /// Number of decreasing wall-clock observations.
    pub date_now_monotonic_violations: u32,
    /// Number of decreasing monotonic-clock observations.
    pub performance_now_monotonic_violations: u32,
    /// Minimum error in `Date.now - (timeOrigin + performance.now)`.
    pub correlation_error_min_ms: f64,
    /// Maximum error in `Date.now - (timeOrigin + performance.now)`.
    pub correlation_error_max_ms: f64,
}

/// Raw and summarized Chrome clock distribution evidence.
#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
pub struct ClockProfile {
    /// Number of back-to-back samples.
    pub tight_loop_samples: u32,
    /// Number of samples separated by a one-millisecond timer request.
    pub delayed_samples: u32,
    /// Samples in exact capture order.
    pub samples: Vec<ClockSample>,
    /// Derived statistics retained with the raw values.
    pub summary: ClockProfileSummary,
}

/// Renderer environment values collected alongside surface descriptors.
#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
pub struct ChromeEnvironment {
    /// Current document URL.
    pub document_url: String,
    /// Current origin serialization.
    pub origin: String,
    /// Navigator values.
    pub navigator: NavigatorSnapshot,
    /// Screen values.
    pub screen: ScreenSnapshot,
    /// Device pixel ratio.
    pub device_pixel_ratio: f64,
    /// Whether the realm is cross-origin isolated.
    pub cross_origin_isolated: bool,
    /// Whether the realm is a secure context.
    pub is_secure_context: bool,
    /// Resolved IANA time-zone identifier.
    pub timezone: String,
    /// Local offset from UTC in minutes.
    pub timezone_offset_minutes: i32,
    /// Clock correlation sample.
    pub clock_sample: ClockSample,
    /// Multi-sample timing distribution. Older M2 snapshots may omit it.
    #[serde(default)]
    pub clock_profile: Option<ClockProfile>,
}

/// JavaScript property-key category.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum PropertyKeyKind {
    /// String property key.
    String,
    /// Symbol property key.
    Symbol,
}

/// Lossless display representation of a string or symbol property key.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct PropertyKeySnapshot {
    /// Key category.
    pub kind: PropertyKeyKind,
    /// String value or `Symbol(description)` display form.
    pub display: String,
    /// Symbol description, when the key is a symbol.
    pub description: Option<String>,
    /// Global symbol registry key, when present.
    pub registry_key: Option<String>,
}

/// Safe shape summary for a function value.
#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
pub struct CallableSnapshot {
    /// Function `name`.
    pub name: String,
    /// Function `length`.
    pub length: u32,
    /// Whether the canonical source string has native-code form.
    pub native_like: bool,
    /// Canonical `Function.prototype.toString` result.
    pub source: String,
}

/// Data or accessor descriptor category.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum DescriptorKind {
    /// Descriptor contains a value and writable flag.
    Data,
    /// Descriptor contains getter and setter slots.
    Accessor,
}

/// One own-property descriptor captured without invoking its accessor.
#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
pub struct PropertyDescriptorSnapshot {
    /// Property key.
    pub key: PropertyKeySnapshot,
    /// Descriptor category.
    pub kind: DescriptorKind,
    /// Configurable flag.
    pub configurable: bool,
    /// Enumerable flag.
    pub enumerable: bool,
    /// Writable flag for a data descriptor.
    pub writable: Option<bool>,
    /// JavaScript `typeof` result for a data value.
    pub value_type: Option<String>,
    /// Bounded primitive representation when safe to read.
    pub value_preview: Option<String>,
    /// Callable shape when the data value is a function.
    pub callable: Option<CallableSnapshot>,
    /// Getter callable shape.
    pub getter: Option<CallableSnapshot>,
    /// Setter callable shape.
    pub setter: Option<CallableSnapshot>,
}

/// Descriptor snapshot for one constructor, prototype, or global object.
#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
pub struct SurfaceSnapshot {
    /// Stable JavaScript path used to resolve the value.
    pub path: String,
    /// Whether the path resolved without invoking an accessor.
    pub available: bool,
    /// JavaScript `typeof` result.
    pub value_type: Option<String>,
    /// Constructor name read from the direct prototype descriptor.
    pub constructor_name: Option<String>,
    /// Known path of the direct prototype, when one was captured.
    pub prototype_path: Option<String>,
    /// Own keys in exact `Reflect.ownKeys` order.
    pub own_keys: Vec<PropertyKeySnapshot>,
    /// Descriptors in the same order as `own_keys`.
    pub descriptors: Vec<PropertyDescriptorSnapshot>,
    /// Bounded diagnostic for unavailable surfaces.
    pub error: Option<String>,
}

/// Before/after proof that the probe did not add or remove global keys.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct PollutionCheck {
    /// Digest of global keys before the probe.
    pub before_global_keys_sha256: String,
    /// Digest of global keys after the probe.
    pub after_global_keys_sha256: String,
    /// Exact equality result.
    pub unchanged: bool,
    /// Keys added during the probe.
    pub added: Vec<String>,
    /// Keys removed during the probe.
    pub removed: Vec<String>,
}

/// Complete M2 Chrome evidence snapshot.
#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
pub struct ChromeSnapshot {
    /// Data-contract version.
    pub schema_version: SchemaVersion,
    /// Baseline family identifier.
    pub baseline_id: BaselineId,
    /// Concrete run identifier.
    pub run_id: String,
    /// UTC RFC 3339 capture timestamp.
    pub captured_at: String,
    /// Chrome launch mode.
    pub capture_mode: CaptureMode,
    /// Browser identity.
    pub browser: BrowserMetadata,
    /// Host identity.
    pub host: HostMetadata,
    /// Collector identity and probe hash.
    pub collector: CollectorMetadata,
    /// Renderer environment.
    pub environment: ChromeEnvironment,
    /// Global pollution proof.
    pub pollution: PollutionCheck,
    /// Ordered surface snapshots.
    pub surfaces: Vec<SurfaceSnapshot>,
}

impl ChromeSnapshot {
    /// Enforces schema version, pollution, and descriptor-order invariants.
    ///
    /// # Errors
    ///
    /// Returns [`SchemaError`] when the snapshot cannot be admitted as evidence.
    pub fn validate(&self) -> Result<(), SchemaError> {
        if self.schema_version != CURRENT_SCHEMA_VERSION {
            return Err(SchemaError::UnsupportedSchemaVersion(self.schema_version.0));
        }
        if !self.pollution.unchanged
            || self.pollution.before_global_keys_sha256 != self.pollution.after_global_keys_sha256
            || !self.pollution.added.is_empty()
            || !self.pollution.removed.is_empty()
        {
            return Err(SchemaError::CollectorPollution);
        }
        if let Some(profile) = &self.environment.clock_profile {
            let expected = profile
                .tight_loop_samples
                .saturating_add(profile.delayed_samples);
            let actual = u32::try_from(profile.samples.len()).unwrap_or(u32::MAX);
            if actual != expected || profile.summary.sample_count != actual {
                return Err(SchemaError::ClockProfileSampleCount);
            }
        }
        for surface in &self.surfaces {
            let descriptor_keys = surface
                .descriptors
                .iter()
                .map(|descriptor| &descriptor.key)
                .collect::<Vec<_>>();
            let own_keys = surface.own_keys.iter().collect::<Vec<_>>();
            if descriptor_keys != own_keys {
                return Err(SchemaError::SurfaceDescriptorMismatch(surface.path.clone()));
            }
        }
        Ok(())
    }
}
