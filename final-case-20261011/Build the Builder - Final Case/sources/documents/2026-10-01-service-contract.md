# Voice assistant: statement and debt services, service contract

Author: Mert Koç, Integration Architecture, Freya Bank (mert.koc@freyabank.example)
Date: 1 October 2026
Distribution: Selin Aydın, Kerem Yalçın, Burcu Tan (Freya Bank); Deniz Arı (Freya)

> Mert: This is the contract the voice assistant integrates against for the statement / debt use case. It covers only the seven services the assistant calls. Everything about how the call reaches the assistant and how it goes back to the phone menu is Burcu's side and is not in here. If something below disagrees with what you see in the test environment, tell me and I'll check which side is wrong.

## 1. Before you start

- The caller is already identified when the assistant picks up. The phone menu hands over the **customer number** with the call, so there is no customer search service in this contract. Start from `cards.list`.
- Every service is `POST`, JSON in, JSON out, UTF-8.
- Base address for all seven:

```
https://api.freyabank.example/voice/v1/
```

  So the card list is `POST https://api.freyabank.example/voice/v1/cards.list`, and so on.
- Dates are strings in `dd.MM.yyyy` (e.g. `"05.11.2026"`). Amounts are JSON numbers with a dot as decimal separator (`5000.13`), never formatted strings. Do not round them.
- Turning numbers and dates into speech is the assistant's job. The services return raw values only, no sentences meant to be read to the caller (the `messageText` in errors is for logs, please don't read it out).

## 2. Access token

The services sit behind our API gateway. You need a bearer token first.

```
POST https://api.freyabank.example/oauth2/token
Content-Type: application/x-www-form-urlencoded

grant_type=client_credentials&client_id=<client id>&client_secret=<client secret>&scope=voice.statement
```

Answer:

```json
{
  "access_token": "<token>",
  "token_type": "Bearer",
  "expires_in": 1800
}
```

Then on every service call:

| Header | Value |
|---|---|
| `Authorization` | `Bearer <token>` |
| `Content-Type` | `application/json` |
| `Accept` | `application/json` |

The token belongs to the integration (service account), not to the caller. Cache it and get a fresh one when it runs out; don't fetch one per call. Client id and secret: I'll send them over the secure channel, not by e-mail.

(Test environment: the token and headers are not checked there. Send them anyway so nothing changes when we switch.)

## 3. Envelope

### Request

```json
{
  "data": { "...service fields..." },
  "call": { "ani": "<caller's number>", "lang": "tr" }
}
```

`data` carries the fields of each service (section 5). `call` is call metadata we log on our side; nothing in this contract depends on it and the test environment ignores it.

### Response

Every answer has a `result` object. Successful answers also have `data`.

```json
{
  "data": { "...service fields..." },
  "result": {
    "guid": "f0e1d2c3b4a5968778695a4b3c2d0002",
    "returnCode": "1",
    "messageText": "Success",
    "code": "1",
    "message": "Success",
    "type": null,
    "details": {
      "guid": "f0e1d2c3b4a5968778695a4b3c2d0002",
      "rootCause": null,
      "errorOrigin": null
    }
  }
}
```

Success = HTTP 200 and `result.returnCode` is `"1"`. Anything else is an error, see section 4. `guid` is our trace id; if you open a ticket with us, give us the `guid`.

## 4. Errors

Error answers have **no `data` object**, only `result`:

```json
{
  "result": {
    "guid": "f0e1d2c3b4a5968778695a4b3c2d0086",
    "returnCode": "FBE00099",
    "messageText": "Teknik hata: ABORTED: ",
    "code": "FBE00099",
    "message": "Teknik hata: ABORTED: ",
    "type": "ERROR",
    "details": {
      "guid": "f0e1d2c3b4a5968778695a4b3c2d0086",
      "rootCause": "TechnicalError",
      "errorOrigin": "ivr-gateway-test:ivr-channel-v0"
    }
  }
}
```

`returnCode` and `code` always carry the same value, and so do `messageText` and `message`. `type` is `"ERROR"` or `"WARNING"`. `rootCause` and `errorOrigin` are diagnostic strings; log them, don't branch on them.

Codes you can get:

