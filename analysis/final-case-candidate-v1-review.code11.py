try:
    d={'customerNo':str(vars.get('customerNumber','')),'intAddressInfoType':'E'}
    config['body']={'data':d,'call':{'ani':'','lang':'tr'} }
except Exception:
    config['body']={'data':{} }
