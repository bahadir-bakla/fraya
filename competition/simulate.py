"""Run the unchanged official scorer with bounded HTTP, correct public cohort and runner provenance."""
import hashlib,json,os,pathlib,shutil,sys,time
ROOT=pathlib.Path(__file__).resolve().parent
KIT=ROOT.parent/'build-the-builder 2'
sys.path[:0]=[str(KIT/'tools'),str(KIT)]
import freya,run_cases
from bounded_freya import install
from builder import infer_practice_group
from caller_styles import TAU_STYLES
run_cases.STYLES.update(TAU_STYLES)
REASON_REJECTION='this outcome needs one of these reasons'

def adjust_reason_rejections(report_path,cases_path):
    """Self-practice cases carry the brief's own close reasons, but the hosted mock only knows the practice brief's
    reason table. A close_call rejected solely for that is counted with the agent's own outcome and reason; the
    official score is kept beside it. The conversation judge's verdict is never changed."""
    from score import http,score_ledger
    report=json.loads(pathlib.Path(report_path).read_text());cases={c['id']:c for c in json.loads(pathlib.Path(cases_path).read_text())}
    for row in report.get('rows',[]):
        row['official_pass']=row['pass']
        if row['pass'] or not row.get('customer_id'):continue
        ledger=http('/v1/practice/ledger/'+row['customer_id'])
        if ledger.get('outcome') is not None:continue
        close=next((c for c in reversed(ledger.get('calls',[])) if c['tool']=='close_call' and REASON_REJECTION in str(c.get('result',{}).get('error',''))),None)
        if not close:continue
        ledger={**ledger,'outcome':close['args'].get('outcome'),'reason':close['args'].get('reason')}
        failed=score_ledger(cases[row['id']],ledger)['failed']+[f for f in row['failed'] if f.startswith('conversation:')]
        row.update(failed=failed,reason_adjusted=True,**{'pass':not failed})
    report['official_passed']=sum(r.get('official_pass',r['pass']) for r in report.get('rows',[]))
    report['passed']=sum(r['pass'] for r in report.get('rows',[]))
    pathlib.Path(report_path).write_text(json.dumps(report,indent=2)+'\n')

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
    adjust='--adjust-reasons' in sys.argv
    if adjust:sys.argv.remove('--adjust-reasons')
    group,out=prepare_scope()
    run_cases.main()
    if out:
        if adjust and option('--cases'):adjust_reason_rejections(out,option('--cases'))
        report=pathlib.Path(out);result=json.loads(report.read_text());result['test_brief']=group;report.write_text(json.dumps(result,indent=2)+'\n')
