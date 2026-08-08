(() => {
  const tag = value => Object.prototype.toString.call(value);
  const keys = value => value == null ? [] : Reflect.ownKeys(value).map(String);
  const descriptor = (object, key) => {
    const value = Object.getOwnPropertyDescriptor(object, key);
    if (!value) return null;
    return {
      kind: "value" in value ? "data" : "accessor",
      enumerable: value.enumerable,
      configurable: value.configurable,
      writable: "writable" in value ? value.writable : null,
      get: typeof value.get,
      set: typeof value.set,
    };
  };
  const canvas = document.createElement("canvas");
  const context2d = canvas.getContext("2d");
  const media = matchMedia("(min-width: 1px) and (orientation: landscape)");
  const plugins = Array.from(navigator.plugins, plugin => ({
    name: plugin.name,
    filename: plugin.filename,
    description: plugin.description,
    length: plugin.length,
    types: Array.from(plugin, mime => ({
      type: mime.type,
      suffixes: mime.suffixes,
      description: mime.description,
    })),
  }));
  const timing = performance.timing;
  const navigation = performance.navigation;
  const memory = performance.memory;
  const entries = performance.getEntriesByType("navigation");
  return {
    globals: {
      chromeKeys: keys(chrome),
      chromeRuntime: typeof chrome.runtime,
      userAgentData: typeof navigator.userAgentData,
      navigatorOwnKeys: keys(navigator),
      screenOwnKeys: keys(screen),
      addEventListener: typeof globalThis.addEventListener,
      removeEventListener: typeof globalThis.removeEventListener,
      dispatchEvent: typeof globalThis.dispatchEvent,
      globalAlias: typeof globalThis.global,
      eventTargetPrototype: EventTarget.prototype.isPrototypeOf(globalThis),
      windowPropertiesTag: tag(Object.getPrototypeOf(Window.prototype)),
    },
    chrome: {
      appKeys: keys(chrome.app),
      isInstalled: chrome.app.isInstalled,
      csiKeys: keys(chrome.csi()),
      loadTimesKeys: keys(chrome.loadTimes()),
    },
    plugins: {
      tag: tag(navigator.plugins),
      length: navigator.plugins.length,
      entries: plugins,
      itemIdentity: navigator.plugins.item(0) === navigator.plugins[0],
      namedIdentity: navigator.plugins.namedItem("PDF Viewer") === navigator.plugins[0],
      indexDescriptor: descriptor(navigator.plugins, "0"),
      nameDescriptor: descriptor(navigator.plugins, "PDF Viewer"),
      mimeTag: tag(navigator.mimeTypes),
      mimeLength: navigator.mimeTypes.length,
    },
    navigator: {
      permissionsTag: tag(navigator.permissions),
      queryType: typeof navigator.permissions.query,
      connectionTag: tag(navigator.connection),
      connection: navigator.connection && {
        effectiveType: navigator.connection.effectiveType,
        rttType: typeof navigator.connection.rtt,
        rttNonNegative: navigator.connection.rtt >= 0,
        downlinkType: typeof navigator.connection.downlink,
        downlinkPositive: navigator.connection.downlink > 0,
        saveData: navigator.connection.saveData,
      },
      gamepads: navigator.getGamepads().length,
      javaEnabled: navigator.javaEnabled(),
    },
    screen: {
      orientationTag: tag(screen.orientation),
      type: screen.orientation && screen.orientation.type,
      angle: screen.orientation && screen.orientation.angle,
    },
    document: { hasFocus: document.hasFocus() },
    performance: {
      timingTag: tag(timing),
      timingKeys: timing && keys(timing.toJSON()),
      navigationTag: tag(navigation),
      navigation: navigation && navigation.toJSON(),
      memoryTag: tag(memory),
      memoryKeys: memory && keys(Object.getPrototypeOf(memory)),
      entryCount: entries.length,
      entryTag: entries[0] ? tag(entries[0]) : null,
      entryType: entries[0] ? entries[0].entryType : null,
    },
    media: {
      tag: tag(media),
      media: media.media,
      matches: media.matches,
      visualViewportTag: tag(visualViewport),
      widthMatchesInner: visualViewport && visualViewport.width === innerWidth,
      heightMatchesInner: visualViewport && visualViewport.height === innerHeight,
      scale: visualViewport && visualViewport.scale,
    },
    canvas: {
      width: canvas.width,
      height: canvas.height,
      context2dTag: tag(context2d),
      webgl: canvas.getContext("webgl"),
      dataUrlPrefix: canvas.toDataURL().slice(0, 22),
    },
  };
})()