| HTTP | `code` | `type` | When | Services |
|---|---|---|---|---|
| 400 | `INVALID_ARGUMENTS_ERROR` | `ERROR` | A required field is missing or empty (message names the field, e.g. `"card number cannot be empty"`) | all |
| 401 | (gateway) | | Token missing or expired. Get a new token and retry once | all |
| 404 | `FB_IVR_CHANNEL_102` | `WARNING` | Customer has no valid card (message: `"Müşteriye ait geçerli kart bilgisi bulunamadı."`) | `cards.list` |
| 404 | `FB_IVR_CHANNEL_120` | `WARNING` | Card not found | `cards.balance` |
| 404 | `FB_IVR_CHANNEL_121` | `WARNING` | Card not found | `statement.week.get` |
| 404 | `FB_IVR_CHANNEL_107` | `WARNING` | No statement document to send (message: `"Pdf dokümanı bulunamadı"`) | `statement.pdf.send` |
| 500 | `FBE00099` | `ERROR` | Technical error on our side (message: `"Teknik hata: ABORTED: "`) | all |

Note on the `cards.list` 404: it's a WARNING, it means "this customer has no card the assistant can work with", not that the service is broken. How the assistant reacts to that vs. a 500 is for Selin's analysis, I'm only flagging that they are different things.

Timeouts: we haven't agreed a client timeout yet. Most answers are well under a second, but under load (and once in the test data) an answer can take longer than ten seconds and still succeed. Open point, see section 7.

## 5. Services

| # | Service | Called with | Gives back |
|---|---|---|---|
| 5.1 | `cards.list` | customer number | the customer's cards the assistant may talk about |
| 5.2 | `cards.balance` | card number | statement and due dates, debt per currency |
| 5.3 | `statement.week.get` | card number | the card's current statement week and day, joint statement info |
| 5.4 | `statement.week.decide` | card number + requested week | what the dates *would* be with that week (does not change anything) |
| 5.5 | `statement.week.change` | card number + requested week | changes the statement week |
| 5.6 | `contact.email.get` | customer number | registered e-mail / phone |
| 5.7 | `statement.pdf.send` | customer, card, currency, statement date, address | sends the statement PDF by e-mail |

Card number: always send the `cardNumber` **exactly as `cards.list` returned it**. Don't rebuild it from digits the caller says.

### 5.1 `cards.list`

Request:

```json
{
  "data": { "customerNo": "90000001", "aiFlow": "CardOps" },
  "call": { "ani": "<caller's number>", "lang": "tr" }
}
```

`customerNo` may be sent as a string or as a number, both are accepted. `aiFlow` tells us which use case is asking; for this one it's `"CardOps"` (not validated in test).

Response, one card:

```json
{
  "data": {
    "cards": [
      {
        "cardNumber": "540000******1234",
        "cardNumberLast4": "1234",
        "productName": "Yıldız Pratik Classic",
        "status": "A",
        "isMainCard": true
      }
    ],
    "validCardsCount": 1,
    "exitState": "1_CARD"
  },
  "result": { "returnCode": "1", "...": "as in section 3" }
}
```

Response, several cards (abridged):

```json
{
  "data": {
    "cards": [
      { "cardNumber": "540000******4253", "cardNumberLast4": "4253", "productName": "Yıldız Pratik", "status": "A", "isMainCard": true },
      { "cardNumber": "545000******4253", "cardNumberLast4": "4253", "productName": "Yıldız Pratik", "status": "A", "isMainCard": true },
      { "cardNumber": "540000******6184", "cardNumberLast4": "6184", "productName": "Yıldız Pratik", "status": "A", "isMainCard": true },
      { "cardNumber": "540000******8870", "cardNumberLast4": "8870", "productName": "Yıldız Tasarım", "status": "A", "isMainCard": true }
    ],
    "validCardsCount": 4,
    "exitState": "MULTI_CARD"
  },
  "result": { "returnCode": "1", "...": "" }
}
```

