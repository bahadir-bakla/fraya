"""Read actual published version metadata and bind a completed generator export."""
import argparse,hashlib,json,pathlib,sys
ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from freya_dpapi_server import inject_credentials
inject_credentials()
sys.path.insert(0,str(ROOT.parent/'skill-creator-skill-lift/integrations/freya-mcp'))
from freya_mcp.bridge import Bridge,Config

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--run',required=True);p.add_argument('--export',required=True);p.add_argument('--version',required=True,type=int);p.add_argument('--out',required=True);p.add_argument('--mock-url',required=True)
    a=p.parse_args();run=pathlib.Path(a.run);export=pathlib.Path(a.export)
    status=json.loads((run/'status.json').read_text());value=json.loads(export.read_text(encoding='utf-8-sig'))
    if status.get('phase')!='completed':raise ValueError('Generation not completed')
    cfg=Config.load(ROOT,ROOT/'build-the-builder 2')
    cfg.workspace_id='2507ffc9-3031-479a-ac9e-dae277fa0743'
    b=Bridge(cfg)
    try:
        wid=value['workflow_id'];aid=value['agent_id']
        rows=b.items(b.request('GET','/api/v2/versions/workflow/'+b.identifier(wid),params={'workspaceId':b.workspace_id()}),'versions')
        published=next(r for r in rows if r.get('versionNumber')==a.version and r.get('isPublished') is True)
        if published.get('entityId')!=wid or published.get('entityType')!='workflow':raise ValueError('Wrong published entity')
        sha=lambda x:hashlib.sha256(x.read_bytes()).hexdigest()
        proof={'run_id':status['id'],'source_workflow_sha256':sha(run/'work/workflow.json'),'workflow_id':wid,'agent_id':aid,'version':a.version,'export_sha256':sha(export),'mock_url':a.mock_url,'published_version':published,'scope':'actual read-only platform published version and exact export bytes'}
        pathlib.Path(a.out).write_text(json.dumps(b.scrub(proof),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(json.dumps({'workflow_id':wid,'agent_id':aid,'version':a.version,'published':True,'proof':a.out}))
    finally:b.close()
if __name__=='__main__':main()
