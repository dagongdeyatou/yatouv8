(() => {
  "use strict";
  const config = globalThis.__yatouConfig;
  if (!config || !config.profile) throw new Error("yatouv8 host config is missing");
  const profile = config.profile;
  const hostLog = [];
  const resources = new Map();
  let requestSequence = 0;
  let timerSequence = 0;
  let clockMs = profile.clock.start_ms;
  const timers = new Map();
  const microtasks = [];

  const data = (object, key, value, enumerable = true) =>
    Object.defineProperty(object, key, {
      value,
      writable: true,
      enumerable,
      configurable: true
    });
  const getter = (object, key, get, enumerable = true, set = undefined) =>
    Object.defineProperty(object, key, { get, set, enumerable, configurable: true });
  const preview = value => {
    if (value === undefined) return "undefined";
    if (value === null) return "null";
    if (typeof value === "string") return value.length > 96 ? `${value.slice(0, 96)}…` : value;
    if (typeof value === "number" || typeof value === "boolean" || typeof value === "bigint") return String(value);
    if (typeof value === "function") return `function:${value.name || "anonymous"}`;
    return Object.prototype.toString.call(value);
  };
  const kindOf = value => value === null ? "null" : typeof value;
  const summary = value => ({ kind: kindOf(value), preview: preview(value) });
  const log = (kind, detail) => hostLog.push({ kind, ...detail });
  const logApi = (target, member, operation, args, outcome, threw = false) =>
    log("api", {
      target,
      member,
      operation,
      arguments: args.map(summary),
      outcome: summary(outcome),
      threw
    });

  data(globalThis, "__yatouTakeHostLog", () => hostLog.splice(0), false);
  data(globalThis, "__yatouInstallResource", resource => {
    resources.set(String(resource.url), Object.freeze({
      url: String(resource.url),
      status: Number(resource.status),
      headers: Object.freeze({ ...(resource.headers || {}) }),
      body: Object.freeze(Array.from(resource.body || [], value => Number(value) & 255)),
      body_sha256: String(resource.body_sha256)
    }));
  }, false);

  class Event {
    constructor(type, init = {}) {
      this.type = String(type);
      this.bubbles = Boolean(init.bubbles);
      this.cancelable = Boolean(init.cancelable);
      this.composed = Boolean(init.composed);
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
        this[key] = Number(init[key] || 0);
      for (const key of ["ctrlKey", "shiftKey", "altKey", "metaKey"])
        this[key] = Boolean(init[key]);
    }
  }

  class EventTarget {
    constructor() { this._listeners = new Map(); }
    addEventListener(type, callback, options = false) {
      type = String(type);
      logApi("EventTarget.prototype", "addEventListener", "call", [type, callback, options], undefined);
      if (callback == null) return;
      const entries = this._listeners.get(type) || [];
      const capture = typeof options === "object" ? Boolean(options.capture) : Boolean(options);
      if (!entries.some(entry => entry.callback === callback && entry.capture === capture))
        entries.push({ callback, capture, once: Boolean(options && options.once) });
      this._listeners.set(type, entries);
    }
    removeEventListener(type, callback, options = false) {
      type = String(type);
      logApi("EventTarget.prototype", "removeEventListener", "call", [type, callback, options], undefined);
      const capture = typeof options === "object" ? Boolean(options.capture) : Boolean(options);
      const entries = this._listeners.get(type) || [];
      this._listeners.set(type, entries.filter(entry => entry.callback !== callback || entry.capture !== capture));
    }
    dispatchEvent(event) {
      if (!(event instanceof Event)) throw new TypeError("parameter 1 is not of type 'Event'");
      logApi("EventTarget.prototype", "dispatchEvent", "call", [event], true);
      if (!event.target) event.target = this;
      event.currentTarget = this;
      event.eventPhase = Event.AT_TARGET;
      const entries = Array.from(this._listeners.get(event.type) || []);
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
      if (!(child instanceof Node)) throw new TypeError("parameter 1 is not of type 'Node'");
      if (child === this) throw new Error("HierarchyRequestError");
      if (child.parentNode) child.parentNode.removeChild(child);
      this.childNodes.push(child);
      child.parentNode = this;
      return child;
    }
    insertBefore(child, reference) {
      if (reference == null) return this.appendChild(child);
      const index = this.childNodes.indexOf(reference);
      if (index < 0) throw new Error("NotFoundError");
      if (child.parentNode) child.parentNode.removeChild(child);
      this.childNodes.splice(index, 0, child);
      child.parentNode = this;
      return child;
    }
    removeChild(child) {
      const index = this.childNodes.indexOf(child);
      if (index < 0) throw new Error("NotFoundError");
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
      const text = String(value ?? "");
      if (this.nodeType === Node.TEXT_NODE) this._text = text;
      else if (text) this.appendChild(new Text(text, this.ownerDocument));
    }
  }
  Object.assign(Node, {
    ELEMENT_NODE: 1,
    TEXT_NODE: 3,
    DOCUMENT_NODE: 9,
    DOCUMENT_FRAGMENT_NODE: 11
  });

  class Text extends Node {
    constructor(dataValue = "", ownerDocument = null) {
      super(Node.TEXT_NODE, "#text", ownerDocument);
      this._text = String(dataValue);
    }
    get data() { return this._text; }
    set data(value) { this._text = String(value); }
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
    _write(tokens) { this._element.className = Array.from(new Set(tokens)).join(" "); }
    get length() { return this._tokens().length; }
    contains(token) { return this._tokens().includes(String(token)); }
    add(...tokens) { this._write(this._tokens().concat(tokens.map(String))); }
    remove(...tokens) { const remove = new Set(tokens.map(String)); this._write(this._tokens().filter(token => !remove.has(token))); }
    toggle(token, force) {
      token = String(token);
      const present = this.contains(token);
      if (force === true || (!present && force !== false)) { this.add(token); return true; }
      if (present) this.remove(token);
      return false;
    }
    replace(previous, next) {
      const tokens = this._tokens();
      const index = tokens.indexOf(String(previous));
      if (index < 0) return false;
      tokens[index] = String(next); this._write(tokens); return true;
    }
    item(index) { return this._tokens()[Number(index)] || null; }
    toString() { return this._element.className; }
    [Symbol.iterator]() { return this._tokens()[Symbol.iterator](); }
  }

  const cssName = name => String(name).replace(/[A-Z]/g, value => `-${value.toLowerCase()}`);
  class CSSStyleDeclaration {
    constructor() { this._values = new Map(); this._priorities = new Map(); }
    get length() { return this._values.size; }
    item(index) { return Array.from(this._values.keys())[Number(index)] || ""; }
    setProperty(name, value, priority = "") {
      name = cssName(name).trim();
      if (!name) return;
      this._values.set(name, String(value));
      this._priorities.set(name, String(priority).toLowerCase() === "important" ? "important" : "");
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
      return Array.from(this._values, ([name, value]) => `${name}: ${value}${this.getPropertyPriority(name) ? " !important" : ""};`).join(" ");
    }
    set cssText(value) {
      this._values.clear(); this._priorities.clear();
      for (const declaration of String(value).split(";")) {
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
  const styleProxy = style => new Proxy(style, {
    get(target, key, receiver) {
      if (typeof key === "string" && !(key in target)) return target.getPropertyValue(key);
      return Reflect.get(target, key, receiver);
    },
    set(target, key, value, receiver) {
      if (typeof key === "string" && !(key in target)) { target.setProperty(key, value); return true; }
      return Reflect.set(target, key, value, receiver);
    },
    ownKeys(target) { return Reflect.ownKeys(target).concat(Array.from(target._values.keys())); },
    getOwnPropertyDescriptor(target, key) {
      return Reflect.getOwnPropertyDescriptor(target, key) || { configurable: true, enumerable: true, writable: true, value: target.getPropertyValue(key) };
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
    selector = String(selector).trim();
    if (!selector) return false;
    const attribute = selector.match(/^(.*)?\[([\w:-]+)(?:=["']?([^\]"']+)["']?)?\]$/);
    if (attribute) {
      if (attribute[1] && !matchesSimple(element, attribute[1])) return false;
      if (!element.hasAttribute(attribute[2])) return false;
      return attribute[3] === undefined || element.getAttribute(attribute[2]) === attribute[3];
    }
    const id = selector.match(/#([\w-]+)/);
    const classes = Array.from(selector.matchAll(/\.([\w-]+)/g), match => match[1]);
    const tag = selector.match(/^[a-zA-Z][\w-]*/)?.[0];
    return (!tag || element.localName === tag.toLowerCase())
      && (!id || element.id === id[1])
      && classes.every(name => element.classList.contains(name));
  };
  const querySelectorFrom = (root, selector, all) => {
    const selectors = String(selector).split(",").map(value => value.trim()).filter(Boolean);
    const found = descendants(root).filter(element => selectors.some(value => matchesSimple(element, value)));
    return all ? found : found[0] || null;
  };

  class Element extends Node {
    constructor(tagName, ownerDocument = null) {
      const upper = String(tagName).toUpperCase();
      super(Node.ELEMENT_NODE, upper, ownerDocument);
      this.tagName = upper;
      this.localName = upper.toLowerCase();
      this.namespaceURI = "http://www.w3.org/1999/xhtml";
      this.attributes = new Map();
      this.style = styleProxy(new CSSStyleDeclaration());
      this.classList = new DOMTokenList(this);
      this.dataset = Object.create(null);
      this.contentWindow = this.localName === "iframe" ? globalThis : null;
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
      for (const node of nodes) this.appendChild(node instanceof Node ? node : new Text(String(node), this.ownerDocument));
    }
    prepend(...nodes) {
      let reference = this.firstChild;
      for (const node of nodes) {
        const value = node instanceof Node ? node : new Text(String(node), this.ownerDocument);
        this.insertBefore(value, reference);
        if (reference === null) reference = value.nextSibling;
      }
    }
    setAttribute(name, value) {
      name = String(name).toLowerCase();
      const text = String(value);
      this.attributes.set(name, text);
      if (name.startsWith("data-")) this.dataset[name.slice(5).replace(/-([a-z])/g, (_, letter) => letter.toUpperCase())] = text;
    }
    getAttribute(name) { name = String(name).toLowerCase(); return this.attributes.has(name) ? this.attributes.get(name) : null; }
    hasAttribute(name) { return this.attributes.has(String(name).toLowerCase()); }
    removeAttribute(name) { this.attributes.delete(String(name).toLowerCase()); }
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
      name = String(name).toLowerCase();
      return descendants(this).filter(element => name === "*" || element.localName === name);
    }
    getBoundingClientRect() {
      return Object.freeze({ x: 0, y: 0, top: 0, left: 0, right: 0, bottom: 0, width: 0, height: 0, toJSON() { return { x: 0, y: 0, width: 0, height: 0, top: 0, right: 0, bottom: 0, left: 0 }; } });
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
      this._cookies = new Map();
      this.documentElement = this.createElement("html");
      this.head = this.createElement("head");
      this.body = this.createElement("body");
      this.appendChild(this.documentElement);
      this.documentElement.appendChild(this.head);
      this.documentElement.appendChild(this.body);
    }
    createElement(tagName) {
      const name = String(tagName).toLowerCase();
      if (name === "iframe") return new HTMLIFrameElement(name, this);
      if (name === "canvas") return new HTMLCanvasElement(name, this);
      return new HTMLElement(name, this);
    }
    createTextNode(value) { return new Text(value, this); }
    createDocumentFragment() { return new DocumentFragment(this); }
    getElementById(id) { return descendants(this).find(element => element.id === String(id)) || null; }
    getElementsByTagName(name) {
      name = String(name).toLowerCase();
      return descendants(this).filter(element => name === "*" || element.localName === name);
    }
    getElementsByClassName(name) {
      const tokens = String(name).trim().split(/\s+/);
      return descendants(this).filter(element => tokens.every(token => element.classList.contains(token)));
    }
    querySelector(selector) { return querySelectorFrom(this, selector, false); }
    querySelectorAll(selector) { return querySelectorFrom(this, selector, true); }
    get cookie() { return Array.from(this._cookies, ([name, value]) => `${name}=${value}`).join("; "); }
    set cookie(serialized) {
      const pair = String(serialized).split(";", 1)[0];
      const separator = pair.indexOf("=");
      if (separator <= 0) return;
      this._cookies.set(pair.slice(0, separator).trim(), pair.slice(separator + 1).trim());
      logApi("Document.prototype", "cookie", "set", [serialized], undefined);
    }
  }

  class Storage {
    constructor(name) { this._name = name; this._entries = new Map(); }
    get length() { return this._entries.size; }
    key(index) { return Array.from(this._entries.keys())[Number(index)] ?? null; }
    getItem(key) {
      key = String(key); const value = this._entries.has(key) ? this._entries.get(key) : null;
      logApi("Storage.prototype", "getItem", "call", [key], value); return value;
    }
    setItem(key, value) {
      key = String(key); value = String(value); this._entries.set(key, value);
      logApi("Storage.prototype", "setItem", "call", [key, value], undefined);
    }
    removeItem(key) { key = String(key); this._entries.delete(key); logApi("Storage.prototype", "removeItem", "call", [key], undefined); }
    clear() { this._entries.clear(); logApi("Storage.prototype", "clear", "call", [], undefined); }
  }

  class Headers {
    constructor(init = {}) {
      this._entries = new Map();
      if (init instanceof Headers) for (const [key, value] of init) this.set(key, value);
      else if (Array.isArray(init)) for (const [key, value] of init) this.append(key, value);
      else for (const [key, value] of Object.entries(init || {})) this.set(key, value);
    }
    append(name, value) { name = String(name).toLowerCase(); value = String(value); this._entries.set(name, this._entries.has(name) ? `${this._entries.get(name)}, ${value}` : value); }
    set(name, value) { this._entries.set(String(name).toLowerCase(), String(value)); }
    get(name) { return this._entries.get(String(name).toLowerCase()) ?? null; }
    has(name) { return this._entries.has(String(name).toLowerCase()); }
    delete(name) { this._entries.delete(String(name).toLowerCase()); }
    entries() { return this._entries.entries(); }
    keys() { return this._entries.keys(); }
    values() { return this._entries.values(); }
    [Symbol.iterator]() { return this.entries(); }
  }

  const utf8Decode = bytes => {
    let output = "";
    for (let index = 0; index < bytes.length;) {
      const first = bytes[index++];
      if (first < 128) { output += String.fromCharCode(first); continue; }
      if ((first & 224) === 192) {
        const second = bytes[index++] ?? 0; output += String.fromCharCode(((first & 31) << 6) | (second & 63)); continue;
      }
      if ((first & 240) === 224) {
        const second = bytes[index++] ?? 0, third = bytes[index++] ?? 0;
        output += String.fromCharCode(((first & 15) << 12) | ((second & 63) << 6) | (third & 63)); continue;
      }
      const second = bytes[index++] ?? 0, third = bytes[index++] ?? 0, fourth = bytes[index++] ?? 0;
      let point = ((first & 7) << 18) | ((second & 63) << 12) | ((third & 63) << 6) | (fourth & 63);
      point -= 0x10000; output += String.fromCharCode(0xD800 + (point >> 10), 0xDC00 + (point & 1023));
    }
    return output;
  };

  class Response {
    constructor(body = [], init = {}) {
      this._body = Array.from(body || [], value => Number(value) & 255);
      this.status = Number(init.status ?? 200);
      this.statusText = String(init.statusText || "");
      this.headers = new Headers(init.headers || {});
      this.url = String(init.url || "");
      this.type = "basic";
      this.redirected = false;
      this.bodyUsed = false;
    }
    get ok() { return this.status >= 200 && this.status <= 299; }
    async text() { this.bodyUsed = true; return utf8Decode(this._body); }
    async json() { return JSON.parse(await this.text()); }
    async arrayBuffer() { this.bodyUsed = true; return Uint8Array.from(this._body).buffer; }
    clone() { return new Response(this._body, { status: this.status, statusText: this.statusText, headers: Object.fromEntries(this.headers), url: this.url }); }
  }

  async function fetch(input, init = {}) {
    const url = String(input && input.url || input);
    const method = String(init.method || input && input.method || "GET").toUpperCase();
    const resource = resources.get(url);
    if (!resource) {
      const error = new TypeError(`offline resource not found: ${url}`);
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
    open(method, url, async = true) { this._method = String(method).toUpperCase(); this._url = String(url); this._async = Boolean(async); this.readyState = 1; }
    setRequestHeader(name, value) { this._requestHeaders.append(name, value); }
    getResponseHeader(name) { return this._responseHeaders.get(name); }
    getAllResponseHeaders() { return Array.from(this._responseHeaders, ([key, value]) => `${key}: ${value}\r\n`).join(""); }
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
    const delayMs = Math.max(0, Number(delay) || 0);
    timers.set(timerId, { callback, args, delayMs, dueMs: clockMs + delayMs, repeating });
    log("timer_schedule", { timer_id: timerId, delay_ms: delayMs, repeating });
    return timerId;
  };
  const setTimeoutHost = (callback, delay = 0, ...args) => schedule(callback, delay, false, args);
  const setIntervalHost = (callback, delay = 0, ...args) => schedule(callback, delay, true, args);
  const clearTimer = timerId => timers.delete(Number(timerId));
  const queueMicrotaskHost = callback => { if (typeof callback !== "function") throw new TypeError("callback is not a function"); microtasks.push(callback); };
  const drain = (limit = 1000) => {
    limit = Math.max(0, Math.min(100000, Number(limit) || 0));
    let callbacks = 0;
    while (callbacks < limit) {
      if (microtasks.length) {
        const callback = microtasks.shift(); callback(); callbacks += 1; continue;
      }
      const next = Array.from(timers, ([id, timer]) => ({ id, timer }))
        .sort((left, right) => left.timer.dueMs - right.timer.dueMs || left.id - right.id)[0];
      if (!next) break;
      clockMs = Math.max(clockMs, next.timer.dueMs);
      if (!next.timer.repeating) timers.delete(next.id);
      else next.timer.dueMs = clockMs + next.timer.delayMs;
      log("timer_fire", { timer_id: next.id });
      if (typeof next.timer.callback === "function") next.timer.callback(...next.timer.args);
      else (0, eval)(String(next.timer.callback));
      callbacks += 1;
    }
    return { callbacks, pendingTimers: timers.size, pendingMicrotasks: microtasks.length, clockMs };
  };
  data(globalThis, "__yatouDrain", drain, false);

  const document = new Document();
  const parseLocation = value => {
    const text = String(value);
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
    assign(value) { this.href = String(value); },
    replace(value) { this.href = String(value); },
    reload() {},
    toString() { return this.href; }
  };
  const navigator = {};
  for (const [key, value] of Object.entries({
    userAgent: profile.user_agent,
    appVersion: profile.user_agent.replace(/^Mozilla\//, ""),
    appCodeName: "Mozilla",
    appName: "Netscape",
    platform: profile.platform,
    language: profile.language,
    languages: Object.freeze(profile.languages.slice()),
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
  for (const [key, value] of Object.entries({
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
  const computedDefaults = Object.freeze({
    display: "block", position: "static", visibility: "visible", opacity: "1",
    width: "auto", height: "auto", color: "rgb(0, 0, 0)",
    fontSize: "16px", lineHeight: "normal", boxSizing: "content-box"
  });
  const getComputedStyle = element => {
    if (!(element instanceof Element)) throw new TypeError("parameter 1 is not of type 'Element'");
    logApi("globalThis", "getComputedStyle", "call", [element], element.style);
    return new Proxy({}, {
      get(_target, key) {
        if (key === "getPropertyValue") return name => element.style.getPropertyValue(name) || computedDefaults[cssName(name)] || "";
        if (key === "length") return Object.keys(computedDefaults).length;
        if (key === "item") return index => Object.keys(computedDefaults)[Number(index)] || "";
        if (key === "cssText") return "";
        if (typeof key === "string") return element.style.getPropertyValue(key) || computedDefaults[cssName(key)] || "";
        return undefined;
      },
      ownKeys() { return Reflect.ownKeys(computedDefaults); },
      getOwnPropertyDescriptor() { return { configurable: true, enumerable: true }; }
    });
  };

  let randomState = (Number(config.random_seed) >>> 0) || 0x9e3779b9;
  const nextRandom = () => { randomState ^= randomState << 13; randomState ^= randomState >>> 17; randomState ^= randomState << 5; return randomState >>> 0; };
  const crypto = {
    getRandomValues(array) {
      if (!ArrayBuffer.isView(array) || array.byteLength > 65536) throw new TypeError("invalid typed array");
      const bytes = new Uint8Array(array.buffer, array.byteOffset, array.byteLength);
      for (let index = 0; index < bytes.length; index++) bytes[index] = nextRandom() & 255;
      return array;
    },
    randomUUID() {
      const bytes = this.getRandomValues(new Uint8Array(16));
      bytes[6] = (bytes[6] & 15) | 64; bytes[8] = (bytes[8] & 63) | 128;
      const hex = Array.from(bytes, value => value.toString(16).padStart(2, "0")).join("");
      return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
    }
  };

  getter(globalThis, "window", () => globalThis);
  getter(globalThis, "self", () => globalThis);
  getter(globalThis, "top", () => globalThis);
  getter(globalThis, "parent", () => globalThis);
  getter(globalThis, "frames", () => globalThis);
  getter(globalThis, "navigator", () => navigator);
  getter(globalThis, "screen", () => screen);
  getter(globalThis, "document", () => document);
  data(globalThis, "location", location);
  data(globalThis, "origin", location.origin);
  data(globalThis, "innerWidth", config.viewport.width);
  data(globalThis, "innerHeight", config.viewport.height);
  data(globalThis, "outerWidth", profile.screen_width);
  data(globalThis, "outerHeight", profile.screen_height);
  data(globalThis, "devicePixelRatio", config.viewport.device_scale_factor);
  data(globalThis, "isSecureContext", location.protocol === "https:");
  data(globalThis, "crossOriginIsolated", false);
  data(globalThis, "Event", Event);
  data(globalThis, "CustomEvent", CustomEvent);
  data(globalThis, "MouseEvent", MouseEvent);
  data(globalThis, "EventTarget", EventTarget);
  data(globalThis, "Node", Node);
  data(globalThis, "Text", Text);
  data(globalThis, "DocumentFragment", DocumentFragment);
  data(globalThis, "Element", Element);
  data(globalThis, "HTMLElement", HTMLElement);
  data(globalThis, "HTMLIFrameElement", HTMLIFrameElement);
  data(globalThis, "HTMLCanvasElement", HTMLCanvasElement);
  data(globalThis, "Document", Document);
  data(globalThis, "CSSStyleDeclaration", CSSStyleDeclaration);
  data(globalThis, "Storage", Storage);
  data(globalThis, "Headers", Headers);
  data(globalThis, "Response", Response);
  data(globalThis, "XMLHttpRequest", XMLHttpRequest);
  data(globalThis, "localStorage", localStorage);
  data(globalThis, "sessionStorage", sessionStorage);
  data(globalThis, "fetch", fetch);
  data(globalThis, "getComputedStyle", getComputedStyle);
  data(globalThis, "setTimeout", setTimeoutHost);
  data(globalThis, "clearTimeout", clearTimer);
  data(globalThis, "setInterval", setIntervalHost);
  data(globalThis, "clearInterval", clearTimer);
  data(globalThis, "queueMicrotask", queueMicrotaskHost);
  data(globalThis, "requestAnimationFrame", callback => schedule(() => callback(clockMs), 1000 / 60, false, []));
  data(globalThis, "cancelAnimationFrame", clearTimer);
  data(globalThis, "crypto", crypto);
  data(globalThis, "addEventListener", EventTarget.prototype.addEventListener.bind(globalThis));
  data(globalThis, "removeEventListener", EventTarget.prototype.removeEventListener.bind(globalThis));
  data(globalThis, "dispatchEvent", EventTarget.prototype.dispatchEvent.bind(globalThis));
  data(globalThis, "_listeners", new Map(), false);
  data(performance, "timeOrigin", config.time_origin_ms);
  data(document, "defaultView", globalThis);
  data(globalThis, "__yatouEnvironment", Object.freeze({
    url: config.url,
    baseline: config.baseline,
    userAgent: profile.user_agent,
    platform: profile.platform,
    language: profile.language,
    viewport: Object.freeze({ ...config.viewport }),
    networkFallback: false,
    clockMode: profile.clock.mode
  }), false);
})()
