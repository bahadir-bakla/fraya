import {readFile,mkdir,writeFile} from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {compile} from './compiler.js';
import {DEFAULT_BRIEF,SCENARIOS} from './presets.js';
import {simulate,checkCase} from './engine.js';
const root=path.dirname(fileURLToPath(import.meta.url));
try {
  const brief=process.argv[2]?await readFile(path.resolve(process.argv[2]),'utf8'):DEFAULT_BRIEF;
  const api=JSON.parse(await readFile(path.join(root,'assets/bank-api.json'),'utf8'));
  const build=compile(brief,api);
  const cases=SCENARIOS.map(s=>checkCase(simulate(build.policy,s.id),s.id));
  const out=path.join(root,'output');await mkdir(out,{recursive:true});
  await writeFile(path.join(out,'demo.workflow.json'),JSON.stringify(build.workflow,null,2)+'\n');
  await writeFile(path.join(out,'demo.trace.json'),JSON.stringify({...build.trace,ended:new Date().toISOString(),policy:build.policy,tests:cases,simulation_type:'local deterministic policy simulation, not Freya workflow execution'},null,2)+'\n');
  console.log(`Workflow: ${path.join(out,'demo.workflow.json')}`);
  console.log(`Trace: ${path.join(out,'demo.trace.json')}`);
  console.log(`Yerel senaryolar: ${cases.filter(c=>c.pass).length}/${cases.length}. Freya platform değerlendirmesi yapılmadı.`);
  if(cases.some(c=>!c.pass))process.exitCode=1;
} catch(error){console.error(error.message);process.exitCode=1;}
