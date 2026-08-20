'use strict';

(() => {
  const dashboard = globalThis.PXDashboard;
  if (!dashboard) throw new Error('PXDashboard foundation must load before components.');

  const escapeHtml = value => String(value ?? '').replace(/[&<>'"]/g, character => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
  }[character]));

  dashboard.define('components', {
    escapeHtml,
    number(value) { return Number.isFinite(Number(value)) ? Number(value).toLocaleString() : '—'; },
    bytes(value) {
      const size = Number(value || 0);
      if (!Number.isFinite(size)) return 'Unavailable';
      if (!size) return '0 B';
      const units = ['B', 'KB', 'MB', 'GB', 'TB'];
      const power = Math.min(Math.floor(Math.log(size) / Math.log(1024)), units.length - 1);
      return `${(size / (1024 ** power)).toFixed(power ? 1 : 0)} ${units[power]}`;
    },
    badge(label, tone = 'neutral') { return `<span class="badge ${escapeHtml(tone)}">${escapeHtml(label)}</span>`; },
    unavailable(label = 'Not instrumented') { return `<span class="unavailable">${escapeHtml(label)}</span>`; },
    card(label, value, detail = '', tone = '') {
      const safeLabel = escapeHtml(label);
      const safeValue = escapeHtml(value);
      const safeDetail = escapeHtml(detail);
      return `<article class="metric-card ${escapeHtml(tone)}" role="button" tabindex="0" data-action="inspectMetric" data-metric-label="${safeLabel}" data-metric-value="${safeValue}" data-metric-detail="${safeDetail}" aria-label="Inspect ${safeLabel}: ${safeValue}"><span class="metric-label">${safeLabel}</span><i class="inspect-cue" aria-hidden="true">INSPECT</i><strong>${safeValue}</strong><small>${safeDetail}</small></article>`;
    },
    section(title, kicker, content, extra = '') {
      if (['Stale operation queue', 'Historical actor sessions'].includes(title) && content.includes('class="empty-state"')) return '';
      const actions = extra ? `<div class="panel-heading-actions">${extra}</div>` : '';
      return `<section class="panel"><div class="panel-heading"><div><span class="eyebrow">${escapeHtml(kicker)}</span><h2>${escapeHtml(title)}</h2></div>${actions}</div>${content}</section>`;
    },
    empty(message) { return `<div class="empty-state" role="status" aria-live="polite"><span class="empty-ring"></span><p>${escapeHtml(message)}</p></div>`; }
  });
})();
