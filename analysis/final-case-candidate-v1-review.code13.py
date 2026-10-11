try:
    d={'customerNo':str(vars.get('customerNumber','')),'cardNumber':str(vars.get('selected_card','')),'currencyType':str(vars.get('send_currency','TL')),'statementDate':str(vars.get('statement_date','')),'emailAddress':str(vars.get('registered_email',''))}
    config['body']={'data':d,'call':{'ani':'','lang':'tr'} }
except Exception:
    config['body']={'data':{} }
