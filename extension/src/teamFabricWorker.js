'use strict';

const { parentPort, workerData } = require('node:worker_threads');
const { inventoryTeamPack } = require('./teamFabricManager');

try {
  parentPort.postMessage({ ok: true, result: inventoryTeamPack(workerData.sourceRoot, workerData.existingIds || []) });
} catch (error) {
  parentPort.postMessage({ ok: false, error: error instanceof Error ? error.message : String(error) });
}
