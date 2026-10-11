"""Autonomous evidence -> Freya -> official tests -> repair -> export. Standard library only."""
import argparse, codecs, contextlib, datetime, getpass, hashlib, json, os, pathlib, queue, re, shutil, signal, subprocess, sys, threading, time, tomllib, uuid
from validation import validate,validate_coverage
from transcripts import compact_messages
from semantic_assist import PROMPT_NOTICE, child_env, python_executable, validate_result
from dialogue_assist import NOTICE as DIALOGUE_NOTICE, PINS as DIALOGUE_PINS, validate_result as validate_dialogue_result
from finetuned_assist import NOTICE as FINETUNED_NOTICE, copy_runtime as copy_finetuned_runtime, prepare_request as finetuned_request, validate_result as validate_finetuned_result, child_environment as finetuned_environment, read_json as read_finetuned_json
from finetuned_context_audit import NOTICE as CONTEXT_NOTICE, validate_audit
import live_layer

ROOT=pathlib.Path(__file__).resolve().parent
KIT=ROOT.parent/'build-the-builder 2'

def model_permissions(environment):
    """Inherit a built-in parent permission profile; never silently widen it."""
    profile=environment.get('CODEX_PERMISSION_PROFILE',':workspace')
    if profile not in {':read-only',':workspace',':danger-full-access'}:
        raise ValueError('Unsupported inherited model permission profile')
    return profile

@contextlib.contextmanager
def slot_lock(path):
    """Nonblocking OS lock, including Windows; release on exception/process exit."""
    path=pathlib.Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('a+b') as handle:
        if os.name=='nt':
            import msvcrt
            if handle.seek(0,os.SEEK_END)==0:handle.write(b'\0');handle.flush()
            handle.seek(0)
            try:msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
            except OSError:raise BlockingIOError('Workflow slot already locked') from None
            unlock=lambda: (handle.seek(0),msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1))
        else:
            import fcntl
            fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
            unlock=lambda: fcntl.flock(handle,fcntl.LOCK_UN)
        try:yield handle
        finally:unlock()

