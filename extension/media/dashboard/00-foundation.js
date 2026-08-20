'use strict';

(() => {
  const root = globalThis;
  if (root.PXDashboard) return;

  const modules = new Map();
  const api = {
    version: '1.0.0',
    define(name, value) {
      if (!name || typeof name !== 'string') throw new TypeError('Dashboard module name must be a non-empty string.');
      if (modules.has(name)) throw new Error(`Dashboard module already defined: ${name}`);
      modules.set(name, Object.freeze(value));
      return modules.get(name);
    },
    require(name) {
      if (!modules.has(name)) throw new Error(`Dashboard module is not available: ${name}`);
      return modules.get(name);
    },
    has(name) { return modules.has(name); },
    list() { return Object.freeze([...modules.keys()]); }
  };

  Object.defineProperty(root, 'PXDashboard', {
    value: Object.freeze(api), configurable: false, enumerable: false, writable: false
  });
})();
