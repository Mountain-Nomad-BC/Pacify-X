'use strict';

function createLatestDiscoveryCoordinator() {
  let pending = null;
  let generation = 0;

  function run(start, options = {}) {
    if (typeof start !== 'function') throw new TypeError('latest-discovery-start-required');
    if (!pending || options.requireFresh === true) {
      generation += 1;
      let candidate;
      try { candidate = Promise.resolve(start(generation)); }
      catch (error) { candidate = Promise.reject(error); }
      pending = candidate;
      const clearIfOwner = () => { if (pending === candidate) pending = null; };
      candidate.then(clearIfOwner, clearIfOwner);
    }
    return pending;
  }

  return { run };
}

module.exports = { createLatestDiscoveryCoordinator };
