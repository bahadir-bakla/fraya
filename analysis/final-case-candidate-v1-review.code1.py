try:
    d={'customerNo':str(vars.get('customerNumber','')),'aiFlow':'CardOps'}
    config['body']={'data':d,'call':{'ani':'','lang':'tr'} }
except Exception:
    config['body']={'data':{} }
