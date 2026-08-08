# Semantic conformance probe

This bounded probe compares browser API semantics that can gate Google VM state
initialization. It intentionally does not add more tracing. Chrome 150 is the
oracle; `iv8_rs` is a behavioral reference only.

```powershell
python tools/semantic-conformance/runner.py `
  --backend all `
  --output .yatou/evidence/semantic-conformance/report.json
```

The report records all three results plus leaf-level Chrome-to-candidate diffs.
It also verifies that the isolated Chrome process was cleaned up. The raw
`document.hasFocus()` value is retained, but comparison normalizes it to its
boolean contract because foreground focus belongs to the collector desktop.
