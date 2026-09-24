'use strict';
const fs=require('node:fs');const path=require('node:path');const cp=require('node:child_process');
const root=path.resolve(__dirname,'..');
function walk(dir){const out=[];for(const e of fs.readdirSync(dir,{withFileTypes:true})){const full=path.join(dir,e.name);if(e.isDirectory())out.push(...walk(full));else if(e.isFile()&&e.name.endsWith('.js'))out.push(full);}return out;}
const files=[...walk(path.join(root,'src','agentHarness')),path.join(root,'media','agent-console.js')];
const failures=[];for(const file of files){const r=cp.spawnSync(process.execPath,['--check',file],{cwd:root,encoding:'utf8',windowsHide:true});if(r.status!==0)failures.push({file:path.relative(root,file),stderr:r.stderr});}
if(failures.length){for(const f of failures)console.error(`FAIL ${f.file}\n${f.stderr}`);process.exitCode=1;}else console.log(`agent-harness syntax PASS (${files.length} files)`);
