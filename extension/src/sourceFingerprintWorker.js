'use strict';

const { parentPort, workerData } = require('node:worker_threads');
const { snapshotSourceFingerprint, snapshotSourceWatchStamp } = require('./pxBridge');

try {
  const args = [workerData.engineRoot, workerData.projectRoot, workerData.workspaceRoot];
  let result;
  if (workerData.mode === 'watch') result = snapshotSourceWatchStamp(...args);
  else if (workerData.mode === 'complete') result = snapshotSourceFingerprint(...args);
  else if (workerData.mode === 'both') result = {
    watchStamp: snapshotSourceWatchStamp(...args),
    value: snapshotSourceFingerprint(...args)
  };
  else throw new Error(`Unsupported source fingerprint worker mode: ${workerData.mode}`);
  parentPort.postMessage({ ok: true, result });
} catch (error) {
  parentPort.postMessage({ ok: false, error: error instanceof Error ? error.message : String(error) });
}
