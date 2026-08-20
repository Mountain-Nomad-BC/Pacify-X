'use strict';

const { parentPort, workerData } = require('worker_threads');
const {
  boundedTree,
  virtualEnvironmentInventory,
  environmentFileInventory
} = require('./discoveryManager');

try {
  const tree = boundedTree(workerData.roots || []);
  const virtualEnvironments = virtualEnvironmentInventory(tree, {
    pythonPath: workerData.pythonPath,
    currentPythonVersion: workerData.currentPythonVersion,
    generatedUtc: workerData.generatedUtc
  });
  const environmentFiles = environmentFileInventory(tree);
  parentPort.postMessage({ ok: true, result: { tree, virtualEnvironments, environmentFiles } });
} catch (error) {
  parentPort.postMessage({ ok: false, error: error instanceof Error ? error.message : String(error) });
}
