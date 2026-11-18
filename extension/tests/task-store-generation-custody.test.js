'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {TaskStore}=require('../src/agentHarness/taskStore');
const {DurableTaskState}=require('../src/agentHarness/durableTaskState');
const {registerAgentConsole}=require('../src/agentHarness/registerAgentConsole');
const {ProjectTaskStore}=require('../src/agentHarness/projectTaskStore');
const {BudgetLedger}=require('../src/agentHarness/budgetLedger');
const {DurableBudgetState}=require('../src/agentHarness/durableTaskState');

function project() {
  assert.ok(process.env.TMPDIR);
  return fs.mkdtempSync(path.join(process.env.TMPDIR,'native-console-'));
}

function host(root, extra={}) {
  const disposable=()=>({dispose(){}});
  return registerAgentConsole({window:{registerWebviewViewProvider:disposable},commands:{registerCommand:disposable}},
    {workspaceState:{get:()=>undefined,update:async()=>{}},extensionPath:'.'},
    {nativeTaskState:true,workspaceRootProvider:()=>root,workspaceRootsProvider:()=>[root],...extra});
}

test('registered native host persists project-owned budget history and preserves outstanding spend across restart',async()=>{
  const root=project();let owner=host(root);
  const worker={workerId:'paid-worker',providerId:'paid-provider',costClass:'billable-api'};
  try {
    assert.deepEqual(fs.readdirSync(root),[]);
    const task=owner.harness.createTask({goal:'native paid reservation',taskCostCeilingUsd:1,requireApprovalBeforeBillable:false});
    const run=owner.harness.taskStore.createRun(task.taskId);
    owner.harness.budgetLedger.reserve({worker,task,runId:run.runId,executionId:'native-reservation',projectedChargeUsd:0.7});
    await owner.harness.budgetLedger.flush();
    const file=new DurableBudgetState(root).file;
    assert.ok(fs.existsSync(file),'registered host must use the canonical physical usage ledger');
    const before=JSON.parse(fs.readFileSync(file,'utf8'));
    assert.equal(before.reservations[0].executionId,'native-reservation');
    assert.deepEqual(before.projectBinding,JSON.parse(fs.readFileSync(new DurableTaskState(root).file,'utf8')).projectBinding);
    owner.dispose();owner=host(root);owner.harness._prepareTaskState();
    const current=owner.harness.taskStore.requireTask(task.taskId);
    assert.equal(owner.harness.budgetLedger.canAdmit(worker,current,0.4).reason,'task-cost-ceiling');
    assert.equal(owner.harness.budgetLedger.canAdmit(worker,current,0.2).allowed,true,'verified native history must not be re-quarantined on restart');
    assert.equal(owner.harness.budgetLedger.reservations.has('native-reservation'),true);
    owner.harness.budgetLedger.record({taskId:task.taskId,runId:run.runId,executionId:'native-reservation',settlementId:'b'.repeat(64),...worker,inputTokens:1,outputTokens:1,totalTokens:2,actualChargeUsd:0.7,projectedChargeUsd:0.7,billingIdentityKnown:true,quotaRemaining:null});
    owner.dispose();owner=host(root);owner.harness._prepareTaskState();
    assert.equal(owner.harness.budgetLedger.canAdmit(worker,owner.harness.taskStore.requireTask(task.taskId),0.4).reason,'task-cost-ceiling');
    assert.equal(owner.harness.budgetLedger.entries[0].receipt.actualChargeUsd,0.7);
    assert.equal(owner.harness.budgetLedger.reservations.size,0);
  } finally {owner.dispose();}
});

test('failed initial task snapshot cannot publish a usable owner or create budget state',()=>{
  const root=project();const owner=host(root);const original=DurableTaskState.prototype.save;
  DurableTaskState.prototype.save=function(){throw Error('fixture-initial-task-save-failed');};
  try {
    assert.throws(()=>owner.harness._prepareTaskState(),/fixture-initial-task-save-failed/);
    assert.equal(owner.harness.taskStore.ownerBinding,undefined);
    assert.deepEqual(fs.readdirSync(root),[]);
  } finally {DurableTaskState.prototype.save=original;owner.dispose();}
});

