'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.resolve(__dirname, '..');

function loadDashboardModules() {
  const context = vm.createContext({});
  context.globalThis = context;
  for (const file of ['00-foundation.js', '25-health-state.js', '30-components.js', '45-system-surfaces.js']) {
    vm.runInContext(fs.readFileSync(path.join(root, 'media', 'dashboard', file), 'utf8'), context, { filename: file });
  }
  return context.PXDashboard;
}

function loadSystemSurfaces() { return loadDashboardModules().require('systemSurfaces'); }

function fixture(overrides = {}) {
  const state = {
    snapshot: {
      connected: true,
      catalogSource: 'runtime.dashboard_api',
      source: { engineRoot: 'C:\\PX' },
      counts: { assurance: 4, contracts: 3 },
      validation: { status: 'passed', detail: 'All checks passed.' },
      runtime: { turbovec: { status: 'fallback', fallback: 'CPU' } },
      readiness: {
        dimensions: [{ id: 'R1', name: '<Bounded>', question: 'Is it bounded?', score: 4, maximum: 5, status: 'partial', blocking: true }],
        summary: { ready: 4, partial: 1, gaps: 1 }, maturity: { level: 3, label: 'Operational', readiness_ceiling: 4 },
        priority_gaps: ['Fresh E2E proof'], authority: 'advisory only'
      },
      authorities: [{ capability: '<unsafe>', owner: 'runtime', status: 'implemented', exposure: 'dashboard' }],
      enterprise: {
        catalog_id: 'enterprise', separation: { state_schema: 'v1', credential_storage: 'none', canonical_memory_import: 'denied' },
        defaults: { billable_services: 'disabled' }
      },
      environment: { summary: { graph_nodes: 12 } }
    },
    coordination: { state: { revision: 7 }, paths: { root: '.engineering-bootstrap/coordination' } },
    settings: {
      refreshIntervalSeconds: 30, showAdvancedSurfaces: false, contextInjectionCapTokens: 12000, ollamaEnabled: false,
      executionPolicy: { master_enabled: false, local_first: true, provider_allowlist: [], require_approval_before_billable_execution: true }
    }
  };
  return {
    state: Object.assign(state, overrides),
    healthState: loadDashboardModules().require('healthState'),
    serviceGrid: () => '<div data-test="service-grid"></div>',
    catalogPanel: kind => `<div data-test="catalog">${kind}</div>`
  };
}

test('U02 system surface router is bounded and rejects missing authority inputs', () => {
  const surfaces = loadSystemSurfaces();
  assert.equal(surfaces.has('diagnostics'), true);
  assert.equal(surfaces.has('projects'), false);
  assert.throws(() => surfaces.render('projects', fixture()), /Unknown system surface/);
  assert.throws(() => surfaces.render('diagnostics', {}), /canonical snapshot/);
});

test('diagnostics renderer preserves controls, integration composition, and catalog request', () => {
  const html = loadSystemSurfaces().render('diagnostics', fixture());
  assert.match(html, /data-action="validate"/);
  assert.match(html, /data-test="service-grid"/);
  assert.match(html, /data-test="catalog">enterprise-integrations/);
  assert.match(html, /All checks passed\./);
});

test('historical runtime failures remain visible evidence but never become live blockers', () => {
  const context = fixture();
  context.state.snapshot.runtime = {
    core: { counters: { failures: 7 } },
    bottlenecks: { failures: 0, historical_failures: 7 },
    turbovec: { status: 'fallback', fallback: 'CPU' }
  };
  const diagnostics = loadSystemSurfaces().render('diagnostics', context);
  assert.match(diagnostics, /7 historical work-plane failures retained as evidence/);
  assert.doesNotMatch(diagnostics, /runtime-failures/);
  const assurance = loadSystemSurfaces().render('assurance', context);
  assert.doesNotMatch(assurance, /runtime failures are retained/);
});

