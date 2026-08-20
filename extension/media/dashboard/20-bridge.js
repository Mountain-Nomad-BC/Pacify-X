'use strict';

(() => {
  const dashboard = globalThis.PXDashboard;
  if (!dashboard) throw new Error('PXDashboard foundation must load before bridge.');

  dashboard.define('bridge', {
    create(vscodeApi, eventTarget = globalThis) {
      if (!vscodeApi || typeof vscodeApi.postMessage !== 'function') throw new TypeError('A VS Code webview API is required.');
      return Object.freeze({
        post(type, payload = {}) {
          if (!type || typeof type !== 'string') throw new TypeError('Message type must be a non-empty string.');
          vscodeApi.postMessage({ type, ...payload });
        },
        subscribe(handler) {
          if (typeof handler !== 'function') throw new TypeError('Message handler must be a function.');
          const listener = event => handler(event.data, event);
          eventTarget.addEventListener('message', listener);
          return () => eventTarget.removeEventListener('message', listener);
        },
        getState() { return vscodeApi.getState?.() || {}; },
        setState(value) { return vscodeApi.setState?.(value); }
      });
    }
  });
})();
