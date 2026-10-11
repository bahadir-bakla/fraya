try:
    d={'cardNumber':str(vars.get('selected_card','')),'newStatementWeek':int(vars.get('new_week',0)),'statementDay':int(vars.get('statement_day',0))}
    config['body']={'data':d,'call':{'ani':'','lang':'tr'} }
except Exception:
    config['body']={'data':{} }
