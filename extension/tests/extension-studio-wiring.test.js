'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const extension = fs.readFileSync(path.join(__dirname, '..', 'src', 'extension.js'), 'utf8');

test('production createStudioDraft dispatch delegates exactly once to the owned host coordinator', () => {
  assert.match(extension, /const \{ createStudioTrustRegistry, dispatchStudioCreateMessage, exactAllocationEnvelope \} = require\('\.\/studioDraftHost'\);/);
  const handler = extension.match(/case 'createStudioDraft': \{([\s\S]*?)\n\s*}\n\s*case 'detachStudioDraft':/)?.[1] || '';
  assert.ok(handler, 'createStudioDraft handler must be extractable');
  assert.equal((handler.match(/dispatchStudioCreateMessage\(/g) || []).length, 1);
  assert.match(handler, /originWebview: dashboardPanel\.webview/);
  assert.match(handler, /allocationOwner/);
  assert.match(handler, /assertInitialCreateAbsent: initialStudioIdentityAbsent/);
  assert.match(handler, /studioTrust\.assertVersionAllocation/);
  assert.match(handler, /studioTrust\.consumeVersionAllocation/);
  assert.match(handler, /materializeSkillPackage/);
  assert.match(handler, /reclaimSkillPackage: reclaimMaterializedSkillPackage/);
  assert.match(handler, /afterCommit: \(\) => publishSnapshot\(true, dashboardPanel\.webview\)/);
  assert.match(handler, /reportPostCommitWarning:/);
  assert.doesNotMatch(handler, /if \(outcome\.status === 'created'\) await publishSnapshot/);
});

test('production wiring reports committed delivery degradation without throwing a create failure', () => {
  const handler = extension.match(/case 'createStudioDraft': \{([\s\S]*?)\n\s*}\n\s*case 'detachStudioDraft':/)?.[1] || '';
  assert.match(handler, /Studio create committed; follow-up delivery degraded/);
  assert.match(handler, /committed the immutable Studio revision/);
  assert.match(handler, /Refresh the catalog to recover the durable receipt/);
});

test('production package edit ingress resolves exact catalog identity in the host', () => {
  const handler = extension.match(/case 'loadSkillPackageEditor': \{([\s\S]*?)\n\s*}\n\s*case 'listHostModels':/)?.[1] || '';
  assert.match(handler, /bridge\(\)\.catalog/);
  assert.match(handler, /item\?\.id === message\.recordId/);
  assert.match(handler, /studioTrust\.registerSourceSelection/);
  assert.doesNotMatch(handler, /message\.packagePath|message\.packageScope/);
});

test('production physical revision editing is host-selected and origin-bound', () => {
  const handler = extension.match(/case 'loadStudioRevisionEditor': \{([\s\S]*?)\n\s*}\n\s*case 'loadSkillPackageEditor':/)?.[1] || '';
  assert.match(handler, /exactCatalogRevision\(catalogPage, message\)/);
  assert.match(handler, /bridge\(\)\.nextStudioVersion/);
  assert.match(handler, /exactAllocationEnvelope\(allocation\)/);
  assert.match(handler, /studioTrust\.registerVersionAllocation/);
  assert.doesNotMatch(handler, /message\.identity|message\.source_version|message\.source_revision_sha256|message\.source_content_sha256/);
});

test('initial Studio identity absence is physically owned by the backend', () => {
  const helper = extension.match(/async function initialStudioIdentityAbsent\(kind, identity\) \{([\s\S]*?)\n  \}/)?.[1] || '';
  assert.match(helper, /bridge\(\)\.studioIdentityAbsence\(kind, identity\)/);
  assert.doesNotMatch(helper, /bridge\(\)\.catalog|has_more|pageIndex/);
  assert.match(helper, /receipt\.absent !== true/);
});

test('production Studio preparation failures retain exact correlation without stale global notifications', () => {
  assert.match(extension, /suboperation: message\?\.type === 'studioOperation' \? message\?\.operation : undefined/);
  assert.match(extension, /requestId: message\?\.requestId, kind: message\?\.kind/);
  assert.match(extension, /catalogKind: \['loadSkillPackageEditor', 'loadStudioRevisionEditor'\]\.includes\(message\?\.type\) \? message\?\.catalogKind : undefined/);
  assert.match(extension, /const requestBoundStudioPreparation = typeof message\?\.requestId === 'string'/);
  assert.match(extension, /\['loadSkillPackageEditor', 'loadStudioRevisionEditor'\]\.includes\(message\?\.type\)/);
  assert.match(extension, /message\?\.type === 'studioOperation' && message\?\.operation === 'next-version'/);
  assert.match(extension, /codexOutput\.appendLine\(`\[studio-request-failed\]/);
  assert.match(extension, /} else if \(!error\?\.pxStudioDetached\) await vscode\.window\.showErrorMessage/);
});

test('production Studio conflict recovery requires and preserves the exact structured envelope', () => {
  assert.match(extension, /const \{ PxBridge, disconnected, exactStudioVersionConflictError \} = require\('\.\/pxBridge'\);/);
  assert.match(extension, /isVersionConflict: exactStudioVersionConflictError/);
  assert.match(extension, /const studioError = exactStudioVersionConflictError\(error\) \? error\.studioError : null/);
  assert.match(extension, /bridge\(\)\.invalidate\('studio-version-conflict', 'repositories'\)/);
  assert.match(extension, /errorCode: studioError\?\.code, errorReason: studioError\?\.reason, studioError/);
  assert.doesNotMatch(extension, /includes\(['"]studio-version-conflict/);
});
