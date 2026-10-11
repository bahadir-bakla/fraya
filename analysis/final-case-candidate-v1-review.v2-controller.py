RESPONSE_SCHEMAS={'Result': {'type': 'object', 'properties': {'guid': {'type': 'string'}, 'returnCode': {'type': 'string'}, 'messageText': {'type': 'string'}, 'code': {'type': 'string'}, 'message': {'type': 'string'}, 'type': {'type': 'string'}, 'details': {'type': 'object', 'properties': {'guid': {'type': 'string'}, 'rootCause': {'type': 'string'}, 'errorOrigin': {'type': 'string'} } } } }, 'ErrorResponse': {'type': 'object', 'properties': {'result': {'type': 'object', 'properties': {'guid': {'type': 'string'}, 'returnCode': {'type': 'string'}, 'messageText': {'type': 'string'}, 'code': {'type': 'string'}, 'message': {'type': 'string'}, 'type': {'type': 'string'}, 'details': {'type': 'object', 'properties': {'guid': {'type': 'string'}, 'rootCause': {'type': 'string'}, 'errorOrigin': {'type': 'string'} } } } } } }, 'Call': {'type': 'object', 'properties': {'ani': {'type': 'string'}, 'lang': {'type': 'string'} } }, 'Card': {'type': 'object', 'properties': {'cardNumber': {'type': 'string'}, 'cardNumberLast4': {'type': 'string'}, 'productName': {'type': 'string'}, 'status': {'type': 'string'}, 'isMainCard': {'type': 'boolean'} } }, 'Debt': {'type': 'object', 'properties': {'statementPaymentStatus': {'type': 'string'}, 'transferAmount': {'type': 'number'}, 'statementDebt': {'type': 'number'}, 'minPayment': {'type': 'number'}, 'remainingDebt': {'type': 'number'}, 'remainingMinPayment': {'type': 'number'}, 'currentPeriodExpense': {'type': 'number'}, 'totalDebt': {'type': 'number'}, 'remainAutomaticPaymentAmount': {'type': 'number'}, 'totalDebtPaymentStatus': {'type': 'string'} } }, 'CardsListData': {'type': 'object', 'properties': {'cards': {'type': 'array', 'items': {'type': 'object', 'properties': {'cardNumber': {'type': 'string'}, 'cardNumberLast4': {'type': 'string'}, 'productName': {'type': 'string'}, 'status': {'type': 'string'}, 'isMainCard': {'type': 'boolean'} } } }, 'validCardsCount': {'type': 'integer'}, 'exitState': {'type': 'string'} } }, 'BalanceData': {'type': 'object', 'properties': {'cardNumber': {'type': 'string'}, 'cardNumberLast4': {'type': 'string'}, 'productName': {'type': 'string'}, 'statementDate': {'type': 'string'}, 'lastPayDate': {'type': 'string'}, 'nextStatementDate': {'type': 'string'}, 'nextLastPayDate': {'type': 'string'}, 'debtTL': {'type': 'object', 'properties': {'statementPaymentStatus': {'type': 'string'}, 'transferAmount': {'type': 'number'}, 'statementDebt': {'type': 'number'}, 'minPayment': {'type': 'number'}, 'remainingDebt': {'type': 'number'}, 'remainingMinPayment': {'type': 'number'}, 'currentPeriodExpense': {'type': 'number'}, 'totalDebt': {'type': 'number'}, 'remainAutomaticPaymentAmount': {'type': 'number'}, 'totalDebtPaymentStatus': {'type': 'string'} } }, 'debtUSD': {'type': 'object', 'properties': {'statementPaymentStatus': {'type': 'string'}, 'transferAmount': {'type': 'number'}, 'statementDebt': {'type': 'number'}, 'minPayment': {'type': 'number'}, 'remainingDebt': {'type': 'number'}, 'remainingMinPayment': {'type': 'number'}, 'currentPeriodExpense': {'type': 'number'}, 'totalDebt': {'type': 'number'}, 'remainAutomaticPaymentAmount': {'type': 'number'}, 'totalDebtPaymentStatus': {'type': 'string'} } }, 'debtEUR': {'type': 'object', 'properties': {'statementPaymentStatus': {'type': 'string'}, 'transferAmount': {'type': 'number'}, 'statementDebt': {'type': 'number'}, 'minPayment': {'type': 'number'}, 'remainingDebt': {'type': 'number'}, 'remainingMinPayment': {'type': 'number'}, 'currentPeriodExpense': {'type': 'number'}, 'totalDebt': {'type': 'number'}, 'remainAutomaticPaymentAmount': {'type': 'number'}, 'totalDebtPaymentStatus': {'type': 'string'} } }, 'debtGBP': {'type': 'object', 'properties': {'statementPaymentStatus': {'type': 'string'}, 'transferAmount': {'type': 'number'}, 'statementDebt': {'type': 'number'}, 'minPayment': {'type': 'number'}, 'remainingDebt': {'type': 'number'}, 'remainingMinPayment': {'type': 'number'}, 'currentPeriodExpense': {'type': 'number'}, 'totalDebt': {'type': 'number'}, 'remainAutomaticPaymentAmount': {'type': 'number'}, 'totalDebtPaymentStatus': {'type': 'string'} } }, 'statementPaymentStatus': {'type': 'string'}, 'totalDebtPaymentStatus': {'type': 'string'}, 'automaticPaymentFlag': {'type': 'string'} } }, 'WeekGetData': {'type': 'object', 'properties': {'cardNumber': {'type': 'string'}, 'cardNumberLast4': {'type': 'string'}, 'productName': {'type': 'string'}, 'statementWeek': {'type': 'integer'}, 'statementDay': {'type': 'integer'}, 'statementDate': {'type': 'string'}, 'lastPayDate': {'type': 'string'}, 'nextStatementDate': {'type': 'string'}, 'nextLastPayDate': {'type': 'string'}, 'relationType': {'type': 'string'}, 'relatedCardNumber': {'type': 'string'}, 'relatedCardProductName': {'type': 'string'} } }, 'WeekDecideData': {'type': 'object', 'properties': {'statementDate': {'type': 'string'}, 'statementDueDate': {'type': 'string'}, 'statementDay': {'type': 'integer'}, 'responseCode': {'type': 'integer'}, 'responseMessage': {'type': 'string'} } }, 'WeekChangeData': {'type': 'object', 'properties': {'responseCode': {'type': 'integer'}, 'responseMessage': {'type': 'string'}, 'statementWeek': {'type': 'string'}, 'statementDay': {'type': 'string'}, 'exitState': {'type': 'string'} } }, 'ContactEmailData': {'type': 'object', 'properties': {'communicationType': {'type': 'string'}, 'ibanCountryCode': {'type': 'string'}, 'ibanAreaCode': {'type': 'string'}, 'ibanPhoneNum': {'type': 'string'}, 'ibanEmail': {'type': 'string'}, 'ttsEmail': {'type': 'string'}, 'commGramType': {'type': 'string'}, 'exitState': {'type': 'string'} } }, 'PdfSendData': {'type': 'object', 'properties': {'exitState': {'type': 'string'} } }, 'CardsListRequest': {'type': 'object', 'properties': {'data': {'type': 'object', 'properties': {'customerNo': {}, 'aiFlow': {'type': 'string'} } }, 'call': {'type': 'object', 'properties': {'ani': {'type': 'string'}, 'lang': {'type': 'string'} } } } }, 'CardsListResponse': {'type': 'object', 'properties': {'data': {'type': 'object', 'properties': {'cards': {'type': 'array', 'items': {'type': 'object', 'properties': {'cardNumber': {'type': 'string'}, 'cardNumberLast4': {'type': 'string'}, 'productName': {'type': 'string'}, 'status': {'type': 'string'}, 'isMainCard': {'type': 'boolean'} } } }, 'validCardsCount': {'type': 'integer'}, 'exitState': {'type': 'string'} } }, 'result': {'type': 'object', 'properties': {'guid': {'type': 'string'}, 'returnCode': {'type': 'string'}, 'messageText': {'type': 'string'}, 'code': {'type': 'string'}, 'message': {'type': 'string'}, 'type': {'type': 'string'}, 'details': {'type': 'object', 'properties': {'guid': {'type': 'string'}, 'rootCause': {'type': 'string'}, 'errorOrigin': {'type': 'string'} } } } } } }, 'BalanceRequest': {'type': 'object', 'properties': {'data': {'type': 'object', 'properties': {'cardNumber': {'type': 'string'} } }, 'call': {'type': 'object', 'properties': {'ani': {'type': 'string'}, 'lang': {'type': 'string'} } } } }, 'BalanceResponse': {'type': 'object', 'properties': {'data': {'type': 'object', 'properties': {'cardNumber': {'type': 'string'}, 'cardNumberLast4': {'type': 'string'}, 'productName': {'type': 'string'}, 'statementDate': {'type': 'string'}, 'lastPayDate': {'type': 'string'}, 'nextStatementDate': {'type': 'string'}, 'nextLastPayDate': {'type': 'string'}, 'debtTL': {'type': 'object', 'properties': {'statementPaymentStatus': {'type': 'string'}, 'transferAmount': {'type': 'number'}, 'statementDebt': {'type': 'number'}, 'minPayment': {'type': 'number'}, 'remainingDebt': {'type': 'number'}, 'remainingMinPayment': {'type': 'number'}, 'currentPeriodExpense': {'type': 'number'}, 'totalDebt': {'type': 'number'}, 'remainAutomaticPaymentAmount': {'type': 'number'}, 'totalDebtPaymentStatus': {'type': 'string'} } }, 'debtUSD': {'type': 'object', 'properties': {'statementPaymentStatus': {'type': 'string'}, 'transferAmount': {'type': 'number'}, 'statementDebt': {'type': 'number'}, 'minPayment': {'type': 'number'}, 'remainingDebt': {'type': 'number'}, 'remainingMinPayment': {'type': 'number'}, 'currentPeriodExpense': {'type': 'number'}, 'totalDebt': {'type': 'number'}, 'remainAutomaticPaymentAmount': {'type': 'number'}, 'totalDebtPaymentStatus': {'type': 'string'} } }, 'debtEUR': {'type': 'object', 'properties': {'statementPaymentStatus': {'type': 'string'}, 'transferAmount': {'type': 'number'}, 'statementDebt': {'type': 'number'}, 'minPayment': {'type': 'number'}, 'remainingDebt': {'type': 'number'}, 'remainingMinPayment': {'type': 'number'}, 'currentPeriodExpense': {'type': 'number'}, 'totalDebt': {'type': 'number'}, 'remainAutomaticPaymentAmount': {'type': 'number'}, 'totalDebtPaymentStatus': {'type': 'string'} } }, 'debtGBP': {'type': 'object', 'properties': {'statementPaymentStatus': {'type': 'string'}, 'transferAmount': {'type': 'number'}, 'statementDebt': {'type': 'number'}, 'minPayment': {'type': 'number'}, 'remainingDebt': {'type': 'number'}, 'remainingMinPayment': {'type': 'number'}, 'currentPeriodExpense': {'type': 'number'}, 'totalDebt': {'type': 'number'}, 'remainAutomaticPaymentAmount': {'type': 'number'}, 'totalDebtPaymentStatus': {'type': 'string'} } }, 'statementPaymentStatus': {'type': 'string'}, 'totalDebtPaymentStatus': {'type': 'string'}, 'automaticPaymentFlag': {'type': 'string'} } }, 'result': {'type': 'object', 'properties': {'guid': {'type': 'string'}, 'returnCode': {'type': 'string'}, 'messageText': {'type': 'string'}, 'code': {'type': 'string'}, 'message': {'type': 'string'}, 'type': {'type': 'string'}, 'details': {'type': 'object', 'properties': {'guid': {'type': 'string'}, 'rootCause': {'type': 'string'}, 'errorOrigin': {'type': 'string'} } } } } } }, 'WeekGetRequest': {'type': 'object', 'properties': {'data': {'type': 'object', 'properties': {'cardNumber': {'type': 'string'} } }, 'call': {'type': 'object', 'properties': {'ani': {'type': 'string'}, 'lang': {'type': 'string'} } } } }, 'WeekGetResponse': {'type': 'object', 'properties': {'data': {'type': 'object', 'properties': {'cardNumber': {'type': 'string'}, 'cardNumberLast4': {'type': 'string'}, 'productName': {'type': 'string'}, 'statementWeek': {'type': 'integer'}, 'statementDay': {'type': 'integer'}, 'statementDate': {'type': 'string'}, 'lastPayDate': {'type': 'string'}, 'nextStatementDate': {'type': 'string'}, 'nextLastPayDate': {'type': 'string'}, 'relationType': {'type': 'string'}, 'relatedCardNumber': {'type': 'string'}, 'relatedCardProductName': {'type': 'string'} } }, 'result': {'type': 'object', 'properties': {'guid': {'type': 'string'}, 'returnCode': {'type': 'string'}, 'messageText': {'type': 'string'}, 'code': {'type': 'string'}, 'message': {'type': 'string'}, 'type': {'type': 'string'}, 'details': {'type': 'object', 'properties': {'guid': {'type': 'string'}, 'rootCause': {'type': 'string'}, 'errorOrigin': {'type': 'string'} } } } } } }, 'WeekDecideRequest': {'type': 'object', 'properties': {'data': {'type': 'object', 'properties': {'cardNumber': {'type': 'string'}, 'newStatementWeek': {}, 'statementDay': {'type': 'integer'} } }, 'call': {'type': 'object', 'properties': {'ani': {'type': 'string'}, 'lang': {'type': 'string'} } } } }, 'WeekDecideResponse': {'type': 'object', 'properties': {'data': {'type': 'object', 'properties': {'statementDate': {'type': 'string'}, 'statementDueDate': {'type': 'string'}, 'statementDay': {'type': 'integer'}, 'responseCode': {'type': 'integer'}, 'responseMessage': {'type': 'string'} } }, 'result': {'type': 'object', 'properties': {'guid': {'type': 'string'}, 'returnCode': {'type': 'string'}, 'messageText': {'type': 'string'}, 'code': {'type': 'string'}, 'message': {'type': 'string'}, 'type': {'type': 'string'}, 'details': {'type': 'object', 'properties': {'guid': {'type': 'string'}, 'rootCause': {'type': 'string'}, 'errorOrigin': {'type': 'string'} } } } } } }, 'WeekChangeRequest': {'type': 'object', 'properties': {'data': {'type': 'object', 'properties': {'cardNumber': {'type': 'string'}, 'newStatementWeek': {}, 'statementDay': {'type': 'integer'} } }, 'call': {'type': 'object', 'properties': {'ani': {'type': 'string'}, 'lang': {'type': 'string'} } } } }, 'WeekChangeResponse': {'type': 'object', 'properties': {'data': {'type': 'object', 'properties': {'responseCode': {'type': 'integer'}, 'responseMessage': {'type': 'string'}, 'statementWeek': {'type': 'string'}, 'statementDay': {'type': 'string'}, 'exitState': {'type': 'string'} } }, 'result': {'type': 'object', 'properties': {'guid': {'type': 'string'}, 'returnCode': {'type': 'string'}, 'messageText': {'type': 'string'}, 'code': {'type': 'string'}, 'message': {'type': 'string'}, 'type': {'type': 'string'}, 'details': {'type': 'object', 'properties': {'guid': {'type': 'string'}, 'rootCause': {'type': 'string'}, 'errorOrigin': {'type': 'string'} } } } } } }, 'ContactEmailRequest': {'type': 'object', 'properties': {'data': {'type': 'object', 'properties': {'customerNo': {}, 'intAddressInfoType': {'type': 'string'} } }, 'call': {'type': 'object', 'properties': {'ani': {'type': 'string'}, 'lang': {'type': 'string'} } } } }, 'ContactEmailResponse': {'type': 'object', 'properties': {'data': {'type': 'object', 'properties': {'communicationType': {'type': 'string'}, 'ibanCountryCode': {'type': 'string'}, 'ibanAreaCode': {'type': 'string'}, 'ibanPhoneNum': {'type': 'string'}, 'ibanEmail': {'type': 'string'}, 'ttsEmail': {'type': 'string'}, 'commGramType': {'type': 'string'}, 'exitState': {'type': 'string'} } }, 'result': {'type': 'object', 'properties': {'guid': {'type': 'string'}, 'returnCode': {'type': 'string'}, 'messageText': {'type': 'string'}, 'code': {'type': 'string'}, 'message': {'type': 'string'}, 'type': {'type': 'string'}, 'details': {'type': 'object', 'properties': {'guid': {'type': 'string'}, 'rootCause': {'type': 'string'}, 'errorOrigin': {'type': 'string'} } } } } } }, 'PdfSendRequest': {'type': 'object', 'properties': {'data': {'type': 'object', 'properties': {'customerNo': {}, 'cardNumber': {'type': 'string'}, 'currencyType': {'type': 'string'}, 'statementDate': {'type': 'string'}, 'emailAddress': {'type': 'string'} } }, 'call': {'type': 'object', 'properties': {'ani': {'type': 'string'}, 'lang': {'type': 'string'} } } } }, 'PdfSendResponse': {'type': 'object', 'properties': {'data': {'type': 'object', 'properties': {'exitState': {'type': 'string'} } }, 'result': {'type': 'object', 'properties': {'guid': {'type': 'string'}, 'returnCode': {'type': 'string'}, 'messageText': {'type': 'string'}, 'code': {'type': 'string'}, 'message': {'type': 'string'}, 'type': {'type': 'string'}, 'details': {'type': 'object', 'properties': {'guid': {'type': 'string'}, 'rootCause': {'type': 'string'}, 'errorOrigin': {'type': 'string'} } } } } } } }
RESPONSE_OPERATIONS={'cards_list': {'type': 'object', 'properties': {'data': {'type': 'object', 'properties': {'cards': {'type': 'array', 'items': {'type': 'object', 'properties': {'cardNumber': {'type': 'string'}, 'cardNumberLast4': {'type': 'string'}, 'productName': {'type': 'string'}, 'status': {'type': 'string'}, 'isMainCard': {'type': 'boolean'} } } }, 'validCardsCount': {'type': 'integer'}, 'exitState': {'type': 'string'} } }, 'result': {'type': 'object', 'properties': {'guid': {'type': 'string'}, 'returnCode': {'type': 'string'}, 'messageText': {'type': 'string'}, 'code': {'type': 'string'}, 'message': {'type': 'string'}, 'type': {'type': 'string'}, 'details': {'type': 'object', 'properties': {'guid': {'type': 'string'}, 'rootCause': {'type': 'string'}, 'errorOrigin': {'type': 'string'} } } } } } }, 'cards_balance': {'type': 'object', 'properties': {'data': {'type': 'object', 'properties': {'cardNumber': {'type': 'string'}, 'cardNumberLast4': {'type': 'string'}, 'productName': {'type': 'string'}, 'statementDate': {'type': 'string'}, 'lastPayDate': {'type': 'string'}, 'nextStatementDate': {'type': 'string'}, 'nextLastPayDate': {'type': 'string'}, 'debtTL': {'type': 'object', 'properties': {'statementPaymentStatus': {'type': 'string'}, 'transferAmount': {'type': 'number'}, 'statementDebt': {'type': 'number'}, 'minPayment': {'type': 'number'}, 'remainingDebt': {'type': 'number'}, 'remainingMinPayment': {'type': 'number'}, 'currentPeriodExpense': {'type': 'number'}, 'totalDebt': {'type': 'number'}, 'remainAutomaticPaymentAmount': {'type': 'number'}, 'totalDebtPaymentStatus': {'type': 'string'} } }, 'debtUSD': {'type': 'object', 'properties': {'statementPaymentStatus': {'type': 'string'}, 'transferAmount': {'type': 'number'}, 'statementDebt': {'type': 'number'}, 'minPayment': {'type': 'number'}, 'remainingDebt': {'type': 'number'}, 'remainingMinPayment': {'type': 'number'}, 'currentPeriodExpense': {'type': 'number'}, 'totalDebt': {'type': 'number'}, 'remainAutomaticPaymentAmount': {'type': 'number'}, 'totalDebtPaymentStatus': {'type': 'string'} } }, 'debtEUR': {'type': 'object', 'properties': {'statementPaymentStatus': {'type': 'string'}, 'transferAmount': {'type': 'number'}, 'statementDebt': {'type': 'number'}, 'minPayment': {'type': 'number'}, 'remainingDebt': {'type': 'number'}, 'remainingMinPayment': {'type': 'number'}, 'currentPeriodExpense': {'type': 'number'}, 'totalDebt': {'type': 'number'}, 'remainAutomaticPaymentAmount': {'type': 'number'}, 'totalDebtPaymentStatus': {'type': 'string'} } }, 'debtGBP': {'type': 'object', 'properties': {'statementPaymentStatus': {'type': 'string'}, 'transferAmount': {'type': 'number'}, 'statementDebt': {'type': 'number'}, 'minPayment': {'type': 'number'}, 'remainingDebt': {'type': 'number'}, 'remainingMinPayment': {'type': 'number'}, 'currentPeriodExpense': {'type': 'number'}, 'totalDebt': {'type': 'number'}, 'remainAutomaticPaymentAmount': {'type': 'number'}, 'totalDebtPaymentStatus': {'type': 'string'} } }, 'statementPaymentStatus': {'type': 'string'}, 'totalDebtPaymentStatus': {'type': 'string'}, 'automaticPaymentFlag': {'type': 'string'} } }, 'result': {'type': 'object', 'properties': {'guid': {'type': 'string'}, 'returnCode': {'type': 'string'}, 'messageText': {'type': 'string'}, 'code': {'type': 'string'}, 'message': {'type': 'string'}, 'type': {'type': 'string'}, 'details': {'type': 'object', 'properties': {'guid': {'type': 'string'}, 'rootCause': {'type': 'string'}, 'errorOrigin': {'type': 'string'} } } } } } }, 'statement_week_get': {'type': 'object', 'properties': {'data': {'type': 'object', 'properties': {'cardNumber': {'type': 'string'}, 'cardNumberLast4': {'type': 'string'}, 'productName': {'type': 'string'}, 'statementWeek': {'type': 'integer'}, 'statementDay': {'type': 'integer'}, 'statementDate': {'type': 'string'}, 'lastPayDate': {'type': 'string'}, 'nextStatementDate': {'type': 'string'}, 'nextLastPayDate': {'type': 'string'}, 'relationType': {'type': 'string'}, 'relatedCardNumber': {'type': 'string'}, 'relatedCardProductName': {'type': 'string'} } }, 'result': {'type': 'object', 'properties': {'guid': {'type': 'string'}, 'returnCode': {'type': 'string'}, 'messageText': {'type': 'string'}, 'code': {'type': 'string'}, 'message': {'type': 'string'}, 'type': {'type': 'string'}, 'details': {'type': 'object', 'properties': {'guid': {'type': 'string'}, 'rootCause': {'type': 'string'}, 'errorOrigin': {'type': 'string'} } } } } } }, 'statement_week_decide': {'type': 'object', 'properties': {'data': {'type': 'object', 'properties': {'statementDate': {'type': 'string'}, 'statementDueDate': {'type': 'string'}, 'statementDay': {'type': 'integer'}, 'responseCode': {'type': 'integer'}, 'responseMessage': {'type': 'string'} } }, 'result': {'type': 'object', 'properties': {'guid': {'type': 'string'}, 'returnCode': {'type': 'string'}, 'messageText': {'type': 'string'}, 'code': {'type': 'string'}, 'message': {'type': 'string'}, 'type': {'type': 'string'}, 'details': {'type': 'object', 'properties': {'guid': {'type': 'string'}, 'rootCause': {'type': 'string'}, 'errorOrigin': {'type': 'string'} } } } } } }, 'statement_week_change': {'type': 'object', 'properties': {'data': {'type': 'object', 'properties': {'responseCode': {'type': 'integer'}, 'responseMessage': {'type': 'string'}, 'statementWeek': {'type': 'string'}, 'statementDay': {'type': 'string'}, 'exitState': {'type': 'string'} } }, 'result': {'type': 'object', 'properties': {'guid': {'type': 'string'}, 'returnCode': {'type': 'string'}, 'messageText': {'type': 'string'}, 'code': {'type': 'string'}, 'message': {'type': 'string'}, 'type': {'type': 'string'}, 'details': {'type': 'object', 'properties': {'guid': {'type': 'string'}, 'rootCause': {'type': 'string'}, 'errorOrigin': {'type': 'string'} } } } } } }, 'contact_email_get': {'type': 'object', 'properties': {'data': {'type': 'object', 'properties': {'communicationType': {'type': 'string'}, 'ibanCountryCode': {'type': 'string'}, 'ibanAreaCode': {'type': 'string'}, 'ibanPhoneNum': {'type': 'string'}, 'ibanEmail': {'type': 'string'}, 'ttsEmail': {'type': 'string'}, 'commGramType': {'type': 'string'}, 'exitState': {'type': 'string'} } }, 'result': {'type': 'object', 'properties': {'guid': {'type': 'string'}, 'returnCode': {'type': 'string'}, 'messageText': {'type': 'string'}, 'code': {'type': 'string'}, 'message': {'type': 'string'}, 'type': {'type': 'string'}, 'details': {'type': 'object', 'properties': {'guid': {'type': 'string'}, 'rootCause': {'type': 'string'}, 'errorOrigin': {'type': 'string'} } } } } } }, 'statement_pdf_send': {'type': 'object', 'properties': {'data': {'type': 'object', 'properties': {'exitState': {'type': 'string'} } }, 'result': {'type': 'object', 'properties': {'guid': {'type': 'string'}, 'returnCode': {'type': 'string'}, 'messageText': {'type': 'string'}, 'code': {'type': 'string'}, 'message': {'type': 'string'}, 'type': {'type': 'string'}, 'details': {'type': 'object', 'properties': {'guid': {'type': 'string'}, 'rootCause': {'type': 'string'}, 'errorOrigin': {'type': 'string'} } } } } } } }
import json, re, datetime