test('legacy unbound task migration cannot adopt an existing bound budget',()=>{
  const root=project();let owner=host(root);owner.harness.createTask({goal:'original task owner'});owner.dispose();
  const taskFile=new DurableTaskState(root).file;const state=JSON.parse(fs.readFileSync(taskFile,'utf8'));
  delete state.projectBinding;fs.writeFileSync(taskFile,JSON.stringify(state));
  const budgetFile=new DurableBudgetState(root).file;const before=fs.readFileSync(budgetFile);owner=host(root);
  try {
    assert.throws(()=>owner.harness._prepareTaskState(),/budget-store-project-binding-mismatch/);
    assert.deepEqual(fs.readFileSync(budgetFile),before);
  } finally {owner.dispose();}
});

test('well-formed hashed native budget cannot introduce an unattributed financial owner',()=>{
  const {sha256}=require('../src/agentHarness/ids');
  const root=project();let owner=host(root);
  const task=owner.harness.createTask({goal:'attributed reservation',taskCostCeilingUsd:1,requireApprovalBeforeBillable:false});
  owner.harness.budgetLedger.reserve({worker:{workerId:'paid-worker',providerId:'paid',costClass:'billable-api'},task,runId:'run',executionId:'execution',projectedChargeUsd:0.2});owner.dispose();
  const file=new DurableBudgetState(root).file;const state=JSON.parse(fs.readFileSync(file,'utf8'));
  state.knownTaskIds=[];const {snapshotSha256,...body}=state;state.snapshotSha256=sha256(body);fs.writeFileSync(file,JSON.stringify(state));
  const before=fs.readFileSync(file);owner=host(root);
  try {assert.throws(()=>owner.harness._prepareTaskState(),/unattributed-financial-owner/);assert.deepEqual(fs.readFileSync(file),before);}
  finally {owner.dispose();}
});

test('copied native task or budget state cannot adopt another physical project',()=>{
  const source=project();const first=host(source);
  first.harness.createTask({goal:'source project'});first.dispose();
  const destination=project();const second=host(destination);
  second.harness.createTask({goal:'destination project'});second.dispose();
  const budgetFile=new DurableBudgetState(destination).file;
  fs.copyFileSync(new DurableBudgetState(source).file,budgetFile);
  const before=fs.readFileSync(budgetFile);const rejected=host(destination);
  try {assert.throws(()=>rejected.harness._prepareTaskState(),/budget-store-project-binding-mismatch/);assert.deepEqual(fs.readFileSync(budgetFile),before);}
  finally {rejected.dispose();}
  const thirdRoot=project();const disk=new DurableTaskState(thirdRoot);fs.mkdirSync(disk.directory,{recursive:true});
  fs.copyFileSync(new DurableTaskState(source).file,disk.file);
  const copied=fs.readFileSync(disk.file);const third=host(thirdRoot);
  try {assert.throws(()=>third.harness._prepareTaskState(),/task-state-project-binding-mismatch/);assert.deepEqual(fs.readFileSync(disk.file),copied);}
  finally {third.dispose();}
});

test('copied native state after same-path directory replacement cannot reuse live or restarted authority',()=>{
  const root=project();const owner=host(root);
  const task=owner.harness.createTask({goal:'physical directory owner',taskCostCeilingUsd:1,requireApprovalBeforeBillable:false});
  const worker={workerId:'paid-worker',providerId:'paid-provider',costClass:'billable-api'};
  const retained=root+'.retained-fixture';fs.renameSync(root,retained);fs.cpSync(retained,root,{recursive:true});
  const file=new DurableBudgetState(root).file;const before=fs.readFileSync(file);
  try {assert.throws(()=>owner.harness.budgetLedger.reserve({worker,task,runId:'replacement-run',executionId:'replacement-execution',projectedChargeUsd:0.1}),/project.*(changed|binding)/);}
  finally {owner.dispose();}
  assert.deepEqual(fs.readFileSync(file),before);
  const restarted=host(root);
  try {assert.throws(()=>restarted.harness._prepareTaskState(),/task-state-project-binding-mismatch/);}
  finally {restarted.dispose();}
});

