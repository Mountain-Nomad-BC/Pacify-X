'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {TaskStore}=require('../src/agentHarness/taskStore');
const {DurableTaskState}=require('../src/agentHarness/durableTaskState');

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
