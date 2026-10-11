try:
    d={'cardNumber':str(vars.get('selected_card',''))}
    config['body']={'data':d,'call':{'ani':'','lang':'tr'} }
except Exception:
    config['body']={'data':{} }