test('an existing binding without native directory identity refuses without adopting a new identity',()=>{
  const root=project();let owner=host(root);owner.harness.createTask({goal:'bound owner'});owner.dispose();
  const taskFile=new DurableTaskState(root).file;const state=JSON.parse(fs.readFileSync(taskFile,'utf8'));
  delete state.projectBinding.directoryIdentity;fs.writeFileSync(taskFile,JSON.stringify(state));
  const taskBytes=fs.readFileSync(taskFile);const budgetFile=new DurableBudgetState(root).file;const budgetBytes=fs.readFileSync(budgetFile);owner=host(root);
  try {
    assert.throws(()=>owner.harness._prepareTaskState(),/task-state-project-binding-mismatch/);
    assert.deepEqual(fs.readFileSync(taskFile),taskBytes);assert.deepEqual(fs.readFileSync(budgetFile),budgetBytes);
  } finally {owner.dispose();}
});

test('unavailable native directory identity cannot fall back to a pathname binding',()=>{
  const root=project();const owner=host(root);const original=fs.statSync;
  fs.statSync=function(file,options){return file===root && options?.bigint ? {isDirectory:()=>true,ino:0n,dev:1n} : original.call(this,file,options);};
  try {assert.throws(()=>owner.harness._prepareTaskState(),/directory-identity-unavailable/);assert.deepEqual(fs.readdirSync(root),[]);}
  finally {fs.statSync=original;owner.dispose();}
});

test('missing native budget after earlier spend fences historical tasks even with a valid Memento ledger',()=>{
  const root=project();let owner=host(root);
  const task=owner.harness.createTask({goal:'history cannot become zero',taskCostCeilingUsd:1,requireApprovalBeforeBillable:false});
  const worker={workerId:'paid-worker',providerId:'paid-provider',costClass:'billable-api'};
  owner.harness.budgetLedger.reserve({worker,task,runId:'old-run',executionId:'old-execution',projectedChargeUsd:0.7});
  owner.dispose();
  const file=new DurableBudgetState(root).file;const legacy=JSON.parse(fs.readFileSync(file,'utf8'));
  fs.renameSync(file,file+'.retained-fixture');
  let updates=0;const disposable=()=>({dispose(){}});
  owner=registerAgentConsole({window:{registerWebviewViewProvider:disposable},commands:{registerCommand:disposable}},
    {workspaceState:{get:key=>key.includes('budgetState')?legacy:undefined,update:async()=>{updates++;}},extensionPath:'.'},
    {nativeTaskState:true,workspaceRootsProvider:()=>[root],workspaceRootProvider:()=>root});
  try {
    owner.harness._prepareTaskState();
    assert.equal(owner.harness.budgetLedger.canAdmit(worker,owner.harness.taskStore.requireTask(task.taskId),0.1).reason,'task-historical-spend-unreconciled');
    const fresh=owner.harness.createTask({goal:'new task after missing history',taskCostCeilingUsd:1,requireApprovalBeforeBillable:false});
    assert.equal(owner.harness.budgetLedger.canAdmit(worker,fresh,0.1).allowed,true);
    assert.equal(updates,0,'legacy source must be retained unchanged');
  } finally {owner.dispose();}
});

test('a task published before known-zero enrollment stays quarantined after restart',()=>{
  const root=project();let owner=host(root);owner.harness._prepareTaskState();
  const partial=owner.harness.taskStore.createTask({goal:'crash between task and budget saves',taskCostCeilingUsd:1,requireApprovalBeforeBillable:false});
  owner.dispose();owner=host(root);
  try {
    owner.harness._prepareTaskState();
    assert.equal(owner.harness.budgetLedger.canAdmit({costClass:'billable-api',providerId:'paid'},owner.harness.taskStore.requireTask(partial.taskId),0.1).reason,'task-historical-spend-unreconciled');
    assert.throws(()=>owner.harness.budgetLedger.registerCreatedTask(owner.harness.taskStore.requireTask(partial.taskId)),/requires-native-task-creation/);
  } finally {owner.dispose();}
});

test('competing native budget writer cannot replace a newer reservation',()=>{
  const root=project();const first=host(root);const worker={workerId:'paid-worker',providerId:'paid-provider',costClass:'billable-api'};
  const task=first.harness.createTask({goal:'competing budget writers',taskCostCeilingUsd:1,requireApprovalBeforeBillable:false});
  const second=host(root);
  try {
    second.harness._prepareTaskState();
    second.harness.budgetLedger.reserve({worker,task:second.harness.taskStore.requireTask(task.taskId),runId:'current-run',executionId:'current-reservation',projectedChargeUsd:0.2});
    const file=new DurableBudgetState(root).file;const before=fs.readFileSync(file);
    assert.throws(()=>first.harness.budgetLedger.reserve({worker,task,runId:'stale-run',executionId:'stale-reservation',projectedChargeUsd:0.1}),/stale-writer/);
    assert.deepEqual(fs.readFileSync(file),before);
  } finally {first.dispose();second.dispose();}
});

