"""Local, same-origin console for real builder runs. Credentials stay in server memory."""
import argparse,datetime,fcntl,getpass,json,os,pathlib,re,secrets,subprocess,sys,threading,urllib.parse
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler

ROOT=pathlib.Path(__file__).resolve().parent
KIT=ROOT.parent/'build-the-builder 2'
PROCESS=None
TOKEN=secrets.token_urlsafe(32)
LOCK=threading.Lock()

def active_run():
    for lock in [ROOT/'.state/builder.lock',*(ROOT/'.state/slots').glob('*.lock')]:
        if not lock.exists():continue
        with lock.open('a') as handle:
            try:fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:return True
            fcntl.flock(handle,fcntl.LOCK_UN)
    return bool(PROCESS and PROCESS.poll() is None)

def latest(selected=None):
    pointer=ROOT/'.state/latest.json'
    if not pointer.exists():return None,None
    run_id=selected or json.loads(pointer.read_text()).get('run_id','')
    if not re.fullmatch(r'[A-Za-z0-9_-]+',run_id):return None,None
    directory=(ROOT/'runs'/run_id).resolve()
    if not directory.is_relative_to((ROOT/'runs').resolve()):return None,None
    status=directory/'status.json'
    return directory,json.loads(status.read_text()) if status.exists() else None

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def send(self,value,status=200,content_type='application/json; charset=utf-8'):
        body=json.dumps(value,ensure_ascii=False).encode() if isinstance(value,(dict,list)) else value
        self.send_response(status);self.send_header('Content-Type',content_type);self.send_header('Content-Length',len(body));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(body)
    def host_valid(self):return self.headers.get('Host')==f'127.0.0.1:{self.server.server_port}'
    def do_GET(self):
        if not self.host_valid():self.send({'error':'Invalid Host'},403);return
        try:
            request=urllib.parse.urlsplit(self.path);selected=urllib.parse.parse_qs(request.query).get('run',[None])[0]
            path=request.path
            if path=='/api/status':
                directory,status=latest(selected)
                if status:
                    status['elapsed_s']=round((datetime.datetime.fromisoformat(status.get('ended') or datetime.datetime.now(datetime.timezone.utc).isoformat())-datetime.datetime.fromisoformat(status['started'])).total_seconds())
                response={'status':status,'active':active_run(),'authenticated':bool(os.environ.get('FREYA_API_KEY')),'csrf':TOKEN,'presets':{key:(KIT/'briefs'/f'brief-{key.lower()}.md').read_text() for key in ('A','B')},'schema':json.loads((KIT/'tools/openapi.json').read_text())}
                response['runs']=[]
                for file in sorted((ROOT/'runs').glob('*/status.json'),reverse=True):
                    item=json.loads(file.read_text());response['runs'].append({key:item.get(key) for key in ('id','slot','phase','test_brief','latest_score')})
                if directory:
                    response['events']=[json.loads(line) for line in (directory/'trace.jsonl').read_text().splitlines()][-35:]
                    export=directory/status['artifacts']['workflow'] if status and status.get('artifacts',{}).get('workflow') else None
                    response['workflow']=json.loads(export.read_text())['workflow'] if export and export.exists() else json.loads((directory/'work/workflow.json').read_text()) if (directory/'work/workflow.json').exists() else None
                    response['workflow_source']='Freya platform export' if export and export.exists() else 'Builder output; not yet published'
                    response['reports']=[json.loads(p.read_text()) for p in sorted(directory.glob('results-*.json'))]
                    response['failures']=json.loads((directory/'work/failed-calls.json').read_text()) if (directory/'work/failed-calls.json').exists() else []
                self.send(response);return
            if path.startswith('/artifact/'):
                directory,_=latest(selected)
                if not directory:self.send({'error':'No run'},404);return
                filename=path.removeprefix('/artifact/')
                allowed={'trace.jsonl','work/policy.json','work/coverage.json'}|{p.name for p in directory.glob('*.workflow.json')}|{p.name for p in directory.glob('results-*.json')}
                if filename not in allowed:self.send({'error':'Unknown artifact'},404);return
                self.send((directory/filename).read_bytes(),content_type='application/json; charset=utf-8');return
            files={'/':('index.html','text/html; charset=utf-8'),'/app.js':('app.js','text/javascript; charset=utf-8'),'/style.css':('style.css','text/css; charset=utf-8')}
            if path not in files:self.send({'error':'Not found'},404);return
            name,mime=files[path];self.send((ROOT/'web'/name).read_bytes(),content_type=mime)
        except (BrokenPipeError,ConnectionResetError):pass
        except Exception:self.send({'error':'Run data is updating; refresh shortly.'},503)
    def do_POST(self):
        global PROCESS
        if not self.host_valid() or self.headers.get('Origin')!=f'http://127.0.0.1:{self.server.server_port}' or self.headers.get('X-Builder-CSRF')!=TOKEN:
            self.send({'error':'Same-origin console requests only.'},403);return
        if self.path!='/api/build':self.send({'error':'Not found'},404);return
        length=int(self.headers.get('Content-Length','0'))
        if length<1 or length>2_000_000:self.send({'error':'Input size must be between 1 byte and 2 MB.'},400);return
        try:
            data=json.loads(self.rfile.read(length))
            with LOCK:
                _,status=latest()
                if active_run():
                    self.send({'error':'Bir builder çalıştırması sürüyor. Tamamlanmasını bekleyin.'},409);return
                brief=data.get('brief','').strip()
                if not brief:self.send({'error':'Banka brief’i gerekli.'},400);return
                schema=data.get('schema')
                if not isinstance(schema,dict) or not schema.get('paths') or not schema.get('servers'):self.send({'error':'Geçerli bir OpenAPI şeması gerekli.'},400);return
                inputs=ROOT/'.state/console-inputs';inputs.mkdir(parents=True,exist_ok=True)
                (inputs/'brief.md').write_text(brief);(inputs/'openapi.json').write_text(json.dumps(schema,ensure_ascii=False))
                command=[sys.executable,str(ROOT/'builder.py'),str(inputs/'brief.md'),'--tool-api',str(inputs/'openapi.json'),'--slot','competition-console']
                if not data.get('official_tests'):command+=['--skip-tests']
                # The builder writes its own traces; avoid duplicating sensitive process output.
                PROCESS=subprocess.Popen(command,cwd=ROOT,env=dict(os.environ),stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
                self.send({'started':True,'pid':PROCESS.pid},202)
        except Exception:self.send({'error':'İstek okunamadı. Brief ve JSON şemasını kontrol edin.'},400)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=4180);args=parser.parse_args()
    if not os.environ.get('FREYA_API_KEY'):os.environ['FREYA_API_KEY']=getpass.getpass('Freya API key (hidden, session memory only): ')
    if pathlib.Path('/etc/ssl/cert.pem').exists():os.environ.setdefault('SSL_CERT_FILE','/etc/ssl/cert.pem')
    server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
    print(f'Competition console: http://127.0.0.1:{args.port}',flush=True);server.serve_forever()

if __name__=='__main__':main()