- `exitState`: `"1_CARD"` or `"MULTI_CARD"`.
- Only active cards come back (`status` `"A"`). `isMainCard` is `false` for a card that isn't the customer's own main card; it's still in the list.
- Two cards can have the same product name and the same last four digits (see above). Don't assume `cardNumberLast4` is unique.
- `productName` is free text from the card system, whatever was typed in there.
- Masking: in the **test environment** `cardNumber` comes back masked, first 6 and last 4 digits visible (`540000******1234`). What production returns in this field I still have to confirm with the card platform team; build so that it works with the masked form.

Errors: 404 `FB_IVR_CHANNEL_102`, 500 `FBE00099`.

### 5.2 `cards.balance`

Request:

```json
{
  "data": { "cardNumber": "540000******1234" },
  "call": { "ani": "<caller's number>", "lang": "tr" }
}
```

Response:

```json
{
  "data": {
    "cardNumber": "5400********1234",
    "cardNumberLast4": "1234",
    "productName": "Yıldız Pratik Classic",
    "statementDate": "05.10.2026",
    "lastPayDate": "15.10.2026",
    "nextStatementDate": "05.11.2026",
    "nextLastPayDate": "15.11.2026",
    "debtTL": {
      "statementPaymentStatus": "HAS_DEBT",
      "transferAmount": 0.0,
      "statementDebt": 5000.13,
      "minPayment": 2000.05,
      "remainingDebt": 5000.13,
      "remainingMinPayment": 2000.05,
      "currentPeriodExpense": 0.0,
      "totalDebt": 5000.13,
      "totalDebtPaymentStatus": "HAS_DEBT",
      "remainAutomaticPaymentAmount": 0.0
    },
    "debtUSD": {
      "statementPaymentStatus": "NO_DEBT",
      "transferAmount": 0.0,
      "statementDebt": 0.0,
      "minPayment": 0.0,
      "remainingDebt": 0.0,
      "remainingMinPayment": 0.0,
      "currentPeriodExpense": 0.0,
      "totalDebt": 0.0,
      "totalDebtPaymentStatus": "NO_DEBT",
      "remainAutomaticPaymentAmount": 0.0
    },
    "debtEUR": { "...": "same fields as debtUSD" },
    "debtGBP": { "...": "same fields as debtUSD" },
    "statementPaymentStatus": "HAS_DEBT",
    "totalDebtPaymentStatus": "HAS_DEBT",
    "automaticPaymentFlag": "N"
  },
  "result": { "returnCode": "1", "...": "" }
}
```

Field notes (my understanding from the card team, Selin please correct me if the business meaning is different):

- `statementDate` / `lastPayDate`: the last issued statement and its due date. `nextStatementDate` / `nextLastPayDate`: the coming ones.
- One block per currency: `debtTL`, `debtUSD`, `debtEUR`, `debtGBP`. **A block can be missing** (some cards have no GBP block at all). Missing block is not the same as a block with `NO_DEBT`; don't invent zeros for it.
- In each block: `statementDebt` is the statement debt, `minPayment` the minimum payment on the statement; `remainingDebt` / `remainingMinPayment` what is left of those after payments made since; `totalDebt` includes spending after the statement; `currentPeriodExpense` that spending; `transferAmount` carried over from the previous period.
- `statementPaymentStatus` / `totalDebtPaymentStatus`: `"HAS_DEBT"` or `"NO_DEBT"`, per block and once more at the top level for the card overall.
- `totalDebt` can be negative (credit balance on that currency). Status is `NO_DEBT` then.
- `automaticPaymentFlag`: `"Y"` / `"N"`. `remainAutomaticPaymentAmount` is only meaningful when it's `"Y"`.
- Heads-up: the `cardNumber` in this answer is masked differently from the card list (first 4 + last 4, `5400********1234`). Don't use it to match against the list; use `cardNumberLast4` or just keep the number you sent.

Errors: 400 `INVALID_ARGUMENTS_ERROR` (empty card number), 404 `FB_IVR_CHANNEL_120`, 500 `FBE00099`. Example 404:

```json
{
  "result": {
    "guid": "<trace id>",
    "returnCode": "FB_IVR_CHANNEL_120",
    "messageText": "Kart bakiye servisi hatası: kart bulunamadı",
    "code": "FB_IVR_CHANNEL_120",
    "message": "Kart bakiye servisi hatası: kart bulunamadı",
    "type": "WARNING",
    "details": { "guid": "<trace id>", "rootCause": "NotFoundException", "errorOrigin": "<gateway>" }
  }
}
```