test('budget persistence failure prevents actual registered provider dispatch',async()=>{
  const root=project();const owner=host(root);let calls=0;
  owner.harness.workerRegistry.register({workerId:'fixture',adapterId:'controlled',providerId:'llama.cpp',modelId:'fixture',displayName:'Controlled',costClass:'local',contextLimit:12000,locality:'local',capabilities:{coding:1,planning:1,review:1,classification:1},supportedEffectClass:'READ_ONLY',enabled:true,reliability:1,latencyClass:'fast'},
    {runTurn:async()=>{calls++;return{text:'must not run'};}});
  const original=DurableBudgetState.prototype.save;
  try {
    const task=owner.harness.createTask({goal:'budget save failure'});
    DurableBudgetState.prototype.save=function(){throw Error('fixture-native-budget-save-failed');};
    await assert.rejects(owner.harness.sendTurn({taskId:task.taskId,message:'inspect'}),/fixture-native-budget-save-failed/);
    assert.equal(calls,0);
  } finally {DurableBudgetState.prototype.save=original;owner.dispose();}
});

test('native financial mutations reject unknown free owners without writes while quarantined local usage remains supported',()=>{
  const root=project();const native=new TaskStore({persistence:new DurableTaskState(root)});
  const historical=native.createTask({goal:'quarantined local history'});const owner=host(root);
  const worker={workerId:'free-worker',providerId:'local-provider',costClass:'local'};
  try {
    owner.harness._prepareTaskState();const ledger=owner.harness.budgetLedger;const file=new DurableBudgetState(root).file;
    const before=fs.readFileSync(file);
    assert.throws(()=>ledger.reserve({worker,task:{...historical,taskId:'unknown-task'},runId:'unknown-run',executionId:'unknown-execution'}),/unattributed-financial-owner/);
    assert.throws(()=>ledger.record({taskId:'unknown-task',runId:'unknown-run',executionId:'unknown-execution',...worker,inputTokens:1,outputTokens:1,totalTokens:2,actualChargeUsd:0,projectedChargeUsd:0,billingIdentityKnown:true,quotaRemaining:null}),/unattributed-financial-owner/);
    assert.throws(()=>ledger.record({taskId:historical.taskId,runId:'unknown-run',executionId:'unknown-execution',...worker,inputTokens:1,outputTokens:1,totalTokens:2,actualChargeUsd:0,projectedChargeUsd:0,billingIdentityKnown:true,quotaRemaining:null}),/native-usage-reservation-required/);
    assert.deepEqual(fs.readFileSync(file),before);
    ledger.reserve({worker,task:owner.harness.taskStore.requireTask(historical.taskId),runId:'local-run',executionId:'local-execution'});
    ledger.record({taskId:historical.taskId,runId:'local-run',executionId:'local-execution',...worker,inputTokens:1,outputTokens:1,totalTokens:2,actualChargeUsd:0,projectedChargeUsd:0,billingIdentityKnown:true,quotaRemaining:null});
    assert.equal(ledger.unreconciledTaskIds.has(historical.taskId),true);
  } finally {owner.dispose();}
  const restarted=host(root);
  try {restarted.harness._prepareTaskState();assert.equal(restarted.harness.budgetLedger.entries.length,1);}
  finally {restarted.dispose();}
});

