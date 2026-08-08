(() => {
  "use strict";
  const globalObject = globalThis;
  const stringValue = String;
  const booleanValue = Boolean;
  const numberValue = Number;
  const ObjectIntrinsic = Object;
  const ReflectIntrinsic = Reflect;
  const reflectGetPrototypeOfIntrinsic = Reflect.getPrototypeOf;
  const reflectOwnKeysIntrinsic = Reflect.ownKeys;
  const reflectGetOwnPropertyDescriptorIntrinsic = Reflect.getOwnPropertyDescriptor;
  const ArrayIntrinsic = Array;
  const PromiseIntrinsic = Promise;
  const DateIntrinsic = Date;
  const RegExpIntrinsic = RegExp;
  const MapIntrinsic = Map;
  const SetIntrinsic = Set;
  const WeakMapIntrinsic = WeakMap;
  const WeakSetIntrinsic = WeakSet;
  const ArrayBufferIntrinsic = ArrayBuffer;
  const Uint8ArrayIntrinsic = Uint8Array;
  const ProxyIntrinsic = Proxy;
  const FunctionIntrinsic = Function;
  const MathIntrinsic = Math;
  const JSONIntrinsic = JSON;
  const TypeErrorIntrinsic = TypeError;
  const ErrorIntrinsic = Error;
  const indirectEvalIntrinsic = eval;
  const config = globalObject.__yatouConfig;
  if (!config || !config.profile) throw new ErrorIntrinsic("yatouv8 host config is missing");
  const profile = config.profile;
  const nextObservationSequence = globalObject.__yatouNextObservationSequence;
  if (typeof nextObservationSequence !== "function")
    throw new ErrorIntrinsic("yatouv8 observation sequencer is missing");
  const hostLog = [];
  const resources = new MapIntrinsic();
  let requestSequence = 0;
  let timerSequence = 0;
  const clockStartMs = profile.clock.mode === "recorded"
    ? numberValue(profile.clock.buckets && profile.clock.buckets[0] && profile.clock.buckets[0].value_ms)
    : numberValue(profile.clock.start_ms);
  let clockMs = clockStartMs;
  const timers = new MapIntrinsic();
  const microtasks = [];

  const getTraceConfig = ObjectIntrinsic.freeze({
    enabled: booleanValue(config.get_trace && config.get_trace.enabled),
    maxEvents: MathIntrinsic.max(0, numberValue(config.get_trace && config.get_trace.max_events) || 0)
  });
  const traceTargets = new WeakMapIntrinsic();
  const traceProxyCache = new WeakMapIntrinsic();
  const traceRawValues = new WeakMapIntrinsic();
  const reflectionFunctions = new WeakSetIntrinsic();
  let getTraceActive = false;
  let getTraceEvents = 0;
  let getTraceDropped = 0;
  let getTraceDepth = 0;
  let normalizeOwnKeys = (_target, keys) => keys;

  const objectLike = value =>
    (typeof value === "object" && value !== null) || typeof value === "function";
  const registerTraceTarget = (value, target) => {
    if (objectLike(value)) traceTargets.set(value, stringValue(target));
    return value;
  };
  const rawTraceValue = value => traceRawValues.get(value) || value;
  const stateFor = (store, value) => {
    let state = store.get(value);
    if (state) return state;
    while (traceRawValues.has(value)) value = traceRawValues.get(value);
    state = store.get(value);
    if (state) return state;
    const proxy = traceProxyCache.get(value);
    return proxy ? store.get(proxy) : undefined;
  };
  const semanticTraceTarget = value => {
    value = rawTraceValue(value);
    for (let current = value; objectLike(current); current = reflectGetPrototypeOfIntrinsic(current)) {
      const target = traceTargets.get(current);
      if (target) return target;
    }
    return null;
  };
  const ownerTraceTarget = (value, key) => {
    value = rawTraceValue(value);
    const fallback = semanticTraceTarget(value) || "Object";
    for (let current = value; objectLike(current); current = reflectGetPrototypeOfIntrinsic(current)) {
      if (!ObjectIntrinsic.prototype.hasOwnProperty.call(current, key)) continue;
      return traceTargets.get(current) || fallback;
    }
    return fallback;
  };
  const traceableKey = key =>
    typeof key === "string" && !key.startsWith("_") && key !== "__proto__";
  const traceableValue = (value, hint) => {
    if (!objectLike(value) || value === globalObject) return false;
    if (ArrayIntrinsic.isArray(value) || value instanceof PromiseIntrinsic || value instanceof DateIntrinsic || value instanceof RegExpIntrinsic)
      return false;
    if (value instanceof MapIntrinsic || value instanceof SetIntrinsic || value instanceof WeakMapIntrinsic || value instanceof WeakSetIntrinsic)
      return false;
    if (value instanceof ArrayBufferIntrinsic || ArrayBufferIntrinsic.isView(value)) return false;
    return !!(hint || semanticTraceTarget(value));
  };
  const logGet = (target, member, outcome, threw = false) => {
    if (!getTraceConfig.enabled || !getTraceActive || getTraceDepth) return;
    if (getTraceEvents >= getTraceConfig.maxEvents) {
      getTraceDropped += 1;
      return;
    }
    getTraceDepth += 1;
    try {
      getTraceEvents += 1;
      logApi(target, member, "get", [], outcome, threw);
    } finally {
      getTraceDepth -= 1;
    }
  };
  const logStructural = (target, member, operation, outcome, args = [], threw = false) => {
    if (!getTraceConfig.enabled || !getTraceActive || getTraceDepth) return;
    if (getTraceEvents >= getTraceConfig.maxEvents) {
      getTraceDropped += 1;
      return;
    }
    getTraceDepth += 1;
    try {
      getTraceEvents += 1;
      logApi(target, stringValue(member), operation, args, outcome, threw);
    } finally {
      getTraceDepth -= 1;
    }
  };
  const observeTraceValue = (value, hint = null) => {
    value = rawTraceValue(value);
    if (!getTraceConfig.enabled || !traceableValue(value, hint)) return value;
    const existingTarget = semanticTraceTarget(value);
    if (hint && (!existingTarget
      || existingTarget === "Object.prototype"
      || existingTarget === "Function.prototype")) registerTraceTarget(value, hint);
    const cached = traceProxyCache.get(value);
    if (cached) return cached;
    const handler = {
      get(target, key) {
        const owner = ownerTraceTarget(target, key);
        try {
          getTraceDepth += 1;
          let result;
          try {
            result = ReflectIntrinsic.get(target, key, target);
          } finally {
            getTraceDepth -= 1;
          }
          if (traceableKey(key)) logGet(owner, key, result);
          const descriptor = reflectGetOwnPropertyDescriptorIntrinsic(target, key);
          const invariantValue = descriptor
            && !descriptor.configurable
            && ObjectIntrinsic.prototype.hasOwnProperty.call(descriptor, "value")
            && !descriptor.writable;
          const invariantUndefined = descriptor
            && !descriptor.configurable
            && !ObjectIntrinsic.prototype.hasOwnProperty.call(descriptor, "value")
            && descriptor.get === undefined;
          if (invariantValue || invariantUndefined) return result;
          const nestedHint = traceableKey(key) ? `${owner}.${key}` : null;
          return observeTraceValue(result, nestedHint);
        } catch (error) {
          if (traceableKey(key))
            logGet(owner, key, `${error && error.name || "Error"}: ${error && error.message || error}`, true);
          throw error;
        }
      },
      set(target, key, next) {
        return ReflectIntrinsic.set(target, key, rawTraceValue(next), target);
      },
      apply(target, thisArg, argumentsList) {
        const callbackBoundary = semanticTraceTarget(target) === "EventTarget.prototype.dispatchEvent";
        const structuralBoundary = reflectionFunctions.has(target);
        if (!callbackBoundary && !structuralBoundary) getTraceDepth += 1;
        let result;
        try {
          result = ReflectIntrinsic.apply(
            target,
            rawTraceValue(thisArg),
            argumentsList.map(rawTraceValue)
          );
        } finally {
          if (!callbackBoundary && !structuralBoundary) getTraceDepth -= 1;
        }
        return structuralBoundary ? result : observeTraceValue(result);
      },
      construct(target, argumentsList, newTarget) {
        getTraceDepth += 1;
        let result;
        try {
          result = ReflectIntrinsic.construct(
            target,
            argumentsList.map(rawTraceValue),
            rawTraceValue(newTarget)
          );
        } finally {
          getTraceDepth -= 1;
        }
        return observeTraceValue(result);
      },
      ownKeys(target) {
        let result;
        getTraceDepth += 1;
        try { result = normalizeOwnKeys(target, reflectOwnKeysIntrinsic(target)); }
        finally { getTraceDepth -= 1; }
        const owner = semanticTraceTarget(target) || "Object";
        for (const key of result) logStructural(owner, key, "own_keys", key);
        return result;
      },
      getOwnPropertyDescriptor(target, key) {
        let result;
        getTraceDepth += 1;
        try { result = reflectGetOwnPropertyDescriptorIntrinsic(target, key); }
        finally { getTraceDepth -= 1; }
        logStructural(semanticTraceTarget(target) || "Object", key, "get_own_property_descriptor", result);
        return result;
      },
      getPrototypeOf(target) {
        let result;
        getTraceDepth += 1;
        try { result = reflectGetPrototypeOfIntrinsic(target); }
        finally { getTraceDepth -= 1; }
        logStructural(semanticTraceTarget(target) || "Object", "[[Prototype]]", "get_prototype_of", result);
        return result;
      },
      has(target, key) {
        let result;
        getTraceDepth += 1;
        try { result = ReflectIntrinsic.has(target, key); }
        finally { getTraceDepth -= 1; }
        logStructural(semanticTraceTarget(target) || "Object", key, "has", result);
        return result;
      },
      defineProperty(target, key, descriptor) {
        let result;
        getTraceDepth += 1;
        try { result = ReflectIntrinsic.defineProperty(target, key, descriptor); }
        finally { getTraceDepth -= 1; }
        logStructural(semanticTraceTarget(target) || "Object", key, "define_property", result, [descriptor]);
        return result;
      }
    };
    const proxy = new ProxyIntrinsic(value, handler);
    traceProxyCache.set(value, proxy);
    traceRawValues.set(proxy, value);
    return proxy;
  };

  registerTraceTarget(globalObject, "globalThis");

  const data = (object, key, value, enumerable = true) => {
    const installed = getTraceConfig.enabled
      && object === globalObject
      && traceableKey(key)
      ? observeTraceValue(value, stringValue(key))
      : value;
    return (
    ObjectIntrinsic.defineProperty(object, key, {
      value: installed,
      writable: true,
      enumerable,
      configurable: true
    })
    );
  };
  const getter = (object, key, get, enumerable = true, set = undefined) => {
    if (!getTraceConfig.enabled || object !== globalObject || !traceableKey(key))
      return ObjectIntrinsic.defineProperty(object, key, { get, set, enumerable, configurable: true });
    const tracedGet = function () {
      return observeTraceValue(get.call(this));
    };
    ObjectIntrinsic.defineProperty(tracedGet, "name", { value: `get ${stringValue(key)}`, configurable: true });
    return ObjectIntrinsic.defineProperty(object, key, {
      get: tracedGet,
      set,
      enumerable,
      configurable: true
    });
  };
  const preview = value => {
    if (value === undefined) return "undefined";
    if (value === null) return "null";
    if (typeof value === "string") return value.length > 96 ? `${value.slice(0, 96)}…` : value;
    if (typeof value === "number" || typeof value === "boolean" || typeof value === "bigint") return stringValue(value);
    if (typeof value === "function") return `function:${value.name || "anonymous"}`;
    return ObjectIntrinsic.prototype.toString.call(value);
  };
  const kindOf = value => value === null ? "null" : typeof value;
  const summary = value => ({ kind: kindOf(value), preview: preview(value) });
  const log = (kind, detail) => hostLog.push({
    order: nextObservationSequence(),
    kind,
    ...detail
  });
  const logApi = (target, member, operation, args, outcome, threw = false) =>
    log("api", {
      target,
      member,
      operation,
      arguments: args.map(summary),
      outcome: summary(outcome),
      threw
    });

  const reflectionTarget = value => semanticTraceTarget(rawTraceValue(value)) ||
    (value === globalObject ? "globalThis" : ObjectIntrinsic.prototype.toString.call(rawTraceValue(value)).slice(8, -1));
  const installReflectionTracing = () => {
    const replace = (owner, name, operation, implementation) => {
      const original = owner[name];
      if (typeof original !== "function") return;
      const wrapped = function (...args) {
        return implementation(original, this, args);
      };
      ObjectIntrinsic.defineProperty(wrapped, "name", { value: name, configurable: true });
      ObjectIntrinsic.defineProperty(wrapped, "length", { value: original.length, configurable: true });
      markNative(wrapped, { name, length: original.length, native_like: true });
      reflectionFunctions.add(wrapped);
      ObjectIntrinsic.defineProperty(owner, name, {
        ...ObjectIntrinsic.getOwnPropertyDescriptor(owner, name),
        value: wrapped
      });
    };
    const invoke = (original, receiver, args) => {
      getTraceDepth += 1;
      try { return ReflectIntrinsic.apply(original, receiver, args.map(rawTraceValue)); }
      finally { getTraceDepth -= 1; }
    };
    const ownKeys = (original, receiver, args) => {
      const target = rawTraceValue(args[0]);
      const result = normalizeOwnKeys(target, invoke(original, receiver, [target]));
      if (!getTraceActive) return result;
      const name = reflectionTarget(target);
      for (const key of result) logStructural(name, key, "own_keys", key);
      return result;
    };
    const descriptor = (original, receiver, args) => {
      const target = rawTraceValue(args[0]);
      const key = args[1];
      const result = invoke(original, receiver, [target, key]);
      if (!getTraceActive) return result;
      logStructural(reflectionTarget(target), key, "get_own_property_descriptor", result);
      return result;
    };
    const descriptors = (original, receiver, args) => {
      const target = rawTraceValue(args[0]);
      const result = invoke(original, receiver, [target]);
      if (!getTraceActive) return result;
      const name = reflectionTarget(target);
      for (const key of ReflectIntrinsic.ownKeys(result))
        logStructural(name, key, "get_own_property_descriptor", result[key]);
      return result;
    };
    const prototype = (original, receiver, args) => {
      const target = rawTraceValue(args[0]);
      const result = invoke(original, receiver, [target]);
      if (!getTraceActive) return result;
      logStructural(reflectionTarget(target), "[[Prototype]]", "get_prototype_of", result);
      return result;
    };
    const has = (original, receiver, args) => {
      const target = rawTraceValue(args[0]);
      const result = invoke(original, receiver, [target, args[1]]);
      if (!getTraceActive) return result;
      logStructural(reflectionTarget(target), args[1], "has", result);
      return result;
    };
    replace(ObjectIntrinsic, "getOwnPropertyNames", "own_keys", ownKeys);
    replace(ObjectIntrinsic, "getOwnPropertySymbols", "own_keys", ownKeys);
    replace(ObjectIntrinsic, "keys", "own_keys", ownKeys);
    replace(ReflectIntrinsic, "ownKeys", "own_keys", ownKeys);
    replace(ObjectIntrinsic, "getOwnPropertyDescriptor", "get_own_property_descriptor", descriptor);
    replace(ReflectIntrinsic, "getOwnPropertyDescriptor", "get_own_property_descriptor", descriptor);
    replace(ObjectIntrinsic, "getOwnPropertyDescriptors", "get_own_property_descriptor", descriptors);
    replace(ObjectIntrinsic, "getPrototypeOf", "get_prototype_of", prototype);
    replace(ReflectIntrinsic, "getPrototypeOf", "get_prototype_of", prototype);
    replace(ReflectIntrinsic, "has", "has", has);
  };

  data(globalObject, "__yatouTakeHostLog", () => hostLog.splice(0), false);
  data(globalObject, "__yatouSetGetTraceActive", active => {
    getTraceActive = getTraceConfig.enabled && booleanValue(active);
  }, false);
  data(globalObject, "__yatouRecordGlobalGet", (member, outcome, threw = false) => {
    member = stringValue(member);
    logGet("globalThis", member, outcome, !!threw);
    if (member === "eval") return outcome;
    return observeTraceValue(
      outcome,
      member === "trustedTypes" ? "TrustedTypePolicyFactory.prototype" : member
    );
  }, false);
  data(globalObject, "__yatouGetTraceStats", () => ObjectIntrinsic.freeze({
    enabled: getTraceConfig.enabled,
    active: getTraceActive,
    maxEvents: getTraceConfig.maxEvents,
    events: getTraceEvents,
    dropped: getTraceDropped
  }), false);
  data(globalObject, "__yatouInstallResource", resource => {
    resources.set(stringValue(resource.url), ObjectIntrinsic.freeze({
      url: stringValue(resource.url),
      status: numberValue(resource.status),
      headers: ObjectIntrinsic.freeze({ ...(resource.headers || {}) }),
      body: ObjectIntrinsic.freeze(ArrayIntrinsic.from(resource.body || [], value => numberValue(value) & 255)),
      body_sha256: stringValue(resource.body_sha256)
    }));
  }, false);

  const eventState = new WeakMapIntrinsic();
  const eventData = event => {
    const state = stateFor(eventState, event);
    if (!state) throw new TypeErrorIntrinsic("Illegal invocation");
    return state;
  };

  class Event {
    constructor(type, init = {}) {
      eventState.set(this, {
        type: stringValue(type), bubbles: booleanValue(init.bubbles),
        cancelable: booleanValue(init.cancelable), composed: booleanValue(init.composed),
        defaultPrevented: false, target: null, currentTarget: null, eventPhase: 0,
        isTrusted: false, timeStamp: performance.now(), stopped: false,
        immediateStopped: false, detail: null
      });
    }
    get type() { return eventData(this).type; }
    get bubbles() { return eventData(this).bubbles; }
    get cancelable() { return eventData(this).cancelable; }
    get composed() { return eventData(this).composed; }
    get defaultPrevented() { return eventData(this).defaultPrevented; }
    get target() { return eventData(this).target; }
    get currentTarget() { return eventData(this).currentTarget; }
    get eventPhase() { return eventData(this).eventPhase; }
    get isTrusted() { return eventData(this).isTrusted; }
    get timeStamp() { return eventData(this).timeStamp; }
    preventDefault() { const state = eventData(this); if (state.cancelable) state.defaultPrevented = true; }
    stopPropagation() { eventData(this).stopped = true; }
    stopImmediatePropagation() {
      const state = eventData(this); state.stopped = true; state.immediateStopped = true;
    }
  }
  data(Event, "NONE", 0);
  data(Event, "CAPTURING_PHASE", 1);
  data(Event, "AT_TARGET", 2);
  data(Event, "BUBBLING_PHASE", 3);

  class CustomEvent extends Event {
    constructor(type, init = {}) {
      super(type, init);
      eventData(this).detail = init.detail === undefined ? null : init.detail;
    }
    get detail() { return eventData(this).detail; }
  }

  class UIEvent extends Event {
    constructor(type, init = {}) {
      super(type, init);
      const state = eventData(this);
      state.view = init.view || null;
      state.detail = numberValue(init.detail || 0);
      state.which = numberValue(init.which || 0);
    }
    get view() { return eventData(this).view; }
    get detail() { return eventData(this).detail; }
    get which() { return eventData(this).which; }
  }

  class MouseEvent extends UIEvent {
    constructor(type, init = {}) {
      super(type, init);
      for (const key of ["screenX", "screenY", "clientX", "clientY", "button", "buttons", "movementX", "movementY"])
        eventData(this)[key] = numberValue(init[key] || 0);
      for (const key of ["ctrlKey", "shiftKey", "altKey", "metaKey"])
        eventData(this)[key] = booleanValue(init[key]);
    }
  }

  const eventTargetState = new WeakMapIntrinsic();
  const listenersFor = target => {
    let listeners = stateFor(eventTargetState, target);
    if (!listeners) { listeners = new MapIntrinsic(); eventTargetState.set(target, listeners); }
    return listeners;
  };

  class EventTarget {
    constructor() { listenersFor(this); }
    addEventListener(type, callback, options = false) {
      type = stringValue(type);
      logApi("EventTarget.prototype", "addEventListener", "call", [type, callback, options], undefined);
      if (callback == null) return;
      const listeners = listenersFor(this);
      const entries = listeners.get(type) || [];
      const capture = typeof options === "object" ? booleanValue(options.capture) : booleanValue(options);
      if (!entries.some(entry => entry.callback === callback && entry.capture === capture))
        entries.push({ callback, capture, once: booleanValue(options && options.once) });
      listeners.set(type, entries);
    }
    removeEventListener(type, callback, options = false) {
      type = stringValue(type);
      logApi("EventTarget.prototype", "removeEventListener", "call", [type, callback, options], undefined);
      const capture = typeof options === "object" ? booleanValue(options.capture) : booleanValue(options);
      const listeners = listenersFor(this);
      const entries = listeners.get(type) || [];
      listeners.set(type, entries.filter(entry => entry.callback !== callback || entry.capture !== capture));
    }
    dispatchEvent(event) {
      if (!(event instanceof Event)) throw new TypeErrorIntrinsic("parameter 1 is not of type 'Event'");
      logApi("EventTarget.prototype", "dispatchEvent", "call", [event], true);
      const state = eventData(event);
      if (!state.target) state.target = this;
      state.currentTarget = this;
      state.eventPhase = Event.AT_TARGET;
      const entries = ArrayIntrinsic.from(listenersFor(this).get(event.type) || []);
      for (const entry of entries) {
        if (entry.once) this.removeEventListener(event.type, entry.callback, { capture: entry.capture });
        if (typeof entry.callback === "function") entry.callback.call(this, event);
        else if (entry.callback && typeof entry.callback.handleEvent === "function") entry.callback.handleEvent(event);
        if (state.immediateStopped) break;
      }
      state.eventPhase = Event.NONE;
      state.currentTarget = null;
      return !state.defaultPrevented;
    }
  }

  const defineIndexedValue = (object, key, value, enumerable) =>
    ObjectIntrinsic.defineProperty(object, key, {
      value,
      writable: false,
      enumerable,
      configurable: true
    });

  const pluginArrayState = new WeakMapIntrinsic();
  const pluginState = new WeakMapIntrinsic();
  const mimeTypeArrayState = new WeakMapIntrinsic();
  const mimeTypeState = new WeakMapIntrinsic();
  const indexedState = (store, receiver) => {
    const state = stateFor(store, receiver);
    if (!state) throw new TypeErrorIntrinsic("Illegal invocation");
    return state;
  };

  class PluginArray {
    constructor() { throw new TypeErrorIntrinsic("Illegal constructor"); }
    get length() { return indexedState(pluginArrayState, this).items.length; }
    item(index) { return indexedState(pluginArrayState, this).items[numberValue(index) >>> 0] || null; }
    namedItem(name) { return indexedState(pluginArrayState, this).named.get(stringValue(name)) || null; }
    refresh() {}
    [Symbol.iterator]() { return indexedState(pluginArrayState, this).items.values(); }
  }

  class Plugin {
    constructor() { throw new TypeErrorIntrinsic("Illegal constructor"); }
    get name() { return indexedState(pluginState, this).name; }
    get filename() { return indexedState(pluginState, this).filename; }
    get description() { return indexedState(pluginState, this).description; }
    get length() { return indexedState(pluginState, this).items.length; }
    item(index) { return indexedState(pluginState, this).items[numberValue(index) >>> 0] || null; }
    namedItem(name) { return indexedState(pluginState, this).named.get(stringValue(name)) || null; }
    [Symbol.iterator]() { return indexedState(pluginState, this).items.values(); }
  }

  class MimeTypeArray {
    constructor() { throw new TypeErrorIntrinsic("Illegal constructor"); }
    get length() { return indexedState(mimeTypeArrayState, this).items.length; }
    item(index) { return indexedState(mimeTypeArrayState, this).items[numberValue(index) >>> 0] || null; }
    namedItem(name) { return indexedState(mimeTypeArrayState, this).named.get(stringValue(name)) || null; }
    [Symbol.iterator]() { return indexedState(mimeTypeArrayState, this).items.values(); }
  }

  class MimeType {
    constructor() { throw new TypeErrorIntrinsic("Illegal constructor"); }
    get type() { return indexedState(mimeTypeState, this).type; }
    get suffixes() { return indexedState(mimeTypeState, this).suffixes; }
    get description() { return indexedState(mimeTypeState, this).description; }
    get enabledPlugin() { return indexedState(mimeTypeState, this).enabledPlugin; }
  }

  const makeMimeType = (type, enabledPlugin = null) => {
    const value = ObjectIntrinsic.create(MimeType.prototype);
    mimeTypeState.set(value, {
      type,
      suffixes: "pdf",
      description: "Portable Document Format",
      enabledPlugin
    });
    return value;
  };
  const populateIndexed = (value, state, names) => {
    state.items.forEach((item, index) => defineIndexedValue(value, stringValue(index), item, true));
    names.forEach((name, index) => defineIndexedValue(value, name, state.items[index], false));
    state.named = new MapIntrinsic(names.map((name, index) => [name, state.items[index]]));
    return value;
  };
  const makePlugin = name => {
    const value = ObjectIntrinsic.create(Plugin.prototype);
    const state = {
      name,
      filename: "internal-pdf-viewer",
      description: "Portable Document Format",
      items: [],
      named: null
    };
    pluginState.set(value, state);
    state.items = [makeMimeType("application/pdf", value), makeMimeType("text/pdf", value)];
    return populateIndexed(value, state, ["application/pdf", "text/pdf"]);
  };
  const makePluginArray = () => {
    const value = ObjectIntrinsic.create(PluginArray.prototype);
    const names = [
      "PDF Viewer",
      "Chrome PDF Viewer",
      "Chromium PDF Viewer",
      "Microsoft Edge PDF Viewer",
      "WebKit built-in PDF"
    ];
    const state = { items: names.map(makePlugin), named: null };
    pluginArrayState.set(value, state);
    return populateIndexed(value, state, names);
  };
  const makeMimeTypeArray = enabledPlugin => {
    const value = ObjectIntrinsic.create(MimeTypeArray.prototype);
    const names = ["application/pdf", "text/pdf"];
    const state = { items: names.map(type => makeMimeType(type, enabledPlugin)), named: null };
    mimeTypeArrayState.set(value, state);
    return populateIndexed(value, state, names);
  };

  const permissionStatusState = new WeakMapIntrinsic();
  class PermissionStatus extends EventTarget {
    constructor() { throw new TypeErrorIntrinsic("Illegal constructor"); }
    get name() { return indexedState(permissionStatusState, this).name; }
    get state() { return indexedState(permissionStatusState, this).state; }
    get onchange() { return indexedState(permissionStatusState, this).onchange; }
    set onchange(value) { indexedState(permissionStatusState, this).onchange = value; }
  }
  const makePermissionStatus = (name, state) => {
    const value = ObjectIntrinsic.create(PermissionStatus.prototype);
    permissionStatusState.set(value, { name, state, onchange: null });
    listenersFor(value);
    return value;
  };
  const permissionStates = ObjectIntrinsic.freeze({
    "clipboard-read": "prompt",
    "clipboard-write": "granted",
    geolocation: "prompt",
    notifications: "prompt",
    camera: "prompt",
    microphone: "prompt"
  });
  class Permissions {
    constructor() { throw new TypeErrorIntrinsic("Illegal constructor"); }
    query(descriptor) {
      const name = descriptor && stringValue(descriptor.name || "");
      if (!name) return PromiseIntrinsic.reject(new TypeErrorIntrinsic("Permission descriptor requires a name"));
      return PromiseIntrinsic.resolve(makePermissionStatus(name, permissionStates[name] || "prompt"));
    }
  }

  const networkInformationState = new WeakMapIntrinsic();
  class NetworkInformation extends EventTarget {
    constructor() { throw new TypeErrorIntrinsic("Illegal constructor"); }
    get onchange() { return indexedState(networkInformationState, this).onchange; }
    set onchange(value) { indexedState(networkInformationState, this).onchange = value; }
    get effectiveType() { return indexedState(networkInformationState, this).effectiveType; }
    get rtt() { return indexedState(networkInformationState, this).rtt; }
    get downlink() { return indexedState(networkInformationState, this).downlink; }
    get saveData() { return indexedState(networkInformationState, this).saveData; }
  }

  const screenOrientationState = new WeakMapIntrinsic();
  class ScreenOrientation extends EventTarget {
    constructor() { throw new TypeErrorIntrinsic("Illegal constructor"); }
    get angle() { return indexedState(screenOrientationState, this).angle; }
    get type() { return indexedState(screenOrientationState, this).type; }
    get onchange() { return indexedState(screenOrientationState, this).onchange; }
    set onchange(value) { indexedState(screenOrientationState, this).onchange = value; }
    lock() { return PromiseIntrinsic.resolve(); }
    unlock() {}
  }

  const mediaQueryListState = new WeakMapIntrinsic();
  class MediaQueryList extends EventTarget {
    constructor() { throw new TypeErrorIntrinsic("Illegal constructor"); }
    get media() { return indexedState(mediaQueryListState, this).media; }
    get matches() { return indexedState(mediaQueryListState, this).matches; }
    get onchange() { return indexedState(mediaQueryListState, this).onchange; }
    set onchange(value) { indexedState(mediaQueryListState, this).onchange = value; }
    addListener(callback) { this.addEventListener("change", callback); }
    removeListener(callback) { this.removeEventListener("change", callback); }
  }

  const visualViewportState = new WeakMapIntrinsic();
  class VisualViewport extends EventTarget {
    constructor() { throw new TypeErrorIntrinsic("Illegal constructor"); }
    get offsetLeft() { return 0; }
    get offsetTop() { return 0; }
    get pageLeft() { return 0; }
    get pageTop() { return 0; }
    get width() { return indexedState(visualViewportState, this).width; }
    get height() { return indexedState(visualViewportState, this).height; }
    get scale() { return 1; }
    get onresize() { return indexedState(visualViewportState, this).onresize; }
    set onresize(value) { indexedState(visualViewportState, this).onresize = value; }
    get onscroll() { return indexedState(visualViewportState, this).onscroll; }
    set onscroll(value) { indexedState(visualViewportState, this).onscroll = value; }
    get onscrollend() { return indexedState(visualViewportState, this).onscrollend; }
    set onscrollend(value) { indexedState(visualViewportState, this).onscrollend = value; }
  }

  const performanceTimingState = new WeakMapIntrinsic();
  const performanceTimingKeys = [
    "connectStart", "secureConnectionStart", "unloadEventEnd", "domainLookupStart",
    "domainLookupEnd", "responseStart", "connectEnd", "responseEnd", "requestStart",
    "domLoading", "redirectStart", "loadEventEnd", "domComplete", "navigationStart",
    "loadEventStart", "domContentLoadedEventEnd", "unloadEventStart", "redirectEnd",
    "domInteractive", "fetchStart", "domContentLoadedEventStart"
  ];
  class PerformanceTiming {
    constructor() { throw new TypeErrorIntrinsic("Illegal constructor"); }
    toJSON() {
      const state = indexedState(performanceTimingState, this);
      return ObjectIntrinsic.fromEntries(performanceTimingKeys.map(key => [key, state[key]]));
    }
  }
  for (const key of performanceTimingKeys) {
    ObjectIntrinsic.defineProperty(PerformanceTiming.prototype, key, {
      get() { return indexedState(performanceTimingState, this)[key]; },
      enumerable: true,
      configurable: true
    });
  }

  const performanceNavigationState = new WeakMapIntrinsic();
  class PerformanceNavigation {
    constructor() { throw new TypeErrorIntrinsic("Illegal constructor"); }
    get type() { return indexedState(performanceNavigationState, this).type; }
    get redirectCount() { return indexedState(performanceNavigationState, this).redirectCount; }
    toJSON() { return { type: this.type, redirectCount: this.redirectCount }; }
  }
  for (const [key, value] of [["TYPE_NAVIGATE", 0], ["TYPE_RELOAD", 1], ["TYPE_BACK_FORWARD", 2], ["TYPE_RESERVED", 255]]) {
    ObjectIntrinsic.defineProperty(PerformanceNavigation.prototype, key, {
      value,
      writable: false,
      enumerable: true,
      configurable: false
    });
  }

  const memoryInfoState = new WeakMapIntrinsic();
  const MemoryInfoPrototype = ObjectIntrinsic.create(ObjectIntrinsic.prototype);
  for (const key of ["totalJSHeapSize", "usedJSHeapSize", "jsHeapSizeLimit"]) {
    ObjectIntrinsic.defineProperty(MemoryInfoPrototype, key, {
      get() { return indexedState(memoryInfoState, this)[key]; },
      enumerable: true,
      configurable: true
    });
  }
  ObjectIntrinsic.defineProperty(MemoryInfoPrototype, Symbol.toStringTag, {
    value: "MemoryInfo",
    writable: false,
    enumerable: false,
    configurable: true
  });

  const nodeState = new WeakMapIntrinsic();
  const nodeData = node => {
    const state = stateFor(nodeState, node);
    if (!state) throw new TypeErrorIntrinsic("Illegal invocation");
    return state;
  };

  class Node extends EventTarget {
    constructor(nodeType, nodeName, ownerDocument = null) {
      super();
      nodeState.set(this, { nodeType, nodeName, ownerDocument, parentNode: null, childNodes: [], text: "" });
    }
    get nodeType() { return nodeData(this).nodeType; }
    get nodeName() { return nodeData(this).nodeName; }
    get ownerDocument() { return nodeData(this).ownerDocument; }
    get parentNode() { return nodeData(this).parentNode; }
    get parentElement() { const parent = this.parentNode; return parent instanceof Element ? parent : null; }
    get childNodes() { return nodeData(this).childNodes; }
    get baseURI() { return this.ownerDocument ? this.ownerDocument.URL : config.url; }
    get nodeValue() { return this.nodeType === Node.TEXT_NODE ? nodeData(this).text : null; }
    set nodeValue(value) { if (this.nodeType === Node.TEXT_NODE) nodeData(this).text = stringValue(value ?? ""); }
    get firstChild() { return this.childNodes[0] || null; }
    get lastChild() { return this.childNodes[this.childNodes.length - 1] || null; }
    get previousSibling() {
      if (!this.parentNode) return null;
      const index = this.parentNode.childNodes.indexOf(this);
      return index > 0 ? this.parentNode.childNodes[index - 1] : null;
    }
    get nextSibling() {
      if (!this.parentNode) return null;
      const index = this.parentNode.childNodes.indexOf(this);
      return index >= 0 ? this.parentNode.childNodes[index + 1] || null : null;
    }
    get isConnected() {
      let current = this;
      while (current) {
        if (current.nodeType === Node.DOCUMENT_NODE) return true;
        current = current.parentNode;
      }
      return false;
    }
    appendChild(child) {
      if (!(child instanceof Node)) throw new TypeErrorIntrinsic("parameter 1 is not of type 'Node'");
      if (child === this) throw new ErrorIntrinsic("HierarchyRequestError");
      if (child.parentNode) child.parentNode.removeChild(child);
      this.childNodes.push(child);
      nodeData(child).parentNode = this;
      return child;
    }
    insertBefore(child, reference) {
      if (reference == null) return this.appendChild(child);
      const index = this.childNodes.indexOf(reference);
      if (index < 0) throw new ErrorIntrinsic("NotFoundError");
      if (child.parentNode) child.parentNode.removeChild(child);
      this.childNodes.splice(index, 0, child);
      nodeData(child).parentNode = this;
      return child;
    }
    removeChild(child) {
      const index = this.childNodes.indexOf(child);
      if (index < 0) throw new ErrorIntrinsic("NotFoundError");
      this.childNodes.splice(index, 1);
      nodeData(child).parentNode = null;
      return child;
    }
    replaceChild(next, previous) {
      this.insertBefore(next, previous);
      this.removeChild(previous);
      return previous;
    }
    remove() { if (this.parentNode) this.parentNode.removeChild(this); }
    contains(candidate) {
      for (let current = candidate; current; current = current.parentNode)
        if (current === this) return true;
      return false;
    }
    cloneNode(deep = false) {
      const clone = this.nodeType === Node.TEXT_NODE
        ? new Text(this.data, this.ownerDocument)
        : this.ownerDocument.createElement(this.localName || "div");
      if (this.attributes) for (const [name, value] of this.attributes) clone.setAttribute(name, value);
      if (deep) for (const child of this.childNodes) clone.appendChild(child.cloneNode(true));
      return clone;
    }
    get textContent() {
      if (this.nodeType === Node.TEXT_NODE) return nodeData(this).text;
      return this.childNodes.map(child => child.textContent).join("");
    }
    set textContent(value) {
      this.childNodes.splice(0);
      const text = stringValue(value ?? "");
      if (this.nodeType === Node.TEXT_NODE) nodeData(this).text = text;
      else if (text) this.appendChild(new Text(text, this.ownerDocument));
    }
  }
  ObjectIntrinsic.assign(Node, {
    ELEMENT_NODE: 1,
    TEXT_NODE: 3,
    DOCUMENT_NODE: 9,
    DOCUMENT_FRAGMENT_NODE: 11
  });

  class CharacterData extends Node {
    constructor(dataValue = "", ownerDocument = null, nodeName = "#text") {
      super(Node.TEXT_NODE, nodeName, ownerDocument);
      nodeData(this).text = stringValue(dataValue);
    }
    get data() { return nodeData(this).text; }
    set data(value) { nodeData(this).text = stringValue(value); }
    get length() { return nodeData(this).text.length; }
  }

  class Text extends CharacterData {
    constructor(dataValue = "", ownerDocument = null) {
      super(dataValue, ownerDocument, "#text");
    }
  }

  class DocumentFragment extends Node {
    constructor(ownerDocument = null) { super(Node.DOCUMENT_FRAGMENT_NODE, "#document-fragment", ownerDocument); }
    querySelector(selector) { return querySelectorFrom(this, selector, false); }
    querySelectorAll(selector) { return querySelectorFrom(this, selector, true); }
  }

  class DOMTokenList {
    constructor(element) { this._element = element; }
    _tokens() { return this._element.className.trim() ? this._element.className.trim().split(/\s+/) : []; }
    _write(tokens) { this._element.className = ArrayIntrinsic.from(new SetIntrinsic(tokens)).join(" "); }
    get length() { return this._tokens().length; }
    contains(token) { return this._tokens().includes(stringValue(token)); }
    add(...tokens) { this._write(this._tokens().concat(tokens.map(stringValue))); }
    remove(...tokens) { const remove = new SetIntrinsic(tokens.map(stringValue)); this._write(this._tokens().filter(token => !remove.has(token))); }
    toggle(token, force) {
      token = stringValue(token);
      const present = this.contains(token);
      if (force === true || (!present && force !== false)) { this.add(token); return true; }
      if (present) this.remove(token);
      return false;
    }
    replace(previous, next) {
      const tokens = this._tokens();
      const index = tokens.indexOf(stringValue(previous));
      if (index < 0) return false;
      tokens[index] = stringValue(next); this._write(tokens); return true;
    }
    item(index) { return this._tokens()[numberValue(index)] || null; }
    toString() { return this._element.className; }
    [Symbol.iterator]() { return this._tokens()[Symbol.iterator](); }
  }

  const cssName = name => stringValue(name).replace(/[A-Z]/g, value => `-${value.toLowerCase()}`);
  class CSSStyleDeclaration {
    constructor() { this._values = new MapIntrinsic(); this._priorities = new MapIntrinsic(); }
    get length() { return this._values.size; }
    item(index) { return ArrayIntrinsic.from(this._values.keys())[numberValue(index)] || ""; }
    setProperty(name, value, priority = "") {
      name = cssName(name).trim();
      if (!name) return;
      this._values.set(name, stringValue(value));
      this._priorities.set(name, stringValue(priority).toLowerCase() === "important" ? "important" : "");
    }
    getPropertyValue(name) { return this._values.get(cssName(name).trim()) || ""; }
    getPropertyPriority(name) { return this._priorities.get(cssName(name).trim()) || ""; }
    removeProperty(name) {
      name = cssName(name).trim();
      const previous = this.getPropertyValue(name);
      this._values.delete(name); this._priorities.delete(name);
      return previous;
    }
    get cssText() {
      return ArrayIntrinsic.from(this._values, ([name, value]) => `${name}: ${value}${this.getPropertyPriority(name) ? " !important" : ""};`).join(" ");
    }
    set cssText(value) {
      this._values.clear(); this._priorities.clear();
      for (const declaration of stringValue(value).split(";")) {
        const separator = declaration.indexOf(":");
        if (separator < 0) continue;
        const name = declaration.slice(0, separator).trim();
        let result = declaration.slice(separator + 1).trim();
        const important = /!important\s*$/i.test(result);
        result = result.replace(/!important\s*$/i, "").trim();
        this.setProperty(name, result, important ? "important" : "");
      }
    }
  }
  const styleProxy = style => new ProxyIntrinsic(style, {
    get(target, key, receiver) {
      if (typeof key === "string" && !(key in target)) return target.getPropertyValue(key);
      return ReflectIntrinsic.get(target, key, receiver);
    },
    set(target, key, value, receiver) {
      if (typeof key === "string" && !(key in target)) { target.setProperty(key, value); return true; }
      return ReflectIntrinsic.set(target, key, value, receiver);
    },
    ownKeys(target) { return ReflectIntrinsic.ownKeys(target).concat(ArrayIntrinsic.from(target._values.keys())); },
    getOwnPropertyDescriptor(target, key) {
      return ReflectIntrinsic.getOwnPropertyDescriptor(target, key) || { configurable: true, enumerable: true, writable: true, value: target.getPropertyValue(key) };
    }
  });

  const descendants = root => {
    const output = [];
    const visit = node => {
      for (const child of node.childNodes || []) {
        if (child.nodeType === Node.ELEMENT_NODE) output.push(child);
        visit(child);
      }
    };
    visit(root);
    return output;
  };
  const matchesSimple = (element, selector) => {
    selector = stringValue(selector).trim();
    if (!selector) return false;
    const attribute = selector.match(/^(.*)?\[([\w:-]+)(?:=["']?([^\]"']+)["']?)?\]$/);
    if (attribute) {
      if (attribute[1] && !matchesSimple(element, attribute[1])) return false;
      if (!element.hasAttribute(attribute[2])) return false;
      return attribute[3] === undefined || element.getAttribute(attribute[2]) === attribute[3];
    }
    const id = selector.match(/#([\w-]+)/);
    const classes = ArrayIntrinsic.from(selector.matchAll(/\.([\w-]+)/g), match => match[1]);
    const tag = selector.match(/^[a-zA-Z][\w-]*/)?.[0];
    return (!tag || element.localName === tag.toLowerCase())
      && (!id || element.id === id[1])
      && classes.every(name => element.classList.contains(name));
  };
  const querySelectorFrom = (root, selector, all) => {
    const selectors = stringValue(selector).split(",").map(value => value.trim()).filter(booleanValue);
    const found = descendants(root).filter(element => selectors.some(value => matchesSimple(element, value)));
    return all ? found : found[0] || null;
  };

  const elementState = new WeakMapIntrinsic();
  const elementData = value => stateFor(elementState, value);

  class Element extends Node {
    constructor(tagName, ownerDocument = null) {
      const upper = stringValue(tagName).toUpperCase();
      super(Node.ELEMENT_NODE, upper, ownerDocument);
      const state = {
        tagName: upper, localName: upper.toLowerCase(), namespaceURI: "http://www.w3.org/1999/xhtml",
        attributes: new MapIntrinsic(), style: styleProxy(new CSSStyleDeclaration()),
        classList: null, dataset: ObjectIntrinsic.create(null), contentWindow: null
      };
      elementState.set(this, state);
      state.classList = new DOMTokenList(this);
      state.contentWindow = state.localName === "iframe" ? globalObject : null;
    }
    get tagName() { return elementData(this).tagName; }
    get localName() { return elementData(this).localName; }
    get namespaceURI() { return elementData(this).namespaceURI; }
    get attributes() { return elementData(this).attributes; }
    get style() { return elementData(this).style; }
    get classList() { return elementData(this).classList; }
    get dataset() { return elementData(this).dataset; }
    get contentWindow() { return elementData(this).contentWindow; }
    get children() { return this.childNodes.filter(child => child.nodeType === Node.ELEMENT_NODE); }
    get childElementCount() { return this.children.length; }
    get firstElementChild() { return this.children[0] || null; }
    get lastElementChild() { return this.children[this.children.length - 1] || null; }
    get id() { return this.getAttribute("id") || ""; }
    set id(value) { this.setAttribute("id", value); }
    get className() { return this.getAttribute("class") || ""; }
    set className(value) { this.setAttribute("class", value); }
    append(...nodes) {
      for (const node of nodes) this.appendChild(node instanceof Node ? node : new Text(stringValue(node), this.ownerDocument));
    }
    prepend(...nodes) {
      let reference = this.firstChild;
      for (const node of nodes) {
        const value = node instanceof Node ? node : new Text(stringValue(node), this.ownerDocument);
        this.insertBefore(value, reference);
        if (reference === null) reference = value.nextSibling;
      }
    }
    setAttribute(name, value) {
      name = stringValue(name).toLowerCase();
      const text = stringValue(value);
      this.attributes.set(name, text);
      if (name.startsWith("data-")) this.dataset[name.slice(5).replace(/-([a-z])/g, (_, letter) => letter.toUpperCase())] = text;
    }
    getAttribute(name) { name = stringValue(name).toLowerCase(); return this.attributes.has(name) ? this.attributes.get(name) : null; }
    hasAttribute(name) { return this.attributes.has(stringValue(name).toLowerCase()); }
    removeAttribute(name) { this.attributes.delete(stringValue(name).toLowerCase()); }
    toggleAttribute(name, force) {
      const present = this.hasAttribute(name);
      if (force === true || (!present && force !== false)) { this.setAttribute(name, ""); return true; }
      if (present) this.removeAttribute(name);
      return false;
    }
    matches(selector) { return matchesSimple(this, selector); }
    closest(selector) { for (let node = this; node && node.nodeType === 1; node = node.parentNode) if (node.matches(selector)) return node; return null; }
    querySelector(selector) { return querySelectorFrom(this, selector, false); }
    querySelectorAll(selector) { return querySelectorFrom(this, selector, true); }
    getElementsByTagName(name) {
      name = stringValue(name).toLowerCase();
      return descendants(this).filter(element => name === "*" || element.localName === name);
    }
    getBoundingClientRect() {
      return ObjectIntrinsic.freeze({ x: 0, y: 0, top: 0, left: 0, right: 0, bottom: 0, width: 0, height: 0, toJSON() { return { x: 0, y: 0, width: 0, height: 0, top: 0, right: 0, bottom: 0, left: 0 }; } });
    }
    get clientWidth() { return this === document.documentElement ? config.viewport.width : 0; }
    get clientHeight() { return this === document.documentElement ? config.viewport.height : 0; }
  }

  class HTMLElement extends Element {}
  class HTMLIFrameElement extends HTMLElement {
    // These members live on HTMLIFrameElement in Chrome, not Element.  Keep
    // them on the specialised prototype so generated Element descriptors can
    // be made exact without removing iframe realm access.
    get contentWindow() { return elementData(this).contentWindow; }
    get contentDocument() { return this.ownerDocument; }
  }
  const canvasState = new WeakMapIntrinsic();
  const canvasContextState = new WeakMapIntrinsic();
  class CanvasRenderingContext2D {
    constructor() { throw new TypeErrorIntrinsic("Illegal constructor"); }
    get canvas() { return indexedState(canvasContextState, this).canvas; }
    getContextAttributes() { return { alpha: true, colorSpace: "srgb", desynchronized: false, willReadFrequently: false }; }
    isContextLost() { return false; }
    getLineDash() { return []; }
    setLineDash() {}
    measureText(text) {
      return ObjectIntrinsic.freeze({ width: stringValue(text).length * 7 });
    }
  }
  class HTMLCanvasElement extends HTMLElement {
    constructor(tagName, ownerDocument) {
      super(tagName, ownerDocument);
      canvasState.set(this, { width: 300, height: 150, context2d: null });
    }
    get width() { return indexedState(canvasState, this).width; }
    set width(value) { indexedState(canvasState, this).width = numberValue(value) >>> 0; }
    get height() { return indexedState(canvasState, this).height; }
    set height(value) { indexedState(canvasState, this).height = numberValue(value) >>> 0; }
    getContext(kind) {
      if (stringValue(kind).toLowerCase() !== "2d") return null;
      const state = indexedState(canvasState, this);
      if (!state.context2d) {
        state.context2d = ObjectIntrinsic.create(CanvasRenderingContext2D.prototype);
        canvasContextState.set(state.context2d, { canvas: this });
      }
      return state.context2d;
    }
    toDataURL() { return "data:image/png;base64,"; }
  }

  const cookieJar = new MapIntrinsic();
  let activeLocation = null;
  const cookieUrl = () => {
    const href = activeLocation && activeLocation.href || config.url;
    const match = stringValue(href).match(/^([a-zA-Z][\w+.-]*:)(?:\/\/([^\/?#]*))?([^?#]*)/);
    const host = match && match[2] || "";
    return {
      secure: !!match && match[1].toLowerCase() === "https:",
      hostname: host.replace(/:\d+$/, "").toLowerCase(),
      pathname: match && match[3] || "/"
    };
  };
  const defaultCookiePath = pathname => {
    const index = pathname.lastIndexOf("/");
    return index <= 0 ? "/" : pathname.slice(0, index);
  };
  const cookieKey = cookie => `${cookie.name}\u0000${cookie.domain}\u0000${cookie.path}`;
  const normalizeCookie = input => {
    const url = cookieUrl();
    const cookie = {
      name: stringValue(input.name || "").trim(),
      value: stringValue(input.value ?? ""),
      domain: stringValue(input.domain || url.hostname).replace(/^\./, "").toLowerCase(),
      path: stringValue(input.path || defaultCookiePath(url.pathname)),
      secure: booleanValue(input.secure),
      httpOnly: booleanValue(input.httpOnly || input.http_only),
      sameSite: stringValue(input.sameSite || input.same_site || "Lax"),
      expires: input.expires == null ? null : numberValue(input.expires)
    };
    return cookie.name ? cookie : null;
  };
  const storeCookie = cookie => {
    cookie = normalizeCookie(cookie);
    if (!cookie) return;
    const key = cookieKey(cookie);
    if (cookie.expires !== null && cookie.expires <= config.time_origin_ms / 1000)
      cookieJar.delete(key);
    else cookieJar.set(key, cookie);
  };
  const visibleCookies = includeHttpOnly => {
    const url = cookieUrl();
    const nowSeconds = config.time_origin_ms / 1000;
    return ArrayIntrinsic.from(cookieJar.values()).filter(cookie => {
      if (cookie.expires !== null && cookie.expires <= nowSeconds) return false;
      const domain = url.hostname === cookie.domain || url.hostname.endsWith(`.${cookie.domain}`);
      const path = url.pathname.startsWith(cookie.path);
      return domain && path && (!cookie.secure || url.secure) && (includeHttpOnly || !cookie.httpOnly);
    });
  };
  const parseCookieAssignment = serialized => {
    const parts = stringValue(serialized).split(";").map(part => part.trim());
    const pair = parts.shift() || "";
    const separator = pair.indexOf("=");
    if (separator <= 0) return null;
    const url = cookieUrl();
    const cookie = {
      name: pair.slice(0, separator).trim(), value: pair.slice(separator + 1).trim(),
      domain: url.hostname, path: defaultCookiePath(url.pathname), secure: false,
      httpOnly: false, sameSite: "Lax", expires: null
    };
    for (const part of parts) {
      const split = part.indexOf("=");
      const name = (split < 0 ? part : part.slice(0, split)).trim().toLowerCase();
      const value = split < 0 ? "" : part.slice(split + 1).trim();
      if (name === "domain") cookie.domain = value.replace(/^\./, "").toLowerCase();
      else if (name === "path") cookie.path = value || "/";
      else if (name === "secure") cookie.secure = true;
      else if (name === "httponly") cookie.httpOnly = true;
      else if (name === "samesite") cookie.sameSite = value || "Lax";
      else if (name === "max-age") cookie.expires = config.time_origin_ms / 1000 + numberValue(value);
      else if (name === "expires") {
        const parsed = DateIntrinsic.parse(value);
        if (!numberValue.isNaN(parsed)) cookie.expires = parsed / 1000;
      }
    }
    return cookie;
  };

  const documentState = new WeakMapIntrinsic();
  const documentData = value => stateFor(documentState, value);

  class Document extends Node {
    constructor() {
      super(Node.DOCUMENT_NODE, "#document", null);
      const state = { documentElement: null, head: null, body: null };
      documentState.set(this, state);
      state.documentElement = this.createElement("html");
      state.head = this.createElement("head");
      state.body = this.createElement("body");
      this.appendChild(state.documentElement);
      state.documentElement.appendChild(state.head);
      state.documentElement.appendChild(state.body);
    }
    get URL() { return activeLocation ? activeLocation.href : config.url; }
    get documentURI() { return this.URL; }
    get referrer() { return ""; }
    get readyState() { return "complete"; }
    get visibilityState() { return "visible"; }
    get hidden() { return false; }
    get compatMode() { return "CSS1Compat"; }
    get characterSet() { return "UTF-8"; }
    get charset() { return "UTF-8"; }
    get inputEncoding() { return "UTF-8"; }
    get contentType() { return "text/html"; }
    get documentElement() { return documentData(this).documentElement; }
    get head() { return documentData(this).head; }
    get body() { return documentData(this).body; }
    set body(value) { documentData(this).body = value; }
    get currentScript() { return null; }
    get defaultView() { return globalObject; }
    createElement(tagName) {
      const name = stringValue(tagName).toLowerCase();
      if (name === "iframe") return new HTMLIFrameElement(name, this);
      if (name === "canvas") return new HTMLCanvasElement(name, this);
      return new HTMLElement(name, this);
    }
    createTextNode(value) { return new Text(value, this); }
    createDocumentFragment() { return new DocumentFragment(this); }
    getElementById(id) { return descendants(this).find(element => element.id === stringValue(id)) || null; }
    getElementsByTagName(name) {
      name = stringValue(name).toLowerCase();
      return descendants(this).filter(element => name === "*" || element.localName === name);
    }
    getElementsByClassName(name) {
      const tokens = stringValue(name).trim().split(/\s+/);
      return descendants(this).filter(element => tokens.every(token => element.classList.contains(token)));
    }
    querySelector(selector) { return querySelectorFrom(this, selector, false); }
    querySelectorAll(selector) { return querySelectorFrom(this, selector, true); }
    hasFocus() { return true; }
    get cookie() { return visibleCookies(false).map(cookie => `${cookie.name}=${cookie.value}`).join("; "); }
    set cookie(serialized) {
      const cookie = parseCookieAssignment(serialized);
      if (cookie) storeCookie(cookie);
      logApi("Document.prototype", "cookie", "set", [serialized], undefined);
    }
  }

  class Storage {
    constructor(name) { this._name = name; this._entries = new MapIntrinsic(); }
    get length() { return this._entries.size; }
    key(index) { return ArrayIntrinsic.from(this._entries.keys())[numberValue(index)] ?? null; }
    getItem(key) {
      key = stringValue(key); const value = this._entries.has(key) ? this._entries.get(key) : null;
      logApi("Storage.prototype", "getItem", "call", [key], value); return value;
    }
    setItem(key, value) {
      key = stringValue(key); value = stringValue(value); this._entries.set(key, value);
      logApi("Storage.prototype", "setItem", "call", [key, value], undefined);
    }
    removeItem(key) { key = stringValue(key); this._entries.delete(key); logApi("Storage.prototype", "removeItem", "call", [key], undefined); }
    clear() { this._entries.clear(); logApi("Storage.prototype", "clear", "call", [], undefined); }
  }

  class Headers {
    constructor(init = {}) {
      this._entries = new MapIntrinsic();
      if (init instanceof Headers) for (const [key, value] of init) this.set(key, value);
      else if (ArrayIntrinsic.isArray(init)) for (const [key, value] of init) this.append(key, value);
      else for (const [key, value] of ObjectIntrinsic.entries(init || {})) this.set(key, value);
    }
    append(name, value) { name = stringValue(name).toLowerCase(); value = stringValue(value); this._entries.set(name, this._entries.has(name) ? `${this._entries.get(name)}, ${value}` : value); }
    set(name, value) { this._entries.set(stringValue(name).toLowerCase(), stringValue(value)); }
    get(name) { return this._entries.get(stringValue(name).toLowerCase()) ?? null; }
    has(name) { return this._entries.has(stringValue(name).toLowerCase()); }
    delete(name) { this._entries.delete(stringValue(name).toLowerCase()); }
    entries() { return this._entries.entries(); }
    keys() { return this._entries.keys(); }
    values() { return this._entries.values(); }
    [Symbol.iterator]() { return this.entries(); }
  }

  const utf8Decode = bytes => {
    let output = "";
    for (let index = 0; index < bytes.length;) {
      const first = bytes[index++];
      if (first < 128) { output += stringValue.fromCharCode(first); continue; }
      if ((first & 224) === 192) {
        const second = bytes[index++] ?? 0; output += stringValue.fromCharCode(((first & 31) << 6) | (second & 63)); continue;
      }
      if ((first & 240) === 224) {
        const second = bytes[index++] ?? 0, third = bytes[index++] ?? 0;
        output += stringValue.fromCharCode(((first & 15) << 12) | ((second & 63) << 6) | (third & 63)); continue;
      }
      const second = bytes[index++] ?? 0, third = bytes[index++] ?? 0, fourth = bytes[index++] ?? 0;
      let point = ((first & 7) << 18) | ((second & 63) << 12) | ((third & 63) << 6) | (fourth & 63);
      point -= 0x10000; output += stringValue.fromCharCode(0xD800 + (point >> 10), 0xDC00 + (point & 1023));
    }
    return output;
  };

  const responseState = new WeakMapIntrinsic();
  const responseData = response => {
    const state = stateFor(responseState, response);
    if (!state) throw new TypeErrorIntrinsic("Illegal invocation");
    return state;
  };

  class Response {
    constructor(body = [], init = {}) {
      responseState.set(this, {
        bodyBytes: ArrayIntrinsic.from(body || [], value => numberValue(value) & 255),
        status: numberValue(init.status ?? 200), statusText: stringValue(init.statusText || ""),
        headers: new Headers(init.headers || {}), url: stringValue(init.url || ""),
        type: "basic", redirected: false, bodyUsed: false, body: null
      });
    }
    get status() { return responseData(this).status; }
    get statusText() { return responseData(this).statusText; }
    get headers() { return responseData(this).headers; }
    get url() { return responseData(this).url; }
    get type() { return responseData(this).type; }
    get redirected() { return responseData(this).redirected; }
    get bodyUsed() { return responseData(this).bodyUsed; }
    get body() { return responseData(this).body; }
    get ok() { const status = responseData(this).status; return status >= 200 && status <= 299; }
    async text() { const state = responseData(this); state.bodyUsed = true; return utf8Decode(state.bodyBytes); }
    async json() { return JSONIntrinsic.parse(await this.text()); }
    async arrayBuffer() {
      const state = responseData(this); state.bodyUsed = true;
      return Uint8ArrayIntrinsic.from(state.bodyBytes).buffer;
    }
    clone() {
      const state = responseData(this);
      return new Response(state.bodyBytes, {
        status: state.status, statusText: state.statusText,
        headers: ObjectIntrinsic.fromEntries(state.headers), url: state.url
      });
    }
  }

  async function fetch(input, init = {}) {
    const url = stringValue(input && input.url || input);
    const method = stringValue(init.method || input && input.method || "GET").toUpperCase();
    const resource = resources.get(url);
    if (!resource) {
      const error = new TypeErrorIntrinsic(`offline resource not found: ${url}`);
      logApi("globalThis", "fetch", "call", [url, init], error, true);
      throw error;
    }
    const requestId = `resource-${++requestSequence}`;
    log("resource_request", { request_id: requestId, method, url });
    log("resource_response", {
      request_id: requestId,
      status: resource.status,
      headers: resource.headers,
      body: resource.body,
      body_sha256: resource.body_sha256
    });
    const response = new Response(resource.body, { status: resource.status, headers: resource.headers, url });
    logApi("globalThis", "fetch", "call", [url, init], response);
    return response;
  }

  class XMLHttpRequest extends EventTarget {
    constructor() {
      super(); this.readyState = 0; this.status = 0; this.responseText = ""; this.response = "";
      this._method = "GET"; this._url = ""; this._async = true; this._requestHeaders = new Headers(); this._responseHeaders = new Headers();
    }
    open(method, url, async = true) { this._method = stringValue(method).toUpperCase(); this._url = stringValue(url); this._async = booleanValue(async); this.readyState = 1; }
    setRequestHeader(name, value) { this._requestHeaders.append(name, value); }
    getResponseHeader(name) { return this._responseHeaders.get(name); }
    getAllResponseHeaders() { return ArrayIntrinsic.from(this._responseHeaders, ([key, value]) => `${key}: ${value}\r\n`).join(""); }
    send() {
      const run = () => {
        const resource = resources.get(this._url);
        if (!resource) { this.readyState = 4; this.status = 0; this.dispatchEvent(new Event("error")); return; }
        const requestId = `resource-${++requestSequence}`;
        log("resource_request", { request_id: requestId, method: this._method, url: this._url });
        log("resource_response", { request_id: requestId, status: resource.status, headers: resource.headers, body: resource.body, body_sha256: resource.body_sha256 });
        this.status = resource.status; this._responseHeaders = new Headers(resource.headers);
        this.responseText = utf8Decode(resource.body); this.response = this.responseText; this.readyState = 4;
        this.dispatchEvent(new Event("readystatechange")); this.dispatchEvent(new Event("load")); this.dispatchEvent(new Event("loadend"));
      };
      if (this._async) setTimeout(run, 0); else run();
    }
    abort() { this.readyState = 0; this.dispatchEvent(new Event("abort")); }
  }

  const schedule = (callback, delay, repeating, args) => {
    const timerId = ++timerSequence;
    const delayMs = MathIntrinsic.max(0, numberValue(delay) || 0);
    timers.set(timerId, { callback, args, delayMs, dueMs: clockMs + delayMs, repeating });
    log("timer_schedule", { timer_id: timerId, delay_ms: delayMs, repeating });
    return timerId;
  };
  const setTimeoutHost = (callback, delay = 0, ...args) => schedule(callback, delay, false, args);
  const setIntervalHost = (callback, delay = 0, ...args) => schedule(callback, delay, true, args);
  const clearTimer = timerId => timers.delete(numberValue(timerId));
  const queueMicrotaskHost = callback => { if (typeof callback !== "function") throw new TypeErrorIntrinsic("callback is not a function"); microtasks.push(callback); };
  const drain = (limit = 1000) => {
    limit = MathIntrinsic.max(0, MathIntrinsic.min(100000, numberValue(limit) || 0));
    let callbacks = 0;
    while (callbacks < limit) {
      if (microtasks.length) {
        const callback = microtasks.shift(); callback(); callbacks += 1; continue;
      }
      const next = ArrayIntrinsic.from(timers, ([id, timer]) => ({ id, timer }))
        .sort((left, right) => left.timer.dueMs - right.timer.dueMs || left.id - right.id)[0];
      if (!next) break;
      clockMs = MathIntrinsic.max(clockMs, next.timer.dueMs);
      if (!next.timer.repeating) timers.delete(next.id);
      else next.timer.dueMs = clockMs + next.timer.delayMs;
      log("timer_fire", { timer_id: next.id });
      if (typeof next.timer.callback === "function") next.timer.callback(...next.timer.args);
      else (0, indirectEvalIntrinsic)(stringValue(next.timer.callback));
      callbacks += 1;
    }
    return { callbacks, pendingTimers: timers.size, pendingMicrotasks: microtasks.length, clockMs };
  };
  data(globalObject, "__yatouDrain", drain, false);

  for (const [constructor, name] of [
    [Event, "Event"],
    [CustomEvent, "CustomEvent"],
    [UIEvent, "UIEvent"],
    [MouseEvent, "MouseEvent"],
    [EventTarget, "EventTarget"],
    [Node, "Node"],
    [CharacterData, "CharacterData"],
    [Text, "Text"],
    [DocumentFragment, "DocumentFragment"],
    [DOMTokenList, "DOMTokenList"],
    [CSSStyleDeclaration, "CSSStyleDeclaration"],
    [Element, "Element"],
    [HTMLElement, "HTMLElement"],
    [HTMLIFrameElement, "HTMLIFrameElement"],
    [HTMLCanvasElement, "HTMLCanvasElement"],
    [Document, "Document"],
    [Storage, "Storage"],
    [Headers, "Headers"],
    [Response, "Response"],
    [XMLHttpRequest, "XMLHttpRequest"]
  ]) {
    registerTraceTarget(constructor, name);
    registerTraceTarget(constructor.prototype, `${name}.prototype`);
  }

  for (const name of [
    "TrustedHTML",
    "TrustedScript",
    "TrustedScriptURL",
    "TrustedTypePolicy",
    "TrustedTypePolicyFactory"
  ]) {
    const descriptor = ObjectIntrinsic.getOwnPropertyDescriptor(globalObject, name);
    const constructor = descriptor && ObjectIntrinsic.prototype.hasOwnProperty.call(descriptor, "value")
      ? descriptor.value
      : descriptor && typeof descriptor.get === "function"
        ? descriptor.get.call(globalObject)
        : undefined;
    if (!objectLike(constructor)) continue;
    registerTraceTarget(constructor, name);
    if (objectLike(constructor.prototype))
      registerTraceTarget(constructor.prototype, `${name}.prototype`);
  }

  const document = new Document();
  registerTraceTarget(document, "Document.prototype");
  const parseLocation = value => {
    const text = stringValue(value);
    const match = text.match(/^([a-zA-Z][\w+.-]*:)(?:\/\/([^\/?#]*))?([^?#]*)(\?[^#]*)?(#.*)?$/);
    if (!match) return { href: text, origin: "null", protocol: "", host: "", hostname: "", port: "", pathname: text, search: "", hash: "" };
    const protocol = match[1], host = match[2] || "", separator = host.lastIndexOf(":");
    const hostname = separator > -1 && host.indexOf("]") < separator ? host.slice(0, separator) : host;
    const port = hostname === host ? "" : host.slice(separator + 1);
    const pathname = match[3] || (host ? "/" : "");
    return {
      href: text,
      origin: host && (protocol === "http:" || protocol === "https:") ? `${protocol}//${host}` : "null",
      protocol, host, hostname, port, pathname, search: match[4] || "", hash: match[5] || ""
    };
  };
  const resolveLocation = value => {
    const text = stringValue(value);
    if (/^[a-zA-Z][\w+.-]*:/.test(text)) return text;
    const base = locationState;
    if (text.startsWith("//")) return `${base.protocol}${text}`;
    if (text.startsWith("/")) return `${base.origin}${text}`;
    if (text.startsWith("?")) return `${base.origin}${base.pathname}${text}`;
    if (text.startsWith("#")) return `${base.origin}${base.pathname}${base.search}${text}`;
    const directory = base.pathname.slice(0, base.pathname.lastIndexOf("/") + 1);
    return `${base.origin}${directory}${text}`;
  };
  let locationState = parseLocation(config.url);
  const pendingNavigations = [];
  const location = {};
  const navigate = (kind, value) => {
    const from = locationState.href;
    const to = resolveLocation(value);
    locationState = parseLocation(to);
    pendingNavigations.push(ObjectIntrinsic.freeze({ kind, from, url: locationState.href }));
    logApi("Location.prototype", kind, "call", [value], undefined);
  };
  for (const key of ["href", "protocol", "host", "hostname", "port", "pathname", "search", "hash"]) {
    ObjectIntrinsic.defineProperty(location, key, {
      get: () => locationState[key],
      set: value => {
        if (key === "href") navigate("assign", value);
        else {
          const next = { ...locationState, [key]: stringValue(value) };
          navigate("assign", `${next.protocol}//${next.host}${next.pathname}${next.search}${next.hash}`);
        }
      },
      enumerable: true,
      configurable: false
    });
  }
  ObjectIntrinsic.defineProperty(location, "origin", {
    get: () => locationState.origin, enumerable: true, configurable: false
  });
  data(location, "assign", function assign(value) { navigate("assign", value); });
  data(location, "replace", function replace(value) { navigate("replace", value); });
  data(location, "reload", function reload() { pendingNavigations.push(ObjectIntrinsic.freeze({ kind: "reload", from: locationState.href, url: locationState.href })); });
  data(location, "toString", function toString() { return locationState.href; });
  activeLocation = location;
  registerTraceTarget(location, "Location.prototype");

  const plugins = makePluginArray();
  const mimeTypes = makeMimeTypeArray(pluginArrayState.get(plugins).items[0]);
  const permissions = ObjectIntrinsic.create(Permissions.prototype);
  const connection = ObjectIntrinsic.create(NetworkInformation.prototype);
  networkInformationState.set(connection, {
    effectiveType: "4g",
    rtt: 150,
    downlink: 1.75,
    saveData: false,
    onchange: null
  });
  listenersFor(connection);
  const orientation = ObjectIntrinsic.create(ScreenOrientation.prototype);
  screenOrientationState.set(orientation, {
    angle: 0,
    type: profile.screen_width >= profile.screen_height ? "landscape-primary" : "portrait-primary",
    onchange: null
  });
  listenersFor(orientation);

  const navigator = {};
  registerTraceTarget(navigator, "Navigator.prototype");
  for (const [key, value] of ObjectIntrinsic.entries({
    userAgent: profile.user_agent,
    appVersion: profile.user_agent.replace(/^Mozilla\//, ""),
    appCodeName: "Mozilla",
    appName: "Netscape",
    platform: profile.platform,
    language: profile.language,
    languages: ObjectIntrinsic.freeze(profile.languages.slice()),
    hardwareConcurrency: profile.hardware_concurrency,
    maxTouchPoints: 0,
    webdriver: false,
    cookieEnabled: true,
    onLine: true,
    product: "Gecko",
    productSub: "20030107",
    vendor: "Google Inc.",
    vendorSub: "",
    pdfViewerEnabled: true,
    plugins,
    mimeTypes,
    permissions,
    connection
  })) data(navigator, key, value);
  const screen = {};
  registerTraceTarget(screen, "Screen.prototype");
  for (const [key, value] of ObjectIntrinsic.entries({
    width: profile.screen_width,
    height: profile.screen_height,
    availWidth: profile.screen_avail_width,
    availHeight: profile.screen_avail_height,
    colorDepth: profile.screen_depth,
    pixelDepth: profile.screen_depth,
    availLeft: 0,
    availTop: 0,
    orientation
  })) data(screen, key, value);

  const visualViewport = ObjectIntrinsic.create(VisualViewport.prototype);
  visualViewportState.set(visualViewport, {
    width: config.viewport.width,
    height: config.viewport.height,
    onresize: null,
    onscroll: null,
    onscrollend: null
  });
  listenersFor(visualViewport);
  const matchMedia = query => {
    const media = stringValue(query);
    const width = config.viewport.width;
    const height = config.viewport.height;
    let matches = true;
    const minWidth = media.match(/\(\s*min-width\s*:\s*([\d.]+)px\s*\)/i);
    const maxWidth = media.match(/\(\s*max-width\s*:\s*([\d.]+)px\s*\)/i);
    const minHeight = media.match(/\(\s*min-height\s*:\s*([\d.]+)px\s*\)/i);
    const maxHeight = media.match(/\(\s*max-height\s*:\s*([\d.]+)px\s*\)/i);
    const requestedOrientation = media.match(/\(\s*orientation\s*:\s*(portrait|landscape)\s*\)/i);
    if (minWidth) matches = matches && width >= numberValue(minWidth[1]);
    if (maxWidth) matches = matches && width <= numberValue(maxWidth[1]);
    if (minHeight) matches = matches && height >= numberValue(minHeight[1]);
    if (maxHeight) matches = matches && height <= numberValue(maxHeight[1]);
    if (requestedOrientation)
      matches = matches && requestedOrientation[1].toLowerCase() === (width >= height ? "landscape" : "portrait");
    if (/prefers-color-scheme\s*:\s*dark/i.test(media)) matches = false;
    if (/prefers-color-scheme\s*:\s*light/i.test(media)) matches = true;
    const value = ObjectIntrinsic.create(MediaQueryList.prototype);
    mediaQueryListState.set(value, { media, matches, onchange: null });
    listenersFor(value);
    return value;
  };

  const navigationStart = MathIntrinsic.floor(config.time_origin_ms);
  const timingOffsets = profile.navigation_timing || {};
  const timingValue = key => timingOffsets[key] == null
    ? 0
    : navigationStart + numberValue(timingOffsets[key]);
  const performanceTiming = ObjectIntrinsic.create(PerformanceTiming.prototype);
  performanceTimingState.set(performanceTiming, {
    navigationStart,
    unloadEventStart: timingValue("unload_event_start"),
    unloadEventEnd: timingValue("unload_event_end"),
    redirectStart: timingValue("redirect_start"),
    redirectEnd: timingValue("redirect_end"),
    fetchStart: timingValue("fetch_start"),
    domainLookupStart: timingValue("domain_lookup_start"),
    domainLookupEnd: timingValue("domain_lookup_end"),
    connectStart: timingValue("connect_start"),
    connectEnd: timingValue("connect_end"),
    secureConnectionStart: timingValue("secure_connection_start"),
    requestStart: timingValue("request_start"),
    responseStart: timingValue("response_start"),
    responseEnd: timingValue("response_end"),
    domLoading: timingValue("dom_loading"),
    domInteractive: timingValue("dom_interactive"),
    domContentLoadedEventStart: timingValue("dom_content_loaded_event_start"),
    domContentLoadedEventEnd: timingValue("dom_content_loaded_event_end"),
    domComplete: timingValue("dom_complete"),
    loadEventStart: timingValue("load_event_start"),
    loadEventEnd: timingValue("load_event_end")
  });
  const performanceNavigation = ObjectIntrinsic.create(PerformanceNavigation.prototype);
  performanceNavigationState.set(performanceNavigation, { type: 0, redirectCount: 0 });
  const performanceMemory = ObjectIntrinsic.create(MemoryInfoPrototype);
  memoryInfoState.set(performanceMemory, {
    totalJSHeapSize: 10_000_000,
    usedJSHeapSize: 10_000_000,
    jsHeapSizeLimit: 3_760_000_000
  });
  const performanceNavigationEntry = {};
  const performanceEntries = [performanceNavigationEntry];

  const chromeApp = {
    isInstalled: false,
    getDetails() { return null; },
    getIsInstalled() { return false; },
    installState(callback) { if (typeof callback === "function") callback("not_installed"); },
    runningState(callback) { if (typeof callback === "function") callback("cannot_run"); },
    InstallState: ObjectIntrinsic.freeze({ DISABLED: "disabled", INSTALLED: "installed", NOT_INSTALLED: "not_installed" }),
    RunningState: ObjectIntrinsic.freeze({ CANNOT_RUN: "cannot_run", READY_TO_RUN: "ready_to_run", RUNNING: "running" })
  };
  const chrome = {
    loadTimes() {
      const startSeconds = config.time_origin_ms / 1000;
      return {
        requestTime: startSeconds,
        startLoadTime: startSeconds,
        commitLoadTime: 0,
        finishDocumentLoadTime: performanceTiming.domContentLoadedEventEnd / 1000,
        finishLoadTime: performanceTiming.loadEventEnd / 1000,
        firstPaintTime: 0,
        firstPaintAfterLoadTime: 0,
        navigationType: "Other",
        wasFetchedViaSpdy: false,
        wasNpnNegotiated: false,
        npnNegotiatedProtocol: "",
        wasAlternateProtocolAvailable: false,
        connectionInfo: "unknown"
      };
    },
    csi() {
      return {
        startE: navigationStart,
        onloadT: performanceTiming.loadEventEnd,
        pageT: performance.now(),
        tran: 15
      };
    },
    app: chromeApp
  };

  const localStorage = new Storage("localStorage");
  const sessionStorage = new Storage("sessionStorage");
  const computedDefaults = ObjectIntrinsic.freeze({
    display: "block", position: "static", visibility: "visible", opacity: "1",
    width: "auto", height: "auto", color: "rgb(0, 0, 0)",
    fontSize: "16px", lineHeight: "normal", boxSizing: "content-box"
  });
  const getComputedStyle = element => {
    if (!(element instanceof Element)) throw new TypeErrorIntrinsic("parameter 1 is not of type 'Element'");
    logApi("globalThis", "getComputedStyle", "call", [element], element.style);
    const computed = new ProxyIntrinsic({}, {
      get(_target, key) {
        if (key === "getPropertyValue") return name => element.style.getPropertyValue(name) || computedDefaults[cssName(name)] || "";
        if (key === "length") return ObjectIntrinsic.keys(computedDefaults).length;
        if (key === "item") return index => ObjectIntrinsic.keys(computedDefaults)[numberValue(index)] || "";
        if (key === "cssText") return "";
        if (typeof key === "string") return element.style.getPropertyValue(key) || computedDefaults[cssName(key)] || "";
        return undefined;
      },
      ownKeys() { return ReflectIntrinsic.ownKeys(computedDefaults); },
      getOwnPropertyDescriptor() { return { configurable: true, enumerable: true }; }
    });
    registerTraceTarget(computed, "CSSStyleDeclaration.prototype");
    return computed;
  };

  let randomState = (numberValue(config.random_seed) >>> 0) || 0x9e3779b9;
  const nextRandom = () => { randomState ^= randomState << 13; randomState ^= randomState >>> 17; randomState ^= randomState << 5; return randomState >>> 0; };
  const crypto = {
    getRandomValues(array) {
      if (!ArrayBufferIntrinsic.isView(array) || array.byteLength > 65536) throw new TypeErrorIntrinsic("invalid typed array");
      const bytes = new Uint8ArrayIntrinsic(array.buffer, array.byteOffset, array.byteLength);
      for (let index = 0; index < bytes.length; index++) bytes[index] = nextRandom() & 255;
      return array;
    },
    randomUUID() {
      const bytes = this.getRandomValues(new Uint8ArrayIntrinsic(16));
      bytes[6] = (bytes[6] & 15) | 64; bytes[8] = (bytes[8] & 63) | 128;
      const hex = ArrayIntrinsic.from(bytes, value => value.toString(16).padStart(2, "0")).join("");
      return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
    }
  };
  registerTraceTarget(crypto, "Crypto.prototype");

  getter(globalObject, "window", () => globalObject);
  getter(globalObject, "self", () => globalObject);
  getter(globalObject, "top", () => globalObject);
  getter(globalObject, "parent", () => globalObject);
  getter(globalObject, "frames", () => globalObject);
  getter(globalObject, "navigator", () => navigator);
  getter(globalObject, "screen", () => screen);
  getter(globalObject, "document", () => document);
  getter(globalObject, "visualViewport", () => visualViewport);
  data(globalObject, "location", location);
  data(globalObject, "origin", location.origin);
  data(globalObject, "innerWidth", config.viewport.width);
  data(globalObject, "innerHeight", config.viewport.height);
  data(globalObject, "outerWidth", profile.screen_width);
  data(globalObject, "outerHeight", profile.screen_height);
  data(globalObject, "devicePixelRatio", config.viewport.device_scale_factor);
  data(globalObject, "isSecureContext", location.protocol === "https:");
  data(globalObject, "crossOriginIsolated", false);
  data(globalObject, "Event", Event);
  data(globalObject, "CustomEvent", CustomEvent);
  data(globalObject, "UIEvent", UIEvent);
  data(globalObject, "MouseEvent", MouseEvent);
  data(globalObject, "EventTarget", EventTarget);
  data(globalObject, "PluginArray", PluginArray);
  data(globalObject, "Plugin", Plugin);
  data(globalObject, "MimeTypeArray", MimeTypeArray);
  data(globalObject, "MimeType", MimeType);
  data(globalObject, "Permissions", Permissions);
  data(globalObject, "PermissionStatus", PermissionStatus);
  data(globalObject, "NetworkInformation", NetworkInformation);
  data(globalObject, "ScreenOrientation", ScreenOrientation);
  data(globalObject, "MediaQueryList", MediaQueryList);
  data(globalObject, "VisualViewport", VisualViewport);
  data(globalObject, "PerformanceTiming", PerformanceTiming);
  data(globalObject, "PerformanceNavigation", PerformanceNavigation);
  data(globalObject, "Node", Node);
  data(globalObject, "CharacterData", CharacterData);
  data(globalObject, "Text", Text);
  data(globalObject, "DocumentFragment", DocumentFragment);
  data(globalObject, "Element", Element);
  data(globalObject, "HTMLElement", HTMLElement);
  data(globalObject, "HTMLIFrameElement", HTMLIFrameElement);
  data(globalObject, "HTMLCanvasElement", HTMLCanvasElement);
  data(globalObject, "CanvasRenderingContext2D", CanvasRenderingContext2D);
  data(globalObject, "Document", Document);
  data(globalObject, "CSSStyleDeclaration", CSSStyleDeclaration);
  data(globalObject, "Storage", Storage);
  data(globalObject, "Headers", Headers);
  data(globalObject, "Response", Response);
  data(globalObject, "XMLHttpRequest", XMLHttpRequest);
  data(globalObject, "localStorage", localStorage);
  data(globalObject, "sessionStorage", sessionStorage);
  data(globalObject, "fetch", fetch);
  data(globalObject, "getComputedStyle", getComputedStyle);
  data(globalObject, "matchMedia", matchMedia);
  data(globalObject, "chrome", chrome);
  data(globalObject, "setTimeout", setTimeoutHost);
  data(globalObject, "clearTimeout", clearTimer);
  data(globalObject, "setInterval", setIntervalHost);
  data(globalObject, "clearInterval", clearTimer);
  data(globalObject, "queueMicrotask", queueMicrotaskHost);
  data(globalObject, "requestAnimationFrame", callback => schedule(() => callback(clockMs), 1000 / 60, false, []));
  data(globalObject, "cancelAnimationFrame", clearTimer);
  data(globalObject, "crypto", crypto);
  data(globalObject, "addEventListener", EventTarget.prototype.addEventListener.bind(globalObject));
  data(globalObject, "removeEventListener", EventTarget.prototype.removeEventListener.bind(globalObject));
  data(globalObject, "dispatchEvent", EventTarget.prototype.dispatchEvent.bind(globalObject));

  const surfaceManifest = config.surface_manifest;
  const generatedSlots = new WeakMapIntrinsic();
  const nativeSources = new WeakMapIntrinsic();
  const callableOwners = new WeakMapIntrinsic();
  const originalFunctionToString = FunctionIntrinsic.prototype.toString;
  const markNative = (callable, spec) => {
    if (typeof callable !== "function" || !spec) return callable;
    try { ObjectIntrinsic.defineProperty(callable, "name", { value: spec.name, configurable: true }); } catch (_error) {}
    try { ObjectIntrinsic.defineProperty(callable, "length", { value: spec.length, configurable: true }); } catch (_error) {}
    if (spec.native_like) nativeSources.set(callable, `function ${spec.name || ""}() { [native code] }`);
    return callable;
  };
  const nativeToString = markNative(function toString() {
    if (nativeSources.has(this)) return nativeSources.get(this);
    return ReflectIntrinsic.apply(originalFunctionToString, this, []);
  }, { name: "toString", length: 0, native_like: true });
  ObjectIntrinsic.defineProperty(FunctionIntrinsic.prototype, "toString", {
    ...ObjectIntrinsic.getOwnPropertyDescriptor(FunctionIntrinsic.prototype, "toString"),
    value: nativeToString
  });
  ObjectIntrinsic.defineProperty(DateIntrinsic, "now", {
    ...ObjectIntrinsic.getOwnPropertyDescriptor(DateIntrinsic, "now"),
    value: markNative(function now() {
      return MathIntrinsic.floor(config.time_origin_ms + performance.now());
    }, { name: "now", length: 0, native_like: true })
  });
  for (const [owner, key, name, length] of [
    [chrome, "loadTimes", "loadTimes", 0],
    [chrome, "csi", "csi", 0],
    [chromeApp, "getDetails", "getDetails", 0],
    [chromeApp, "getIsInstalled", "getIsInstalled", 0],
    [chromeApp, "installState", "installState", 1],
    [chromeApp, "runningState", "runningState", 1]
  ]) {
    const descriptor = ObjectIntrinsic.getOwnPropertyDescriptor(owner, key);
    if (descriptor && typeof descriptor.value === "function")
      markNative(descriptor.value, { name, length, native_like: true });
  }
  for (const key of ["totalJSHeapSize", "usedJSHeapSize", "jsHeapSizeLimit"]) {
    const descriptor = ObjectIntrinsic.getOwnPropertyDescriptor(MemoryInfoPrototype, key);
    if (descriptor && typeof descriptor.get === "function")
      markNative(descriptor.get, { name: `get ${key}`, length: 0, native_like: true });
  }

  const manifestKey = key => {
    if (key.kind === "string") return key.display;
    if (key.registry_key != null) return Symbol.for(key.registry_key);
    const wellKnown = {
      "Symbol(Symbol.iterator)": Symbol.iterator,
      "Symbol(Symbol.toStringTag)": Symbol.toStringTag,
      "Symbol(Symbol.toPrimitive)": Symbol.toPrimitive,
      "Symbol(Symbol.hasInstance)": Symbol.hasInstance,
      "Symbol(Symbol.match)": Symbol.match,
      "Symbol(Symbol.matchAll)": Symbol.matchAll,
      "Symbol(Symbol.replace)": Symbol.replace,
      "Symbol(Symbol.search)": Symbol.search,
      "Symbol(Symbol.species)": Symbol.species,
      "Symbol(Symbol.split)": Symbol.split,
      "Symbol(Symbol.unscopables)": Symbol.unscopables,
      "Symbol(Symbol.dispose)": Symbol.dispose,
      "Symbol(Symbol.asyncDispose)": Symbol.asyncDispose
    };
    return wellKnown[key.display] || Symbol(key.description || "");
  };
  const interfaceTag = path => path.replace(/\.prototype$/, "").split(".").pop();
  const slotsFor = receiver => {
    if (!objectLike(receiver)) return new MapIntrinsic();
    let slots = generatedSlots.get(receiver);
    if (!slots) { slots = new MapIntrinsic(); generatedSlots.set(receiver, slots); }
    return slots;
  };
  const accessorDefault = (path, key, receiver) => {
    const slots = slotsFor(receiver);
    if (slots.has(key)) return slots.get(key);
    const node = stateFor(nodeState, receiver);
    if (node && ObjectIntrinsic.prototype.hasOwnProperty.call(node, key)) return node[key];
    const element = stateFor(elementState, receiver);
    if (element && ObjectIntrinsic.prototype.hasOwnProperty.call(element, key)) return element[key];
    const documentValues = stateFor(documentState, receiver);
    if (documentValues && ObjectIntrinsic.prototype.hasOwnProperty.call(documentValues, key)) return documentValues[key];
    const eventValues = stateFor(eventState, receiver);
    if (eventValues && ObjectIntrinsic.prototype.hasOwnProperty.call(eventValues, key)) return eventValues[key];
    const responseValues = stateFor(responseState, receiver);
    if (responseValues && ObjectIntrinsic.prototype.hasOwnProperty.call(responseValues, key)) return responseValues[key];
    if (path === "Navigator.prototype") {
      const values = {
        userAgent: profile.user_agent, appVersion: profile.user_agent.replace(/^Mozilla\//, ""),
        appCodeName: "Mozilla", appName: "Netscape", platform: profile.platform,
        language: profile.language, languages: ObjectIntrinsic.freeze(profile.languages.slice()),
        hardwareConcurrency: profile.hardware_concurrency, deviceMemory: 8, maxTouchPoints: 0,
        webdriver: false, cookieEnabled: true, onLine: true, product: "Gecko",
        productSub: "20030107", vendor: "Google Inc.", vendorSub: "", pdfViewerEnabled: true
      };
      if (ObjectIntrinsic.prototype.hasOwnProperty.call(values, key)) return values[key];
      if (key === "plugins") return plugins;
      if (key === "mimeTypes") return mimeTypes;
      if (key === "permissions") return permissions;
      if (key === "connection") return connection;
    }
    if (path === "Screen.prototype") {
      const values = {
        width: profile.screen_width, height: profile.screen_height,
        availWidth: profile.screen_avail_width, availHeight: profile.screen_avail_height,
        colorDepth: profile.screen_depth, pixelDepth: profile.screen_depth,
        availLeft: 0, availTop: 0, orientation
      };
      if (ObjectIntrinsic.prototype.hasOwnProperty.call(values, key)) return values[key];
    }
    if (path === "Performance.prototype") {
      const values = {
        timeOrigin: config.time_origin_ms,
        timing: performanceTiming,
        navigation: performanceNavigation,
        memory: performanceMemory,
        interactionCount: 0
      };
      if (ObjectIntrinsic.prototype.hasOwnProperty.call(values, key)) return values[key];
    }
    if (path === "Document.prototype") {
      const values = {
        URL: location.href, documentURI: location.href, referrer: "", readyState: "complete",
        visibilityState: "visible", hidden: false, compatMode: "CSS1Compat",
        characterSet: "UTF-8", charset: "UTF-8", inputEncoding: "UTF-8",
        contentType: "text/html", defaultView: globalObject, currentScript: null
      };
      if (ObjectIntrinsic.prototype.hasOwnProperty.call(values, key)) return values[key];
    }
    if (/^(on|aria)/.test(key)) return null;
    if (/^(hidden|disabled|draggable|spellcheck|is|was|webkitHidden)/.test(key)) return false;
    return null;
  };
  const stubFunction = spec => markNative(function () {}, spec);
  const semanticMethod = (path, key) => {
    if (path === "Navigator.prototype") {
      if (key === "getGamepads") return function () { return [null, null, null, null]; };
      if (key === "javaEnabled") return function () { return false; };
      if (key === "sendBeacon") return function () { return false; };
      if (key === "vibrate") return function () { return true; };
    }
    if (path === "Performance.prototype") {
      if (key === "getEntries") return function () { return performanceEntries.slice(); };
      if (key === "getEntriesByType") return function (type) {
        return stringValue(type) === "navigation" ? performanceEntries.slice() : [];
      };
      if (key === "getEntriesByName") return function (name, type) {
        return performanceEntries.filter(entry => entry.name === stringValue(name)
          && (type === undefined || entry.entryType === stringValue(type)));
      };
      if (key === "toJSON") return function () { return { timeOrigin: config.time_origin_ms }; };
    }
    if (path === "PerformanceEntry.prototype" && key === "toJSON") return function () {
      const slots = slotsFor(this);
      return ObjectIntrinsic.fromEntries(ArrayIntrinsic.from(slots.entries()));
    };
    return null;
  };
  const stubValue = (path, member) => {
    if (member.f) {
      const semantic = semanticMethod(path, member.k.display);
      return semantic ? markNative(semantic, member.f) : stubFunction(member.f);
    }
    if (member.k.kind === "symbol" && member.k.display === "Symbol(Symbol.toStringTag)")
      return interfaceTag(path);
    if (member.t === "number") return 0;
    if (member.t === "string") return "";
    if (member.t === "boolean") return false;
    if (member.t === "undefined") return undefined;
    if (member.t === "function") return stubFunction({ name: member.k.display, length: 0, native_like: true });
    return {};
  };
  const makeConstructor = name => {
    const constructor = function () {};
    return markNative(constructor, { name, length: 0, native_like: true });
  };
  const surfaceObjects = new MapIntrinsic([
    ["globalThis", globalObject], ["Object", ObjectIntrinsic], ["Object.prototype", ObjectIntrinsic.prototype],
    ["Function", FunctionIntrinsic], ["Function.prototype", FunctionIntrinsic.prototype]
  ]);
  const interfaces = surfaceManifest && ArrayIntrinsic.isArray(surfaceManifest.interfaces)
    ? surfaceManifest.interfaces : [];
  const manifestByPath = new MapIntrinsic(interfaces.map(spec => [spec.path, spec]));
  normalizeOwnKeys = (target, keys) => {
    target = rawTraceValue(target);
    const path = target === globalObject ? "globalThis" : semanticTraceTarget(target);
    const spec = path && manifestByPath.get(path);
    if (!spec) return keys;
    const available = new SetIntrinsic(keys);
    const ordered = spec.members.map(member => manifestKey(member.k)).filter(key => available.has(key));
    const expected = new SetIntrinsic(ordered);
    for (const key of keys) if (!expected.has(key)) ordered.push(key);
    return ordered;
  };
  for (const spec of interfaces) {
    if (surfaceObjects.has(spec.path) || spec.path === "globalThis") continue;
    if (spec.path.endsWith(".prototype")) {
      const name = spec.path.slice(0, -10);
      let constructor = surfaceObjects.get(name) || globalObject[name];
      if (typeof constructor !== "function") {
        constructor = makeConstructor(name);
        data(globalObject, name, constructor, false);
      }
      surfaceObjects.set(name, constructor);
      surfaceObjects.set(spec.path, constructor.prototype);
    } else {
      let value = globalObject[spec.path];
      if (spec.value_type === "function" && typeof value !== "function") {
        value = makeConstructor(spec.path);
        data(globalObject, spec.path, value, false);
      }
      if (objectLike(value)) surfaceObjects.set(spec.path, value);
    }
  }
  // Chrome exposes these historical factory functions with prototype objects
  // aliased to their WebIDL element prototypes. Ordinary JavaScript functions
  // receive a fresh prototype, so repair the identity before descriptors are
  // frozen to the captured shape.
  for (const [alias, canonical] of [
    ["Option.prototype", "HTMLOptionElement.prototype"],
    ["Image.prototype", "HTMLImageElement.prototype"],
    ["Audio.prototype", "HTMLAudioElement.prototype"]
  ]) {
    const prototype = surfaceObjects.get(canonical);
    const constructor = surfaceObjects.get(alias.slice(0, -10));
    if (!objectLike(prototype) || typeof constructor !== "function") continue;
    const descriptor = ObjectIntrinsic.getOwnPropertyDescriptor(constructor, "prototype");
    if (descriptor && "value" in descriptor && descriptor.writable) {
      try { ObjectIntrinsic.defineProperty(constructor, "prototype", { ...descriptor, value: prototype }); }
      catch (_error) {}
    }
    surfaceObjects.set(alias, prototype);
  }
  for (const spec of interfaces) {
    const object = surfaceObjects.get(spec.path);
    const prototype = spec.prototype_path && surfaceObjects.get(spec.prototype_path);
    if (objectLike(object) && objectLike(prototype)) {
      try { ReflectIntrinsic.setPrototypeOf(object, prototype); } catch (_error) {}
    }
  }
  const bindInstance = (value, name, migrateOwn = true) => {
    const prototype = surfaceObjects.get(`${name}.prototype`);
    if (!objectLike(value) || !objectLike(prototype)) return;
    try { ReflectIntrinsic.setPrototypeOf(value, prototype); } catch (_error) {}
    registerTraceTarget(value, `${name}.prototype`);
    if (!migrateOwn) return;
    const spec = interfaces.find(item => item.path === `${name}.prototype`);
    if (!spec) return;
    const slots = slotsFor(value);
    for (const member of spec.members) {
      if (member.k.kind !== "string" || member.d !== "accessor") continue;
      const descriptor = ObjectIntrinsic.getOwnPropertyDescriptor(value, member.k.display);
      if (!descriptor || !descriptor.configurable) continue;
      if ("value" in descriptor) slots.set(member.k.display, descriptor.value);
      else if (typeof descriptor.get === "function") slots.set(member.k.display, descriptor.get.call(value));
      else continue;
      delete value[member.k.display];
    }
  };
  bindInstance(navigator, "Navigator");
  bindInstance(screen, "Screen");
  bindInstance(plugins, "PluginArray", false);
  for (const plugin of pluginArrayState.get(plugins).items) {
    bindInstance(plugin, "Plugin", false);
    for (const mimeType of pluginState.get(plugin).items) bindInstance(mimeType, "MimeType", false);
  }
  bindInstance(mimeTypes, "MimeTypeArray", false);
  for (const mimeType of mimeTypeArrayState.get(mimeTypes).items) bindInstance(mimeType, "MimeType", false);
  bindInstance(permissions, "Permissions", false);
  bindInstance(connection, "NetworkInformation", false);
  bindInstance(orientation, "ScreenOrientation", false);
  bindInstance(visualViewport, "VisualViewport", false);
  bindInstance(performanceTiming, "PerformanceTiming", false);
  bindInstance(performanceNavigation, "PerformanceNavigation", false);
  bindInstance(location, "Location", false);
  const nativeNow = ObjectIntrinsic.getOwnPropertyDescriptor(performance, "now");
  bindInstance(performance, "Performance");
  if (nativeNow && typeof nativeNow.value === "function") {
    ObjectIntrinsic.defineProperty(surfaceObjects.get("Performance.prototype"), "now", nativeNow);
    if (ObjectIntrinsic.getOwnPropertyDescriptor(performance, "now")?.configurable) delete performance.now;
  }
  bindInstance(document, "Document");
  bindInstance(performanceNavigationEntry, "PerformanceNavigationTiming", false);
  const navigationEntrySlots = slotsFor(performanceNavigationEntry);
  for (const [key, value] of ObjectIntrinsic.entries({
    name: location.href,
    entryType: "navigation",
    startTime: 0,
    duration: 31,
    initiatorType: "navigation",
    deliveryType: "cache",
    nextHopProtocol: "",
    renderBlockingStatus: "non-blocking",
    contentType: "",
    contentEncoding: "",
    transferSize: 0,
    encodedBodySize: 0,
    decodedBodySize: 0,
    responseStatus: 0,
    redirectStart: 0,
    redirectEnd: 0,
    fetchStart: 0,
    domainLookupStart: 0,
    domainLookupEnd: 0,
    connectStart: 0,
    secureConnectionStart: 0,
    connectEnd: 0,
    requestStart: 0,
    responseStart: 0,
    responseEnd: 30,
    domInteractive: 30,
    domContentLoadedEventStart: 30,
    domContentLoadedEventEnd: 30,
    domComplete: 31,
    loadEventStart: 31,
    loadEventEnd: 31,
    type: "navigate",
    redirectCount: 0,
    activationStart: 0,
    criticalCHRestart: 0,
    notRestoredReasons: null
  })) navigationEntrySlots.set(key, value);
  registerTraceTarget(MemoryInfoPrototype, "MemoryInfo.prototype");
  registerTraceTarget(performanceMemory, "MemoryInfo.prototype");

  const applyMember = (path, object, member) => {
    const key = manifestKey(member.k);
    const current = ObjectIntrinsic.getOwnPropertyDescriptor(object, key);
    if (current && !current.configurable) {
      if (current.value && member.f) markNative(current.value, member.f);
      if (member.d === "data" && current.writable && member.w === false) {
        try { ObjectIntrinsic.defineProperty(object, key, { ...current, writable: false }); } catch (_error) {}
      }
      return;
    }
    if (member.d === "data") {
      let value = current && "value" in current ? current.value : stubValue(path, member);
      const previousOwner = typeof value === "function" ? callableOwners.get(value) : undefined;
      if (member.f && typeof value === "function" && previousOwner && previousOwner !== member.f.name) {
        const original = value;
        value = function (...args) { return ReflectIntrinsic.apply(original, this, args); };
      }
      if (member.f) {
        markNative(value, member.f);
        callableOwners.set(value, member.f.name);
      }
      ObjectIntrinsic.defineProperty(object, key, {
        value, writable: !!member.w, enumerable: !!member.e, configurable: !!member.c
      });
      return;
    }
    let backing = current && "value" in current ? current.value : undefined;
    const get = current && current.get || markNative(function () {
      return backing !== undefined ? backing : accessorDefault(path, stringValue(key), this);
    }, member.g);
    const set = current && current.set || (member.s ? markNative(function (value) {
      backing = value;
      slotsFor(this).set(stringValue(key), value);
    }, member.s) : undefined);
    if (get && member.g) markNative(get, member.g);
    if (set && member.s) markNative(set, member.s);
    ObjectIntrinsic.defineProperty(object, key, {
      get, set, enumerable: !!member.e, configurable: !!member.c
    });
  };
  const reorderConfigurableMembers = (object, spec) => {
    const expected = spec.members.map(member => manifestKey(member.k));
    const actual = reflectOwnKeysIntrinsic(object);
    if (actual.length === expected.length && actual.every((key, index) => key === expected[index])) return;
    const saved = new MapIntrinsic();
    for (const key of expected) {
      const descriptor = ObjectIntrinsic.getOwnPropertyDescriptor(object, key);
      if (descriptor && descriptor.configurable) {
        saved.set(key, descriptor);
        ReflectIntrinsic.deleteProperty(object, key);
      }
    }
    for (const key of expected) {
      const descriptor = saved.get(key);
      if (descriptor) ObjectIntrinsic.defineProperty(object, key, descriptor);
    }
  };
  for (const spec of interfaces) {
    if (spec.path === "globalThis") continue;
    const object = surfaceObjects.get(spec.path);
    if (!objectLike(object)) continue;
    const expected = new SetIntrinsic(spec.members.map(member => manifestKey(member.k)));
    for (const key of ReflectIntrinsic.ownKeys(object)) {
      if (expected.has(key)) continue;
      const descriptor = ObjectIntrinsic.getOwnPropertyDescriptor(object, key);
      if (descriptor && descriptor.configurable) ReflectIntrinsic.deleteProperty(object, key);
    }
    for (const member of spec.members) applyMember(spec.path, object, member);
    reorderConfigurableMembers(object, spec);
    registerTraceTarget(object, spec.path);
  }
  const globalSpec = interfaces.find(spec => spec.path === "globalThis");
  if (globalSpec) {
    const expected = new SetIntrinsic(globalSpec.members.map(member => manifestKey(member.k)));
    for (const key of ReflectIntrinsic.ownKeys(globalObject)) {
      if (expected.has(key) || (typeof key === "string" && key.startsWith("__yatou"))) continue;
      const descriptor = ObjectIntrinsic.getOwnPropertyDescriptor(globalObject, key);
      if (descriptor && descriptor.configurable) ReflectIntrinsic.deleteProperty(globalObject, key);
    }
    for (const member of globalSpec.members) applyMember("globalThis", globalObject, member);
    // Namespace singletons such as Math, JSON, Reflect, Atomics and Intl do
    // not have dedicated interface rows in the first surface baseline. Give
    // their actual global values a direct semantic identity; otherwise owner
    // resolution walks into Object.prototype and reports misleading targets
    // such as Object.prototype.random for Math.random.
    for (const member of globalSpec.members) {
      const key = manifestKey(member.k);
      if (typeof key !== "string") continue;
      const descriptor = ObjectIntrinsic.getOwnPropertyDescriptor(globalObject, key);
      if (!descriptor || !("value" in descriptor)) continue;
      const value = rawTraceValue(descriptor.value);
      if (objectLike(value) && !traceTargets.has(value)) registerTraceTarget(value, key);
    }
  }

  if (getTraceConfig.enabled) {
    const descriptor = ObjectIntrinsic.getOwnPropertyDescriptor(globalObject, "performance");
    if (descriptor && ObjectIntrinsic.prototype.hasOwnProperty.call(descriptor, "value")) {
      const performanceValue = rawTraceValue(descriptor.value);
      registerTraceTarget(performanceValue, "Performance.prototype");
      ObjectIntrinsic.defineProperty(globalObject, "performance", {
        ...descriptor,
        value: observeTraceValue(performanceValue)
      });
    }
  }
  data(globalObject, "__yatouImportCookies", cookies => {
    for (const cookie of ArrayIntrinsic.from(cookies || [])) storeCookie(cookie);
    return visibleCookies(true).length;
  }, false);
  data(globalObject, "__yatouExportCookies", () => visibleCookies(true).map(cookie => ({ ...cookie })), false);
  data(globalObject, "__yatouTakeNavigation", () => pendingNavigations.shift() || null, false);
  data(globalObject, "__yatouPeekNavigation", () => pendingNavigations[0] || null, false);
  data(globalObject, "__yatouEnvironment", ObjectIntrinsic.freeze({
    url: config.url,
    baseline: config.baseline,
    userAgent: profile.user_agent,
    platform: profile.platform,
    language: profile.language,
    viewport: ObjectIntrinsic.freeze({ ...config.viewport }),
    networkFallback: false,
    clockMode: profile.clock.mode,
    getTrace: ObjectIntrinsic.freeze({
      enabled: getTraceConfig.enabled,
      maxEvents: getTraceConfig.maxEvents
    })
  }), false);
  installReflectionTracing();
})()
