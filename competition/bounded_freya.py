"""Apply the builder's time budget to the unchanged kit client's HTTP calls."""
import json,urllib.error,urllib.parse,urllib.request

def install(freya,remaining,event=lambda *args,**kwargs:None):
    def api(method,path,body=None,**params):
        seconds=remaining()
        if seconds<=1:raise TimeoutError('The 30-minute builder budget is exhausted.')
        query='?'+urllib.parse.urlencode(params) if params else ''
        request=urllib.request.Request(freya.URL+path+query,data=json.dumps(body).encode() if body is not None else None,headers=freya.HEADERS,method=method)
        try:
            with urllib.request.urlopen(request,timeout=min(90,seconds)) as response:result=json.load(response)
        except urllib.error.HTTPError as error:raise RuntimeError(f'{method} {path} -> {error.code}: {error.read().decode()[:1500]}') from None
        if isinstance(result,dict) and result.get('success') is False:raise RuntimeError(f'{method} {path}: {json.dumps(result)[:1500]}')
        value=result.get('data',{}).get('result',result) if isinstance(result,dict) else result
        metadata={}
        if method=='POST' and path=='/api/v2/simulations' and isinstance(value,dict):metadata['simulation_id']=(value.get('simulation') or value).get('id')
        event('freya_api',method=method,path=path,**metadata)
        return value
    freya.api=api