test('workspace switch rejects new reservations while original owned settlement persists',()=>{
  const root=project();const other=project();let selected=root;const owner=host(root,{workspaceRootsProvider:()=>[selected]});
  const worker={workerId:'paid-worker',providerId:'paid-provider',costClass:'billable-api'};
  try {
    const task=owner.harness.createTask({goal:'pinned budget settlement',taskCostCeilingUsd:1,requireApprovalBeforeBillable:false});
    owner.harness.budgetLedger.reserve({worker,task,runId:'owned-run',executionId:'owned-execution',projectedChargeUsd:0.2});
    selected=other;
    assert.throws(()=>owner.harness.budgetLedger.reserve({worker,task,runId:'other-run',executionId:'other-execution',projectedChargeUsd:0.1}),/project-changed/);
    owner.harness.budgetLedger.record({taskId:task.taskId,runId:'owned-run',executionId:'owned-execution',settlementId:'a'.repeat(64),...worker,inputTokens:1,outputTokens:1,totalTokens:2,actualChargeUsd:0.1,projectedChargeUsd:0.2,billingIdentityKnown:true,quotaRemaining:null});
    const state=JSON.parse(fs.readFileSync(new DurableBudgetState(root).file,'utf8'));
    assert.equal(state.entries[0].receipt.actualChargeUsd,0.1);assert.equal(state.reservations.length,0);
    assert.deepEqual(fs.readdirSync(other),[]);
  } finally {owner.dispose();}
});

test('valid native state takes precedence over corrupt legacy data even at registration',()=>{
  const root=project();const native=new TaskStore({persistence:new DurableTaskState(root)});
  const task=native.createTask({goal:'native survives corrupt legacy'});
  const store=new ProjectTaskStore({rootsProvider:()=>[root],legacySnapshot:{tasks:'corrupt'}});
  assert.equal(store.listTasks().length,0);
  store.prepare();assert.equal(store.requireTask(task.taskId).goal,task.goal);
});

test('native state appearing at actual load cannot replay legacy-only tasks',()=>{
  const root=project();const legacy=new TaskStore();const old=legacy.createTask({goal:'must not resurrect'});
  const original=DurableTaskState.prototype.load;let injected=false;let nativeTask;
  DurableTaskState.prototype.load=function(){
    if (!injected && this.root===root) {
      injected=true;
      const native=new TaskStore({persistence:new DurableTaskState(root)});
      nativeTask=native.createTask({goal:'concurrently published native task'});
    }
    return original.call(this);
  };
  try {
    const store=new ProjectTaskStore({rootsProvider:()=>[root],legacySnapshot:legacy.snapshot()});
    store.prepare();assert.equal(store.requireTask(nativeTask.taskId).goal,nativeTask.goal);
    assert.throws(()=>store.requireTask(old.taskId));
  } finally {DurableTaskState.prototype.load=original;}
});

test('native preexisting tasks with absent usage history are fenced while newly created tasks remain distinct',()=>{
  const root=project();const native=new TaskStore({persistence:new DurableTaskState(root)});
  const old=native.createTask({goal:'historical task'});const owner=host(root);
  try {
    const fresh=owner.harness.createTask({goal:'new task'});
    const budget=owner.harness.budgetLedger;
    assert.equal(budget.unreconciledTaskIds.has(old.taskId),true);
    assert.equal(budget.unreconciledTaskIds.has(fresh.taskId),false);
    const worker={costClass:'billable-api',providerId:'paid'};
    const task={taskId:old.taskId,constraints:{taskCostCeilingUsd:10,requireApprovalBeforeBillable:false}};
    assert.equal(budget.canAdmit(worker,task,1).reason,'task-historical-spend-unreconciled');
    assert.equal(budget.canAdmit(worker,{...task,taskId:fresh.taskId},1).allowed,true);
  } finally {owner.dispose();}
});

test('missing-history quarantine persists and a failed persistence owner refuses further admission',async()=>{
  let image;let fail=false;
  const ledger=new BudgetLedger(()=>({}),{persistence:{synchronous:true,load:()=>null,save:value=>{if(fail)throw Error('fixture-budget-write-failed');image=value;}}});
  ledger.reconcilePreexistingTasks(['historical-task']);
  assert.deepEqual(image.unreconciledTaskIds,['historical-task']);
  const restarted=new BudgetLedger(()=>({}),{persistence:{synchronous:true,load:()=>image,save:value=>{image=value;}}});
  restarted.reconcilePreexistingTasks(['native-task-not-in-workspace-ledger']);
  assert.equal(restarted.unreconciledTaskIds.has('native-task-not-in-workspace-ledger'),true);
  fail=true;assert.throws(()=>ledger.reconcilePreexistingTasks(['another-task']),/fixture-budget-write-failed/);
  await assert.rejects(ledger.flush(),/fixture-budget-write-failed/);
});

