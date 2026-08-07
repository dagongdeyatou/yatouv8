//! `PyO3` boundary for the yatouv8 Python package.
#![allow(linker_messages)]

#[cfg(feature = "v8-runtime")]
use std::collections::BTreeMap;

use pyo3::prelude::*;

/// Returns immutable build metadata without starting V8.
#[pyfunction]
fn build_info() -> (String, String, String) {
    let info = yatou_core::build_info();
    (
        info.version.to_owned(),
        info.baseline.to_owned(),
        info.v8_crate.to_owned(),
    )
}

/// Executes the M1 smoke expression when the extension is built with V8 support.
#[cfg(feature = "v8-runtime")]
#[pyfunction]
fn v8_smoke_value(py: Python<'_>) -> PyResult<String> {
    py.detach(|| yatou_core::evaluate_to_string("6 * 7"))
        .map_err(runtime_error)
}

/// Reports that the native V8 feature was not linked into this extension build.
#[cfg(not(feature = "v8-runtime"))]
#[pyfunction]
fn v8_smoke_value(_py: Python<'_>) -> PyResult<String> {
    Err(pyo3::exceptions::PyRuntimeError::new_err(
        "yatouv8 was built without the v8-runtime feature",
    ))
}

#[cfg(feature = "v8-runtime")]
fn runtime_error(error: impl std::fmt::Display) -> PyErr {
    pyo3::exceptions::PyRuntimeError::new_err(error.to_string())
}

/// Native owner-thread runtime. The public Python facade lives in `yatouv8.runtime`.
#[cfg(feature = "v8-runtime")]
#[pyclass(name = "Runtime")]
struct PyRuntime {
    runtime: yatou_core::BrowserRuntime,
}

#[cfg(feature = "v8-runtime")]
type RawEvalResult = (
    bool,
    String,
    String,
    Option<String>,
    Option<String>,
    Option<String>,
);

#[cfg(feature = "v8-runtime")]
#[pymethods]
impl PyRuntime {
    #[new]
    #[pyo3(signature = (config_json=None))]
    fn new(config_json: Option<&str>) -> PyResult<Self> {
        let config = config_json.map_or_else(
            || Ok(yatou_core::RuntimeConfig::default()),
            |value| serde_json::from_str(value).map_err(runtime_error),
        )?;
        Ok(Self {
            runtime: yatou_core::BrowserRuntime::new(config).map_err(runtime_error)?,
        })
    }

    /// Evaluate source while releasing Python's GIL.
    fn eval_raw(&self, py: Python<'_>, source: String) -> PyResult<RawEvalResult> {
        let result = py
            .detach(|| self.runtime.eval(source))
            .map_err(runtime_error)?;
        Ok((
            result.ok,
            result.kind,
            result.display,
            result.json,
            result.exception_name,
            result.exception_message,
        ))
    }

    /// Install one exact response in the offline resource store.
    #[pyo3(signature = (url, body, status=200, headers=None))]
    fn add_resource(
        &self,
        py: Python<'_>,
        url: String,
        body: Vec<u8>,
        status: u16,
        headers: Option<BTreeMap<String, String>>,
    ) -> PyResult<()> {
        let resource = yatou_core::Resource::new(url, status, headers.unwrap_or_default(), body)
            .map_err(runtime_error)?;
        py.detach(|| self.runtime.add_resource(resource))
            .map_err(runtime_error)
    }

    /// Drain deterministic timers and queued microtasks.
    #[pyo3(signature = (limit=1000))]
    fn drain_json(&self, py: Python<'_>, limit: u32) -> PyResult<String> {
        let value = py
            .detach(|| self.runtime.drain(limit))
            .map_err(runtime_error)?;
        serde_json::to_string(&value).map_err(runtime_error)
    }

    /// Serialize the current validated trace.
    fn trace_json(&self, py: Python<'_>) -> PyResult<String> {
        let trace = py.detach(|| self.runtime.trace()).map_err(runtime_error)?;
        trace.to_ndjson().map_err(runtime_error)
    }

    /// Serialize immutable environment metadata.
    fn environment_json(&self, py: Python<'_>) -> PyResult<String> {
        let environment = py
            .detach(|| self.runtime.environment())
            .map_err(runtime_error)?;
        serde_json::to_string(&environment).map_err(runtime_error)
    }

    /// Close the owner thread. Idempotent.
    fn close(&self, py: Python<'_>) -> PyResult<()> {
        py.detach(|| self.runtime.close()).map_err(runtime_error)
    }

    /// Whether runtime shutdown has begun.
    #[getter]
    fn closed(&self) -> bool {
        self.runtime.is_closed()
    }
}

/// Native yatouv8 module.
#[pymodule]
fn _native(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_function(wrap_pyfunction!(build_info, module)?)?;
    module.add_function(wrap_pyfunction!(v8_smoke_value, module)?)?;
    #[cfg(feature = "v8-runtime")]
    module.add_class::<PyRuntime>()?;
    Ok(())
}
