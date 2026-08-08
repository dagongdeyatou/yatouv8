(() => {
  const manifest = __YATOU_RUNTIME_SURFACE__;
  const display = key => typeof key === "symbol" ? String(key) : key;
  const resolve = path => path === "globalThis"
    ? globalThis
    : path.split(".").reduce((value, key) => value == null ? undefined : value[key], globalThis);
  let expected = 0;
  let present = 0;
  let descriptorExact = 0;
  let callableExpected = 0;
  let callableExact = 0;
  const failures = [];
  for (const interfaceSpec of manifest.interfaces) {
    const object = resolve(interfaceSpec.path);
    if ((typeof object !== "object" || object === null) && typeof object !== "function") {
      failures.push({ path: interfaceSpec.path, kind: "missing_interface" });
      continue;
    }
    const actualKeys = Reflect.ownKeys(object).map(display);
    const expectedKeys = interfaceSpec.members.map(member => member.k.display);
    if (JSON.stringify(actualKeys) !== JSON.stringify(expectedKeys)) {
      failures.push({
        path: interfaceSpec.path,
        kind: "key_order",
        expected: expectedKeys.length,
        actual: actualKeys.length
      });
    }
    for (const member of interfaceSpec.members) {
      expected += 1;
      const key = member.k.kind === "string"
        ? member.k.display
        : Reflect.ownKeys(object).find(candidate => display(candidate) === member.k.display);
      const descriptor = key === undefined ? undefined : Object.getOwnPropertyDescriptor(object, key);
      if (!descriptor) {
        failures.push({ path: interfaceSpec.path, key: member.k.display, kind: "missing" });
        continue;
      }
      present += 1;
      const kind = "value" in descriptor ? "data" : "accessor";
      const basic = kind === member.d
        && descriptor.configurable === member.c
        && descriptor.enumerable === member.e
        && (kind !== "data" || descriptor.writable === member.w);
      if (basic) descriptorExact += 1;
      else failures.push({ path: interfaceSpec.path, key: member.k.display, kind: "descriptor" });
      for (const [slot, callable] of [["value", member.f], ["get", member.g], ["set", member.s]]) {
        if (!callable) continue;
        callableExpected += 1;
        const value = descriptor[slot];
        const exact = typeof value === "function"
          && value.name === callable.name
          && value.length === callable.length
          && (!callable.native_like || Function.prototype.toString.call(value).includes("[native code]"));
        if (exact) callableExact += 1;
        else failures.push({ path: interfaceSpec.path, key: member.k.display, kind: "callable", slot });
      }
    }
  }
  return {
    expected,
    present,
    descriptorExact,
    callableExpected,
    callableExact,
    failureCount: failures.length,
    failures: failures.slice(0, 100)
  };
})()