test('registered production host defers project writes then publishes native task authority',()=>{
  const root=project();const owner=host(root);
  try {
    assert.deepEqual(fs.readdirSync(root),[], 'registration must remain project-write-free');
    const task=owner.harness.createTask({goal:'native host task'});
    const file=path.join(root,'.agentic_engineering_os_px','runtime-core','agent-console','task-state.json');
    assert.ok(fs.existsSync(file),'actual console task must be visible at the native bridge authority path');
    const state=JSON.parse(fs.readFileSync(file,'utf8'));
    assert.equal(state.tasks[0].taskId,task.taskId);
    assert.equal(state.epoch,task.epoch);
    assert.equal(owner.harness.projectId,path.basename(root));
  } finally {owner.dispose();}
});

test('native preparation preserves attributed legacy data and never replays it over native state',()=>{
  const root=project();const legacy=new TaskStore();
  const task=legacy.createTask({goal:'legacy task'});
  const snapshot=legacy.snapshot();const before=JSON.stringify(snapshot);
  const first=new ProjectTaskStore({rootsProvider:()=>[root],legacySnapshot:snapshot,legacyRootProvider:()=>root});
  assert.deepEqual(fs.readdirSync(root),[]);
  first.prepare();assert.equal(first.requireTask(task.taskId).goal,'legacy task');
  first.updateTask(task.taskId,{goal:'native revision'});
  const otherLegacy=new TaskStore();const extra=otherLegacy.createTask({goal:'unattributed old task'});
  const second=new ProjectTaskStore({rootsProvider:()=>[root],legacySnapshot:otherLegacy.snapshot()});
  second.prepare();
  assert.equal(second.requireTask(task.taskId).goal,'native revision');
  assert.throws(()=>second.requireTask(extra.taskId));
  assert.equal(JSON.stringify(snapshot),before,'legacy snapshot must remain unchanged');
  const bytes=fs.readFileSync(new DurableTaskState(root).file);
  assert.throws(()=>first.updateTask(task.taskId,{goal:'stale writer'}),/stale-writer/);
  assert.deepEqual(fs.readFileSync(new DurableTaskState(root).file),bytes);
});

test('unattributed legacy tasks and absent or multiple project roots fail before publication',()=>{
  const root=project();const other=project();const legacy=new TaskStore();legacy.createTask({goal:'unattributed'});
  const pending=new ProjectTaskStore({rootsProvider:()=>[root],legacySnapshot:legacy.snapshot()});
  assert.throws(()=>pending.prepare(),/attribution-required/);
  assert.deepEqual(fs.readdirSync(root),[]);
  for (const roots of [[],[root,other]]) {
    const store=new ProjectTaskStore({rootsProvider:()=>roots});
    assert.throws(()=>store.createTask({goal:'wrong root'}),/one-explicit-project-root/);
  }
  assert.deepEqual(fs.readdirSync(other),[]);
});

test('native corruption cannot fall back to workspace storage or replace original bytes',()=>{
  const root=project();const disk=new DurableTaskState(root);fs.mkdirSync(disk.directory,{recursive:true});
  const bad=Buffer.from('{"schemaVersion":"corrupted"}');fs.writeFileSync(disk.file,bad);
  const owner=host(root);
  try {
    assert.throws(()=>owner.harness.createTask({goal:'must refuse'}),/invalid-generation/);
    assert.deepEqual(fs.readFileSync(disk.file),bad);
    assert.throws(()=>owner.harness.createTask({goal:'must stay refused'}),/invalid-generation/);
  } finally {owner.dispose();}
});

