'use strict';

(() => {
  const vscode = acquireVsCodeApi();
  const VERSION = 'px.sidebar.message/1.1';
  const ASSET_PROTOCOL = 'px.sidebar.asset/1.2';
  const roots = Object.fromEntries([...document.querySelectorAll('[data-component]')].map(node => [node.dataset.component, node]));
  const hashes = new Map();
  let projection = null;
  let providerIndex = 0;
  let ageTimer = null;
  let latestRevision = -1;
  let latestGeneratedAt = 0;
  let renderAcknowledgementEnabled = false;

  const esc = value => String(value ?? '').replace(/[&<>"']/g, character => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[character]));
  const post = message => vscode.postMessage({ schemaVersion: VERSION, ...message });
  const percent = value => value == null ? '—' : `${Number(value).toFixed(Number(value) % 1 ? 1 : 0)}%`;
  const symbol = state => ({ complete: '✓', active: '◉', verifying: '↻', blocked: '⊘', failed: '!', stale: '!', recovering: '↻', queued: '○', waiting: '○' }[state] || '•');
  const time = value => value ? new Intl.DateTimeFormat(undefined, { hour: '2-digit', minute: '2-digit' }).format(new Date(value)) : 'unknown';
  const age = value => {
    if (!value) return 'unknown'; const seconds = Math.max(0, Math.floor((Date.now() - new Date(value).getTime()) / 1000));
    if (seconds < 10) return 'now'; if (seconds < 60) return `${seconds}s`; if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${seconds % 60}s`; return `${Math.floor(seconds / 3600)}h`;
  };
  const entity = (type, id, content, className = 'entity-row') => id ? `<button class="${className}" data-entity-type="${esc(type)}" data-entity-id="${esc(id)}">${content}</button>` : `<div class="${className}">${content}</div>`;
  const progress = (value, label) => value == null ? `<div class="unknown-progress" aria-label="${esc(label)} unknown">Progress unavailable</div>` : `<progress max="100" value="${esc(value)}" aria-label="${esc(label)}" aria-valuetext="${esc(percent(value))}">${esc(percent(value))}</progress>`;
  const sectionTitle = (label, count = null) => `<div class="section-title"><h2>${esc(label)}</h2>${count == null ? '' : `<span>${esc(count)}</span>`}</div>`;

  function patch(name, data, html) {
    const hash = JSON.stringify(data);
    if (hashes.get(name) === hash) return;
    hashes.set(name, hash); roots[name].innerHTML = html; roots[name].hidden = !html;
  }

  function renderHeader(p) {
    patch('header', [p.status.state, p.status.version, p.revision], `<div class="identity"><span class="px-mark" aria-hidden="true">PX</span><strong>PACIFY-X</strong></div><button class="control-plane" data-action="open-control-plane">OPEN CONTROL PLANE <span aria-hidden="true">→</span></button><div class="status-strip state-${esc(p.status.state)}"><span class="status-symbol" aria-hidden="true">${p.status.state === 'recovering' ? '↻' : p.status.connected ? '●' : '○'}</span><strong>${esc(p.status.label)}</strong><span>v${esc(p.status.version)}</span><span>REV ${esc(p.revision)}</span></div>`);
  }

  function renderConnection(p) {
    if (p.status.state === 'connected') { patch('connection', null, ''); return; }
    const details = p.status.subsystems.map(item => `<li><span>${symbol(item.state === 'healthy' ? 'complete' : item.state === 'degraded' ? 'blocked' : 'queued')}</span>${esc(item.label)} <em>${esc(item.state)}</em></li>`).join('');
    patch('connection', p.status, `<div class="state-panel state-${esc(p.status.state)}"><strong>${esc(p.status.label)}</strong><p>${esc(p.status.reason || (p.status.state === 'disconnected' ? 'Pacify-X runtime is unavailable.' : 'Operational state requires attention.'))}</p><ul>${details}</ul>${p.status.state === 'disconnected' ? `<p class="meta">Last known revision ${esc(p.revision)} · ${esc(time(p.status.lastConnectedAt))}</p><button class="retry" data-action="retry">RETRY CONNECTION</button>` : ''}</div>`);
  }

  function renderExecution(p) {
    if (!p.execution) {
      const last = p.lastRun ? `${entity('plan', p.lastRun.planId, `<strong>${esc(p.lastRun.planName)}</strong><span>${esc(p.lastRun.completedTasks)} / ${esc(p.lastRun.totalTasks)} tasks · ${esc(time(p.lastRun.completedAt))}</span>`, 'last-run')}` : '<p class="empty">No completed run is recorded.</p>';
      patch('execution', [p.execution, p.lastRun], `${sectionTitle('NO ACTIVE EXECUTION')}<div class="idle-copy"><span class="ready-check">✓</span><div><strong>PX is idle</strong><p>Authoritative coordination has no active plan.</p></div></div>${p.lastRun ? `<div class="subheading">LAST RUN</div>${last}` : last}`);
      return;
    }
    const e = p.execution;
    patch('execution', e, `${sectionTitle('ACTIVE EXECUTION', percent(e.progressPercent))}${entity('plan', e.planId, `<strong class="execution-name" title="${esc(e.planName)}">${esc(e.planName)}</strong>`, 'plan-link')}${progress(e.progressPercent, `Plan progress ${percent(e.progressPercent)}`)}<div class="execution-meta"><span>${esc(e.currentWaveName || 'Wave not assigned')}</span><span>${esc(e.completedTasks)} / ${esc(e.totalEligibleTasks)} tasks</span><span>${esc(e.activeAgentCount)} agents · ${esc(e.activeOrchestrationCount)} orchestrations</span></div>`);
  }

  function taskHtml(task, expandedTasks) {
    const hasChildren = task.subtasks.length > 0; const expanded = expandedTasks.has(task.id);
    const body = `<span class="state-icon state-${esc(task.status)}" aria-hidden="true">${symbol(task.status)}</span><span class="row-label" title="${esc(task.name)}">${esc(task.name)}</span>${task.progressPercent == null ? '' : `<span class="row-percent">${esc(percent(task.progressPercent))}</span>`}`;
    const button = hasChildren ? `<button class="tree-row task-row" data-toggle-task="${esc(task.id)}" aria-expanded="${expanded}" title="${esc(task.name)}"><span aria-hidden="true">${expanded ? '▾' : '▸'}</span>${body}</button>` : entity('task', task.id, body, 'tree-row task-row');
    const subtasks = expanded ? `<div class="subtasks">${task.subtasks.map(subtask => entity('task', subtask.id, `<span class="state-icon state-${esc(subtask.status)}" aria-hidden="true">${symbol(subtask.status)}</span><span class="row-label">${esc(subtask.name)}</span>`, 'tree-row subtask-row')).join('')}</div>` : '';
    return button + subtasks;
  }

  function renderWaves(p) {
    if (!p.waves.length) { patch('waves', [], ''); return; }
    const expandedWaves = new Set(p.ui.expandedWaveIds.length ? p.ui.expandedWaveIds : [p.execution?.currentWaveId].filter(Boolean));
    const expandedTasks = new Set(p.ui.expandedTaskIds);
    patch('waves', [p.waves, [...expandedWaves], [...expandedTasks]], `${sectionTitle('PLAN WAVES', p.waves.length)}<div class="tree">${p.waves.map(wave => {
      const expanded = expandedWaves.has(wave.id); return `<div class="wave"><button class="tree-row wave-row" data-toggle-wave="${esc(wave.id)}" aria-expanded="${expanded}" title="${esc(wave.name)}"><span aria-hidden="true">${expanded ? '▾' : '▸'}</span><span class="state-icon state-${esc(wave.status)}" aria-hidden="true">${symbol(wave.status)}</span><span class="row-label">${esc(wave.name)}</span><span class="row-percent">${esc(percent(wave.progressPercent))}</span></button>${expanded ? `<div class="tasks">${wave.tasks.map(task => taskHtml(task, expandedTasks)).join('')}</div>` : ''}</div>`;
    }).join('')}</div>`);
  }

  function renderPunch(p) {
    if (!p.execution) { patch('punch', null, ''); return; }
    const q = p.punch; const completion = q.total ? (q.complete / q.total) * 100 : null;
    patch('punch', q, `<button class="punch-card" data-plan-punch="${esc(p.execution.planId)}"><span class="section-title"><strong>PUNCH CARD</strong><b>${esc(q.complete)} / ${esc(q.total)}</b></span>${progress(completion, 'Punch card completion')}<span class="punch-counts"><span>✓${esc(q.complete)} <small>done</small></span><span>◉${esc(q.active)} <small>active</small></span><span>↻${esc(q.verifying)} <small>verify</small></span><span>○${esc(q.queued)} <small>queued</small></span><span>⊘${esc(q.blocked)} <small>blocked</small></span></span></button>`);
  }

  function renderAgents(p) {
    if (!p.agents.length) { patch('agents', [], ''); return; }
    patch('agents', p.agents.map(agent => ({ ...agent, heartbeatAgeMs: null })), `${sectionTitle('ACTIVE AGENTS', p.agents.filter(agent => agent.state !== 'stale').length)}<div class="rows">${p.agents.map(agent => {
      const content = `<span class="state-icon state-${esc(agent.state)}" aria-hidden="true">${symbol(agent.state)}</span><span class="row-stack"><strong>${esc(agent.displayName)}</strong><small title="${esc(agent.taskName || agent.type)}">${esc(agent.taskName || agent.type)}</small>${agent.state === 'stale' ? `<em data-heartbeat="${esc(agent.lastHeartbeatAt || '')}">stale · ${esc(age(agent.lastHeartbeatAt))}</em>` : ''}</span>${agent.progressPercent == null ? '' : `<span class="row-percent">${esc(percent(agent.progressPercent))}</span>`}`;
      return entity('agent', agent.agentId, content, 'entity-row agent-row');
    }).join('')}</div>`);
  }

  function renderOrchestrations(p) {
    if (!p.orchestrations.length) { patch('orchestrations', [], ''); return; }
    patch('orchestrations', p.orchestrations, `${sectionTitle('ORCHESTRATIONS', p.orchestrations.length)}<div class="rows">${p.orchestrations.map(item => entity('orchestration', item.id, `<span class="state-icon" aria-hidden="true">↳</span><span class="row-label">${esc(item.name)}</span><b class="state-word">${esc(item.state.toUpperCase())}</b>`)).join('')}</div>`);
  }

  function renderRecent(p) {
    if (!p.recent.length) { patch('recent', [], ''); return; }
    patch('recent', p.recent, `${sectionTitle('RECENT')}<div class="rows recent-rows">${p.recent.map(item => entity(item.entityType, item.entityId, `<span class="state-icon state-${esc(item.state)}" aria-hidden="true">${symbol(item.state)}</span><span class="row-label">${esc(item.label)}</span><time datetime="${esc(item.occurredAt || '')}">${esc(time(item.occurredAt))}</time>`)).join('')}</div>`);
  }

  function renderAttention(p) {
    if (!p.attention.length) { patch('attention', [], ''); return; }
    patch('attention', p.attention, `${sectionTitle('⚠ ATTENTION', p.attention.length)}<div class="attention-list">${p.attention.map(item => entity(item.entityType || 'attention', item.entityId || item.id, `<span aria-hidden="true">!</span><span><strong>${esc(item.title)}</strong>${item.detail ? `<small>${esc(item.detail)}</small>` : ''}</span>`, `attention-row severity-${esc(item.severity)}`)).join('')}</div>`);
  }

  function money(value, currency) { return value == null ? 'UNKNOWN' : new Intl.NumberFormat(undefined, { style: 'currency', currency: currency || 'USD' }).format(value); }
  function budgetLabel(value) { if (value == null) return 'BUDGET UNKNOWN'; if (value >= 100) return 'BUDGET LIMIT REACHED'; if (value >= 95) return `BUDGET CRITICAL · ${percent(value)}`; if (value >= 85) return `BUDGET HIGH · ${percent(value)}`; if (value >= 70) return `BUDGET WARNING · ${percent(value)}`; return `BUDGET · ${percent(value)}`; }

  function renderProviders(p) {
    const state = p.providerState; const providers = state.providers;
    if (!providers.length) {
      const text = state.configuredCount ? `<strong>✓ NO BILLABLE API ACTIVITY</strong><span>${esc(state.configuredCount)} provider${state.configuredCount === 1 ? '' : 's'} configured · 0 active requests</span>` : '<strong>NO EXTERNAL BILLING ROUTES</strong><span>No provider telemetry is configured.</span>';
      patch('providers', state, `${sectionTitle('PROVIDER ACTIVITY')}<div class="provider-idle">${text}</div>`); return;
    }
    const selected = p.ui.selectedProviderId; const selectedIndex = providers.findIndex(item => item.providerId === selected);
    providerIndex = selectedIndex >= 0 ? selectedIndex : Math.min(providerIndex, providers.length - 1);
    const provider = providers[providerIndex]; const local = provider.providerClass === 'local'; const budget = provider.budgetPercent;
    const billing = local ? 'LOCAL · NON-BILLABLE' : provider.billingEnabled == null ? 'BILLING STATE: UNKNOWN' : `BILLING: ${provider.billingEnabled ? 'ENABLED' : 'DISABLED'}`;
    const fallback = provider.fallbackActive ? '! BILLABLE FALLBACK IN USE' : provider.fallbackEnabled == null ? 'FALLBACK: UNKNOWN' : `FALLBACK: ${provider.fallbackEnabled ? 'ENABLED' : 'DISALLOWED'}`;
    const usage = provider.spendCurrent != null ? `<dl><div><dt>Spend</dt><dd>${esc(money(provider.spendCurrent, provider.currency))} / ${esc(money(provider.budgetLimit, provider.currency))}</dd></div><div><dt>Remaining</dt><dd>${esc(money(provider.budgetRemaining, provider.currency))}</dd></div><div><dt>Burn</dt><dd>${provider.ratePerMinute == null ? 'UNKNOWN' : `${esc(money(provider.ratePerMinute, provider.currency))}/min`}</dd></div></dl>` : provider.tokenTotal != null ? `<dl><div><dt>Tokens</dt><dd>${esc(provider.tokenTotal)} / ${esc(provider.tokenBudget ?? 'UNKNOWN')}</dd></div></dl>` : '<p class="telemetry-warning">Usage / cost telemetry unavailable.</p>';
    const providerOptions = providers.map(item => `<option value="${esc(item.providerId)}"${item.providerId === provider.providerId ? ' selected' : ''}>${esc(item.providerName)} · ${esc(item.activityState)}</option>`).join('');
    patch('providers', [state, providerIndex, p.ui.selectedProviderId], `${sectionTitle('PROVIDER ACTIVITY')}<div class="provider-card ${provider.fallbackActive ? 'fallback-active' : ''}"><label class="provider-selector"><span>Selected provider</span><select data-action="provider-select" aria-label="Select provider telemetry">${providerOptions}</select></label><div class="provider-carousel"><button data-action="provider-previous" aria-label="Previous provider" ${providers.length === 1 ? 'disabled' : ''}>‹</button>${entity('provider', provider.providerId, `<strong>${esc(provider.providerName)}</strong><small>${esc(providerIndex + 1)} / ${esc(providers.length)}</small>`, 'provider-name')}<button data-action="provider-next" aria-label="Next provider" ${providers.length === 1 ? 'disabled' : ''}>›</button></div><div class="provider-state state-${esc(provider.activityState)}"><span>${symbol(provider.activityState)}</span><strong>${esc(provider.stale ? 'TELEMETRY STALE' : provider.activityState.toUpperCase())}</strong></div>${provider.currentTaskName ? entity('task', provider.currentTaskId, `<span>Current task</span><strong>${esc(provider.currentTaskName)}</strong>`, 'provider-work') : ''}${progress(budget, budgetLabel(budget))}<strong class="budget-label">${esc(budgetLabel(budget))}</strong>${usage}<div class="billing-state ${provider.billingEnabled == null && !local ? 'warning' : ''}">${esc(billing)}</div><div class="fallback-state ${provider.fallbackActive ? 'critical' : provider.fallbackEnabled ? 'warning' : ''}">${esc(fallback)}</div><small class="telemetry-source">${esc(provider.telemetrySource)} · ${esc(provider.stale ? 'not current' : age(provider.telemetryFreshAt))}</small></div>`);
  }

  function render(p) {
    projection = p;
    renderHeader(p); renderConnection(p); renderExecution(p); renderWaves(p); renderPunch(p); renderAgents(p); renderOrchestrations(p); renderRecent(p); renderAttention(p); renderProviders(p);
    if (renderAcknowledgementEnabled) {
      post({
        type: 'rendered', assetProtocol: ASSET_PROTOCOL, revision: p.revision,
        visibleComponentCount: Object.values(roots).filter(node => !node.hidden).length,
        waveCount: p.waves.length, taskCount: p.waves.reduce((sum, wave) => sum + wave.tasks.length, 0), agentCount: p.agents.length,
        orchestrationCount: p.orchestrations.length, recentCount: p.recent.length, attentionCount: p.attention.length,
        providerCount: p.providerState.providers.length, connected: p.status.connected
      });
    }
  }

  document.addEventListener('click', event => {
    const button = event.target.closest('button'); if (!button) return;
    if (button.dataset.action === 'open-control-plane') return post({ type: 'openControlPlane' });
    if (button.dataset.action === 'retry') return post({ type: 'retryConnection' });
    if (button.dataset.action === 'provider-previous') return post({ type: 'providerPrevious' });
    if (button.dataset.action === 'provider-next') return post({ type: 'providerNext' });
    if (button.dataset.toggleWave) { const expanded = button.getAttribute('aria-expanded') !== 'true'; const ids = new Set(projection.ui.expandedWaveIds); expanded ? ids.add(button.dataset.toggleWave) : ids.delete(button.dataset.toggleWave); projection.ui.expandedWaveIds = [...ids]; post({ type: 'toggleWave', waveId: button.dataset.toggleWave, expanded }); renderWaves(projection); return; }
    if (button.dataset.toggleTask) { const expanded = button.getAttribute('aria-expanded') !== 'true'; const ids = new Set(projection.ui.expandedTaskIds); expanded ? ids.add(button.dataset.toggleTask) : ids.delete(button.dataset.toggleTask); projection.ui.expandedTaskIds = [...ids]; post({ type: 'toggleTask', taskId: button.dataset.toggleTask, expanded }); renderWaves(projection); return; }
    if (button.dataset.planPunch) return post({ type: 'openPlanFromPunch', planId: button.dataset.planPunch });
    if (button.dataset.entityType && button.dataset.entityId) return post({ type: 'openEntity', entityType: button.dataset.entityType, entityId: button.dataset.entityId });
  });
  document.addEventListener('change', event => {
    const select = event.target.closest('select[data-action="provider-select"]');
    if (!select) return;
    post({ type: 'selectProvider', providerId: select.value || null });
  });

  window.addEventListener('message', event => {
    const message = event.data;
    const error = document.getElementById('contract-error');
    if (!message || message.schemaVersion !== VERSION || !['snapshot', 'error'].includes(message.type) || Object.keys(message).some(key => !['schemaVersion', 'type', 'projection', 'capabilities', 'code', 'detail'].includes(key))) {
      error.hidden = false; error.textContent = 'Sidebar contract rejected an unsupported host message.'; return;
    }
    if (message.type === 'error') { error.hidden = false; error.textContent = message.detail || 'Sidebar host error.'; return; }
    if (!message.projection || message.projection.schemaVersion !== 'px.sidebar.snapshot/1.0' || !Number.isSafeInteger(message.projection.revision)) { error.hidden = false; error.textContent = 'Sidebar snapshot schema is invalid.'; return; }
    const capabilities = message.capabilities;
    renderAcknowledgementEnabled = Boolean(capabilities && capabilities.renderAcknowledgement === true && capabilities.assetProtocol === ASSET_PROTOCOL && Object.keys(capabilities).length === 2);
    const generatedAt = Date.parse(message.projection.generatedAt || '') || 0;
    if (message.projection.revision < latestRevision && generatedAt <= latestGeneratedAt) return;
    latestRevision = message.projection.revision; latestGeneratedAt = generatedAt;
    error.hidden = true; render(message.projection);
  });

  ageTimer = window.setInterval(() => {
    for (const node of document.querySelectorAll('[data-heartbeat]')) node.textContent = `stale · ${age(node.dataset.heartbeat)}`;
  }, 5000);
  window.addEventListener('unload', () => window.clearInterval(ageTimer), { once: true });
  post({ type: 'ready', assetProtocol: ASSET_PROTOCOL });
})();