test('retained operational cards are history while the active repair campaign owns live blockers', () => {
  const context = fixture();
  context.state.snapshot.completion = { operational_punch_cards: { source_status: 'open', count: 40, open_count: 0, retained_unclosed_count: 38, progress: {}, cards: [] } };
  context.state.snapshot.repair_campaign = { valid: true, campaign_id: 'repair:test', phase: 'repair', unresolved_count: 1, unresolved: ['studio-operability'] };
  const html = loadSystemSurfaces().render('diagnostics', context);
  assert.match(html, /active-repair-campaign/);
  assert.match(html, /1 functional repair tracks remain/);
  assert.match(html, /0 ACTIVE \/ 38 UNCLOSED HISTORY \/ 40 RETAINED/);
  assert.doesNotMatch(html, /operational findings are not closed/);
});

test('diagnostics renders truthful ledger states, exact-card actions, and invalid-ledger failure', () => {
  const context = fixture();
  context.state.snapshot.completion = { operational_punch_cards: {
    source_status: 'open', count: 2, open_count: 2, offset: 0, limit: 50, filtered_count: 2, has_more: false,
    progress: { total_known_surfaces: 20, surfaces_examined: 0, known_controls: 385, controls_with_disposition: 0, controls_not_yet_disposed: 385, gaps_discovered: 2, discovered: 1, scoped: 1, cards_lacking_required_evidence: ['PX-OS-001'], cards_with_unbound_evidence: [], report_findings: 1, report_findings_reconciled: 1 },
    cards: [{ id: 'PX-OS-001', area: 'dashboard', feature: 'exact detail', finding: 'detail is required', severity: 'critical', status: 'discovered' }]
  } };
  const html = loadSystemSurfaces().render('diagnostics', context);
  assert.match(html, /TOTAL GAPS/);
  assert.match(html, /DISCOVERED/);
  assert.match(html, /data-action="inspectPunchCard" data-gap-id="PX-OS-001"/);
  assert.match(html, /data-action="inspectOperationalInventory"/);
  context.state.snapshot.completion.operational_punch_cards = { source_status: 'invalid', error: 'hash-chain broken', count: 0, open_count: 0, progress: {}, cards: [] };
  const invalid = loadSystemSurfaces().render('diagnostics', context);
  assert.match(invalid, /OPERATIONAL LEDGER INVALID/);
  assert.match(invalid, /hash-chain broken/);
  context.state.snapshot.completion.operational_punch_cards = { source_status: 'checkpoint_stale', error: 'checkpoint fingerprint changed', recovery_action: 'python -m scripts.operational_gap_ledger --root . project', count: 0, open_count: 0, progress: {}, cards: [] };
  const stale = loadSystemSurfaces().render('diagnostics', context);
  assert.match(stale, /OPERATIONAL LEDGER CHECKPOINT STALE/);
  assert.match(stale, /Retry checkpoint read/);
  context.state.snapshot.completion.operational_punch_cards = { source_status: 'recovery_required', error: 'tail requires recovery', recovery_action: 'python -m scripts.operational_gap_ledger --root . project', count: 0, open_count: 0, progress: {}, cards: [] };
  const recovery = loadSystemSurfaces().render('diagnostics', context);
  assert.match(recovery, /OPERATIONAL LEDGER RECOVERY REQUIRED/);
  assert.match(recovery, /Bounded recovery action/);
  assert.match(recovery, /Retry checkpoint read/);
});

test('assurance renderer escapes canonical data and preserves readiness inspection controls', () => {
  const html = loadSystemSurfaces().render('assurance', fixture());
  assert.match(html, /Agent readiness matrix/);
  assert.match(html, /data-action="inspectReadiness"/);
  assert.match(html, /data-action="inspectReadinessReport"/);
  assert.match(html, /&lt;unsafe&gt;/);
  assert.doesNotMatch(html, /<unsafe>/);
});

test('settings renderer keeps billable policy denied and all guardrail interactions addressable', () => {
  const html = loadSystemSurfaces().render('settings', fixture());
  assert.match(html, /role="switch" aria-checked="false"/);
  assert.match(html, /data-action="toggleBillablePolicy" data-enabled="true"/);
  assert.match(html, /No billable provider execution can pass\./);
  assert.equal((html.match(/data-action="openSettings"/g) || []).length, 3);
  assert.match(html, /Edit Pacify-X settings in host/);
  assert.match(html, /Open authoritative editor/);
  assert.match(html, /Edit guardrails/);
});
