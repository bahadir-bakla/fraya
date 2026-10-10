"""Run the unchanged official scorer with bounded HTTP, correct public cohort and runner provenance."""
import hashlib,json,os,pathlib,shutil,sys,time
ROOT=pathlib.Path(__file__).resolve().parent
KIT=ROOT.parent/'build-the-builder 2'
sys.path[:0]=[str(KIT/'tools'),str(KIT)]
import freya,run_cases
from bounded_freya import install
from builder import infer_practice_group

def option(name):
    return sys.argv[sys.argv.index(name)+1] if name in sys.argv else None

def prepare_scope():
    group=option('--brief')
    cases=option('--cases') or str(KIT/'public-test-set.json')
    if not group and pathlib.Path(cases).resolve()==(KIT/'public-test-set.json').resolve():
        sources=sorted((pathlib.Path.cwd()/'inputs').glob('[0-9][0-9]-*'))
        if sources:
            group=infer_practice_group(sources)
            if group:sys.argv+=['--brief',group]
    out=option('--out')
    if out:
        snapshot=pathlib.Path(out).parent/'runner-sources'/pathlib.Path(out).stem;snapshot.mkdir(parents=True,exist_ok=True)
        for name in ('simulate.py','bounded_freya.py','builder.py'):
            shutil.copyfile(ROOT/name,snapshot/name)
        print(json.dumps({'kind':'official_runner','effective_arguments':sys.argv[1:],'test_brief':group,'sha256':{name:hashlib.sha256((snapshot/name).read_bytes()).hexdigest() for name in ('simulate.py','bounded_freya.py','builder.py')}}),flush=True)
    return group,out

deadline=float(os.environ.get('COMPETITION_DEADLINE_EPOCH',str(time.time()+1800)))
def event(kind,**data):
    if data.get('simulation_id'):print(json.dumps({'kind':kind,**data}),flush=True)
install(freya,lambda:deadline-time.time(),event)
if __name__=='__main__':
    group,out=prepare_scope()
    run_cases.main()
    if out:
        report=pathlib.Path(out);result=json.loads(report.read_text());result['test_brief']=group;report.write_text(json.dumps(result,indent=2)+'\n')