def obj(v, fallback):
    if isinstance(v, (dict, list)): return v
    try: return json.loads(v)
    except Exception: return fallback

def norm(v):
    return str(v or '').replace('İ','i').replace('I','ı').lower().strip()

def integer(n):
    n=int(n)
    ones=['','bir','iki','üç','dört','beş','altı','yedi','sekiz','dokuz']
    tens=['','on','yirmi','otuz','kırk','elli','altmış','yetmiş','seksen','doksan']
    if n==0:return 'sıfır'
    def small(k):
        return ' '.join(x for x in [(('' if k//100==1 else ones[k//100]+' ')+'yüz') if k>=100 else '',tens[(k%100)//10],ones[k%10]] if x)
    parts=[]
    for power,label in [(1000000000000,'trilyon'),(1000000000,'milyar'),(1000000,'milyon'),(1000,'bin')]:
        k=n//power
        if k: parts.append((integer(k)+' ' if not(power==1000 and k==1) else '')+label);n%=power
    if n:parts.append(small(n))
    return ' '.join(parts)

def money(v,c):
    # Decimal digits are taken from JSON's decimal representation, never rounded.
    t=str(v)
    if not re.fullmatch(r'-?\d+(?:\.\d{1,2})?',t): raise ValueError('amount precision')
    if t.startswith('-'):return 'alacak bakiyesi'
    a,_,b=t.partition('.'); b=(b+'00')[:2]
    unit={'TL':'Türk Lirası','USD':'Dolar','EUR':'Euro','GBP':'İngiliz Sterlini'}[c]
    return integer(int(a))+' '+unit+((' '+integer(int(b))+' '+('kuruş' if c=='TL' else 'peni' if c=='GBP' else 'sent')) if int(b) else '')

def date(v):
    if not v:return ''
    d=datetime.datetime.strptime(str(v),'%d.%m.%Y').date()
    months=['Ocak','Şubat','Mart','Nisan','Mayıs','Haziran','Temmuz','Ağustos','Eylül','Ekim','Kasım','Aralık']
    return str(d.day)+' '+months[d.month-1]+' '+str(d.year)

def digits(v):
    words=['sıfır','bir','iki','üç','dört','beş','altı','yedi','sekiz','dokuz']
    return ' '.join(words[int(x)] for x in str(v) if x.isdigit())

def eligible(s):return [c for c in s.get('cards',[]) if str(c.get('isMainCard','')).lower() in ('true','1')]
def card(s):return next((c for c in eligible(s) if c['cardNumber']==s.get('card')), {})
def intro(s):
    c=card(s)
    return 'Sonu '+digits(c.get('cardNumberLast4',''))+' ile biten '+((c.get('productName','')+' ') if c.get('productName') else '')+'kartınız'

def join_names(xs):
    if len(xs)<2:return ''.join(xs)
    return ', '.join(xs[:-1])+' ve '+xs[-1]

def say(s,phase,line):
    s['phase']=phase;s['line']=line;s['route']='listen'
    questions={'select':'Hangi kartınızı seçersiniz?','last4':'Kartınızın son dört hanesini söyler misiniz?','last6':'Kartınızın son altı hanesini söyler misiniz?','full_number':'Kart numaranızı söyler misiniz?','another':'Başka bir kartınızın borcunu öğrenmek ister misiniz?','scope':'Ana menüye aktarılmak ister misiniz?','offer':'Hangi ekstre işlemini tercih edersiniz?','email_confirm':'Kayıtlı adrese gönderimi onaylıyor musunuz?','latest_accept':'Son ekstrenizi kayıtlı adrese göndermemi ister misiniz?','week_start':'Hesap kesim haftanızı değiştirmek ister misiniz?','week_select':'Sunulan haftalardan hangisini seçersiniz?','week_confirm':'Okuduğum yeni tarihlerle değişikliği onaylıyor musunuz?'}
    s['short_question']=questions.get(phase,line)
    if s.get('question_key')!=phase:
        s['tries']=0;s['format_tries']=0;s['question_key']=phase
    s['revision']=s.get('revision',0)+1
    return s

def finish(s,destination,line,reason):
    s['route']='finish';s['destination']=destination;s['line']=line;s['reason']=reason;s['authorization']=''
    return s

def menu(s,prefix=''):
    return finish(s,'MAIN_MENU',prefix+'Sizi ana menüye yönlendiriyorum.','normal')

def fail(s,op):
    prefix='Şu anda hesap kesim tarihinizi değiştiremiyorum, ' if op.startswith('statement_week') else 'Şu anda işleminizi gerçekleştiremiyorum, '
    return finish(s,'AGENT',prefix+'sizi müşteri temsilcimize aktarıyorum.','service_error')

def dispatch(s,op):
    s['route']=op;s['pending']=op;s['authorization']='consumed' if op in ('statement_week_change','statement_pdf_send') else ''
    vars['bank_receipt']='';vars['receipt_operation']='';vars[op+'_payload']=''
    clear_response(op)
    return s

def clear_response(op):
    # Explicit neutral patches: removing local keys does not clear the provider store.
    for key in list(vars):
        if key==op+'_response' or key.startswith(op+'_response.') or key==op+'_status_code' or key==op+'_payload' or key.startswith(op+'_payload.'):
            vars[key]=''

def provider_receipt(op):
    root=obj(vars.get(op+'_response'),{})
    root=dict(root) if isinstance(root,dict) else {}
    prefix=op+'_response.'
    tree={}
    for key,value in list(vars.items()):
        if not key.startswith(prefix) or value=='':continue
        parts=key[len(prefix):].split('.')
        cur=tree
        for part in parts[:-1]:
            if part not in cur or not isinstance(cur[part],dict):cur[part]={}
            cur=cur[part]
        cur[parts[-1]]=value
    def materialize(value):
        if not isinstance(value,dict):return value
        if value and all(k.isdigit() for k in value):
            indexes=sorted(int(k) for k in value)
            if indexes!=list(range(len(indexes))):raise ValueError('incomplete provider array')
            return [materialize(value[str(i)]) for i in indexes]
        return {k:materialize(v) for k,v in value.items()}
    def merge(a,b):
        for k,v in b.items():
            if isinstance(v,dict) and isinstance(a.get(k),dict):merge(a[k],v)
            else:a[k]=v
        return a
    root=merge(root,materialize(tree))
    if not root.get('status_code'):root['status_code']=vars.get(op+'_status_code','')
    body=obj(root.get('data'),{})
    if not body:
        payload=obj(vars.get(op+'_payload'),{})
        if payload:body={'data':payload}
    root['data']=body
    def typed(value,schema):
        if '$ref' in schema:schema=RESPONSE_SCHEMAS[schema['$ref'].split('/')[-1]]
        typ=schema.get('type')
        if isinstance(value,dict):return {k:typed(v,schema.get('properties',{}).get(k,{})) for k,v in value.items()}
        if isinstance(value,list):return [typed(v,schema.get('items',{})) for v in value]
        if value is None:return None
        if typ=='boolean':
            if str(value).lower() not in ('true','false'):raise ValueError('invalid bank boolean')
            return str(value).lower()=='true'
        if typ in ('number','integer'):
            if not re.fullmatch(r'-?\d+(?:\.\d+)?',str(value)):raise ValueError('invalid bank number')
            return int(value) if typ=='integer' else float(value)
        if typ=='string':return str(value)
        return value
    root['data']=typed(body,RESPONSE_OPERATIONS[op])
    return root

def selection(s, prefix=''):
    names=list(dict.fromkeys(c.get('productName') or 'sonu '+digits(c['cardNumberLast4'])+' ile biten kart' for c in eligible(s)))
    return say(s,'select',prefix+'Hangi kartınızın borcunu öğrenmek istersiniz? '+('Örneğin, '+join_names(names[:2])+' diyebilirsiniz.' if names else ''))

def retry(s, question=None, formatting=False):
    key='format_tries' if formatting else 'tries';s[key]=s.get(key,0)+1
    if s[key]>=3:return finish(s,'MAIN_MENU','Size şu anda yardımcı olamıyorum. Sizi ana menüye aktarıyorum.','format_exhausted' if formatting else 'tries_exhausted')
    q=question or s.get('line','Hangi işlemi tercih edersiniz?')
    if s[key]==2:
        if s['phase'] in ('email_confirm','week_confirm','week_start','latest_accept','scope','another'):
            q='Onaylıyorsanız evet, istemiyorsanız hayır diyebilirsiniz. '+s.get('short_question',q)
        elif s['phase']=='week_select':
            opts=[i for i in range(1,5) if i!=int(s['week']['statementWeek'])]
            q='Lütfen '+join_names([integer(i) for i in opts])+' haftalarından birini seçin.'
        elif s['phase'] in ('select','last4','last6','full_number'):
            q='Kart adını söyleyerek de seçebilirsiniz. '+selection(dict(s))['line']
    return say(s,s['phase'],q)

def resolve(s,ref,ds):
    cs=eligible(s)
    if s.get('candidates'):cs=[c for c in cs if c['cardNumber'] in s['candidates']]
    if ds:
        if len(ds)==4:return [c for c in cs if str(c['cardNumberLast4'])==ds]
        if len(ds) in (6,16):return [c for c in cs if '*' not in str(c['cardNumber']) and str(c['cardNumber']).endswith(ds)]
        return []
    if not ref:return []
    exact=[c for c in cs if norm(c.get('productName'))==norm(ref)]
    return exact or [c for c in cs if norm(ref) in norm(c.get('productName'))]

def select_reply(s,e):
    ref=e.get('card_reference','');ds=e.get('card_digits','')
    if e['act']=='all_cards':return retry(s,'Her seferinde bir kartın borcunu okuyabilirim. Hangi kartınızı seçersiniz?')
    if ds and (not re.fullmatch(r'\d{4}|\d{6}|\d{16}',ds)):return retry(s,'Kartınızın istenen son hanelerini tamamlar mısınız?',True)
    matches=resolve(s,ref,ds)
    if len(matches)==1:
        s['card']=matches[0]['cardNumber'];s['candidates']=[];s['balance']={};s['week']={};s['preview']={};s['readback']=''
        return dispatch(s,'cards_balance')
    if len(matches)>1:
        s['candidates']=[c['cardNumber'] for c in matches]
        if ds and len(ds)==4:return say(s,'last6','Son dört hanesi '+digits(ds)+' olan birden fazla kartınız var. Kartınızın son altı hanesini söyler misiniz?')
        if ds and len(ds)==6:return say(s,'full_number','Son altı hanesi aynı olan birden fazla kartınız var. Kart numaranızı söyler misiniz?')
        return say(s,'last4',join_names(list(dict.fromkeys(c.get('productName','') for c in matches)))+' isimli birden fazla kartınız var. Kartınızın son dört hanesini söyler misiniz?')
    if ds and len(ds)>=6 and any('*' in c['cardNumber'] for c in eligible(s)):
        return retry(s,'Bu kartların gizli hanelerini karşılaştıramıyorum. Farklı bir kart adıyla seçim yapabilir misiniz?')
    if ref and any(norm(ref) in norm(c.get('productName')) for c in s.get('cards',[]) if c not in eligible(s)):
        return retry(s,'Bu ek kart için uygun bir kartınız bulunmuyor. Farklı bir kartınızı seçer misiniz?')
    return retry(s,'Bu seçimle uygun bir kart bulamadım. '+selection(dict(s))['line'])

def debt_reading(s):
    b=s['balance']; today=datetime.date.fromisoformat(str(vars.get('now'))[:10])
    sd=datetime.datetime.strptime(b['statementDate'],'%d.%m.%Y').date() if b.get('statementDate') else None
    next_sd=datetime.datetime.strptime(b['nextStatementDate'],'%d.%m.%Y').date() if b.get('nextStatementDate') else None
    due=datetime.datetime.strptime(b['lastPayDate'],'%d.%m.%Y').date() if b.get('lastPayDate') else None
    s['no_statement_debt']=b.get('statementPaymentStatus')=='NO_DEBT'
    blocks=[(cc,b.get('debt'+cc)) for cc in ('TL','USD','EUR','GBP') if isinstance(b.get('debt'+cc),dict) and b.get('debt'+cc)]
    names={'TL':'Türk Lirası','USD':'Dolar','EUR':'Euro','GBP':'İngiliz Sterlini'}
    due_line=('Borçlarınız için son ödeme tarihiniz bugündür.' if due==today else 'Borçlarınız için son ödeme tarihiniz '+date(b['lastPayDate'])+'.') if due else ''
    requested=s.get('detail','')
    if requested=='due':return intro(s)+' için '+due_line if due_line else intro(s)+' için son ödeme tarihi bilgisi bulunmuyor.'
    if requested in ('minimum','remaining','total'):
        cc=s.get('currency') or 'TL';d=b.get('debt'+cc)
        if not isinstance(d,dict):return intro(s)+' için bu para biriminde bilgi bulunmuyor.'
        k={'minimum':'minPayment','remaining':'remainingDebt','total':'totalDebt'}[requested]
        return intro(s)+' için '+{'minimum':'minimum ödeme tutarı ','remaining':'kalan toplam borç ','total':'toplam borç '}[requested]+money(max(0,d[k]),cc)+'.'
    if not sd and next_sd!=today:
        text=intro(s)+'ın henüz kesilmiş bir ekstresi olmadığı için ekstre borcunuz bulunmamaktadır.'
        if b.get('nextStatementDate'):text+=' İlk hesap kesim tarihiniz '+date(b['nextStatementDate'])+' olacak.'
        return text
    if next_sd==today or (due and today>due):
        text=intro(s)+'. '+('Hesap kesim tarihiniz bugün, ekstreniz saat 00.00 itibarıyla kesilecek.' if next_sd==today else 'Son ödeme tarihiniz geçmiştir.')
        for cc,d in blocks:
            text+=' '+names[cc]+' toplam borcunuz '+money(d['totalDebt'],cc)+'.' if d['totalDebt']>0 else ' '+names[cc]+' borcunuz bulunmamaktadır.'
        if due and today>due and b.get('automaticPaymentFlag')=='Y' and b.get('debtTL',{}).get('remainAutomaticPaymentAmount',0)>0:
            text+=' Otomatik ödemenizden kalan tutar '+money(b['debtTL']['remainAutomaticPaymentAmount'],'TL')+'.'
        return text
    if s['no_statement_debt']:
        text=intro(s)+'ın '+date(b['statementDate'])+' tarihli ekstresinden borcunuz bulunmamaktadır.'
        if b.get('debtTL',{}).get('totalDebt') is not None:
            t=b['debtTL']['totalDebt'];text+=' Gelecek dönemler dahil '+('toplam borcunuz '+money(t,'TL') if t>=0 else 'alacak bakiyeniz '+money(abs(t),'TL'))+'.'
        if due:text+=' Son ödeme tarihiniz '+date(b['lastPayDate'])+' olacaktır.'
        return text
    lines=[];clear=[]
    for cc,d in blocks:
        if d['remainingDebt']<=0:clear.append(names[cc]);continue
        x=names[cc]+' borcunuz '+money(d['statementDebt'],cc)
        if cc=='TL':
            if d['remainingMinPayment']<=0:x+=', kalan toplam borcunuz '+money(d['remainingDebt'],cc)+'. Minimum ödemenizi yaptığınız için teşekkür ederiz.'
            elif d['remainingMinPayment']>=d['minPayment']:x+=', ödenmesi gereken minimum tutar '+money(d['minPayment'],cc)+'.'
            else:x+=', ödenmesi gereken minimum tutar '+money(d['minPayment'],cc)+', kalan toplam borcunuz '+money(d['remainingDebt'],cc)+', kalan minimum ödeme tutarınız '+money(d['remainingMinPayment'],cc)+'.'
        else:x+=', kalan toplam borcunuz '+money(d['remainingDebt'],cc)+', ödenmesi gereken minimum tutar '+money(d['minPayment'],cc)+'.'
        lines.append(x)
    text=intro(s)+'a ait '+date(b['statementDate'])+' tarihinde kesilen ekstre '+(' '.join(lines) if lines else 'borcunuz bulunmamaktadır.')
    transferred=[names[cc] for cc,d in blocks if cc!='TL' and d.get('transferAmount',0)>0]
    if transferred:text=intro(s)+'. '+join_names(transferred)+' borcunuz Türk Lirasına aktarılmıştır. '+text
    if clear and lines:text+=' '+join_names(clear)+' borcunuz bulunmamaktadır.'
    return text+' '+due_line

def after_reading(s,prefix=''):
    s['seen']=list(dict.fromkeys(s.get('seen',[])+[s['card']]))
    unread=[c for c in eligible(s) if c['cardNumber'] not in s['seen']]
    if s.get('detail'):s['detail']='';s['currency']=''
    s['prefix']=prefix
    if unread:return say(s,'another',prefix+' Başka bir kartınızın borcunu öğrenmek ister misiniz?')
    if s.get('no_statement_debt'):return menu(s,prefix+' ')
    s['prefix']=prefix;return dispatch(s,'contact_email_get')

def email_question(s,prefix=''):
    em=s.get('contact',{}).get('ibanEmail','')
    if not em or s.get('contact',{}).get('communicationType')=='Phone':
        return offer(s,prefix+'Bankamızda kayıtlı bir e-posta adresiniz bulunmadığı için ekstrenizi gönderemiyorum. ')
    if not s.get('balance',{}).get('statementDate'):
        return menu(s,prefix+'Henüz kesilmiş bir ekstreniz bulunmadığı için gönderim yapamıyorum. ')
    display=s['contact'].get('ttsEmail') or em
    if len(display)>40:
        display=em[0]+' ile başlayan '+em.split('@')[-1]+' adresiniz'
    s['readback']={'operation':'statement_pdf_send','card':s['card'],'email':em,'date':s['balance']['statementDate'],'currency':s.get('currency') or 'TL'}
    return say(s,'email_confirm',prefix+'Ekstrenizi '+display+' adresine göndermemi ister misiniz?')

def offer(s,prefix=''):
    em=s.get('contact',{}).get('ibanEmail') and s.get('contact',{}).get('communicationType')!='Phone'
    can=s['card'] not in s.get('changed',[])
    # The contract has no annual entitlement flag. Do not fabricate a pre-check.
    if can and em:line='Hesap kesim tarihinizi yılda bir kez değiştirebilirsiniz; yıllık hakkınız uygunsa hesap kesim tarihinizi değiştirebilirim ya da ekstrenizi kayıtlı mail adresinize gönderebilirim. Hangisini tercih edersiniz?'
    elif can:line='Yıllık değişiklik hakkınız uygunsa hesap kesim tarihinizi değiştirebilirim. İster misiniz?'
    elif em:line='Ekstrenizi kayıtlı mail adresinize gönderebilirim. İster misiniz?'
    else:return menu(s,prefix)
    return say(s,'offer',prefix+line)

def week_options(s,prefix=''):
    opts=[i for i in range(1,5) if i!=int(s['week']['statementWeek'])]
    return say(s,'week_select',prefix+'Hesap kesim tarihinizi ayın '+join_names([integer(i)+'. haftası' for i in opts])+'na alabilirim. Hangisini tercih edersiniz?')

def current_week(s):
    w=s['week'];line=intro(s)+'ın hesap kesim tarihi her ayın '+integer(w['statementWeek'])+'. haftası olarak tanımlı.'
    if w.get('relationType') in ('M','C'):
        line+=' '+('Bu karta bağlı ' if w['relationType']=='M' else 'Bu kartın bağlı olduğu ')+str(w.get('relatedCardProductName') or 'kart')+', sonu '+digits(str(w.get('relatedCardNumber',''))[-4:])+' ile biten kartınız da aynı ekstreyi paylaşır.'
    if w.get('nextStatementDate'):line+=' Bir sonraki hesap kesim tarihiniz '+date(w['nextStatementDate'])+'.'
    if w.get('nextLastPayDate'):line+=' Son ödeme tarihiniz '+date(w['nextLastPayDate'])+'.'
    return say(s,'week_start',line+' Hesap kesim tarihinizi değiştirmek ister misiniz?')

def preview_question(s):
    p=s['preview'];w=s['week']
    line='Yeni hesap kesim haftanız her ayın '+integer(s['new_week'])+'. haftası olacak. Yeni hesap kesim tarihiniz '+date(p['statementDate'])+', son ödeme tarihiniz '+date(p['statementDueDate'])+' olacak.'
    if w.get('relationType') in ('M','C'):
        line+=' Bu değişiklik '+('kartınıza bağlı ' if w['relationType']=='M' else 'kartınızın bağlı olduğu ')+str(w.get('relatedCardProductName') or 'diğer')+' kartınızı da etkileyecek.'
    s['readback']={'operation':'statement_week_change','card':s['card'],'week':s['new_week'],'day':w['statementDay'],'statementDate':p['statementDate'],'dueDate':p['statementDueDate']}
    return say(s,'week_confirm',line+' Onaylıyor musunuz?')

def receive(s,op,receipt):
    body=receipt.get('data',{}); body=obj(body,{})
    result=body.get('result',{}) if isinstance(body,dict) else {}
    code=str(result.get('returnCode',''))
    if op=='cards_list' and code=='FB_IVR_CHANNEL_102':return finish(s,'MAIN_MENU','Ekstre borcunu sorgulayabileceğiniz uygun bir kredi kartınız bulunmuyor. Sizi ana menüye aktarıyorum.','no_card')
    if str(receipt.get('status_code',''))!='200' or code!='1' or not isinstance(body.get('data'),dict):return fail(s,op)
    d=body['data']
    if op=='cards_list':
        if not isinstance(d.get('cards'),list):return fail(s,op)
        s['cards']=d['cards']
        if not eligible(s):return finish(s,'MAIN_MENU','Ekstre borcunu sorgulayabileceğiniz uygun bir kredi kartınız bulunmuyor. Sizi ana menüye aktarıyorum.','no_card')
        if len(eligible(s))==1:s['card']=eligible(s)[0]['cardNumber'];return dispatch(s,'cards_balance')
        ref=vars.get('initialCardReference','')
        if ref:
            return select_reply(s,{'act':'select','card_reference':ref,'card_digits':''})
        return selection(s)
    if op=='cards_balance':s['balance']=d;return after_reading(s,debt_reading(s))
    if op=='contact_email_get':
        s['contact']=d;prefix=s.get('prefix','');s['prefix']=''
        if s.get('email_pending'):s['email_pending']=False;return email_question(s,prefix+' ')
        if s.get('week_pending'):s['week_pending']=False;return dispatch(s,'statement_week_get')
        return offer(s,prefix+' ')
    if op=='statement_week_get':s['week']=d;return current_week(s)
    if op=='statement_week_decide':
        if str(d.get('responseCode'))!='0' or not d.get('statementDate') or not d.get('statementDueDate'):return fail(s,op)
        s['preview']=d;return preview_question(s)
    if op=='statement_week_change':
        if d.get('exitState')!='OK' or str(d.get('responseCode'))!='0':return fail(s,op)
        s['changed']=list(dict.fromkeys(s.get('changed',[])+[s['card']]))
        related=s.get('week',{}).get('relatedCardNumber')
        if related:s['changed']=list(dict.fromkeys(s['changed']+[related]))
        p=s['preview']
        return menu(s,intro(s)+'ın hesap kesim haftası her ayın '+integer(s['new_week'])+'. haftası olarak değiştirildi. Yeni hesap kesim tarihiniz '+date(p['statementDate'])+', son ödeme tarihiniz '+date(p['statementDueDate'])+'. ')
    if op=='statement_pdf_send':
        if d.get('exitState')!='DONE':return fail(s,op)
        s['send_count']=s.get('send_count',0)+1
        return menu(s,'Ekstreniz kayıtlı e-posta adresinize gönderildi. ')
    return fail(s,op)

def speech(s,e):
    act=e.get('act','unknown');phase=s['phase'];raw=norm(e.get('raw',''))
    for k,allowed in [('completion',('complete','partial')),('consent',('','explicit','vague','withdrawn')),('currency',('','TL','USD','EUR','GBP')),('detail',('','due','minimum','remaining','total')),('followup',('','email')),('admin',('','ai'))]:
        if e.get(k,'') not in allowed:
            s['authorization']='';return retry(s,s.get('short_question'),True)
    if e.get('completion')!='complete' and act not in ('silence','repeat','aside'):
        s['authorization']='';return retry(s,'Söylemek istediğiniz '+('kartın adını veya istenen hanelerini' if phase in ('select','last4','last6','full_number') else 'yanıtı')+' tamamlar mısınız?',True)
    if act=='third_party':return finish(s,'IVR_LOGIN','Güvenlik nedeniyle yalnızca kendi kartlarınız için işlem yapabilirim. Kart sahibinin kimlik doğrulaması için sizi giriş adımına yönlendiriyorum.','third_party')
    if act=='human':return finish(s,'AGENT','Sizi müşteri temsilcimize aktarıyorum.','human_requested')
    if act=='payment':return finish(s,'AGENT','Borç ödeme işleminiz için sizi müşteri temsilcimize aktarıyorum.','payment')
    if act=='dispute':return finish(s,'AGENT','Bu konuda size müşteri temsilcimiz yardımcı olacak, sizi aktarıyorum.','dispute')
    if act=='non_turkish':return finish(s,'MAIN_MENU','Sizi ana menüye aktarıyorum.','language')
    if act=='silence':
        s['silences']=s.get('silences',0)+1
        if s['silences']>=3:return finish(s,'DISCONNECT','Sesinizi alamadığım için görüşmeyi sonlandırıyorum.','silence')
        return say(s,phase,s.get('short_question') or s['line'])
    s['silences']=0
    if act=='repeat':return say(s,phase,s['line'])
    if act=='aside':return say(s,phase,'Buradayım. '+s['line'])
    if act=='complaint':
        if s.get('calming',0)>=3:return finish(s,'AGENT','Sizi müşteri temsilcimize aktarıyorum.','continued_complaint')
        s['calming']=s.get('calming',0)+1;s['authorization']=''
        return say(s,phase,'Sizi anlıyorum; size yardımcı olmak istiyorum. '+s['line'])
    if act=='secret':return say(s,phase,'Şifre veya tek kullanımlık kod istemiyoruz; lütfen paylaşmayın. '+s['line'])
    if act=='private_digits':return say(s,phase,'Güvenliğiniz için yalnızca kartınızın son dört hanesini paylaşabilirim. '+s['line'])
    if act=='injection':return say(s,phase,'Yalnızca bu hizmet kapsamında yardımcı olabilirim. '+s['line'])
    if act=='other_transaction':return menu(s)
    if act=='out_of_scope':
        s['resume_phase']=phase;s['resume_line']=s['line'];s['resume_tries']=s.get('tries',0);s['authorization']=''
        return say(s,'scope','Size bu konuda yardımcı olamıyorum. Sizi ana menüye aktarmamı ister misiniz?')
    if phase=='scope':
        if act=='yes':return menu(s)
        if act in ('no','continue'):
            saved=s['resume_phase'];line=s['resume_line'];old=s.get('resume_tries',0)
            s=say(s,saved,line);s['tries']=old;return s
        return retry(s,'Ana menüye aktarılmak mı, ekstre işleminize devam etmek mi istersiniz?')
    if act=='done':return menu(s)
    if phase in ('select','last4','last6','full_number'):
        if e.get('followup')=='email':s['email_pending']=True
        if e.get('detail'):s['detail']=e['detail'];s['currency']=e.get('currency','')
        return select_reply(s,e)
    if act=='select' and (e.get('card_reference') or e.get('card_digits')):
        s['candidates']=[];return select_reply(s,e)
    if phase=='another':
        if act=='yes':s['candidates']=[];return selection(s)
        if act=='no':
            if s.get('no_statement_debt'):return menu(s)
            return dispatch(s,'contact_email_get')
        if act in ('email','week'):
            s['email_pending']=act=='email';s['week_pending']=act=='week';s['currency']=e.get('currency') or 'TL'
            return retry(s,'Önce başka bir kartınızın borcunu öğrenmek ister misiniz?')
        return retry(s,'Başka bir kartınızın borcunu öğrenmek ister misiniz?')
    if act=='fact':
        s['detail']=e.get('detail') or 'due';s['currency']=e.get('currency') or 'TL'
        line=debt_reading(s);s['detail']='';s['currency']=''
        return say(s,phase,line+' '+s['line'])
    if phase=='offer':
        if act=='no':return menu(s)
        if act=='email' or (act=='yes' and s['card'] in s.get('changed',[])):
            s['currency']=e.get('currency') or 'TL';return email_question(s)
        if act=='week' or (act=='yes' and not s.get('contact',{}).get('ibanEmail')):
            if s['card'] in s.get('changed',[]):return offer(s,'Hesap kesim tarihinizi yılda bir kez değiştirebilirsiniz; bu hakkı kullandınız. ')
            return dispatch(s,'statement_week_get')
        if act=='past_email':return say(s,'latest_accept','Yalnızca son kesilmiş ekstrenizi gönderebilirim. Son ekstrenizi ister misiniz?')
        if act=='alternate_email':return say(s,'latest_accept','Yalnızca bankamızda kayıtlı adrese gönderebilirim. Kayıtlı adrese göndermemi ister misiniz?')
        if act in ('paper','sms'):return menu(s,'Bu hizmette kâğıt veya kısa mesajla ekstre gönderimi yapamıyorum. ')
        return retry(s,'Ekstrenizi e-posta ile göndermemi mi, hesap kesim haftası değişikliğini mi istersiniz?')
    if phase=='latest_accept':
        if act=='yes':return email_question(s)
        if act=='no':return menu(s)
        return retry(s,'Son ekstrenizi kayıtlı e-posta adresinize göndermemi ister misiniz?')
    if phase=='email_confirm':
        if act in ('no','withdraw'):return menu(s)
        if act=='wrong_email':return menu(s,'Bu görüşmede kayıtlı e-posta adresinizi değiştiremiyorum. ')
        if act in ('past_email','alternate_email'):return say(s,'latest_accept','Yalnızca son ekstrenizi kayıtlı adrese gönderebilirim. Bunu ister misiniz?')
        if act=='yes' and e.get('consent')=='explicit' and not re.search(r'herhalde|belki|sanırım|galiba|ama|vazgeç|onaylam|gönderme|değiştir|\.\.\.|…',raw):
            rb=s.get('readback',{})
            if rb.get('operation')=='statement_pdf_send' and rb.get('card')==s['card'] and rb.get('email')==s['contact']['ibanEmail'] and s.get('send_count',0)<3:
                s['authorized_terms']=rb;return dispatch(s,'statement_pdf_send')
        return retry(s,'Son ekstrenizi az önce belirttiğim kayıtlı e-posta adresine göndermemi açıkça onaylıyor musunuz?',e.get('act')=='unknown')
    if phase=='week_start':
        if act=='no':return menu(s)
        if act in ('yes','week'):return week_options(s)
        return retry(s,'Hesap kesim haftanızı değiştirmek ister misiniz?')
    if phase=='week_select' or (phase=='week_confirm' and act=='week'):
        wk=str(e.get('week',''))
        if not re.fullmatch('[1-4]',wk):return retry(s,week_options(dict(s))['line'])
        if int(wk)==int(s['week']['statementWeek']):return menu(s,'Hesap kesim tarihiniz zaten bu haftada; değişiklik gerekmiyor. ')
        s['new_week']=int(wk);s['preview']={};s['readback']='';return dispatch(s,'statement_week_decide')
    if phase=='week_confirm':
        if act in ('no','withdraw'):return menu(s)
        if act=='yes' and e.get('consent')=='explicit' and not re.search(r'herhalde|belki|sanırım|galiba|ama|vazgeç|onaylam|değiştirme|\.\.\.|…',raw):
            rb=s.get('readback',{})
            if rb.get('operation')=='statement_week_change' and rb.get('card')==s['card'] and rb.get('week')==s['new_week'] and s['card'] not in s.get('changed',[]):
                s['authorized_terms']=rb;return dispatch(s,'statement_week_change')
        return retry(s,'Az önce okuduğum yeni hesap kesim ve son ödeme tarihleriyle değişikliği açıkça onaylıyor musunuz?',act=='unknown')
    return retry(s,formatting=True)

try:
    s=obj(vars.get('bank_state'),{})
    if s:s['invocations']=s.get('invocations',0)+1
    if s.get('invocations',0)>300:
        s=finish(s,'MAIN_MENU','Size şu anda yardımcı olamıyorum. Sizi ana menüye aktarıyorum.','progress_limit')
    if not s:
        s={'phase':'start','route':'cards_list','pending':'cards_list','cards':[],'seen':[],'changed':[],'send_count':0,'tries':0,'silences':0,'calming':0,'revision':0,'line':'','readback':'','authorization':''}
        s=dispatch(s,'cards_list')
        if not re.fullmatch(r'\d{8}',str(vars.get('customerNumber',''))) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T.*',str(vars.get('now',''))):
            s=finish(s,'IVR_LOGIN','Kimlik doğrulama adımına yönlendiriyorum.','missing_ivr_context')
    elif s.get('route')=='finish':
        pass
    elif s.get('pending'):
        op=s['pending'];s['pending']=''
        receipt=obj(vars.get('bank_receipt'),{})
        if vars.get('receipt_operation')!=op or not receipt:
            receipt=provider_receipt(op)
        clear_response(op)
        s=receive(s,op,receipt)
        vars['bank_receipt']='';vars['receipt_operation']=''
        vars[op+'_payload']=''
    else:
        e={k:vars.get(k,'') for k in ('act','completion','raw','card_reference','card_digits','week','currency','consent','detail','followup','admin')}
        if not e['act']:e['act']='unknown'
        s=speech(s,e)
        if e.get('admin')=='ai':s['admin_pending']=True
    if s.get('admin_pending') and s.get('route') in ('listen','finish'):
        s['line']='Ben Freya Bankın dijital asistanıyım. '+s['line'];s['admin_pending']=False
    vars['bank_state']=json.dumps(s,ensure_ascii=False)
    vars['route']=s['route'];vars['dialogue_line']=s['line'];vars['phase']=s['phase']
    vars['routing_result']=s.get('destination','');vars['exit_reason']=s.get('reason','')
    vars['selected_card']=s.get('card','');vars['new_week']=s.get('new_week',0);vars['statement_day']=s.get('week',{}).get('statementDay',0)
    vars['statement_date']=s.get('balance',{}).get('statementDate','');vars['registered_email']=s.get('contact',{}).get('ibanEmail','')
    vars['send_currency']=s.get('authorized_terms',{}).get('currency','TL')
    vars['card_choices']=json.dumps([{'name':c.get('productName',''),'last4':c.get('cardNumberLast4','')} for c in eligible(s)],ensure_ascii=False)
    for k in ('act','completion','raw','card_reference','card_digits','week','currency','consent','detail','followup','admin'):vars[k]=''
except Exception:
    vars['route']='safe_exit';vars['routing_result']='MAIN_MENU';vars['exit_reason']='controller_format_error';vars['dialogue_line']='Size şu anda yardımcı olamıyorum. Sizi ana menüye aktarıyorum.'
