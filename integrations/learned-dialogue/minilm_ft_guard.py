"""Independent wall guardian covers image build, scheduling and computation."""
import json,os,subprocess,sys,time
from pathlib import Path
launch,receipt,seconds,app_name=sys.argv[1:];seconds=int(seconds)
if not app_name.startswith('freya-minilm-ft-') or not 1<=seconds<=2700:raise ValueError('Guardian input')
deadline=time.monotonic()+seconds;app=None;last_list=0
def apps():
    result=subprocess.run([sys.executable,'-m','modal','app','list','--json'],env=os.environ.copy(),capture_output=True,text=True,encoding='utf8',timeout=20)
    if result.returncode:return []
    return json.loads(result.stdout)
while time.monotonic()<deadline:
    try:
        data=json.loads(Path(launch).read_text(encoding='utf8'));app=data.get('app_id') or app
        if data.get('status') in ('completed','failed'):break
    except (OSError,ValueError):pass
    if app is None and time.monotonic()-last_list>20:
        last_list=time.monotonic()
        try:
            matches=[r['app_id'] for r in apps() if r.get('description')==app_name]
            if len(matches)==1:app=matches[0]
        except Exception:pass
    time.sleep(1)
if app is None:
    try:
        matches=[r['app_id'] for r in apps() if r.get('description')==app_name]
        if len(matches)==1:app=matches[0]
    except Exception:pass
record={'app_id':app,'at_epoch':time.time(),'status':'no_owned_app_identified' if app is None else 'stop_requested'}
if app:
    if not app.startswith('ap-'):raise ValueError('Exact app ID required')
    result=subprocess.run([sys.executable,'-m','modal','app','stop','--yes',app],env=os.environ.copy(),capture_output=True,timeout=45)
    record['stop_exit_code']=result.returncode
    try:record['provider_after']=[{k:r.get(k) for k in ['app_id','state','tasks','stopped_at']} for r in apps() if r.get('app_id')==app]
    except Exception:record['provider_after']='unknown'
Path(receipt).write_text(json.dumps(record)+'\n',encoding='utf8')
