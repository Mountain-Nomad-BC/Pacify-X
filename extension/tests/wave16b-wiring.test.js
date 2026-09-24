'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const root=path.resolve(__dirname,'..');

test('extension registers the governed PX provider beside, not instead of, the legacy Ollama provider',()=>{
 const source=fs.readFileSync(path.join(root,'src','extension.js'),'utf8');
 assert.match(source,/registerLanguageModelChatProvider\('pacify-local'/);
 assert.match(source,/registerLanguageModelChatProvider\('pacify-x'/);
 assert.match(source,/new McpModelFabricBridge/);
 assert.match(source,/new PxLanguageModelProvider/);
});

test('governed provider has no direct llama.cpp or arbitrary localhost transport',()=>{
 const provider=fs.readFileSync(path.join(root,'src','pxLanguageModelProvider.js'),'utf8');
 const bridge=fs.readFileSync(path.join(root,'src','mcpModelFabricBridge.js'),'utf8');
 assert.doesNotMatch(provider,/fetch\(|http:\/\/|llama-server|models\/load/);
 assert.doesNotMatch(bridge,/http:\/\/|models\/load|models\/unload/);
 assert.match(bridge,/runtime\.vscode_model_bridge/);
});

test('package activates the governed language model surface and includes its refresh command',()=>{
 const pkg=JSON.parse(fs.readFileSync(path.join(root,'package.json'),'utf8'));
 assert.ok(pkg.activationEvents.includes('onLanguageModelChat:pacify-x'));
 assert.ok(pkg.contributes.commands.some(row=>row.command==='pacifyX.refreshModelFabric'));
 assert.match(pkg.scripts.check,/pxLanguageModelProvider\.js/);
 assert.match(pkg.scripts.check,/mcpModelFabricBridge\.js/);
});
