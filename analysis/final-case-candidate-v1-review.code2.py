try:
    if isinstance(result,dict):
        result.pop('header',None)
        body=result.get('data')
        if isinstance(body,dict):
            body['receipt']={'status_code':result.get('status_code',''),'data':dict(body)}
            body['receipt_operation']='cards_list'
            body['what_to_do_next']='Return to the controller immediately; it validates bank status and computes the next spoken line.'
except Exception:
    pass
