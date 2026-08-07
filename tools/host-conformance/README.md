# M8 host conformance

`probe.js` is deliberately bounded to the MVP contract: DOM tree mutation/query,
inline CSSOM plus fixed `getComputedStyle`, one-shot events, same-origin iframe
surface presence, and navigator identity. `collector.py` runs the probe in an
isolated Chrome 150 target; `session_runner` evaluates the identical source in
yatouv8; `finalize.py` admits only exact canonical equality.