def stamp(): return datetime.datetime.now(datetime.timezone.utc).isoformat()
_WRITE_LOCKS={}
_WRITE_LOCKS_GUARD=threading.Lock()
def write_json(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    # Windows may deny concurrent replacements even when temp names are unique.
    with _WRITE_LOCKS_GUARD:lock=_WRITE_LOCKS.setdefault(str(path.absolute()),threading.Lock())
    with lock:
        temp=path.with_name(f'{path.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp')
        try:
            temp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
            for attempt in range(8):
                try:temp.replace(path);break
                except PermissionError:
                    if attempt==7:raise
                    time.sleep(min(0.05,0.005*2**attempt))
        finally:
            with contextlib.suppress(OSError):temp.unlink(missing_ok=True)

def infer_practice_group(brief_paths):
    canonical=lambda value:re.sub(r'\s+',' ',value).strip()
    evidence=[canonical(pathlib.Path(path).read_text()) for path in brief_paths]
    a=canonical((KIT/'briefs/brief-a.md').read_text());b=canonical((KIT/'briefs/brief-b.md').read_text())
    if evidence==[a]:return 'A'
    if evidence==[a,b] or evidence==[a+' '+b] or evidence==[b]:return 'B'
    return None

def validate_case_scope(brief_paths,case_path,skip_tests):
    case_path=pathlib.Path(case_path)
    public_path=KIT/'public-test-set.json'
    is_public=case_path.resolve()==public_path.resolve()
    if not is_public and case_path.is_file():
        try:is_public=json.loads(case_path.read_text())==json.loads(public_path.read_text())
        except (OSError,ValueError):pass
    if not skip_tests and is_public and infer_practice_group(brief_paths) is None:
        raise ValueError('Unseen briefs require their own --cases test set or --skip-tests; public A/B customers do not evaluate a new specification')

def validate_practice_seed(work,seed,sources):
    known={path.read_bytes() for path in (KIT/'briefs').glob('brief-*.md')}
    if any((work/entry['path']).read_bytes() not in known for entry in sources):
        raise ValueError('Practice repair is only allowed for the supplied public practice briefs; unseen builds must start fresh')
    current={pathlib.Path(entry['path']).name:(work/entry['path']).read_bytes() for entry in sources}
    previous={path.name:path.read_bytes() for path in (seed/'work/inputs').glob('[0-9][0-9]-*')}
    if current!=previous:raise ValueError('Practice repair evidence must match the earlier run exactly, including the complete document set and order')
    if (work/'inputs/openapi.json').read_bytes()!=(seed/'work/inputs/openapi.json').read_bytes():
        raise ValueError('Practice repair API must be byte-identical')

def practice_seed_stopped_or_untested(prior):
    return prior.get('phase') in {'failed','needs_attention'} or (prior.get('phase')=='completed' and prior.get('evaluation')=='not_evaluated')

class Run:
    def __init__(self,args):
        self.args=args;self.start=time.monotonic();self.deadline=self.start+args.minutes*60;self.wall_deadline=time.time()+args.minutes*60
        if args.resume_run:
            if not re.fullmatch(r'[A-Za-z0-9_-]+',args.resume_run):raise ValueError('Invalid resume run ID')
            self.id=args.resume_run;self.path=ROOT/'runs'/self.id
            self.status=json.loads((self.path/'status.json').read_text())
            if self.status['phase'] not in {'failed','needs_attention'}:raise ValueError('Only a stopped run may resume')
            recorded_limit=self.status.get('maximum_minutes')
            if recorded_limit is None:
                records=[json.loads(line) for line in (self.path/'trace.jsonl').read_text().splitlines()]
                recorded_limit=next(record['maximum_minutes'] for record in records if record['kind']=='run_start')
            args.minutes=min(args.minutes,recorded_limit)
            elapsed=(datetime.datetime.now(datetime.timezone.utc)-datetime.datetime.fromisoformat(self.status['started'])).total_seconds()
            self.start=time.monotonic()-elapsed;self.deadline=self.start+args.minutes*60
            self.wall_deadline=datetime.datetime.fromisoformat(self.status['started']).timestamp()+args.minutes*60
            if self.remaining()<120:raise ValueError('Original 30-minute budget has insufficient time left')
            if self.status['slot']!=args.slot or self.status['model']!=args.model:raise ValueError('Resume must preserve the workflow slot and model')
            self.status.pop('ended',None);self.status.pop('error',None)
        else:
            self.id=datetime.datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:6]
            self.path=ROOT/'runs'/self.id;self.path.mkdir(parents=True)
            self.status={'id':self.id,'started':stamp(),'phase':'starting','slot':args.slot,'model':args.model,'round':0,'artifacts':{},'tests':[],'maximum_minutes':args.minutes}
        self.secrets=[os.environ.get('FREYA_API_KEY',''),os.environ.get('FREYA_BANK_TEAM_KEY','')]
        self.trace=self.path/'trace.jsonl';self.work=self.path/'work';self.work.mkdir(exist_ok=bool(args.resume_run))
        self.feedback=[]
        self.test_brief=getattr(args,'brief',None) or infer_practice_group(args.briefs)
        self.status['test_brief']=self.test_brief
        write_json(ROOT/'.state/latest.json',{'run_id':self.id})
    def clean(self,value):
        text=json.dumps(value,ensure_ascii=False,default=str)
        for secret in self.secrets:
            if secret:text=text.replace(secret,'[REDACTED]')
        return json.loads(re.sub(r'fak_[A-Za-z0-9_-]+','[REDACTED]',text))
    def event(self,kind,**data):
        record=self.clean({'at':stamp(),'kind':kind,**data})
        with self.trace.open('a') as out:out.write(json.dumps(record,ensure_ascii=False)+'\n')
    def phase(self,name,**data):
        self.status.update(phase=name,**data,updated=stamp(),elapsed_s=round(self.elapsed()))
        write_json(self.path/'status.json',self.clean(self.status));self.event('phase',phase=name,**data)
        print(f'[{stamp()}] {name}',flush=True)
    def remaining(self): return max(0,min(self.deadline-time.monotonic(),self.wall_deadline-time.time()))
    def elapsed(self):return max(time.monotonic()-self.start,time.time()-datetime.datetime.fromisoformat(self.status['started']).timestamp())
    def prepare(self):
        source=self.path/('builder-source-resume' if self.args.resume_run else 'builder-source');source.mkdir(exist_ok=True)
        source_names=('builder.py','validation.py','bounded_freya.py','simulate.py','transcripts.py','semantic_assist.py','dialogue_assist.py','finetuned_assist.py','finetuned_context_audit.py','live_layer.py')
        for name in source_names:
            shutil.copyfile(ROOT/name,source/name)
        self.event('builder_source',sha256={name:hashlib.sha256((source/name).read_bytes()).hexdigest() for name in source_names})
        self.builder_source=source
        inputs=self.work/'inputs';inputs.mkdir(exist_ok=bool(self.args.resume_run))
        self.sources=[]
        for i,source in enumerate(self.args.briefs):
            source=pathlib.Path(source).resolve();target=inputs/f'{i+1:02d}-{source.name}'
            if self.args.resume_run and (not target.exists() or target.read_bytes()!=source.read_bytes()):raise ValueError('Resume evidence must be byte-identical')
            if not self.args.resume_run:shutil.copyfile(source,target)
            self.sources.append({'path':str(target.relative_to(self.work)),'source':str(source),'sha256':hashlib.sha256(source.read_bytes()).hexdigest()})
        if self.args.resume_run:
            if pathlib.Path(self.args.tool_api).read_bytes()!=(inputs/'openapi.json').read_bytes():raise ValueError('Resume OpenAPI must be byte-identical')
        else:
            shutil.copyfile(self.args.tool_api,inputs/'openapi.json')
            for name in ('workflow-format.md','tools-and-code.md'):shutil.copyfile(KIT/'docs'/name,inputs/name)
            shutil.copyfile(KIT/'examples/base-agent.json',inputs/'base-agent.json')
            shutil.copyfile(ROOT/'skills/build-phone-agent.md',self.work/'BUILD_INSTRUCTIONS.md')
        if getattr(self.args,'practice_repair',None):
            seed_id=self.args.practice_repair
            if not re.fullmatch(r'[A-Za-z0-9_-]+',seed_id):raise ValueError('Invalid practice run ID')
            seed=ROOT/'runs'/seed_id
            prior=json.loads((seed/'status.json').read_text())
            if not practice_seed_stopped_or_untested(prior):raise ValueError('Practice repair requires a stopped or explicitly untested public practice run')
            validate_practice_seed(self.work,seed,self.sources)
            for name in ('workflow.json','policy.json','coverage.json'):
                shutil.copyfile(seed/'work'/name,self.work/name)
            feedback_files=[]
            for path in list((seed/'work').glob('early-*.json'))+list((seed/'work').glob('failed-calls.json'))+list(seed.glob('results-*.json')):
                target=self.work/('previous-'+path.name)
                if path.name=='failed-calls.json':
                    prior_calls=json.loads(path.read_text())
                    for entry in prior_calls:
                        entry['messages']=compact_messages(entry.get('messages',[]))
                    write_json(target,self.clean(prior_calls))
                else:shutil.copyfile(path,target)
                feedback_files.append(target.name)
            self.feedback=[{'practice_repair_from':seed_id,'previous_status':prior,'read_files':feedback_files,'instruction':'Repair this same public practice candidate using actual call events and score failures. Read all feedback. Extractor output must provide every field consumed by code, with raw-speech fallback. If the dialogue ignores dynamic instructions, use the documented tts on_enter with a computed literal customer sentence for each state, not imperative meta-instructions. No invented bank success or debt before verified. Preserve all brief rules.'}]
            self.event('practice_seed',source_run=seed_id,artifact_sha256={name:hashlib.sha256((self.work/name).read_bytes()).hexdigest() for name in ('workflow.json','policy.json','coverage.json')},feedback_files=feedback_files)
        self.api=json.loads((inputs/'openapi.json').read_text())
        self.api_sha256=hashlib.sha256((inputs/'openapi.json').read_bytes()).hexdigest()
        schema={'type':'object','properties':{key:{'type':'string'} for key in ('workflow_file','policy_file','coverage_file','summary')},'required':['workflow_file','policy_file','coverage_file','summary'],'additionalProperties':False}
        write_json(self.path/'response.schema.json',schema)
        self.event('inputs',briefs=self.sources,tool_api_sha256=hashlib.sha256((inputs/'openapi.json').read_bytes()).hexdigest())
        self.live_layer_contract=None
        live_mode=getattr(self.args,'live_layer','off')
        if live_mode!='off':
            self.live_layer_contract=live_layer.prepare(self.work,ROOT/'recipient_assertion.py',
                getattr(self.args,'live_student',None) if live_mode=='v2-student' else None,
                getattr(self.args,'live_student_sha256',None),getattr(self.args,'live_student_use','shadow'))
            self.event('live_layer_input',mode=live_mode,component_sha256=self.live_layer_contract['files']['live-layer-code.py'],
                component_bytes=self.live_layer_contract['component_bytes'],bank_authority=False,hosted_runtime_verified=False)
        self.prepare_semantic_assist()
    def prepare_semantic_assist(self):
        mode=getattr(self.args,'semantic_assist','auto')
        self.semantic_ready=False
        # A resumed classic build must never consume a stale enhanced index.
        for name in ('semantic-evidence.json','semantic-evidence.txt'):
            (self.work/name).unlink(missing_ok=True)
        if mode=='off':
            self.status['semantic_assist']={'mode':'off','status':'disabled'}
            self.event('semantic_assist',**self.status['semantic_assist']);return
        seconds=min(60,max(0,self.remaining()-120))
        try:
            if seconds<5:raise TimeoutError('Insufficient navigation budget')
            repo=ROOT.parent
            runtime=repo/'integrations/learned-dialogue/day2_pretrained_runtime.py'
            snapshot=self.builder_source/'day2_pretrained_runtime.py'
            shutil.copyfile(runtime,snapshot)
            runtime_sha=hashlib.sha256(snapshot.read_bytes()).hexdigest()
            request={'repo':str(repo),'work':str(self.work),'sources':self.sources,
                     'head':str(repo/'integrations/learned-dialogue/day2_pretrained_head.json'),
                     'runtime':str(snapshot),'runtime_sha256':runtime_sha,'seconds':seconds}
            write_json(self.path/'semantic-request.json',request)
            command=[python_executable(getattr(self.args,'semantic_python',None)),'-I','-B',
                     str(self.builder_source/'semantic_assist.py'),'--request',str(self.path/'semantic-request.json')]
            self.child(command,timeout=seconds,env=child_env(os.environ),log_name='semantic-assist.log',purpose='Local pinned MiniLM evidence navigation')
            result=json.loads((self.work/'semantic-evidence.json').read_text(encoding='utf-8'))
            head=json.loads((repo/'integrations/learned-dialogue/day2_pretrained_head.json').read_text(encoding='utf-8'))
            validate_result(result,self.sources,work=self.work,runtime_sha256=runtime_sha,encoder_files=head['encoder']['files'])
            self.semantic_hashes={name:hashlib.sha256((self.work/name).read_bytes()).hexdigest() for name in ('semantic-evidence.json','semantic-evidence.txt')}
            self.semantic_ready=True
            self.status['semantic_assist']={'mode':mode,'status':'ready','bank_authority':False,
                                           'elapsed_seconds':result['elapsed_seconds'],'chunks':len(result['chunks']),
                                           'head_sha256':result['head_sha256'],'runtime_sha256':runtime_sha,
                                           'artifact_sha256':self.semantic_hashes}
        except (OSError,ValueError,KeyError,RuntimeError,TimeoutError) as error:
            for name in ('semantic-evidence.json','semantic-evidence.txt'):(self.work/name).unlink(missing_ok=True)
            self.status['semantic_assist']={'mode':mode,'status':'unavailable','error_type':type(error).__name__}
            self.event('semantic_assist',**self.status['semantic_assist'])
            if mode=='required':raise RuntimeError('Required local MiniLM navigation is unavailable') from None
            return
        self.event('semantic_assist',**self.status['semantic_assist'])
    def prepare_dialogue_assist(self):
        self.dialogue_ready=False
        (self.work/'dialogue-evidence.json').unlink(missing_ok=True)
        mode=getattr(self.args,'dialogue_assist','auto')
        if mode=='off' or getattr(self.args,'semantic_assist','auto')=='off':return
        calls=self.work/'failed-calls.json'
        if not calls.exists():calls=self.work/'previous-failed-calls.json'
        if not calls.exists():return
        try:
            if self.remaining()<125:raise TimeoutError('Insufficient diagnostic budget')
            bundle=self.builder_source/'source-act-model';bundle.mkdir(exist_ok=True)
            for name,digest in DIALOGUE_PINS.items():
                original=ROOT.parent/'integrations/learned-dialogue'/name
                if hashlib.sha256(original.read_bytes()).hexdigest()!=digest:raise ValueError('Source-act model changed')
                shutil.copyfile(original,bundle/name)
            request={'calls':str(calls),'calls_sha256':hashlib.sha256(calls.read_bytes()).hexdigest(),
                     'bundle':str(bundle),'output':str(self.work/'dialogue-evidence.json')}
            write_json(self.path/'dialogue-request.json',request)
            self.child([sys.executable,'-I','-B',str(self.builder_source/'dialogue_assist.py'),'--request',str(self.path/'dialogue-request.json')],
                       timeout=5,env=child_env(os.environ),log_name='dialogue-assist.log',purpose='Observed source-act hypotheses for repair')
            result=json.loads((self.work/'dialogue-evidence.json').read_text(encoding='utf-8'))
            validate_dialogue_result(result,request)
            self.dialogue_hash=hashlib.sha256((self.work/'dialogue-evidence.json').read_bytes()).hexdigest()
            self.dialogue_ready=True
            self.event('dialogue_assist',status='ready',turns=len(result['rows']),model_pins=DIALOGUE_PINS,
                       source_sha256=request['calls_sha256'],artifact_sha256=self.dialogue_hash,bank_authority=False)
        except (OSError,ValueError,KeyError,RuntimeError,TimeoutError) as error:
            (self.work/'dialogue-evidence.json').unlink(missing_ok=True)
            self.event('dialogue_assist',status='unavailable',error_type=type(error).__name__)
            if mode=='required':raise RuntimeError('Required dialogue diagnostics unavailable') from None
    def child(self,command,*,timeout,env=None,stdin=None,log_name='command.jsonl',purpose='command'):
        end=time.monotonic()+min(timeout,self.remaining())
        wall_end=time.time()+min(timeout,self.remaining())
        self.event('command_start',command=command,purpose=purpose,timeout_s=round(end-time.monotonic()))
        proc=subprocess.Popen(command,cwd=self.work,env=env,stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,start_new_session=True)
        chunks=queue.Queue()
        def read_output():
            try:
                while True:
                    chunk=proc.stdout.read1(65536)
                    if not chunk:break
                    chunks.put(chunk)
            finally:chunks.put(None)
        reader=threading.Thread(target=read_output,daemon=True);reader.start()
        def write_input():
            try:proc.stdin.write(stdin.encode('utf-8'));proc.stdin.flush()
            except (BrokenPipeError,OSError,ValueError):pass
            finally:
                try:proc.stdin.close()
                except (OSError,ValueError):pass
        if stdin is not None:threading.Thread(target=write_input,daemon=True).start()
        def stop_process():
            if proc.poll() is not None:return
            if os.name=='nt':
                # Kill the owned CLI process tree: terminating a .cmd/node parent
                # alone leaves its children holding the output pipe and workdir.
                try:subprocess.run(['taskkill','/PID',str(proc.pid),'/T','/F'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=1,creationflags=subprocess.CREATE_NO_WINDOW)
                except (OSError,subprocess.TimeoutExpired):proc.kill()
            else:
                try:os.killpg(proc.pid,signal.SIGTERM)
                except ProcessLookupError:pass
            try:proc.wait(timeout=.5)
            except subprocess.TimeoutExpired:
                if os.name=='nt':proc.kill()
                else:
                    try:os.killpg(proc.pid,signal.SIGKILL)
                    except ProcessLookupError:pass
                proc.wait(timeout=1)
        lines=[];timed_out=False;pending='';decoder=codecs.getincrementaldecoder('utf-8')()
        try:
            with (self.path/log_name).open('a',encoding='utf-8') as log:
                eof=False
                while not eof or proc.poll() is None:
                    left=min(end-time.monotonic(),wall_end-time.time(),self.remaining())
                    if left<=0:
                        timed_out=True;stop_process();break
                    try:chunk=chunks.get(timeout=min(.1,left))
                    except queue.Empty:continue
                    if chunk is None:eof=True
                    else:pending+=decoder.decode(chunk)
                    while '\n' in pending or (eof and pending):
                        line,separator,tail=pending.partition('\n');pending=tail if separator else ''
                        safe=self.clean({'output':line.rstrip()})['output'];lines.append(safe);log.write(safe+'\n');log.flush()
                if pending:
                    safe=self.clean({'output':pending})['output'];lines.append(safe);log.write(safe+'\n');log.flush()
                if proc.poll() is None:proc.wait(timeout=max(.01,min(1,end-time.monotonic(),wall_end-time.time())))
        finally:
            stop_process();reader.join(timeout=1);proc.stdout.close()
        self.event('command_end',purpose=purpose,returncode=proc.returncode,timed_out=timed_out,log=log_name)
        if timed_out:raise TimeoutError(f'{purpose} exceeded the run time budget')
        if proc.returncode:raise RuntimeError(f'{purpose} failed (exit {proc.returncode}): '+'\n'.join(lines[-8:])[:3000])
        return lines
    def prepare_finetuned_assist(self):
        self.finetuned_ready=False
        self.finetuned_context_ready=False;self.finetuned_context_status=None
        output=self.work/'finetuned-evidence.json';output.unlink(missing_ok=True)
        audit_output=self.work/'finetuned-context-evidence.json';audit_output.unlink(missing_ok=True)
        mode=getattr(self.args,'finetuned_assist','auto')
        if mode=='off' or getattr(self.args,'semantic_assist','auto')=='off':return
        calls=self.work/'failed-calls.json'
        if not calls.exists():calls=self.work/'previous-failed-calls.json'
        if not calls.exists():return
        try:
            repo=ROOT.parent;base=repo/'integrations/learned-dialogue'
            version=getattr(self.args,'finetuned_version','auto')
            if version=='auto':
                newest=base/'minilm_ft_v2/release.json'
                version='v2' if newest.exists() and json.loads(newest.read_text(encoding='utf8')).get('default_enabled') is True else 'v1'
            if version=='v2':self.finetuned_context_status='UNAVAILABLE'
            if self.remaining()<125:raise TimeoutError('Insufficient fine-tuned diagnostic budget')
            release=base/f'minilm_ft_{version}/release.json'
            default=release.parent/'model'
            model=pathlib.Path(getattr(self.args,'finetuned_model',None) or default).resolve()
            # The release pin is created only after actual training/evaluation/export checks.
            if not release.exists():
                if mode=='required':raise ValueError('Fine-tuned release unavailable')
                if version=='v2':self.event('finetuned_context_audit',status='UNAVAILABLE',reason='Fine-tuned release unavailable',bank_authority=False)
                return
            pin=json.loads(release.read_text(encoding='utf8'))
            runtime_source=base/'minilm_ft_v2/runtime' if version=='v2' else base
            runtime=self.builder_source/'finetuned-runtime'
            if runtime.exists():
                for name,digest in pin['runtime_sha256'].items():
                    if hashlib.sha256((runtime/name).read_bytes()).hexdigest()!=digest:raise ValueError('Fine-tuned runtime changed')
            else:copy_finetuned_runtime(runtime_source,runtime,pin['runtime_sha256'])
            seconds=min(60,self.remaining()-120)
            request=finetuned_request(calls=calls,model_directory=model,manifest_sha256=pin['manifest_sha256'],runtime_directory=runtime,runtime_sha256=pin['runtime_sha256'],seconds=seconds,mode=mode)
            if request is None:
                if version=='v2':self.event('finetuned_context_audit',status='UNAVAILABLE',reason='Fine-tuned request unavailable',bank_authority=False)
                return
            write_json(self.path/'finetuned-request.json',request)
            script='finetuned_context_audit.py' if version=='v2' else 'finetuned_assist.py'
            command=[python_executable(getattr(self.args,'semantic_python',None)),'-I','-B',str(self.builder_source/script),'--request',str(self.path/'finetuned-request.json'),'--output',str(output)]
            if version=='v2':command+=['--audit-output',str(audit_output)]
            self.child(command,timeout=seconds,env=finetuned_environment(os.environ),log_name='finetuned-assist.log',purpose='Actual fine-tuned MiniLM observed semantic proposals')
            result=read_finetuned_json(output) if version=='v2' else json.loads(output.read_text(encoding='utf8'))
            validate_finetuned_result(result,request)
            self.finetuned_hash=hashlib.sha256(output.read_bytes()).hexdigest();self.finetuned_ready=True
            self.event('finetuned_assist',status='ready',version=version,turns=len(result['rows']),manifest_sha256=pin['manifest_sha256'],bank_authority=False,artifact_sha256=self.finetuned_hash)
            if version=='v2':
                # FULL is strictly validated before any audit can become prompt evidence.
                try:
                    audit=read_finetuned_json(audit_output);validate_audit(audit,request,result)
                    self.finetuned_context_hash=hashlib.sha256(audit_output.read_bytes()).hexdigest()
                    self.finetuned_context_status=audit['status'];self.finetuned_context_ready=True
                    self.event('finetuned_context_audit',status=audit['status'],reason=audit['reason'],turns=len(audit['rows']),bank_authority=False,artifact_sha256=self.finetuned_context_hash)
                except (OSError,ValueError,KeyError,TypeError,RuntimeError,TimeoutError) as error:
                    self.finetuned_context_ready=False;self.finetuned_context_status='UNAVAILABLE'
                    audit_output.unlink(missing_ok=True)
                    self.event('finetuned_context_audit',status='UNAVAILABLE',error_type=type(error).__name__,bank_authority=False)
        except (OSError,ValueError,KeyError,RuntimeError,TimeoutError) as error:
            self.finetuned_ready=False;self.finetuned_context_ready=False
            audit_output.unlink(missing_ok=True)
            if self.finetuned_context_status is not None:self.event('finetuned_context_audit',status='UNAVAILABLE',error_type=type(error).__name__,bank_authority=False)
            output.unlink(missing_ok=True);self.event('finetuned_assist',status='unavailable',error_type=type(error).__name__)
            if mode=='required':raise RuntimeError('Required fine-tuned semantic model unavailable') from None
    def model(self,round_number):
        self.prepare_dialogue_assist()
        self.prepare_finetuned_assist()
        if getattr(self,'semantic_ready',False):
            if any(hashlib.sha256((self.work/name).read_bytes()).hexdigest()!=digest for name,digest in self.semantic_hashes.items()):
                raise ValueError('Semantic evidence changed after its pinned generation')
        repairing=round_number!=1 or bool(getattr(self.args,'practice_repair',None))
        self.phase('model_repair' if repairing else 'model_build',round=round_number)
        purpose='Repair validation or official-case failures in generated artifacts' if repairing else 'Build the phone agent from evidence'
        model_seconds=min(660 if round_number==1 and not getattr(self.args,'practice_repair',None) else 360,max(1,int(self.remaining()-30)))
        prompt=f'''Read BUILD_INSTRUCTIONS.md and follow it fully. Bank evidence files, in precedence order: {json.dumps([s['path'] for s in self.sources])}. Tool schema: inputs/openapi.json. Platform docs: inputs/workflow-format.md, inputs/tools-and-code.md. Base schema example: inputs/base-agent.json.
The output contract is workflow.json, policy.json and coverage.json in this current working directory; never edit host builder sources. Produce a real bank agent for all supplied evidence, not a demo. No network calls, credentials, installations, other agents or background tasks. Finish by returning artifact paths (relative file names) and summary using the supplied response schema.
Round {round_number}. Remaining full build budget: {int(self.remaining())} seconds. You have at most {model_seconds} seconds for this model step. Finish the artifact contract promptly after the essential checks; the host still needs time for real platform tests. Keep the graph efficient and code facts explicit. Read every evidence rule. You may generate JSON programmatically with Python but do not edit inputs. Put all helper scripts inside this workdir, not in /tmp.
Feedback from previous validation/tests: {json.dumps(self.feedback,ensure_ascii=False)}
'''
        if getattr(self,'semantic_ready',False):prompt+='\n'+PROMPT_NOTICE
        if getattr(self,'dialogue_ready',False):prompt+='\n'+DIALOGUE_NOTICE
        if getattr(self,'live_layer_contract',None):prompt+='\n'+self.live_layer_contract['notice']
        if getattr(self,'finetuned_ready',False):prompt+='\nRead finetuned-evidence.json for the pinned observed-turn hypotheses, matching each call/message index to the failed calls. '+FINETUNED_NOTICE
        if getattr(self,'finetuned_ready',False) and getattr(self,'finetuned_context_status',None) is not None:
            if self.finetuned_context_ready:prompt+='\n'+CONTEXT_NOTICE
            if self.finetuned_context_status=='UNAVAILABLE':prompt+='\nContext audit UNAVAILABLE: no context agreement was established; do not treat FULL hypotheses as agreed proposals.'
        (self.path/f'prompt-{round_number}.txt').write_text(prompt)
        profile=model_permissions(os.environ)
        command=['codex','exec','--ignore-user-config','--skip-git-repo-check','--ephemeral','--config','default_permissions='+profile,'--config','approval_policy=never','--json','--color','never','--output-schema',str(self.path/'response.schema.json'),'--output-last-message',str(self.path/f'answer-{round_number}.json')]
        if self.args.model:command+=['--model',self.args.model]
        command+=['-']
        # The model process never inherits bank or API credentials.
        env={key:value for key,value in os.environ.items() if not any(word in key.upper() for word in ('API_KEY','TEAM_KEY','TOKEN','SECRET','PASSWORD'))}
        self.event('model_call',model=self.args.model or 'Codex CLI default',purpose=purpose,round=round_number,permission_profile=profile)
        self.check_pinned_evidence()
        self.child(command,timeout=model_seconds,env=env,stdin=prompt,log_name=f'model-{round_number}.jsonl',purpose=purpose)
        self.check_pinned_evidence()
        answer=json.loads((self.path/f'answer-{round_number}.json').read_text())
        for key,name in [('workflow_file','workflow.json'),('policy_file','policy.json'),('coverage_file','coverage.json')]:
            target=(self.work/answer[key]).resolve()
            if not target.is_relative_to(self.work.resolve()) or not target.is_file():raise RuntimeError(f'Invalid artifact path: {key}')
            if target.name!=name:shutil.copyfile(target,self.work/name)
        self.event('model_result',summary=answer.get('summary'),round=round_number)
        workflow=json.loads((self.work/'workflow.json').read_text())
        if getattr(self,'live_layer_contract',None):
            evidence=live_layer.validate_embedding(workflow,self.work,self.live_layer_contract)
            self.event('live_layer_embedding',**evidence)
        return workflow
    def check_pinned_evidence(self):
        if getattr(self,'live_layer_contract',None):live_layer.verify_inputs(self.work,self.live_layer_contract)
        if getattr(self,'semantic_ready',False) and any(hashlib.sha256((self.work/name).read_bytes()).hexdigest()!=digest for name,digest in self.semantic_hashes.items()):
            raise ValueError('Model changed the pinned semantic evidence')
        if getattr(self,'dialogue_ready',False) and hashlib.sha256((self.work/'dialogue-evidence.json').read_bytes()).hexdigest()!=self.dialogue_hash:
            raise ValueError('Model changed the pinned dialogue hypotheses')
        if getattr(self,'finetuned_ready',False) and hashlib.sha256((self.work/'finetuned-evidence.json').read_bytes()).hexdigest()!=self.finetuned_hash:
            raise ValueError('Model changed the pinned fine-tuned hypotheses')
        if getattr(self,'finetuned_context_ready',False) and hashlib.sha256((self.work/'finetuned-context-evidence.json').read_bytes()).hexdigest()!=self.finetuned_context_hash:
            raise ValueError('Model changed the pinned context audit')
        if any(hashlib.sha256((self.work/s['path']).read_bytes()).hexdigest()!=s['sha256'] for s in self.sources):
            raise ValueError('Model changed original brief evidence')
        if hasattr(self,'api_sha256') and hashlib.sha256((self.work/'inputs/openapi.json').read_bytes()).hexdigest()!=self.api_sha256:
            raise ValueError('Model changed original tool API evidence')
    def publish(self,workflow):
        import freya
        self.phase('validating')
        errors=validate(workflow,self.api)
        errors+=validate_coverage(json.loads((self.work/'coverage.json').read_text()))
        if errors:raise ValueError(json.dumps({'local_validation':errors},ensure_ascii=False))
        freya.validate_workflow(self.args.slot,workflow)
        self.event('validation',local='passed',freya_dry_run='passed')
        self.phase('publishing')
        state=ROOT/'.state/freya-agents.json'
        ids=freya.save_workflow(self.args.slot,workflow,str(state))
        # Also publish/normalize a newly created slot, exactly through the kit model settings.
        if 'version' not in ids:
            ids['version']=freya.update_workflow(ids['workflow_id'],workflow)
            all_ids=json.loads(state.read_text());all_ids[self.args.slot]=ids;write_json(state,all_ids)
        self.status['freya']=ids
        self.event('freya_published',**ids)
        self.phase('exporting')
        export=self.path/f'{self.args.slot}.workflow.json'
        freya.export_workflow(ids['workflow_id'],str(export))
        self.status['artifacts']={'workflow':export.name,'policy':'work/policy.json','coverage':'work/coverage.json','trace':'trace.jsonl'}
        self.phase('published',freya=ids)
        return ids
    def test(self,ids,round_number):
        import freya
        self.phase('official_simulation',round=round_number)
        report=self.path/f'results-{round_number}.json'
        command=[sys.executable,str(ROOT/'simulate.py'),ids['agent_id'],'--cases',str(pathlib.Path(self.args.cases).resolve()),'--out',str(report)]
        if self.test_brief:command+=['--brief',self.test_brief]
        if self.args.only:command+=['--only',self.args.only]
        if self.args.style:command+=['--style',self.args.style]
        env={**os.environ,'COMPETITION_DEADLINE_EPOCH':str(time.time()+self.remaining())}
        self.child(command,timeout=min(900,self.remaining()),env=env,log_name=f'simulation-{round_number}.log',purpose='Official practice customers: bank ledger plus conversation judge')
        result=json.loads(report.read_text())
        if result.get('total',0)<=0:raise RuntimeError('No customer was evaluated; an empty test cannot count as success')
        result.update(freya_version=ids['version'],workflow_id=ids['workflow_id'],test_brief=self.test_brief);write_json(report,self.clean(result));self.status['tests'].append({'freya_version':ids['version'],'round':round_number,'passed':result['passed'],'total':result['total'],'simulation_id':result['simulation_id'],'report':report.name})
        self.event('official_test',**self.status['tests'][-1])
        failures=[row for row in result['rows'] if not row['pass']]
        self.feedback=[{'official_report':report.name,'passed':result['passed'],'total':result['total'],'failures':failures}]
        transcripts=[]
        for row in failures:
            if self.remaining()<30:break
            if row.get('call_id'):
                try:
                    call=freya.get_call(row['call_id']);messages=call.get('messages',[])
                    raw=self.path/'call-transcripts'/f"{row['id']}.json"
                    write_json(raw,self.clean(call))
                    entry={'case':row['id'],'failed':row['failed'],'endedReason':call.get('endedReason'),'full_call':str(raw.relative_to(self.path)),'messages':compact_messages(messages)}
                    transcripts.append(entry)
                except Exception as error:self.event('transcript_error',case=row['id'],error=str(error))
        if transcripts:
            write_json(self.work/'failed-calls.json',self.clean(transcripts))
            self.feedback.append({'read_file':'failed-calls.json','instruction':'Read actual tool/routing events and dialogue before repairing. Do not hardcode case identities or expected outcomes.'})
        return result
    def execute(self):
        local_only=getattr(self.args,'local_only',False)
        if not local_only:
            import freya
            from bounded_freya import install
            install(freya,self.remaining,self.event)
        self.event('run_resume' if self.args.resume_run else 'run_start',model=self.args.model,phone_agent_model=None if local_only else freya.AGENT_LLM,local_only=local_only,maximum_minutes=self.args.minutes,remaining_seconds=round(self.remaining()))
        self.prepare();last_result=None;completed=False
        if self.args.resume_run:
            self.feedback=[{'resume_same_budget':'Continue these generated artifacts in the same run, with unchanged bank evidence and the original deadline. Read the latest model log and fix the actual remaining failure.'}]
            if self.status['tests']:
                last_result=json.loads((self.path/self.status['tests'][-1]['report']).read_text())
                self.feedback.append({'official_test_report':last_result,'read_file':'failed-calls.json','instruction':'Read actual failed-call events, diagnose the remaining root cause and preserve all bank rules. Earlier model-step interruptions are not the current failure when a newer test report exists.'})
            if (self.work/'workflow.json').exists():self.feedback.append({'local_validation':validate(json.loads((self.work/'workflow.json').read_text()),self.api)})
            if (self.work/'coverage.json').exists():self.feedback.append({'coverage_validation':validate_coverage(json.loads((self.work/'coverage.json').read_text())),'instruction':'Remove any fallback that weakens mandatory policy guards. A sandbox outage must fail closed; never substitute an unconstrained dialogue/tool model for unavailable financial enforcement. Do not tune business rules to infrastructure-failed scores.'})
        try:
            if getattr(self.args,'practice_repair',None) and not self.args.skip_tests and not self.args.repair_first and not local_only:
                ids=self.publish(json.loads((self.work/'workflow.json').read_text()))
                last_result=self.test(ids,0)
                completed=last_result['passed']==last_result['total']
            first_round=self.status['round']+1 if self.args.resume_run else 1
            for number in range(first_round,self.args.rounds+1):
                if completed or self.remaining()<90:break
                try:
                    workflow=self.model(number)
                    if local_only:
                        errors=validate(workflow,self.api)+validate_coverage(json.loads((self.work/'coverage.json').read_text()))
                        if errors:raise ValueError(json.dumps({'local_validation':errors},ensure_ascii=False))
                        self.event('local_validation',status='passed',published=False)
                        self.status['artifacts']={'workflow':'work/workflow.json','policy':'work/policy.json','coverage':'work/coverage.json','trace':'trace.jsonl'}
                        completed=True;break
                    ids=self.publish(workflow)
                except TimeoutError as error:
                    if self.remaining()<120:raise
                    self.feedback=[{'model_step_timeout':str(error),'existing_artifacts':[name for name in ('workflow.json','policy.json','coverage.json') if (self.work/name).exists()],'read_file':f'../model-{number}.jsonl','instruction':'Continue this same run automatically; inspect already generated artifacts and the last model message, finish essential repairs, then return the required artifact contract. Do not change input evidence.'}]
                    self.event('model_timeout_recovery',round=number,remaining_seconds=round(self.remaining()))
                    continue
                except (ValueError,RuntimeError) as error:
                    self.feedback=[{'validation_or_build_error':str(error)}];self.event('build_error',round=number,error=str(error));continue
                if self.args.skip_tests:completed=True;break
                if self.remaining()<120:self.event('test_skipped',reason='Insufficient remaining run budget');break
                last_result=self.test(ids,number)
                if last_result['passed']==last_result['total']:completed=True;break
            self.phase('completed' if completed else 'needs_attention',ended=stamp(),evaluation='local_validation_only' if local_only else 'not_evaluated' if self.args.skip_tests else 'official_practice' if last_result else 'incomplete',published=False if local_only else bool(self.status.get('freya')),latest_score={key:last_result[key] for key in ('passed','total','freya_version','workflow_id','simulation_id') if key in last_result} if last_result else {},within_30_minutes=self.elapsed()<=1800)
        except Exception as error:
            self.phase('failed',ended=stamp(),error=self.clean(str(error)))
            raise
        finally:
            self.event('run_end',phase=self.status['phase'],ended=stamp(),seconds=round(self.elapsed()),active_seconds=round(time.monotonic()-self.start))
        print(json.dumps(self.clean(self.status),ensure_ascii=False,indent=2),flush=True)
        return completed

def arguments():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('briefs',nargs='+');parser.add_argument('--tool-api',default=str(KIT/'tools/openapi.json'))
    parser.add_argument('--cases',default=str(KIT/'public-test-set.json'));parser.add_argument('--slot',default='competition-builder')
    parser.add_argument('--rounds',type=int,help='Build/repair rounds within the same 30 minutes (default 3 with tests, 6 with --skip-tests)');parser.add_argument('--minutes',type=float,default=30)
    parser.add_argument('--brief',help='Case group in the provided test set; public A/B groups are inferred from their exact evidence')
    parser.add_argument('--only');parser.add_argument('--style',choices=['pieces','corrects','talkative','asks_back','in_words'])
    parser.add_argument('--skip-tests',action='store_true');parser.add_argument('--model',default=os.environ.get('BUILDER_MODEL'))
    parser.add_argument('--semantic-assist',choices=['auto','off','required'],default='auto',help='Local pinned MiniLM evidence navigation; off preserves the classic builder')
    parser.add_argument('--semantic-python',help='Python executable containing torch/transformers; also accepts MINILM_PYTHON environment variable')
    parser.add_argument('--dialogue-assist',choices=['auto','off','required'],default='auto',help='Generic source-act repair diagnostics; classic semantic off disables this too')
    parser.add_argument('--finetuned-assist',choices=['auto','off','required'],default='auto',help='Actual fine-tuned MiniLM repair hypotheses; classic semantic off disables it')
    parser.add_argument('--finetuned-version',choices=['auto','v1','v2'],default='auto',help='Select a pinned trained model; auto uses v2 only after its measured release gate')
    parser.add_argument('--finetuned-model',help='Explicit fine-tuned model directory; must match reviewed release manifest')
    parser.add_argument('--live-layer',choices=['off','recipient','v2-student'],default='off',help='Embed pinned portable per-turn components through automatic generation')
    parser.add_argument('--live-student',help='Reviewed portable student directory; distinct from the full MiniLM encoder')
    parser.add_argument('--live-student-sha256',help='Explicit manifest SHA256 for a frozen portable V2 student')
    parser.add_argument('--live-student-use',choices=['shadow','clarify'],default='shadow',help='Explicit experimental source-grounded clarification; never bank authority')
    parser.add_argument('--local-only',action='store_true',help='Generate and locally validate without credentials, Freya publication or simulation')
    parser.add_argument('--practice-repair',help='New explicitly logged practice cycle from a stopped public-brief run; never permitted for unseen briefs')
    parser.add_argument('--repair-first',action='store_true',help='With public practice repair, use the existing failed-call evidence before rerunning the candidate')
    parser.add_argument('--resume-run',help='Continue a stopped run with identical evidence and its original total time budget')
    args=parser.parse_args()
    if args.live_layer=='v2-student' and (not args.live_student or not re.fullmatch(r'[a-f0-9]{64}',args.live_student_sha256 or '')):parser.error('V2 live student requires a directory and explicit frozen manifest SHA256')
    if args.live_layer!='v2-student' and (args.live_student or args.live_student_sha256):parser.error('Student arguments require --live-layer v2-student')
    if args.repair_first and not args.practice_repair:parser.error('--repair-first requires --practice-repair')
    try:validate_case_scope(args.briefs,args.cases,args.skip_tests or args.local_only)
    except ValueError as error:parser.error(str(error))
    if args.resume_run and args.practice_repair:parser.error('Use either same-budget resume or a separate public practice repair cycle')
    if not 0<args.minutes<=30:parser.error('Each build is limited to 30 minutes.')
    # Without tests a round costs only model time, so the full budget may need more than three short rounds.
    if args.rounds is None:args.rounds=6 if args.skip_tests else 3
    if not 1<=args.rounds<=6:parser.error('Use 1 to 6 bounded build/repair rounds within the same 30-minute maximum.')
    if not re.fullmatch(r'[A-Za-z0-9_-]+',args.slot):parser.error('slot must use letters, numbers, - or _.')
    if not args.model:
        config=pathlib.Path.home()/'.codex/config.toml'
        if config.exists():args.model=tomllib.loads(config.read_text()).get('model')
    return args

def main():
    args=arguments()
    if not os.environ.get('SSL_CERT_FILE') and pathlib.Path('/etc/ssl/cert.pem').exists():os.environ['SSL_CERT_FILE']='/etc/ssl/cert.pem'
    if not args.local_only and not os.environ.get('FREYA_API_KEY'):os.environ['FREYA_API_KEY']=getpass.getpass('Freya API key (hidden, session memory only): ')
    if not args.local_only and not os.environ.get('FREYA_BANK_TEAM_KEY'):
        # Non-authenticating namespace token for synthetic practice data. Stable across runs, never serialized to traces.
        os.environ['FREYA_BANK_TEAM_KEY']='freya-practice-'+hashlib.sha256(os.environ['FREYA_API_KEY'].encode()).hexdigest()[:32]
    sys.path.insert(0,str(KIT))
    lock=ROOT/'.state/slots'/f'{args.slot}.lock';lock.parent.mkdir(parents=True,exist_ok=True)
    with slot_lock(lock):
        run=Run(args)
        awake=None
        if sys.platform=='darwin' and shutil.which('caffeinate'):
            awake=subprocess.Popen(['caffeinate','-i','-t',str(int(args.minutes*60)),'-w',str(os.getpid())],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,env={key:value for key,value in os.environ.items() if not any(word in key.upper() for word in ('KEY','TOKEN','SECRET','PASSWORD'))})
            run.event('idle_sleep_guard',scope='This builder process only; bounded by the run maximum')
        try:success=run.execute()
        except Exception as error:
            if run.status.get('phase')!='failed':run.phase('failed',ended=stamp(),error=run.clean(str(error)))
            print(run.clean(str(error)),file=sys.stderr);return 1
        finally:
            if awake and awake.poll() is None:awake.terminate()
        return 0 if success else 2

if __name__=='__main__':sys.exit(main())
