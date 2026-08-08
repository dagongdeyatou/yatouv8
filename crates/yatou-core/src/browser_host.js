(() => {
  "use strict";
  const globalObject = globalThis;
  const stringValue = String;
  const booleanValue = Boolean;
  const numberValue = Number;
  const ObjectIntrinsic = Object;
  const ReflectIntrinsic = Reflect;
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
  let clockMs = profile.clock.start_ms;
  const timers = new MapIntrinsic();
  const microtasks = [];

  const getTraceConfig = ObjectIntrinsic.freeze({
    enabled: booleanValue(config.get_trace && config.get_trace.enabled),
    maxEvents: MathIntrinsic.max(0, numberValue(config.get_trace && config.get_trace.max_events) || 0)
  });
  const traceTargets = new WeakMapIntrinsic();
  const traceProxyCache = new WeakMapIntrinsic();
  const traceRawValues = new WeakMapIntrinsic();
  let getTraceActive = false;
  let getTraceEvents = 0;
  let getTraceDropped = 0;
  let getTraceDepth = 0;

  const objectLike = value =>
    (typeof value === "object" && value !== null) || typeof value === "function";
  const registerTraceTarget = (value, target) => {
    if (objectLike(value)) traceTargets.set(value, stringValue(target));
    return value;
  };
  const rawTraceValue = value => traceRawValues.get(value) || value;
  const semanticTraceTarget = value => {
    value = rawTraceValue(value);
    for (let current = value; objectLike(current); current = ReflectIntrinsic.getPrototypeOf(current)) {
      const target = traceTargets.get(current);
      if (target) return target;
    }
    return null;
  };
  const ownerTraceTarget = (value, key) => {
    value = rawTraceValue(value);
    const fallback = semanticTraceTarget(value) || "Object";
    for (let current = value; objectLike(current); current = ReflectIntrinsic.getPrototypeOf(current)) {
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
  const observeTraceValue = (value, hint = null) => {
    value = rawTraceValue(value);
    if (!getTraceConfig.enabled || !traceableValue(value, hint)) return value;
    if (hint && !semanticTraceTarget(value)) registerTraceTarget(value, hint);
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
          const descriptor = ReflectIntrinsic.getOwnPropertyDescriptor(target, key);
          const invariantValue = descriptor
            && !descriptor.configurable
            && ObjectIntrinsic.prototype.hasOwnProperty.call(descriptor, "value")
            && !descriptor.writable;
          const invariantUndefined = descriptor
            && !descriptor.configurable
            && !ObjectIntrinsic.prototype.hasOwnProperty.call(descriptor, "value")
            && descriptor.get === undefined;
          if (invariantValue || invariantUndefined) return result;
          const nestedHint = typeof result === "function" && traceableKey(key)
            ? `${owner}.${key}`
            : null;
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
        if (!callbackBoundary) getTraceDepth += 1;
        let result;
        try {
          result = ReflectIntrinsic.apply(
            target,
            rawTraceValue(thisArg),
            argumentsList.map(rawTraceValue)
          );
        } finally {
          if (!callbackBoundary) getTraceDepth -= 1;
        }
        return observeTraceValue(result);
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

  class Event {
    constructor(type, init = {}) {
      this.type = stringValue(type);
      this.bubbles = booleanValue(init.bubbles);
      this.cancelable = booleanValue(init.cancelable);
      this.composed = booleanValue(init.composed);
      this.defaultPrevented = false;
      this.target = null;
      this.currentTarget = null;
      this.eventPhase = 0;
      this.isTrusted = false;
      this.timeStamp = clockMs;
      this._stopped = false;
      this._immediateStopped = false;
    }
    preventDefault() { if (this.cancelable) this.defaultPrevented = true; }
    stopPropagation() { this._stopped = true; }
    stopImmediatePropagation() { this._stopped = this._immediateStopped = true; }
  }
  data(Event, "NONE", 0);
  data(Event, "CAPTURING_PHASE", 1);
  data(Event, "AT_TARGET", 2);
  data(Event, "BUBBLING_PHASE", 3);

  class CustomEvent extends Event {
    constructor(type, init = {}) {
      super(type, init);
      this.detail = init.detail === undefined ? null : init.detail;
    }
  }

  class MouseEvent extends Event {
    constructor(type, init = {}) {
      super(type, init);
      for (const key of ["screenX", "screenY", "clientX", "clientY", "button", "buttons", "movementX", "movementY"])
        this[key] = numberValue(init[key] || 0);
      for (const key of ["ctrlKey", "shiftKey", "altKey", "metaKey"])
        this[key] = booleanValue(init[key]);
    }
  }

  class EventTarget {
    constructor() { this._listeners = new MapIntrinsic(); }
    addEventListener(type, callback, options = false) {
      type = stringValue(type);
      logApi("EventTarget.prototype", "addEventListener", "call", [type, callback, options], undefined);
      if (callback == null) return;
      const entries = this._listeners.get(type) || [];
      const capture = typeof options === "object" ? booleanValue(options.capture) : booleanValue(options);
      if (!entries.some(entry => entry.callback === callback && entry.capture === capture))
        entries.push({ callback, capture, once: booleanValue(options && options.once) });
      this._listeners.set(type, entries);
    }
    removeEventListener(type, callback, options = false) {
      type = stringValue(type);
      logApi("EventTarget.prototype", "removeEventListener", "call", [type, callback, options], undefined);
      const capture = typeof options === "object" ? booleanValue(options.capture) : booleanValue(options);
      const entries = this._listeners.get(type) || [];
      this._listeners.set(type, entries.filter(entry => entry.callback !== callback || entry.capture !== capture));
    }
    dispatchEvent(event) {
      if (!(event instanceof Event)) throw new TypeErrorIntrinsic("parameter 1 is not of type 'Event'");
      logApi("EventTarget.prototype", "dispatchEvent", "call", [event], true);
      if (!event.target) event.target = this;
      event.currentTarget = this;
      event.eventPhase = Event.AT_TARGET;
      const entries = ArrayIntrinsic.from(this._listeners.get(event.type) || []);
      for (const entry of entries) {
        if (entry.once) this.removeEventListener(event.type, entry.callback, { capture: entry.capture });
        if (typeof entry.callback === "function") entry.callback.call(this, event);
        else if (entry.callback && typeof entry.callback.handleEvent === "function") entry.callback.handleEvent(event);
        if (event._immediateStopped) break;
      }
      event.eventPhase = Event.NONE;
      event.currentTarget = null;
      return !event.defaultPrevented;
    }
  }

  class Node extends EventTarget {
    constructor(nodeType, nodeName, ownerDocument = null) {
      super();
      this.nodeType = nodeType;
      this.nodeName = nodeName;
      this.ownerDocument = ownerDocument;
      this.parentNode = null;
      this.childNodes = [];
      this._text = "";
    }
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
      child.parentNode = this;
      return child;
    }
    insertBefore(child, reference) {
      if (reference == null) return this.appendChild(child);
      const index = this.childNodes.indexOf(reference);
      if (index < 0) throw new ErrorIntrinsic("NotFoundError");
      if (child.parentNode) child.parentNode.removeChild(child);
      this.childNodes.splice(index, 0, child);
      child.parentNode = this;
      return child;
    }
    removeChild(child) {
      const index = this.childNodes.indexOf(child);
      if (index < 0) throw new ErrorIntrinsic("NotFoundError");
      this.childNodes.splice(index, 1);
      child.parentNode = null;
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
      if (this.nodeType === Node.TEXT_NODE) return this._text;
      return this.childNodes.map(child => child.textContent).join("");
    }
    set textContent(value) {
      this.childNodes.splice(0);
      const text = stringValue(value ?? "");
      if (this.nodeType === Node.TEXT_NODE) this._text = text;
      else if (text) this.appendChild(new Text(text, this.ownerDocument));
    }
  }
  ObjectIntrinsic.assign(Node, {
    ELEMENT_NODE: 1,
    TEXT_NODE: 3,
    DOCUMENT_NODE: 9,
    DOCUMENT_FRAGMENT_NODE: 11
  });

  class Text extends Node {
    constructor(dataValue = "", ownerDocument = null) {
      super(Node.TEXT_NODE, "#text", ownerDocument);
      this._text = stringValue(dataValue);
    }
    get data() { return this._text; }
    set data(value) { this._text = stringValue(value); }
    get length() { return this._text.length; }
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

  class Element extends Node {
    constructor(tagName, ownerDocument = null) {
      const upper = stringValue(tagName).toUpperCase();
      super(Node.ELEMENT_NODE, upper, ownerDocument);
      this.tagName = upper;
      this.localName = upper.toLowerCase();
      this.namespaceURI = "http://www.w3.org/1999/xhtml";
      this.attributes = new MapIntrinsic();
      this.style = styleProxy(new CSSStyleDeclaration());
      this.classList = new DOMTokenList(this);
      this.dataset = ObjectIntrinsic.create(null);
      this.contentWindow = this.localName === "iframe" ? globalObject : null;
    }
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
    getContext() { return null; }
    toDataURL() { return "data:,"; }
  }

  class HTMLElement extends Element {}
  class HTMLIFrameElement extends HTMLElement {}
  class HTMLCanvasElement extends HTMLElement {}

  class Document extends Node {
    constructor() {
      super(Node.DOCUMENT_NODE, "#document", null);
      this.ownerDocument = null;
      this.URL = config.url;
      this.documentURI = config.url;
      this.referrer = "";
      this.readyState = "complete";
      this.visibilityState = "visible";
      this.hidden = false;
      this.compatMode = "CSS1Compat";
      this.characterSet = "UTF-8";
      this.contentType = "text/html";
      this._cookies = new MapIntrinsic();
      this.documentElement = this.createElement("html");
      this.head = this.createElement("head");
      this.body = this.createElement("body");
      this.appendChild(this.documentElement);
      this.documentElement.appendChild(this.head);
      this.documentElement.appendChild(this.body);
    }
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
    get cookie() { return ArrayIntrinsic.from(this._cookies, ([name, value]) => `${name}=${value}`).join("; "); }
    set cookie(serialized) {
      const pair = stringValue(serialized).split(";", 1)[0];
      const separator = pair.indexOf("=");
      if (separator <= 0) return;
      this._cookies.set(pair.slice(0, separator).trim(), pair.slice(separator + 1).trim());
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

  class Response {
    constructor(body = [], init = {}) {
      this._body = ArrayIntrinsic.from(body || [], value => numberValue(value) & 255);
      this.status = numberValue(init.status ?? 200);
      this.statusText = stringValue(init.statusText || "");
      this.headers = new Headers(init.headers || {});
      this.url = stringValue(init.url || "");
      this.type = "basic";
      this.redirected = false;
      this.bodyUsed = false;
    }
    get ok() { return this.status >= 200 && this.status <= 299; }
    async text() { this.bodyUsed = true; return utf8Decode(this._body); }
    async json() { return JSONIntrinsic.parse(await this.text()); }
    async arrayBuffer() { this.bodyUsed = true; return Uint8ArrayIntrinsic.from(this._body).buffer; }
    clone() { return new Response(this._body, { status: this.status, statusText: this.statusText, headers: ObjectIntrinsic.fromEntries(this.headers), url: this.url }); }
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
    [MouseEvent, "MouseEvent"],
    [EventTarget, "EventTarget"],
    [Node, "Node"],
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
  const locationUrl = parseLocation(config.url);
  const location = {
    href: locationUrl.href,
    origin: locationUrl.origin,
    protocol: locationUrl.protocol,
    host: locationUrl.host,
    hostname: locationUrl.hostname,
    port: locationUrl.port,
    pathname: locationUrl.pathname,
    search: locationUrl.search,
    hash: locationUrl.hash,
    assign(value) { this.href = stringValue(value); },
    replace(value) { this.href = stringValue(value); },
    reload() {},
    toString() { return this.href; }
  };
  registerTraceTarget(location, "Location.prototype");
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
    deviceMemory: 8,
    maxTouchPoints: 0,
    webdriver: false,
    cookieEnabled: true,
    onLine: true,
    product: "Gecko",
    productSub: "20030107",
    vendor: "Google Inc."
  })) getter(navigator, key, () => value);
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
    availTop: 0
  })) getter(screen, key, () => value);

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
  data(globalObject, "MouseEvent", MouseEvent);
  data(globalObject, "EventTarget", EventTarget);
  data(globalObject, "Node", Node);
  data(globalObject, "Text", Text);
  data(globalObject, "DocumentFragment", DocumentFragment);
  data(globalObject, "Element", Element);
  data(globalObject, "HTMLElement", HTMLElement);
  data(globalObject, "HTMLIFrameElement", HTMLIFrameElement);
  data(globalObject, "HTMLCanvasElement", HTMLCanvasElement);
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
  data(globalObject, "_listeners", new MapIntrinsic(), false);
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
  data(performance, "timeOrigin", config.time_origin_ms);
  data(document, "defaultView", globalObject);
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
})()
