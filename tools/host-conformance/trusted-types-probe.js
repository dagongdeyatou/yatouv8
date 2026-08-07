(() => {
  const descriptor = (object, key) => {
    const value = Object.getOwnPropertyDescriptor(object, key);
    if (!value) return null;
    return {
      configurable: value.configurable,
      enumerable: value.enumerable,
      writable: Object.hasOwn(value, "writable") ? value.writable : null,
      get: typeof value.get,
      set: typeof value.set,
      value_type: typeof value.value,
    };
  };
  const attempt = callback => {
    try {
      const value = callback();
      return {
        ok: true,
        type: typeof value,
        value: String(value),
        tag: Object.prototype.toString.call(value),
        constructor: value?.constructor?.name ?? null,
      };
    } catch (error) {
      return { ok: false, name: error.name, message: error.message };
    }
  };
  const describePrototype = value => {
    const prototype = Object.getPrototypeOf(value);
    const keys = Object.getOwnPropertyNames(prototype);
    return {
      name: prototype.constructor?.name ?? null,
      keys,
      descriptors: Object.fromEntries(keys.map(key => [key, descriptor(prototype, key)])),
      callables: Object.fromEntries(keys.flatMap(key => {
        const value = Object.getOwnPropertyDescriptor(prototype, key)?.value;
        return typeof value === "function"
          ? [[key, { name: value.name, length: value.length, native: Function.prototype.toString.call(value).includes("[native code]") }]]
          : [];
      })),
    };
  };

  const globals = {};
  for (const name of [
    "trustedTypes",
    "TrustedHTML",
    "TrustedScript",
    "TrustedScriptURL",
    "TrustedTypePolicy",
    "TrustedTypePolicyFactory",
  ]) {
    globals[name] = {
      type: typeof globalThis[name],
      descriptor: descriptor(globalThis, name),
      tag: globalThis[name] == null ? null : Object.prototype.toString.call(globalThis[name]),
    };
  }

  const suffix = "probe";
  const policy = trustedTypes.createPolicy(`yatou-values-${suffix}`, {
    createHTML: value => `H:${value}`,
    createScript: value => `S:${value}`,
    createScriptURL: value => `U:${value}`,
  });
  const html = policy.createHTML("x");
  const script = policy.createScript("x");
  const scriptURL = policy.createScriptURL("x");
  const duplicateName = `yatou-duplicate-${suffix}`;

  return {
    globals,
    factory: {
      tag: Object.prototype.toString.call(trustedTypes),
      own_keys: Object.getOwnPropertyNames(trustedTypes),
      prototype: describePrototype(trustedTypes),
      default_policy: trustedTypes.defaultPolicy === null ? null : String(trustedTypes.defaultPolicy),
      empty_html: String(trustedTypes.emptyHTML),
      empty_script: String(trustedTypes.emptyScript),
    },
    policy: {
      name: policy.name,
      tag: Object.prototype.toString.call(policy),
      own_keys: Object.getOwnPropertyNames(policy),
      prototype: describePrototype(policy),
    },
    values: {
      html: { value: String(html), json: JSON.stringify(html), prototype: describePrototype(html) },
      script: { value: String(script), json: JSON.stringify(script), prototype: describePrototype(script) },
      script_url: { value: String(scriptURL), json: JSON.stringify(scriptURL), prototype: describePrototype(scriptURL) },
    },
    calls: {
      create_html: attempt(() => policy.createHTML("x")),
      create_script: attempt(() => policy.createScript("x")),
      create_script_url: attempt(() => policy.createScriptURL("x")),
      is_html_true: attempt(() => trustedTypes.isHTML(html)),
      is_script_true: attempt(() => trustedTypes.isScript(script)),
      is_script_url_true: attempt(() => trustedTypes.isScriptURL(scriptURL)),
      is_html_string: attempt(() => trustedTypes.isHTML("x")),
      duplicate_name: attempt(() => {
        trustedTypes.createPolicy(duplicateName, { createHTML: value => value });
        return trustedTypes.createPolicy(duplicateName, { createHTML: value => value });
      }),
      missing_rule: attempt(() =>
        trustedTypes.createPolicy(`yatou-missing-${suffix}`, {}).createScript("x")
      ),
      invalid_rule: attempt(() =>
        trustedTypes.createPolicy(`yatou-invalid-${suffix}`, { createScript: 1 })
      ),
      construct_html: attempt(() => new TrustedHTML()),
      construct_policy: attempt(() => new TrustedTypePolicy()),
      get_attribute_type: attempt(() => trustedTypes.getAttributeType("script", "src")),
      get_property_type: attempt(() => trustedTypes.getPropertyType("script", "src")),
      get_attribute_unknown: attempt(() => trustedTypes.getAttributeType("foo", "bar")),
      get_property_unknown: attempt(() => trustedTypes.getPropertyType("foo", "bar")),
      get_type_mapping: attempt(() => trustedTypes.getTypeMapping()),
    },
  };
})()