(The message text here is just my example; only the code matters.)

### 5.3 `statement.week.get`

Request:

```json
{
  "data": { "cardNumber": "540000******3201" },
  "call": { "ani": "<caller's number>", "lang": "tr" }
}
```

Response:

```json
{
  "data": {
    "cardNumber": "540000******3201",
    "cardNumberLast4": "3201",
    "productName": "Yıldız Pratik",
    "statementWeek": 3,
    "statementDay": 16,
    "statementDate": "16.10.2026",
    "lastPayDate": "26.10.2026",
    "nextStatementDate": "16.11.2026",
    "nextLastPayDate": "26.11.2026",
    "relationType": "M",
    "relatedCardNumber": "540000******3202",
    "relatedCardProductName": "Yıldız Premium"
  },
  "result": { "returnCode": "1", "...": "" }
}
```

(Taken from test customer 92220795, who has two cards on one statement.)

- `statementWeek`: 1 to 4, the week of the month the statement is cut. `statementDay`: day of the month. Both numbers here.
- `relationType`: empty string when the card has its own statement. `"M"` or `"C"` when two cards share one statement: `"M"` = this is the main card of the pair, `"C"` = this is the card linked to it. `relatedCardNumber` / `relatedCardProductName` then name the other card; otherwise they are empty strings. Changing the week on either card moves the shared statement, i.e. both cards.
- There is **no field telling you whether the customer can still change the week** (yearly limit etc.). Kerem said the rule lives in the card system and the change call either goes through or it doesn't; I'll ask whether we can expose a flag, no promises.

Errors: 404 `FB_IVR_CHANNEL_121`, 500 `FBE00099`.

### 5.4 `statement.week.decide`

Preview only. Tells you which statement date, due date and day the card would get with the requested week. **It does not change the card.**

Request:

```json
{
  "data": {
    "cardNumber": "540000******1234",
    "newStatementWeek": 2,
    "statementDay": 5
  },
  "call": { "ani": "<caller's number>", "lang": "tr" }
}
```

- `newStatementWeek`: 1-4, number or string both fine.
- `statementDay`: the card's current `statementDay` from `statement.week.get`.
- Asking for the week the card already has: there is nothing to preview, you'll get an error, so don't call it for that.

Response:

```json
{
  "data": {
    "statementDate": "09.11.2026",
    "statementDueDate": "19.11.2026",
    "statementDay": 9,
    "responseCode": 0,
    "responseMessage": "Success"
  },
  "result": { "returnCode": "1", "...": "" }
}
```

`statementDate` / `statementDueDate` are the first statement and due date under the requested week. Note the due date is `statementDueDate` here, not `lastPayDate` like elsewhere (not my naming...). `responseCode` `0` = fine.

Errors: 400 `INVALID_ARGUMENTS_ERROR`, 500 `FBE00099`.

### 5.5 `statement.week.change`

This one changes the card. Call it only after the caller has agreed to the dates from 5.4.

Request:

```json
{
  "data": {
    "cardNumber": "540000******1234",
    "newStatementWeek": 2,
    "statementDay": 5
  },
  "call": { "ani": "<caller's number>", "lang": "tr" }
}
```

`statementDay` is required by the request model even though the backend recalculates the day. Send the current day.

Response:

```json
{
  "data": {
    "responseCode": 0,
    "responseMessage": "00",
    "statementWeek": "2",
    "statementDay": "9",
    "exitState": "OK"
  },
  "result": { "returnCode": "1", "...": "" }
}
```

Careful: `statementWeek` and `statementDay` come back as **strings** here (numbers everywhere else). Ignore `statementDay` in this answer; the dates to tell the caller are the ones from 5.4. Success = `exitState` `"OK"` and `responseCode` `0`.

Errors: 400 `INVALID_ARGUMENTS_ERROR`, 401 (token), 500 `FBE00099`.

### 5.6 `contact.email.get`

Request:

```json
{
  "data": { "customerNo": 90000001, "intAddressInfoType": "E" },
  "call": { "ani": "<caller's number>", "lang": "tr" }
}
```

