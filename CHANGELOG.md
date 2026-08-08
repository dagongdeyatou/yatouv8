# Changelog

## 0.1.0 - 2026-08-07

- Completed the evidence-driven M0–M10 architecture and conformance pipeline.
- Added a V8 150 owner-thread runtime and persistent Python `Runtime`/`Context` API.
- Added deterministic DOM, CSSOM, events, timers, storage, cookie, resource replay,
  profile, clock, trace, and strict no-network-fallback host services.
- Verified the bounded M8 host probe exactly against Chrome 150.
- Verified the archived Google BotGuard M6 path and current public Google/
  recaptcha.net loader paths with content-addressed evidence.
- Added repaired CPython 3.13 Windows wheels, CI, SBOM, release audit, performance,
  concurrency, exception-recovery, and cleanup gates.
- Added opt-in bounded GET tracing for global/browser-host/native Trusted Types
  properties with causal ordering across JS host and Rust native observations.
- Added SG_SS-oriented reflection tracing, private runtime bridges, generated
  runtime-surface installation, recorded Chrome clock replay, structured Cookie/
  navigation handoff, and local final acceptance gates.
- Replaced the fixed 29-interface surface ceiling with a verified Chrome 150
  headful full-surface capture: 1,469 surfaces, 12,841 descriptors, and 9,565
  callable/accessor metadata entries; fixed intrinsic namespace trace ownership.
