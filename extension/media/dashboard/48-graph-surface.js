'use strict';

(() => {
  const dashboard = globalThis.PXDashboard;
  if (!dashboard) throw new Error('PXDashboard foundation must load before graph surface.');
  const { escapeHtml: esc, number, card, empty } = dashboard.require('components');

  function requireContext(context) {
    if (!context || typeof context !== 'object' || !context.state?.snapshot) throw new TypeError('Graph surface requires a canonical snapshot context.');
    if (typeof context.graphPositions !== 'function') throw new TypeError('Graph surface requires graphPositions.');
    return context;
  }

  function sceneDimensions(data, nodes) {
    if (data.mode === 'full') {
      const groups = new Map();
      for (const item of nodes) groups.set(item.community_id || `${item.kind || 'unknown'}::general`, (groups.get(item.community_id || `${item.kind || 'unknown'}::general`) || 0) + 1);
      const count = Math.max(1, groups.size); const largest = Math.max(1, ...groups.values());
      const columns = Math.max(1, Math.ceil(Math.sqrt(count * 1.35))); const rows = Math.max(1, Math.ceil(count / columns));
      const cell = Math.max(520, Math.min(1180, 390 + Math.ceil(Math.sqrt(largest)) * 74));
      return { width: Math.max(1180, columns * cell), height: Math.max(760, rows * Math.round(cell * .82)) };
    }
    const neighbors = Math.max(0, nodes.length - 1); let width = 1760; let height = 920;
    if (globalThis.PXDashboard && nodes.length) {
      let remaining = neighbors; let radius = 280;
      while (remaining > 0) { remaining -= Math.max(8, Math.floor((Math.PI * 2 * radius) / 210)); if (remaining > 0) radius += 190; }
      if (neighbors > 22) width = height = Math.max(1100, (radius + 150) * 2);
    }
    return { width, height };
  }

  function provenanceSummary(value) {
    if (!value || typeof value !== 'object') return 'not declared';
    return Object.entries(value).slice(0, 4).map(([key, item]) => `${key}: ${typeof item === 'object' ? JSON.stringify(item) : item}`).join(' · ') || 'not declared';
  }

  function finiteLayoutAttribute(value, minimum, maximum, fallback) {
    const numeric = Number(value);
    const bounded = Number.isFinite(numeric) ? Math.min(maximum, Math.max(minimum, numeric)) : fallback;
    return esc(String(Number(bounded.toFixed(4))));
  }

  function projection(data, context) {
    const { state, graphPositions } = context;
    if (state.graphError && !data) return `<div class="graph-loading graph-error" role="alert"><span class="empty-ring"></span><p>${esc(state.graphError)}</p><button class="primary" data-action="runGraphSearch">Retry graph query</button></div>`;
    if (!data) return `<div class="graph-loading"><span class="empty-ring"></span><p>Loading a bounded page from the canonical graph…</p></div>`;
    if (data.available === false) return `<div class="graph-loading graph-error" role="status"><span class="empty-ring"></span><p>${esc((data.limitations || ['Repository graph is unavailable.'])[0])}</p>${data.build_action ? '<button class="primary" data-action="buildRepositoryGraph">Build repository graph</button>' : ''}</div>`;
    if (!data.nodes?.length) return empty(data.ambiguous_matches?.length ? 'That node ID is ambiguous. Select a qualified key.' : 'No graph records match the current source, community, and filters.');

    const mode = data.mode || state.graphRequest?.mode || state.graphMode || 'full';
    const effectiveData = data.mode === mode ? data : { ...data, mode };
    const center = data.selected; const ordered = [...data.nodes].sort((left, right) => left.key === center ? -1 : right.key === center ? 1 : String(left.community_id || '').localeCompare(String(right.community_id || '')) || Number(right.degree || 0) - Number(left.degree || 0) || left.title.localeCompare(right.title));
    const dimensions = sceneDimensions(effectiveData, ordered); const { width, height } = dimensions; const positions = graphPositions(effectiveData, ordered, width, height);
    const selected = ordered.find(item => item.key === center) || ordered[0]; const loadedKeys = new Set(ordered.map(item => item.key));
    const drawableEdges = (data.edges || []).filter(edge => loadedKeys.has(edge.source) && loadedKeys.has(edge.target));
    const incident = (data.edges || []).filter(edge => edge.source === selected.key || edge.target === selected.key);
    const showEdgeLabels = drawableEdges.length <= 180;

    const communityHulls = (positions.communities || []).map(item => `<g class="graph-community-hull" data-community-id="${esc(item.id)}"><rect x="${item.x}" y="${item.y}" width="${item.width}" height="${item.height}" rx="28"></rect><text x="${item.x + 24}" y="${item.y + 34}">${esc(item.label)} · ${number(item.loaded)} loaded / ${number(item.total)}</text></g>`).join('');
    const edges = drawableEdges.map((edge, index) => {
      const from = positions.get(edge.source); const to = positions.get(edge.target); if (!from || !to) return '';
      const dx = to.x - from.x; const dy = to.y - from.y; const length = Math.max(1, Math.hypot(dx, dy)); const bend = ((index % 7) - 3) * 5;
      const cx = (from.x + to.x) / 2 - (dy / length) * bend; const cy = (from.y + to.y) / 2 + (dx / length) * bend; const edgeId = `graph-edge-${index}`; const relation = String(edge.relation || 'related_to').replaceAll('_', ' ');
      return `<g class="graph-edge-group" data-edge-source="${esc(edge.source)}" data-edge-target="${esc(edge.target)}"><title>${esc(`${edge.source} ${relation} ${edge.target}. ${edge.why || ''}`)}</title><path id="${edgeId}" d="M ${from.x} ${from.y} Q ${cx} ${cy} ${to.x} ${to.y}" marker-end="url(#graph-arrow)"></path>${showEdgeLabels ? `<text><textPath href="#${edgeId}" startOffset="54%">${esc(relation)}</textPath></text>` : ''}</g>`;
    }).join('');
    const nodes = ordered.map(item => {
      const point = positions.get(item.key); const isSelected = item.key === selected.key; const connections = incident.filter(edge => edge.source === item.key || edge.target === item.key).length || Number(item.degree || 0);
      const interaction = mode === 'full'
        ? 'data-action="selectGraphNode"'
        : 'data-action="focusGraphNode"';
      return `<button class="graph-node actual kind-${esc(item.kind)}${isSelected ? ' core selected' : ''}" data-graph-x="${finiteLayoutAttribute(point.x, -20000, 20000, 0)}" data-graph-y="${finiteLayoutAttribute(point.y, -20000, 20000, 0)}" ${interaction} data-node-key="${esc(item.key)}" aria-pressed="${isSelected}" aria-label="${esc(`${item.title}, ${item.kind}, ${item.status}, ${connections} connections, community ${item.community_id || 'unclassified'}`)}" title="${esc(item.summary || item.key)}"><b>${esc(item.title)}</b><span>${esc(item.kind)} · ${esc(item.status)}</span><small>${number(connections)} links · ${esc(item.community_id || 'unclassified')}</small></button>`;
    }).join('');

    const relationships = incident.map(edge => {
      const target = edge.source === selected.key ? edge.target : edge.source; const direction = edge.source === selected.key ? 'outgoing' : 'incoming';
      const interaction = mode === 'full' && loadedKeys.has(target)
        ? 'data-action="selectGraphNode"'
        : 'data-action="focusGraphNode"';
      return `<button class="relationship-row" ${interaction} data-node-key="${esc(target)}"><span class="relationship-direction ${direction}">${direction === 'outgoing' ? 'OUT' : 'IN'}</span><span class="relationship-endpoint"><small>${esc(edge.source)}</small><b>${esc(String(edge.relation).replaceAll('_', ' '))}</b><small>${esc(edge.target)}</small></span><p>${esc(edge.why || 'Typed source relationship')}</p><small class="relationship-provenance">${esc(edge.source_path || edge.source_sha256 || provenanceSummary(edge.provenance))}</small></button>`;
    }).join('');
    const incomingCount = incident.filter(edge => edge.target === selected.key).length; const outgoingCount = incident.filter(edge => edge.source === selected.key).length;
    const page = data.page || {}; const nodeHasMore = page.node_has_more === true; const edgeHasMore = page.edge_has_more === true; const hasMore = nodeHasMore || edgeHasMore;
    const loadedNodes = Number(data.covered_nodes ?? data.nodes.length); const loadedEdges = Number(data.covered_edges ?? data.edges.length);
    // Selection is part of the viewport identity. A full-map selection can sit
    // in any community, so retaining the previous scene key could leave the
    // newly selected record outside the readable viewport.
    const sceneKey = `${data.view}|${mode}|${state.graphLayout}|${state.graphCommunity}|${state.graphKind}|${state.graphStatus}|${selected.key}`;
    const nonvisualOptions = ordered.map(item => `<option value="${esc(item.key)}" ${item.key === selected.key ? 'selected' : ''}>${esc(item.title)} — ${esc(item.kind)} — ${esc(item.status)} — ${esc(item.community_id || 'unclassified')}</option>`).join('');

    const layoutControls = mode === 'full' ? '<div class="graph-segmented graph-layout-readout" aria-label="Graph layout"><output>Deterministic communities</output></div>' : `<div class="graph-segmented" role="group" aria-label="Graph layout"><button data-action="graphLayout" data-layout="flow" aria-pressed="${state.graphLayout === 'flow'}">Flow</button><button data-action="graphLayout" data-layout="orbit" aria-pressed="${state.graphLayout === 'orbit'}">Orbit</button></div>`;
    const depthControls = mode === 'full' ? '' : `<div class="graph-segmented" role="group" aria-label="Relationship depth"><button data-action="graphDepth" data-delta="-1" ${state.graphDepth <= 1 ? 'disabled' : ''} aria-label="Decrease relationship depth">−</button><output>Depth ${number(state.graphDepth)}</output><button data-action="graphDepth" data-delta="1" ${state.graphDepth >= 6 ? 'disabled' : ''} aria-label="Increase relationship depth">+</button></div>`;
    return `${state.graphError ? `<div class="graph-inline-error" role="alert">${esc(state.graphError)}</div>` : ''}${state.graphPending ? `<div class="graph-progress" role="status"><span></span>Loading the next bounded graph page…</div>` : ''}<div class="graph-commandbar"><div class="graph-segmented" role="group" aria-label="Graph coverage"><button data-action="graphOverview" aria-pressed="${mode === 'full'}">Full map</button><output>${mode === 'full' ? `${number(loadedNodes)}/${number(data.total_nodes)} records` : mode === 'overview' ? 'Community index' : 'Focused analysis'}</output></div>${layoutControls}${depthControls}<div class="graph-zoom-controls" role="group" aria-label="Map zoom"><button data-action="graphZoomOut" aria-label="Zoom out">−</button><output data-graph-zoom aria-live="polite">100%</output><button data-action="graphZoomIn" aria-label="Zoom in">+</button><button data-action="graphFit">Fit</button><button data-action="graphReset">100%</button></div><button data-action="graphBack" ${state.graphBackStack.length ? '' : 'disabled'}>Back</button><button class="graph-inspector-toggle" data-action="graphToggleInspector" aria-pressed="${state.graphInspectorOpen}">${state.graphInspectorOpen ? 'Hide' : 'Show'} inspector</button><button class="graph-focus-toggle" data-action="graphFocus" aria-pressed="${state.graphFocusMode}">${state.graphFocusMode ? 'Exit focus' : 'Focus map'}</button><button class="primary graph-load-more" data-action="graphLoadMore" ${hasMore && !state.graphPending ? '' : 'disabled'}>${hasMore ? `Load next page (${number(loadedNodes)}/${number(data.total_nodes)} nodes · ${number(loadedEdges)}/${number(data.total_edges)} edges)` : 'All eligible pages loaded'}</button><span class="graph-gesture-help">Drag or arrows pan · Ctrl+wheel or +/− zoom · 0 fits</span></div><div class="graph-workspace${state.graphInspectorOpen ? '' : ' inspector-collapsed'}"><div class="graph-stage"><div class="graph-canvas" data-graph-canvas data-scene-key="${esc(sceneKey)}" data-scene-width="${finiteLayoutAttribute(width, 320, 20000, 1280)}" data-scene-height="${finiteLayoutAttribute(height, 240, 20000, 780)}" tabindex="0" role="region" aria-label="Interactive ${esc(data.view)} graph. ${number(loadedNodes)} of ${number(data.total_nodes)} eligible records are loaded. Use the nonvisual map below for a list equivalent."><div class="graph-scene" data-graph-scene data-scene-width="${finiteLayoutAttribute(width, 320, 20000, 1280)}" data-scene-height="${finiteLayoutAttribute(height, 240, 20000, 780)}" data-graph-translate-x="0" data-graph-translate-y="0" data-graph-scale="1"><svg viewBox="0 0 ${width} ${height}" aria-hidden="true" focusable="false"><defs><marker id="graph-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M 0 0 L 10 5 L 0 10 z"></path></marker></defs>${communityHulls}${edges}</svg>${nodes}</div><article class="graph-selection-card"><span>${mode === 'full' ? 'SELECTED RECORD' : 'FOCUS NODE'}</span><strong>${esc(selected.title)}</strong><small>${esc(selected.key)}</small><div><b>${esc(selected.kind || 'node')}</b><i>${number(incomingCount)} in</i><i>${number(outgoingCount)} out</i></div></article><button class="graph-minimap" data-action="graphFit" aria-label="Fit loaded graph records"><span></span></button><span class="graph-interaction-status" data-graph-status role="status" aria-live="polite">Map fitted</span><span class="graph-truncated${hasMore ? '' : ' complete'}">${hasMore ? 'Progressive coverage' : 'Eligible set loaded'}</span></div></div><aside class="relationship-inspector" aria-label="Selected record and readable relationships"><header><div><span>SELECTED RECORD</span><strong>${esc(selected.title)}</strong><small>${esc(selected.key)}</small></div><div class="relationship-counts"><b>${number(incident.length)} loaded</b><span>${number(incomingCount)} incoming · ${number(outgoingCount)} outgoing</span></div></header><dl class="graph-record-provenance"><div><dt>Community</dt><dd>${esc(selected.community_id || 'unclassified')}</dd></div><div><dt>Source</dt><dd class="mono">${esc(selected.path || selected.source?.path || data.source || 'not declared')}</dd></div><div><dt>Hash</dt><dd class="mono">${esc(selected.source_sha256 || 'not declared')}</dd></div><div><dt>Provenance</dt><dd>${esc(provenanceSummary(selected.provenance || selected.source))}</dd></div></dl><div class="graph-inspector-actions"><button data-action="inspectGraphRecord" data-node-key="${esc(selected.key)}">Inspect source record</button><button data-action="graphOpenNeighborhood" data-node-key="${esc(selected.key)}">Open relationship neighborhood</button></div><div class="relationship-list">${relationships || empty('No loaded relationship page currently touches this record. Load more edges or open its neighborhood.')}</div></aside></div><details class="graph-accessible-map"><summary>Nonvisual map — ${number(loadedNodes)} loaded records and selected relationships</summary><div><label><span>Loaded graph records</span><select size="10" data-graph-record-list>${nonvisualOptions}</select></label><section aria-label="Selected record summary"><h3>${esc(selected.title)}</h3><p>${esc(selected.summary || 'No source summary is available.')}</p><dl><div><dt>Key</dt><dd>${esc(selected.key)}</dd></div><div><dt>Kind/status</dt><dd>${esc(selected.kind)} / ${esc(selected.status)}</dd></div><div><dt>Community</dt><dd>${esc(selected.community_id || 'unclassified')}</dd></div></dl><h4>Loaded relationships</h4><ol>${incident.map(edge => `<li><b>${esc(edge.source)}</b> ${esc(String(edge.relation).replaceAll('_', ' '))} <b>${esc(edge.target)}</b>. ${esc(edge.why || '')}</li>`).join('') || '<li>No loaded relationships touch this record.</li>'}</ol></section></div></details><div class="graph-legend"><span><i class="legend-skill"></i>Skill</span><span><i class="legend-agent"></i>Agent</span><span><i class="legend-file"></i>File / module</span><span><i class="legend-contract"></i>Contract / policy</span><span>Visual nodes are viewport-culled in bounded animation frames; the list equivalent remains available.</span></div>`;
  }

  function communities(data, state) {
    if (!data?.communities?.length) return '';
    const rows = data.communities.map(item => `<details class="graph-community" ${state.graphCommunity === item.id ? 'open' : ''}><summary><span>${esc(item.label)}</span><b>${number(item.member_count)} records</b></summary><div><span>${number(item.edge_count)} incident relationships · ${esc(Object.entries(item.status_counts || {}).map(([key, value]) => `${key} ${value}`).join(' · ') || 'status unavailable')}</span><button data-action="graphCommunity" data-community-id="${esc(item.id)}">Show only this community</button></div></details>`).join('');
    return `<section class="graph-community-index" aria-label="Graph communities"><header><div><span>COMMUNITIES</span><strong>${number(data.communities.length)} source-derived groups</strong></div>${state.graphCommunity ? `<button data-action="graphClearCommunity">Clear community filter</button>` : ''}</header><div>${rows}</div></section>`;
  }

  function render(context) {
    const { state } = requireContext(context); const data = state.graphData; const requested = state.graphPending && state.graphRequest ? state.graphRequest : data || {};
    const availableNodes = data?.nodes || [];
    const kinds = data?.available_kinds || [...new Set(availableNodes.map(item => item.kind).filter(Boolean))].sort();
    const statuses = data?.available_statuses || [...new Set(availableNodes.map(item => item.status).filter(Boolean))].sort();
    const saved = (state.graphSavedViews || []).map((item, index) => `<span class="graph-saved-view"><button data-action="graphApplySavedView" data-view-index="${index}">${esc(item.name)}</button><button data-action="graphDeleteSavedView" data-view-index="${index}" aria-label="Delete saved view ${esc(item.name)}">×</button></span>`).join('');
    const kindOptions = kinds.map(value => `<option value="${esc(value)}" ${state.graphKind === value ? 'selected' : ''}>${esc(value)}</option>`).join(''); const statusOptions = statuses.map(value => `<option value="${esc(value)}" ${state.graphStatus === value ? 'selected' : ''}>${esc(value)}</option>`).join('');
    const savedControls = `<div class="graph-saved-views" aria-label="Saved graph views and server-side filters"><b>VIEWS + FILTERS</b><select data-graph-kind aria-label="Filter source node kind"><option value="">All node kinds</option>${kindOptions}</select><select data-graph-status-filter aria-label="Filter source node status"><option value="">All statuses</option>${statusOptions}</select><button data-action="graphSaveView">Save current view</button>${saved || '<span>No local views saved.</span>'}</div>`;
    const relationOptions = (data?.relations || []).map(value => `<option value="${esc(value)}" ${(requested.relation || requested.requested_relation) === value ? 'selected' : ''}>${esc(String(value).replaceAll('_', ' '))}</option>`).join('');
    const matches = (data?.search_results || []).map(item => `<button data-action="focusGraphNode" data-node-key="${esc(item.key)}"><b>${esc(item.title)}</b><small>${esc(item.kind)} · ${esc(item.match)} match</small></button>`).join('');
    const sourceNodes = data?.source_total_nodes ?? data?.total_nodes; const eligibleNodes = data?.total_nodes; const loadedNodes = data?.covered_nodes ?? (data?.nodes?.length || 0); const loadedEdges = data?.covered_edges ?? (data?.edges?.length || 0);
    const metrics = `<div class="metric-grid compact">${card('SOURCE RECORDS', number(sourceNodes ?? 'unavailable'), 'canonical denominator')}${card('ELIGIBLE RECORDS', number(eligibleNodes ?? 'unavailable'), state.graphCommunity || state.graphKind || state.graphStatus ? 'after source filters' : 'current graph source')}${card('LOADED RECORDS', number(loadedNodes), `${number(data?.total_nodes || 0)} eligible`)}${card('LOADED RELATIONSHIPS', number(loadedEdges), `${number(data?.total_edges || 0)} eligible`)}</div>`;
    const labels = { full: 'Full map', overview: 'Community index', neighborhood: 'Neighborhood', path: 'Shortest path', impact: 'Downstream impact', dependencies: 'Dependencies', dependents: 'Dependents', hubs: 'Highest-connectivity hubs', orphans: 'Disconnected records', provenance: 'Evidence / provenance links' };
    const mode = state.graphMode || data?.mode || 'full'; const analysisOptions = Object.entries(labels).map(([value, label]) => `<option value="${value}" ${mode === value ? 'selected' : ''}>${label}</option>`).join('');
    const requestedQuery = state.graphRequest?.query ?? data?.requested_query ?? '';
    const target = mode === 'path' ? `<input data-graph-target value="${esc(state.graphTarget || data?.requested_target || '')}" placeholder="Path target node…" aria-label="Path target node">` : '';
    const directionControl = ['full', 'overview', 'hubs', 'orphans'].includes(mode) ? '' : `<select data-graph-direction aria-label="Relationship direction"><option value="both" ${data?.direction === 'both' ? 'selected' : ''}>Both directions</option><option value="outgoing" ${data?.direction === 'outgoing' ? 'selected' : ''}>Outgoing</option><option value="incoming" ${data?.direction === 'incoming' ? 'selected' : ''}>Incoming</option></select>`;
    return `${metrics}<div class="catalog-tabs graph-view-tabs" role="group" aria-label="Graph source"><button data-action="graphView" data-view="capabilities" aria-pressed="${state.graphView === 'capabilities'}" class="${state.graphView === 'capabilities' ? 'active' : ''}">Capability map</button><button data-action="graphView" data-view="repository" aria-pressed="${state.graphView === 'repository'}" class="${state.graphView === 'repository' ? 'active' : ''}">Repository map</button></div><section class="panel graph-panel${state.graphFocusMode ? ' graph-focus-mode' : ''}"><div class="panel-heading"><div><span class="eyebrow">PROGRESSIVE RECORD MAP · EXPLICIT COVERAGE</span><h2>${state.graphView === 'repository' ? 'Repository architecture explorer' : 'Knowledge graph explorer'}</h2><p class="graph-heading-note">Record and relationship pages accumulate without substituting aggregates for records. Source, eligible, loaded, and rendered coverage remain distinct.</p></div><div class="graph-tools"><select data-graph-analysis aria-label="Graph analysis">${analysisOptions}</select>${target}<input data-graph-search value="${esc(requestedQuery)}" placeholder="Find a node, file, skill, agent…" aria-label="Search the full graph source"><select data-graph-relation aria-label="Filter relationship"><option value="">All relationships</option>${relationOptions}</select>${directionControl}<button class="primary" data-action="runGraphSearch">Apply</button></div></div>${matches ? `<div class="catalog-tabs graph-search-results" aria-label="Ranked global graph search results">${matches}</div>` : ''}${savedControls}${communities(data, state)}${projection(data, context)}</section>`;
  }

  dashboard.define('graphSurface', { ids: Object.freeze(['knowledgeGraph']), has(id) { return id === 'knowledgeGraph'; }, render(context) { return render(requireContext(context)); } });
})();
