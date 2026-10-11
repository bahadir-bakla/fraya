"""Parent-owned launch, shared35USD budget and absolute remote stop watchdog."""
import argparse, contextlib, datetime, gzip, hashlib, io, json, os, subprocess, sys, time, uuid, zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
LEDGER=ROOT/'local-runs/autonomous-rd/modal-budget.json'

def now():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def atomic(path,data):
    temp=path.with_name(path.name+'.tmp-'+uuid.uuid4().hex);temp.write_text(json.dumps(data,indent=2)+'\n',encoding='utf8');os.replace(temp,path)
@contextlib.contextmanager
def lock():
    p=LEDGER.with_suffix('.lock');p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('a+b') as f:
        if os.name=='nt':
            import msvcrt
            if not f.seek(0,2):f.write(b'0');f.flush()
            f.seek(0);msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
        try:yield
        finally:
            if os.name=='nt':f.seek(0);msvcrt.locking(f.fileno(),msvcrt.LK_UNLCK,1)
            else:fcntl.flock(f,fcntl.LOCK_UN)

def reserve(run_id,usd):
    with lock():
        data=json.loads(LEDGER.read_text(encoding='utf8'))
        holds=sum(float(r.get('reserved_usd',r.get('usd',0))) for r in data.get('reservations',[]) if r.get('status') not in ('settled','released'))
        charged=float(data.get('actual_task_cost_usd',0))+float(data.get('accounted_upper_cost_usd',0))
        if charged+holds+usd>35:raise ValueError('Aggregate35USD cap would be exceeded')
        if any(r.get('status') in ('reserved','starting','running','unknown') for r in data.get('reservations',[])):raise ValueError('Another reservation/job is live or unknown')
        if len(data.get('invocations',[]))>=3:raise ValueError('Lifetime three-start cap reached')
        data['reservations'].append({'id':run_id,'reserved_usd':usd,'status':'reserved','at_utc':now()})
        data['new_authorization_at_utc']=now();data['cloud_stop_utc']=datetime.datetime.fromtimestamp(time.time()+2700,datetime.timezone.utc).isoformat()
        atomic(LEDGER,data)

def update(run_id,status,invocation=None,settle=False):
    with lock():
        data=json.loads(LEDGER.read_text(encoding='utf8'));entry=next(r for r in data['reservations'] if r['id']==run_id);entry['status']=status;entry['updated_at_utc']=now()
        if invocation:
            existing=next((v for v in data['invocations'] if v.get('id')==run_id),None)
            if existing is None:data['invocations'].append(invocation)
            else:existing.update(invocation)
            data['actual_task_cost_verified']=False
        if settle:
            # Conservatively charge the entire reservation, not an invented invoice.
            data['accounted_upper_cost_usd']=float(data.get('accounted_upper_cost_usd',0))+entry['reserved_usd'];entry['status']='settled';entry['provider_invoice_verified']=False
        atomic(LEDGER,data)

def identity():
    import asyncio
    from modal.client import _Client
    from modal_proto import api_pb2
    async def inner():
        client=await asyncio.wait_for(_Client.from_env(),15);r=await asyncio.wait_for(client.stub.TokenInfoGet(api_pb2.TokenInfoGetRequest()),15)
        workspace=r.workspace_name
        if workspace!='businessforever2338':raise ValueError('Wrong Modal workspace')
        return {'workspace_name':workspace,'workspace_id':r.workspace_id}
    return asyncio.run(inner())

def compress(path):
    result=path.with_suffix(path.suffix+'.gz')
    with path.open('rb') as src,gzip.open(result,'wb',compresslevel=1) as dst:
        import shutil
        shutil.copyfileobj(src,dst)
    return result

