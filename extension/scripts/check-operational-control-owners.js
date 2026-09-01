'use strict';
const fs = require('node:fs'); const path = require('node:path'); const walk = require('./run-operational-ui-walk');
const root = path.resolve(__dirname, '..', '..'); const matrix = JSON.parse(fs.readFileSync(path.join(root, 'registry', 'operational_control_proof_matrix.json'), 'utf8'));
const probes = [
  () => walk.studioLifecycleControlProbe(matrix, []), () => walk.learningLifecycleControlProbe(matrix, { operations: [], errors: [] }),
  () => walk.coordinationMemoryControlProbe(matrix, { operations: [], errors: [] }), () => walk.cleanupControlProbe(matrix, { errors: [] }),
  () => walk.projectsControlProbe(matrix, { errors: [] }), () => walk.knowledgeGraphControlProbe(matrix, { errors: [] }),
  () => walk.systemProjectionControlProbe(matrix, { errors: [] }), () => walk.sidebarStateControlProbe(matrix, { errors: [], baseline: {}, reopened: {}, fault: {}, recovered: {} }),
  () => walk.pluginReadControlProbe(matrix, { operations: {}, errors: [] }), () => walk.pluginMutationControlProbe(matrix, { errors: [] }),
  () => walk.knowledgeLifecycleControlProbe(matrix, { operations: [], errors: [] }), () => walk.hostBoundaryControlProbe(matrix, { operations: {} }),
  () => walk.enterpriseControlProbe(matrix, { controls: {} }), () => walk.environmentLifecycleControlProbe(matrix, { errors: [] }),
  () => walk.codexHandoffControlProbe(matrix, { errors: [] }), () => walk.validationControlProbe(matrix, { errors: [] })
];
const direct = new Set(['pxui.activity.action.activityPause', 'pxui.diagnostics.action.dynamicRepair.configureCanonicalMemory', 'pxui.memory.action.configureCanonicalMemory', 'pxui.memory.action.disconnectCanonicalMemory', 'pxui.settings.action.toggleBillablePolicy', 'pxui.agent-studio.action.setupStudio', 'pxui.agents.action.setupStudio', 'pxui.workflows.action.setupStudio', 'pxui.agent-studio.action.submitStudioDraft.agent', 'pxui.workflow-studio.action.submitStudioDraft.workflow', 'pxui.skill-studio.action.submitStudioDraft.skill']);
const owned = new Map([...direct].map(id => [id, ['direct-owned-profile']]));
for (const probe of probes) for (const record of probe().records || []) { const owners = owned.get(record.control_id) || []; owners.push(String(record.evidence_mode || 'typed-profile')); owned.set(record.control_id, owners); }
const effects = new Set(['clipboard-write', 'configuration-write', 'destructive-filesystem', 'filesystem-write', 'host-extension-write', 'host-ui', 'host-ui-or-routed-preview', 'owned-process', 'owned-process-control', 'process', 'workspace-write', 'workspace-write-and-owned-process', 'workspace-write-or-owned-process']);
const denominator = matrix.controls.filter(control => effects.has(control.effect)); const missing = denominator.filter(control => !owned.has(control.control_id)); const duplicate = denominator.filter(control => (owned.get(control.control_id) || []).length !== 1);
const result = { schema_version: 'px.operational-control-owner-check/1.0', total: denominator.length, owned_once: denominator.length - missing.length - duplicate.length, missing: missing.map(item => item.control_id), duplicate: duplicate.map(item => ({ control_id: item.control_id, owners: owned.get(item.control_id) })) };
process[missing.length || duplicate.length ? 'stderr' : 'stdout'].write(`${JSON.stringify(result, null, 2)}\n`); if (missing.length || duplicate.length) process.exitCode = 1;
