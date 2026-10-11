import subprocess,json,time,datetime
from pathlib import Path
p=Path(__file__).resolve().parent
start=time.monotonic()
cmd=['codex','exec','--ignore-user-config','--skip-git-repo-check','--ephemeral','--config','default_permissions=:danger-full-access','--config','approval_policy=never','--json','--color','never','--output-schema',str(p/'response.schema.json'),'--output-last-message',str(p/'answer.json'),'--model','gpt-6-astra','-']
try:
 with (p/'model.jsonl').open('w') as log:
  r=subprocess.run(cmd,cwd=p/'work',input=(p/'prompt.txt').read_text(),text=True,stdout=log,stderr=subprocess.STDOUT,timeout=330)
 status={'returncode':r.returncode,'elapsed_s':round(time.monotonic()-start),'automatic_followup':True,'parent_run':'20261011-181159-77db0d','hosted_evaluated':False}
except subprocess.TimeoutExpired:
 status={'timed_out':True,'elapsed_s':round(time.monotonic()-start)}
(p/'status.json').write_text(json.dumps(status,indent=2))
print(json.dumps(status))