def main():
    p=argparse.ArgumentParser();p.add_argument('--packet',required=True);p.add_argument('--encoder',required=True);p.add_argument('--output',required=True);p.add_argument('--seconds',type=int,default=1800);p.add_argument('--epochs',type=int,default=2);p.add_argument('--batch-size',type=int,default=128);a=p.parse_args()
    if not 1<=a.seconds<=1800:raise ValueError('Initial experiment compute cap1800s')
    os.environ['MODAL_PROFILE']='businessforever2338'
    for k in ['MODAL_TOKEN_ID','MODAL_TOKEN_SECRET']:os.environ.pop(k,None)
    packet=Path(a.packet).resolve();encoder=Path(a.encoder).resolve();out=Path(a.output).resolve();out.mkdir(parents=True,exist_ok=True)
    account=identity()
    head=json.loads((ROOT/'integrations/learned-dialogue/day2_pretrained_head.json').read_text(encoding='utf8'))
    for name,record in head['encoder']['files'].items():
        if hashlib.sha256((encoder/name).read_bytes()).hexdigest()!=record['sha256']:raise ValueError('Base encoder pin mismatch '+name)
    from minilm_ft_core import read_rows,targets,observed_text
    train=read_rows(packet/'train.jsonl');cal=read_rows(packet/'cal.jsonl')
    if set(r['group'] for r in train)&set(r['group'] for r in cal):raise ValueError('Group split overlaps')
    for part,expected in [(train,'TRAIN'),(cal,'CAL')]:
        for r in part:
            if r.get('split')!=expected:raise ValueError('Wrong upload split '+expected)
            targets(r);observed_text(r)
    for path in [packet/'train.jsonl',packet/'cal.jsonl']:
        raw=path.read_bytes()
        if len(raw)>200_000_000:raise ValueError('Payload too large')
        if b'fak_' in raw or b'MODAL_TOKEN_SECRET' in raw:raise ValueError('Credential-like payload')
    compressed=[compress(packet/name) for name in ['train.jsonl','cal.jsonl']]
    run_id='minilm-ft-'+uuid.uuid4().hex[:12];reserve(run_id,10)
    receipt={'id':run_id,'started_at_utc':now(),'account':account,'reserved_upper_USD':10,'hard_aggregate_USD':35,'compute_seconds':a.seconds,'wall_seconds':2700,'source_sha256':{name:hashlib.sha256((Path(__file__).parent/name).read_bytes()).hexdigest() for name in ['minilm_ft_core.py','minilm_ft_modal.py','minilm_ft_launch.py']},'payload_sha256':{name:hashlib.sha256((packet/name).read_bytes()).hexdigest() for name in ['train.jsonl','cal.jsonl']},'holdout_uploaded':False,'status':'starting'}
    atomic(out/'launch.json',receipt)
    # Independent process kills the exact ephemeral app at wall deadline even if parent stalls.
    from minilm_ft_modal import create_app
    app_name='freya-'+run_id
    app,fn=create_app(compressed[0],compressed[1],encoder,a.seconds,app_name);call=None;started=time.monotonic()
    guard=Path(__file__).with_name('minilm_ft_guard.py')
    guardian=subprocess.Popen([sys.executable,str(guard),str(out/'launch.json'),str(out/'guardian.json'),'2700',app_name],env=os.environ.copy(),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=(subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0))
    receipt['guardian_pid']=guardian.pid;receipt['app_name']=app_name;atomic(out/'launch.json',receipt)
    update(run_id,'starting',{'id':run_id,'app_name':app_name,'started_at_utc':now(),'status':'starting'})
    try:
        with app.run():
            receipt['app_id']=app.app_id;atomic(out/'launch.json',receipt)
            call=fn.spawn(a.seconds,a.epochs,a.batch_size);receipt['call_id']=call.object_id;receipt['status']='running';atomic(out/'launch.json',receipt);update(run_id,'running',{'id':run_id,'app_id':app.app_id,'call_id':call.object_id,'started_at_utc':now()})
            while True:
                if time.monotonic()-started>2600:raise TimeoutError('Parent wall cutoff')
                try:result=call.get(timeout=10);break
                except TimeoutError:print('training job active (bounded)',flush=True)
            blob=result.pop('archive');(out/'result.zip').write_bytes(blob)
            with zipfile.ZipFile(io.BytesIO(blob)) as archive:
                for name in archive.namelist():
                    if '..' in Path(name).parts or Path(name).is_absolute():raise ValueError('Unsafe archive path')
                archive.extractall(out/'models')
            receipt['reports']=result['reports'];receipt['status']='completed';receipt['completed_at_utc']=now();atomic(out/'launch.json',receipt)
        receipt['app_context_closed']=True;atomic(out/'launch.json',receipt);update(run_id,'finished',settle=True)
    except BaseException as exc:
        receipt['status']='failed';receipt['error_class']=type(exc).__name__
        if call:
            try:call.cancel(terminate_containers=True);receipt['call_cancel_requested']=True
            except Exception:receipt['call_cancel_requested']=False
        atomic(out/'launch.json',receipt);update(run_id,'unknown');raise
    finally:
        # Guardian remains armed until a provider state check establishes shutdown.
        print(json.dumps({'status':receipt['status'],'app_id':receipt.get('app_id'),'reserved_upper_USD':10}),flush=True)

if __name__=='__main__':main()