test('workspace switch during awaited refresh blocks provider dispatch and preserves old state',async()=>{
  const root=project();const other=project();let selected=root;
  const owner=host(root,{workspaceRootsProvider:()=>[selected]});
  let release;const gate=new Promise(resolve=>{release=resolve;});let calls=0;
  owner.harness.refreshWorkers=()=>gate;
  owner.harness.workerRegistry.register({workerId:'fixture',adapterId:'controlled',providerId:'llama.cpp',modelId:'fixture',displayName:'Controlled',costClass:'local',contextLimit:12000,locality:'local',capabilities:{coding:1,planning:1,review:1,classification:1},supportedEffectClass:'READ_ONLY',enabled:true,reliability:1,latencyClass:'fast'},
    {runTurn:async()=>{calls++;return{text:'fixture'};}});
  try {
    const task=owner.harness.createTask({goal:'root-bound task'});
    const file=new DurableTaskState(root).file;const before=fs.readFileSync(file);
    const pending=owner.harness.sendTurn({taskId:task.taskId,message:'inspect'});
    selected=other;release();
    await assert.rejects(pending,/project-changed/);
    assert.equal(calls,0);assert.deepEqual(fs.readFileSync(file),before);
    assert.deepEqual(fs.readdirSync(other),[]);
  } finally {owner.dispose();}
});

test('root changes forbid new actions while owned cancellation can settle the original run',()=>{
  const root=project();const other=project();let selected=root;
  const store=new ProjectTaskStore({rootsProvider:()=>[selected]});
  const task=store.createTask({goal:'owned old-root run'});const run=store.createRun(task.taskId);
  selected=other;
  assert.throws(()=>store.createTask({goal:'foreign-root mutation'}),/project-changed/);
  store.updateRun(run.runId,{status:'cancelled'});
  assert.equal(JSON.parse(fs.readFileSync(new DurableTaskState(root).file,'utf8')).runs[0].status,'cancelled');
  assert.deepEqual(fs.readdirSync(other),[]);
});

test('actual registered host publishes the exact native run generation before adapter dispatch',async()=>{
  const root=project();const owner=host(root);let observed=false;
  owner.harness.workerRegistry.register({workerId:'fixture',adapterId:'controlled',providerId:'llama.cpp',modelId:'fixture',displayName:'Controlled',costClass:'local',contextLimit:12000,locality:'local',capabilities:{coding:1,planning:1,review:1,classification:1},supportedEffectClass:'READ_ONLY',enabled:true,reliability:1,latencyClass:'fast'},
    {runTurn:async input=>{
      const state=JSON.parse(fs.readFileSync(new DurableTaskState(root).file,'utf8'));
      const run=state.runs.find(row=>row.runId===input.executionContext.root_execution_id);
      assert.equal(state.epoch,input.executionContext.epoch);
      assert.equal(run.epoch,input.executionContext.epoch);
      assert.equal(run.revision,input.executionContext.revision);
      assert.equal(run.status,'running');assert.equal(run.activeWorkerId,'fixture');
      assert.equal(input.executionContext.project_id,path.basename(root));
      assert.equal(run.taskId,input.task.taskId);observed=true;
      return{text:'controlled native-state observation'};
    }});
  try {
    const result=await owner.harness.sendTurn({goal:'native dispatch',message:'inspect'});
    assert.equal(observed,true);assert.equal(result.run.status,'complete');
    const state=JSON.parse(fs.readFileSync(new DurableTaskState(root).file,'utf8'));
    assert.equal(state.runs[0].status,'complete');
  } finally {owner.dispose();}
});

test('native durable restart advances epoch and fences a real stale writer without changing bytes',()=>{
  // Both focused and governed test owners supply this registered process temp
  // root before starting Node; no independently owned temporary root is made.
  const root=process.env.TMPDIR;
  assert.ok(root && fs.statSync(root).isDirectory());
  const disk=new DurableTaskState(root);
  const first=new TaskStore({persistence:disk});
  const task=first.createTask({goal:'native persistence probe'});
  const old={epoch:task.epoch,revision:task.revision};
  const secondDisk=new DurableTaskState(root);
  const second=new TaskStore({persistence:secondDisk});
  assert.equal(second.epoch,first.epoch+1);
  const before=fs.readFileSync(secondDisk.file);
  assert.throws(()=>first.updateTask(task.taskId,{goal:'stale write'}));
  assert.deepEqual(fs.readFileSync(secondDisk.file),before);
  assert.throws(()=>second.updateTask(task.taskId,{goal:'stale object'},old),/stale-object-writer/);
  const current=second.requireTask(task.taskId);
  const updated=second.updateTask(task.taskId,{goal:'current writer'},{epoch:current.epoch,revision:current.revision});
  assert.equal(updated.revision,current.revision+1);
  assert.equal(JSON.parse(fs.readFileSync(secondDisk.file,'utf8')).tasks[0].goal,'current writer');
});
