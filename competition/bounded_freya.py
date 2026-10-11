"""Apply the builder's time budget to the unchanged kit client's HTTP calls."""
import json,socket,time,urllib.error,urllib.parse,urllib.request

TRANSIENT_STATUS={502,503,504}
UNPROCESSED='API key validation is temporarily unavailable'

def resendable(method,params,status,body_text,path=''):
    """A transient failure may be resent only when a repeat cannot create a second side effect."""
    if status==503 and UNPROCESSED in body_text:return True    # rejected before the request was processed
    if method in ('GET','PUT'):return True                      # reads, and full-body workflow updates
    if method=='POST' and path.startswith('/api/v2/versions/') and path.endswith('/publish'):return True  # same version again
    return method=='POST' and str(params.get('dryRun','')).lower()=='true'

def creates_workflow(method,path,params):return method=='POST' and path=='/api/v2/workflow' and str(params.get('dryRun','')).lower()!='true'

def find_created_workflow(api,freya,name):
    """After an ambiguous create, look the workflow up by its unique name instead of creating a second one."""
    try:
        listed=api('GET','/api/v2/workflow',workspaceId=freya.workspace_id())
        items=(listed.get('workflows') or listed.get('items') or []) if isinstance(listed,dict) else listed
        match=next((item for item in items or [] if isinstance(item,dict) and item.get('name')==name),None)
        if not match:return None
        agent=match.get('agentId') or (match.get('agent') or {}).get('id')
        if not agent:agent=api('GET',f"/api/v2/workflow/{match['id']}",workspaceId=freya.workspace_id())['workflow']['agentId']
        return {'workflow':{'id':match['id'],'agentId':agent}}
    except (RuntimeError,KeyError,TypeError,StopIteration):return None

def install(freya,remaining,event=lambda *args,**kwargs:None,sleep=time.sleep,reserve=120,pause=15):
    def api(method,path,body=None,**params):
        attempt=0
        while True:
            seconds=remaining()
            if seconds<=1:raise TimeoutError('The 30-minute builder budget is exhausted.')
            query='?'+urllib.parse.urlencode(params) if params else ''
            request=urllib.request.Request(freya.URL+path+query,data=json.dumps(body).encode() if body is not None else None,headers=freya.HEADERS,method=method)
            try:
                with urllib.request.urlopen(request,timeout=min(90,seconds)) as response:result=json.load(response)
                break
            except urllib.error.HTTPError as error:
                text=error.read().decode()[:1500];failure=RuntimeError(f'{method} {path} -> {error.code}: {text}')
                ambiguous=error.code in (502,504);retry=error.code in TRANSIENT_STATUS and resendable(method,params,error.code,text,path)
            except (urllib.error.URLError,socket.timeout,TimeoutError,ConnectionError) as error:
                failure=RuntimeError(f'{method} {path} -> network: {error}')
                ambiguous=True;retry=resendable(method,params,None,'',path)
            if ambiguous and creates_workflow(method,path,params) and isinstance(body,dict) and remaining()-pause*4>=reserve:
                # The create may have succeeded. Adopt it if it exists; otherwise nothing was created and a resend is safe.
                for _ in range(3):
                    sleep(pause);found=find_created_workflow(api,freya,body.get('name'))
                    if found:event('freya_create_adopted',name=body.get('name'),workflow_id=found['workflow']['id']);return found
                retry=True
            # Platform outages are not workflow defects: retry within the budget instead of sending them to model repair.
            if not retry or remaining()-pause<reserve:raise failure from None
            attempt+=1;event('freya_transient_retry',method=method,path=path,attempt=attempt,error=str(failure)[:200]);sleep(pause)
        if isinstance(result,dict) and result.get('success') is False:raise RuntimeError(f'{method} {path}: {json.dumps(result)[:1500]}')
        value=result.get('data',{}).get('result',result) if isinstance(result,dict) else result
        metadata={}
        if method=='POST' and path=='/api/v2/simulations' and isinstance(value,dict):metadata['simulation_id']=(value.get('simulation') or value).get('id')
        event('freya_api',method=method,path=path,**metadata)
        return value
    freya.api=api
