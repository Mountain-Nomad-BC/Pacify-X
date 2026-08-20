'use strict';

(() => {
  const dashboard = globalThis.PXDashboard;
  if (!dashboard) throw new Error('PXDashboard foundation must load before surfaces.');

  const visible = [
    ['dashboard', 'Dashboard', 'pulse'], ['projects', 'Projects', 'folder'], ['agents', 'Agents', 'agents'],
    ['agent-studio', 'Agent Studio', 'agents'], ['workflow-studio', 'Workflow Studio', 'flow'], ['skill-studio', 'Skill Studio', 'tools'],
    ['knowledgeGraph', 'Knowledge Graph', 'graph'], ['skillsTools', 'Skills & Tools', 'tools'], ['workflows', 'Workflows', 'flow'],
    ['plugins', 'Plugin Manager', 'plugin'], ['memory', 'Memory', 'memory'], ['activity', 'Activity', 'activity'],
    ['diagnostics', 'Diagnostics', 'diagnostics'], ['assurance', 'Assurance', 'shield'], ['studio-lifecycle', 'Studio Lifecycle', 'settings'],
    ['settings', 'Settings', 'settings']
  ].map(entry => Object.freeze(entry));
  const advanced = [
    ['knowledgeCore', 'Knowledge Core', 'knowledge'], ['runtimeCore', 'Runtime Core', 'runtime']
  ].map(entry => Object.freeze(entry));

  dashboard.define('surfaces', {
    visible: Object.freeze(visible),
    advanced: Object.freeze(advanced),
    all: Object.freeze([...visible, ...advanced]),
    find(id) { return [...visible, ...advanced].find(([surfaceId]) => surfaceId === id) || null; }
  });
})();
