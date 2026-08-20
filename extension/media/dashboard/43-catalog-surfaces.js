'use strict';

(() => {
  const dashboard = globalThis.PXDashboard;
  if (!dashboard) throw new Error('PXDashboard foundation must load before catalog surfaces.');
  const { escapeHtml: esc, number, badge, card, section, unavailable } = dashboard.require('components');

  function requireContext(context) {
    if (!context || typeof context !== 'object' || !context.state?.snapshot) {
      throw new TypeError('Catalog surfaces require a canonical snapshot context.');
    }
    for (const helper of ['catalogPanel', 'enterprisePackPanel']) {
      if (typeof context[helper] !== 'function') throw new TypeError(`Catalog surfaces require ${helper}.`);
    }
    return context;
  }

  function agents(context) {
    const { state, catalogPanel, enterprisePackPanel } = requireContext(context);
    const coordination = state.coordination?.state;
    const adapters = state.snapshot.teamFabric?.adapters || [];
    const adapterRows = adapters.map(item => `<article class="adapter-row"><div><strong>${esc(item.id)}</strong><small>${esc(item.kind)} · ${esc(item.capabilities.join(', '))}</small></div>${badge(item.status, item.status === 'ready' ? 'success' : item.status === 'disabled' ? 'neutral' : 'warning')}<span>${esc(item.authentication_identity)} / billing ${esc(item.billing_identity)}</span></article>`).join('');
    const enterprise = state.agentScope === 'enterprise';
    const counts = state.snapshot.counts || {};
    const activeSessionCount = (coordination?.sessions || []).filter(item => { const heartbeat = Date.parse(item.heartbeat_utc || item.last_heartbeat_at || ''); return item.status === 'active' && Number.isFinite(heartbeat) && Date.now() - heartbeat <= 5 * 60_000; }).length;
    const metrics = enterprise
      ? `${card('ENTERPRISE RECORDS', number(counts.enterprise_agents), 'separate restricted catalog')}${card('ACTIVE SESSIONS', number(activeSessionCount), 'heartbeat within 5 minutes')}${card('WORKER ADAPTERS', number(adapters.length), 'doctor + identity separation')}${card('BILLABLE FALLBACK', 'Disabled', 'no implicit provider')}`
      : `${card('REGISTERED RECORDS', number(counts.agents_registered), 'all core source records')}${card('RUNNABLE REVISIONS', number(counts.agents_runnable_revisions), 'current admitted Studio revisions')}${card('RUNNING PROCESSES', number(counts.agents_running), 'live owned harness processes')}${card('ADVISORY RECORDS', number(counts.agents_advisory), 'reference-only; not executable')}`;
    const setup = !enterprise && Number(counts.agents_runnable_revisions || 0) < 1 ? '<button class="primary" data-action="setupStudio">Set up runnable Agent + Workflow</button>' : '';
    return `<div class="metric-grid compact">${metrics}</div><div class="catalog-tabs" role="group" aria-label="Agent catalog scope"><button data-action="surfaceScope" data-target="agents" data-scope="core" aria-pressed="${!enterprise}" class="${enterprise ? '' : 'active'}">Core records</button><button data-action="surfaceScope" data-target="agents" data-scope="enterprise" aria-pressed="${enterprise}" class="${enterprise ? 'active' : ''}">MS+Enterprise</button></div>${enterprise ? `<div class="two-col wide-left">${catalogPanel('enterprise-agents', 'MS+Enterprise agents', 'SEPARATE NAMESPACE · NO CLOUD AUTHORITY')}${enterprisePackPanel()}</div>` : `${section('Agent Studio', 'VERSIONED SPEC → STRUCTURAL PREFLIGHT → ADMISSION → OWNED HARNESS', `<p>Create and edit immutable Studio revisions. The source registry below is reference material, not a live fleet.</p><div class="action-grid">${setup}<button class="primary" data-action="openStudioDraft" data-kind="agent">New agent candidate</button><button data-action="openStudioRuns" data-kind="agent">Open durable runs</button></div>`)}<div class="two-col wide-left">${catalogPanel('agents', 'Agent source registry (not a live fleet)', 'REGISTERED + ADVISORY + RUNNABLE DIMENSIONS')}${section('Worker adapters', 'TEAM FABRIC DOCTOR', `<div class="adapter-list">${adapterRows || unavailable()}</div><button class="primary" data-action="teamPackPreview">Audit / stage team package</button>`)}</div>`}`;
  }

  function skillsTools(context) {
    const { state, catalogPanel, enterprisePackPanel } = requireContext(context);
    const kind = state.capabilityKind;
    const enterprise = kind === 'enterprise-skills';
    const preserved = kind === 'preserved-skills';
    const microsoft = kind === 'microsoft-skills';
    const queryDomain = enterprise ? 'enterprise-restricted' : microsoft ? 'microsoft-vendor' : preserved ? 'user-preserved' : 'px-standard';
    const queryLabel = enterprise ? 'enterprise' : microsoft ? 'Microsoft / vendor' : preserved ? 'preserved original' : 'standard';
    const operations = section('Skill operations', 'QUERY / PACKAGE / TEST / ADMIT / PROMOTE / ROLLBACK', `<div class="skill-operation-grid"><article><b>Semantic broker</b>${badge('LIVE', 'success')}<p>Returns at most three eligible metadata candidates with score, rationale, origin, domain, and admission state. Body hydration is a separate exact-ID action.</p><button class="primary" data-action="skillSemanticQuery" data-domain="${queryDomain}">Query ${queryLabel} skills</button></article><article><b>Package editor</b>${badge(kind === 'skills' ? 'AVAILABLE' : 'READ-ONLY SOURCE', kind === 'skills' ? 'success' : 'info')}<p>Native candidates use the versioned Skill Studio. Preserved and vendor packages remain unchanged unless deliberately loaded as a new revision.</p><button data-action="openStudioDraft" data-kind="skill">Stage skill candidate</button></article><article><b>Lifecycle controller</b>${badge('RECEIPT-BOUND', 'success')}<p>Validation, admission, promotion, and rollback appear on an inspected Studio revision only when its current state permits the transition.</p><button data-action="capabilityTab" data-kind="skills">Open native revisions</button></article><article><b>Preserved originals</b>${badge('NON-DESTRUCTIVE', 'info')}<p>Original packages remain separately cataloged with provenance and backup paths. Loading creates a candidate; it never overwrites the original.</p><button data-action="capabilityTab" data-kind="preserved-skills">View preserved originals</button></article></div>`);
    return `<div class="metric-grid compact">${card('PX NATIVE', number(state.snapshot.counts.skills), 'lazy native skill packages')}${card('PRESERVED', 'Retained', 'hash-verified originals')}${card('ENTERPRISE', number(state.snapshot.counts.enterprise_skills), 'restricted metadata')}${card('TOOLS', number(state.snapshot.counts.tools), 'effect-governed tools')}</div><div class="catalog-tabs" role="group" aria-label="Capability catalog scope"><button data-action="capabilityTab" data-kind="skills" aria-pressed="${kind === 'skills'}" class="${kind === 'skills' ? 'active' : ''}">PX Native</button><button data-action="capabilityTab" data-kind="preserved-skills" aria-pressed="${preserved}" class="${preserved ? 'active' : ''}">Preserved Originals</button><button data-action="capabilityTab" data-kind="microsoft-skills" aria-pressed="${microsoft}" class="${microsoft ? 'active' : ''}">Microsoft / Vendor</button><button data-action="capabilityTab" data-kind="enterprise-skills" aria-pressed="${enterprise}" class="${enterprise ? 'active' : ''}">Enterprise Restricted</button><button data-action="capabilityTab" data-kind="tools" aria-pressed="${kind === 'tools'}" class="${kind === 'tools' ? 'active' : ''}">Tools</button></div>
    ${section('Parallel planning coordination', 'EXTENSION-OWNED SKILL', `<div class="skill-feature"><div><strong>parallel-planning-coordination</strong><p>Task DAG → assignment → dependency readiness → file/area claims → IDE dispatch → progress receipts → conflict gate → reconciliation → layered memory.</p></div>${badge('ACTIVE LOCAL', 'success')}</div><div class="gate-stack"><span>Task graph</span><i>→</i><span>Claims</span><i>→</i><span>Dispatch</span><i>→</i><span>Receipts</span><i>→</i><span>Memory</span></div>`, '<button data-surface="workflows" class="secondary small">Open coordination</button>')}
    ${operations}${enterprise ? enterprisePackPanel() : ''}${catalogPanel(kind, enterprise ? 'Enterprise-restricted skill catalog' : preserved ? 'Preserved original skills' : microsoft ? 'Microsoft / vendor skills' : kind === 'skills' ? 'PX-native skill catalog' : 'Tool catalog', enterprise ? 'EXPLICIT ENTERPRISE POLICY REQUIRED' : microsoft ? 'EXPLICIT VENDOR INTENT + ADMISSION REQUIRED' : preserved ? 'USER-OWNED EVIDENCE / NEVER AUTO-PURGED' : 'COMPLETE FIRST-CLASS SOURCE')}`;
  }

  const renderers = Object.freeze({ agents, skillsTools });
  dashboard.define('catalogSurfaces', {
    ids: Object.freeze(Object.keys(renderers)),
    has(id) { return Object.hasOwn(renderers, id); },
    render(id, context) {
      if (!Object.hasOwn(renderers, id)) throw new RangeError(`Unknown catalog surface: ${id}`);
      return renderers[id](requireContext(context));
    }
  });
})();
