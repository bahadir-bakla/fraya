"""Apply the builder's time budget to the unchanged kit client's HTTP calls."""
import json,socket,time,urllib.error,urllib.parse,urllib.request

TRANSIENT_STATUS={502,503,504}
UNPROCESSED='API key validation is temporarily unavailable'

def resendable(method,params,status,body_text):
    """A transient failure may be resent only when a repeat cannot create a second side effect."""
    if status==503 and UNPROCESSED in body_text:return True    # rejected before the request was processed
    if method in ('GET','PUT'):return True                      # reads, and full-body workflow updates
    return method=='POST' and str(params.get('dryRun','')).lower()=='true'

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
                retry=error.code in TRANSIENT_STATUS and resendable(method,params,error.code,text)
            except (urllib.error.URLError,socket.timeout,TimeoutError,ConnectionError) as error:
                failure=RuntimeError(f'{method} {path} -> network: {error}')
                retry=resendable(method,params,None,'')
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
