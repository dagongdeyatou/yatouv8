(async () => {
  "use strict";

  const ownDescriptor = Object.getOwnPropertyDescriptor;
  const ownKeys = Reflect.ownKeys;
  const functionToString = Function.prototype.toString;
  const seedSurfacePaths = [
    "globalThis",
    "Object",
    "Object.prototype",
    "Function",
    "Function.prototype",
    "EventTarget",
    "EventTarget.prototype",
    "Window",
    "Window.prototype",
    "Navigator",
    "Navigator.prototype",
    "Performance",
    "Performance.prototype",
    "Document",
    "Document.prototype",
    "Node",
    "Node.prototype",
    "Element",
    "Element.prototype",
    "HTMLElement",
    "HTMLElement.prototype",
    "Location",
    "Location.prototype",
    "Screen",
    "Screen.prototype",
    "CSSStyleDeclaration",
    "CSSStyleDeclaration.prototype",
    "Storage",
    "Storage.prototype",
  ];

  // The first M2 baseline intentionally covered only a small hand-picked
  // browser spine. That is sufficient for harness validation but not for a
  // VM which walks every exposed WebIDL brand. Discover every global
  // constructor and its prototype from data descriptors without invoking a
  // single accessor. Namespace singletons are included explicitly because
  // they have no `.prototype` object.
  const namespaceSingletons = new Set([
    "Atomics", "Intl", "JSON", "Math", "Reflect", "WebAssembly",
  ]);
  const discoveredSurfacePaths = [];
  for (const key of ownKeys(globalThis)) {
    if (typeof key !== "string" || key.includes(".")) continue;
    const descriptor = ownDescriptor(globalThis, key);
    if (!descriptor || !Object.hasOwn(descriptor, "value")) continue;
    const value = descriptor.value;
    if (value === globalThis) continue;
    if (typeof value === "function") {
      let prototype;
      try {
        prototype = value.prototype;
      } catch {
        continue;
      }
      if ((typeof prototype === "object" && prototype !== null) || typeof prototype === "function") {
        discoveredSurfacePaths.push(key, `${key}.prototype`);
      }
    } else if (namespaceSingletons.has(key) && value !== null && typeof value === "object") {
      discoveredSurfacePaths.push(key);
    }
  }
  const surfacePaths = [...new Set([...seedSurfacePaths, ...discoveredSurfacePaths])];

  function boundedText(value, limit = 512) {
    const text = String(value);
    return text.length <= limit ? text : `${text.slice(0, limit)}…`;
  }

  function keySnapshot(key) {
    if (typeof key === "symbol") {
      return {
        kind: "symbol",
        display: boundedText(key),
        description: key.description ?? null,
        registry_key: Symbol.keyFor(key) ?? null,
      };
    }
    return {
      kind: "string",
      display: key,
      description: null,
      registry_key: null,
    };
  }

  function callableSnapshot(value) {
    if (typeof value !== "function") return null;
    let source = "";
    try {
      source = functionToString.call(value);
    } catch (error) {
      source = `<toString threw ${boundedText(error?.name ?? "Error", 80)}>`;
    }
    return {
      name: boundedText(value.name ?? "", 256),
      length: Number.isSafeInteger(value.length) && value.length >= 0 ? value.length : 0,
      native_like: /\{\s*\[native code\]\s*\}/u.test(source),
      source: boundedText(source, 2048),
    };
  }

  function primitivePreview(value) {
    const type = typeof value;
    if (type === "undefined") return "undefined";
    if (value === null) return "null";
    if (type === "string") return boundedText(JSON.stringify(value), 512);
    if (type === "number") {
      if (Number.isNaN(value)) return "NaN";
      if (Object.is(value, -0)) return "-0";
      if (value === Infinity) return "Infinity";
      if (value === -Infinity) return "-Infinity";
      return String(value);
    }
    if (type === "bigint") return `${value}n`;
    if (type === "boolean") return String(value);
    if (type === "symbol") return boundedText(value, 512);
    return null;
  }

  function descriptorSnapshot(key, descriptor) {
    const common = {
      key: keySnapshot(key),
      configurable: descriptor.configurable === true,
      enumerable: descriptor.enumerable === true,
    };
    if (Object.hasOwn(descriptor, "value")) {
      return {
        ...common,
        kind: "data",
        writable: descriptor.writable === true,
        value_type: typeof descriptor.value,
        value_preview: primitivePreview(descriptor.value),
        callable: callableSnapshot(descriptor.value),
        getter: null,
        setter: null,
      };
    }
    return {
      ...common,
      kind: "accessor",
      writable: null,
      value_type: null,
      value_preview: null,
      callable: null,
      getter: callableSnapshot(descriptor.get),
      setter: callableSnapshot(descriptor.set),
    };
  }

  function resolveDataPath(path) {
    if (path === "globalThis") return globalThis;
    let value = globalThis;
    for (const segment of path.split(".")) {
      const descriptor = ownDescriptor(value, segment);
      if (!descriptor) throw new Error(`missing own property ${segment}`);
      if (!Object.hasOwn(descriptor, "value")) {
        throw new Error(`refusing to invoke accessor ${segment}`);
      }
      value = descriptor.value;
    }
    return value;
  }

  const resolved = new Map();
  for (const path of surfacePaths) {
    try {
      resolved.set(path, resolveDataPath(path));
    } catch {
      // Unavailable surfaces are represented explicitly below.
    }
  }

  function prototypePath(value) {
    if ((typeof value !== "object" && typeof value !== "function") || value === null) {
      return null;
    }
    let prototype;
    try {
      prototype = Object.getPrototypeOf(value);
    } catch {
      return null;
    }
    for (const [path, candidate] of resolved) {
      if (candidate === prototype) return path;
    }
    return prototype === null ? "null" : null;
  }

  function constructorName(value) {
    if ((typeof value !== "object" && typeof value !== "function") || value === null) {
      return null;
    }
    try {
      const prototype = Object.getPrototypeOf(value);
      if (prototype === null) return null;
      const descriptor = ownDescriptor(prototype, "constructor");
      if (!descriptor || !Object.hasOwn(descriptor, "value")) return null;
      return typeof descriptor.value === "function"
        ? boundedText(descriptor.value.name ?? "", 256)
        : null;
    } catch {
      return null;
    }
  }

  function captureSurface(path) {
    let value;
    try {
      value = resolveDataPath(path);
      const keys = ownKeys(value);
      const descriptors = keys.map((key) => {
        const descriptor = ownDescriptor(value, key);
        if (!descriptor) throw new Error(`descriptor disappeared for ${String(key)}`);
        return descriptorSnapshot(key, descriptor);
      });
      return {
        path,
        available: true,
        value_type: typeof value,
        constructor_name: constructorName(value),
        prototype_path: prototypePath(value),
        own_keys: keys.map(keySnapshot),
        descriptors,
        error: null,
      };
    } catch (error) {
      return {
        path,
        available: false,
        value_type: null,
        constructor_name: null,
        prototype_path: null,
        own_keys: [],
        descriptors: [],
        error: boundedText(`${error?.name ?? "Error"}: ${error?.message ?? error}`, 512),
      };
    }
  }

  function clockSample() {
    return {
      date_now_ms: Date.now(),
      performance_now_ms: performance.now(),
      performance_time_origin_ms: performance.timeOrigin,
    };
  }

  function minPositive(values) {
    let minimum = Infinity;
    for (const value of values) {
      if (value > 0 && value < minimum) minimum = value;
    }
    return minimum === Infinity ? null : minimum;
  }

  function summarizeClock(samples) {
    const dateDeltas = [];
    const performanceDeltas = [];
    let dateViolations = 0;
    let performanceViolations = 0;
    for (let index = 1; index < samples.length; index += 1) {
      const dateDelta = samples[index].date_now_ms - samples[index - 1].date_now_ms;
      const performanceDelta =
        samples[index].performance_now_ms - samples[index - 1].performance_now_ms;
      dateDeltas.push(dateDelta);
      performanceDeltas.push(performanceDelta);
      if (dateDelta < 0) dateViolations += 1;
      if (performanceDelta < 0) performanceViolations += 1;
    }
    const correlationErrors = samples.map(
      (sample) =>
        sample.date_now_ms -
        (sample.performance_time_origin_ms + sample.performance_now_ms),
    );
    return {
      sample_count: samples.length,
      date_now_min_positive_delta_ms: minPositive(dateDeltas),
      performance_now_min_positive_delta_ms: minPositive(performanceDeltas),
      date_now_monotonic_violations: dateViolations,
      performance_now_monotonic_violations: performanceViolations,
      correlation_error_min_ms: Math.min(...correlationErrors),
      correlation_error_max_ms: Math.max(...correlationErrors),
    };
  }

  async function captureClockProfile() {
    const tightLoopSamples = 256;
    const delayedSamples = 32;
    const samples = [];
    for (let index = 0; index < tightLoopSamples; index += 1) samples.push(clockSample());
    for (let index = 0; index < delayedSamples; index += 1) {
      await new Promise((resolve) => setTimeout(resolve, 1));
      samples.push(clockSample());
    }
    return {
      tight_loop_samples: tightLoopSamples,
      delayed_samples: delayedSamples,
      samples,
      summary: summarizeClock(samples),
    };
  }

  let userAgentData = null;
  if (navigator.userAgentData) {
    try {
      userAgentData = {
        brands: navigator.userAgentData.brands,
        mobile: navigator.userAgentData.mobile,
        platform: navigator.userAgentData.platform,
        high_entropy: await navigator.userAgentData.getHighEntropyValues([
          "architecture",
          "bitness",
          "formFactors",
          "fullVersionList",
          "model",
          "platformVersion",
          "wow64",
        ]),
      };
    } catch (error) {
      userAgentData = { error: boundedText(`${error?.name ?? "Error"}: ${error?.message ?? error}`) };
    }
  }

  const initialClockSample = clockSample();
  const clockProfile = await captureClockProfile();

  return {
    environment: {
      document_url: document.URL,
      origin: location.origin,
      navigator: {
        user_agent: navigator.userAgent,
        app_version: navigator.appVersion,
        platform: navigator.platform,
        language: navigator.language,
        languages: Array.from(navigator.languages),
        hardware_concurrency: navigator.hardwareConcurrency,
        device_memory: navigator.deviceMemory ?? null,
        webdriver: navigator.webdriver === true,
        user_agent_data: userAgentData,
      },
      screen: {
        width: screen.width,
        height: screen.height,
        avail_width: screen.availWidth,
        avail_height: screen.availHeight,
        color_depth: screen.colorDepth,
        pixel_depth: screen.pixelDepth,
        orientation_type: screen.orientation?.type ?? null,
        orientation_angle: screen.orientation?.angle ?? null,
      },
      device_pixel_ratio: devicePixelRatio,
      cross_origin_isolated: crossOriginIsolated === true,
      is_secure_context: isSecureContext === true,
      timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      timezone_offset_minutes: new Date().getTimezoneOffset(),
      clock_sample: initialClockSample,
      clock_profile: clockProfile,
    },
    surfaces: surfacePaths.map(captureSurface),
  };
})()