`intAddressInfoType`: `"E"` e-mail, `"P"` phone, `"B"` both. Empty value gives a 400 (`"intAddressInfoType cannot be empty"`). The test environment returns the same answer whatever you ask for.

Response, e-mail registered:

```json
{
  "data": {
    "communicationType": "Both",
    "ibanCountryCode": "90",
    "ibanAreaCode": "500",
    "ibanPhoneNum": "0000000",
    "ibanEmail": "ornek@freyabank.example",
    "ttsEmail": "ornek@freyabank.example",
    "commGramType": "A",
    "exitState": "Done"
  },
  "result": { "returnCode": "1", "...": "" }
}
```

Response, only a phone registered:

```json
{
  "data": {
    "communicationType": "Phone",
    "ibanCountryCode": "90",
    "ibanAreaCode": "500",
    "ibanPhoneNum": "0000000",
    "ibanEmail": "",
    "ttsEmail": "",
    "commGramType": "A",
    "exitState": "Done"
  },
  "result": { "returnCode": "1", "...": "" }
}
```

- The registered e-mail is `ibanEmail`. `ttsEmail` is the same address prepared for reading aloud (today identical in practice).
- No registered e-mail = `communicationType` `"Phone"` and/or empty `ibanEmail`. Check the field, not only the type.
- The `iban*` prefix is historical, it has nothing to do with IBANs.

Errors: 400 `INVALID_ARGUMENTS_ERROR`, 500 `FBE00099`.

### 5.7 `statement.pdf.send`

Sends the statement PDF to the address in the request.

Request:

```json
{
  "data": {
    "customerNo": "90000001",
    "cardNumber": "540000******1234",
    "currencyType": "TL",
    "statementDate": "05.10.2026",
    "emailAddress": "ornek@freyabank.example"
  },
  "call": { "ani": "<caller's number>", "lang": "tr" }
}
```

- `statementDate`: the `statementDate` from `cards.balance` (the issued statement).
- `currencyType`: `"TL"`, `"USD"`, `"EUR"` or `"GBP"`.
- `emailAddress`: the backend sends to whatever is in this field. It does **not** check it against the registered address. Whether any address other than the registered one is acceptable is a business/compliance question, Elçin and Selin's call, not mine.

Response:

```json
{
  "data": { "exitState": "DONE" },
  "result": { "returnCode": "1", "...": "" }
}
```

Errors: 400 `INVALID_ARGUMENTS_ERROR`, 404 `FB_IVR_CHANNEL_107` (no PDF for that statement), 500 `FBE00099`. Example 404:

```json
{
  "result": {
    "guid": "f0e1d2c3b4a5968778695a4b3c2d0466",
    "returnCode": "FB_IVR_CHANNEL_107",
    "messageText": "Pdf dokümanı bulunamadı",
    "code": "FB_IVR_CHANNEL_107",
    "message": "Pdf dokümanı bulunamadı",
    "type": "WARNING",
    "details": {
      "guid": "f0e1d2c3b4a5968778695a4b3c2d0466",
      "rootCause": "com.freyabank.ivrgateway.ivrchannel.rest.exception.NotFoundException",
      "errorOrigin": "ivr-gateway-test:ivr-channel-v0"
    }
  }
}
```

## 6. Test environment

- Same paths and shapes as above. The synthetic customers and every answer they get are in `test-environment/test-customers.json` (overview in `test-environment/test-customers.md`). Nothing in there is a real person or card.
- If you build your own mock, it has to return those answers exactly (status code and body). For a customer or card that isn't in the file, return the 404 for that service from section 4 (for services without a 404 there, a 400 `INVALID_ARGUMENTS_ERROR` body).
- Only the `data` fields decide the answer in test. Token, headers and `call` are not checked.

## 7. Open points (as of today)

1. Client timeout and retry policy: not agreed. My suggestion is no automatic retry on `statement.week.change` and `statement.pdf.send` (both have side effects).
2. Card number masking in production `cards.list`: confirming with the card platform team.
3. A flag for "can still change the statement week this year": asked, no answer.
4. Rate limits per client: will share when the gateway team sets them up. Shouldn't matter at pilot volume.

Mert
