# M8 host conformance

`probe.js` is deliberately bounded to the MVP contract: DOM tree mutation/query,
inline CSSOM plus fixed `getComputedStyle`, one-shot events, same-origin iframe
surface presence, and navigator identity. `collector.py` runs the probe in an
isolated Chrome 150 target; `session_runner` evaluates the identical source in
yatouv8; `finalize.py` admits only exact canonical equality.

`trusted-types-probe.js` is a separate Chrome 150 contract probe for the native
Trusted Types compatibility layer. It covers global/prototype descriptors,
native callable signatures, policy transforms, branded values, illegal
constructors, error behavior, and the bounded sink type map. Run it with:

```powershell
.\scripts\run-trusted-types.ps1
```

The report is written below
`.yatou/evidence/reports/trusted-types/<run-id>/trusted-types.report.json`.
This probe establishes API-surface compatibility; it does not claim CSP
directive enforcement or complete DOM trusted-type sink enforcement.
