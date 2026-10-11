# Statement debt by voice: analysis for the Freya build

Freya Bank, Card Self-Service
Owner: Selin Aydın
Reviewers: Kerem Yalçın (card payments), Burcu Tan (IVR operations), Elçin Ural (compliance), Mert Koç (services)
For: Deniz Arı, Ozan Er (Freya)
Date: 8 October 2026

| Date | Note |
|---|---|
| 2 Sep 2026 | First write-up after the two IVR walkthroughs. |
| 29 Sep 2026 | Answers from the kickoff question thread with Deniz (identity, payments, e-mail) worked in. |
| 1 Oct 2026 | Service names aligned with Mert's contract of 1 Oct. |
| 8 Oct 2026 | Edge cases reworked after the 7 Oct session. Reading rules, card selection and statement week sections rewritten. Short note on the branches we added (section 9). |

> Deniz, Ozan: I went through my notes from Wednesday and the edge cases are mostly redone. I have not got to everything from the session yet (Elçin's notes came in late), so if something here disagrees with what we said on the 7th, tell me and I'll fix it. Turkish in quotes is what the assistant says; the rest is for us.

---

## 1. What the step does, in one breath

The caller asks for their statement debt in the phone menu and is handed to the assistant, already identified. The assistant finds the card, reads that card's statement debt per currency and the due date, then offers what can still be done on the call: move the statement week, or e-mail the statement to the address we hold. Payments and disputes go to an agent. Everything else goes back to the main menu.

Not in this step: interest and late-payment rates, available limit, Yıldız points and miles, spending lines, instalments, loan questions, card blocking, address changes, statements of earlier months. Section 8 says how the assistant deals with these.

## 2. Before the first sentence

- The IVR has done the full identity step. We pass the customer number with the call. The assistant does **not** ask for any code, PIN or date of birth. (The box for a second check on the flow drawing was never built, Burcu confirmed on 28 Sep.)
- The assistant works only for the caller's own cards. Someone phoning about a relative's card: see 8.5.
- Services, all under `https://api.freyabank.example/voice/v1/` (details in Mert's contract):

| Service | What we take from it |
|---|---|
| `cards.list` | eligible credit cards: `productName`, `cardNumberLast4`, `cardNumber`, `isMainCard`, `validCardsCount` |
| `cards.balance` | per-currency blocks `debtTL`, `debtUSD`, `debtEUR`, `debtGBP`; `statementDate`, `lastPayDate`, `nextStatementDate`, `nextLastPayDate`, `statementPaymentStatus`, `automaticPaymentFlag` |
| `statement.week.get` | `statementWeek`, `statementDay`, `relationType`, `relatedCardProductName`, next dates |
| `statement.week.decide` | preview of the dates for a chosen week (`statementDate`, `statementDueDate`, `statementDay`); changes nothing |
| `statement.week.change` | makes the change |
| `contact.email.get` | `ibanEmail`, `communicationType` |
| `statement.pdf.send` | sends the statement PDF to the registered address |

- Card numbers: the card number comes back masked from the services (first six and last four visible on the card list). We only ever need the last four for speech, so this is fine for us.
- A `cards.list` answer of "no valid card for this customer" (the 404 warning in Mert's table) is the no-eligible-card case below, not a broken service. A 500 or a timeout is a broken service.

## 3. Card

### 3.1 Picking the card

1. Call `cards.list`.
2. No eligible card: “Ekstre borcunu sorgulayabileceğiniz uygun bir kredi kartınız bulunmuyor. Sizi ana menüye aktarıyorum.” End.
3. One eligible card: it is the card. No question, go to the debt.
4. More than one: “Hangi kartınızın borcunu öğrenmek istersiniz? Örneğin, [kart adı] veya [kart adı] diyebilirsiniz.” At most two examples, and only names from this caller's own list. Never a card name the caller does not have.
5. If the caller already said a card name when they arrived and it fits exactly one card, skip the question and read that card.

Once the card is settled there is no "carrying on with your … card" line and no "is that right?". The card name comes at the start of the reading anyway.

### 3.2 Two cards with the same name

Reworked on 7 Oct, three steps:

| Step | When | Assistant says |
|---|---|---|
| a | two or more cards with the name the caller gave | “[kart adı] isimli birden fazla kartınız var. Kartınızın son dört hanesini söyler misiniz?” e.g. “Yıldız isimli birden fazla kartınız var. Kartınızın son dört hanesini söyler misiniz?” |
| b | the last four are the same on two cards too | “Son dört hanesi 4253 olan birden fazla kartınız var. Kartınızın son altı hanesini söyler misiniz?” (caller's own four digits in place of 4253) |
| c | the last six are the same as well | “Son altı hanesi aynı olan birden fazla kartınız var. Kart numaranızı söyler misiniz?” |

Then read the debt of the card that matches.

(Mert: with the masked list I'm not sure step b can tell two cards apart in every case. Leaving the step in, please check.)

### 3.3 When the answer doesn't settle the card

- **Name half-said or described** (a colour, "the travel one", only the brand): if it fits several cards, read back just those names; if it fits none, read all the names again, and that uses up one try. A card we don't have on the list at all (another bank's, one that's been closed): tell them there's no card under that name and read the eligible ones again.
- **"All of them, please":** we can't, the balance service works one card at a time. Put the selection question from 3.1 again; this costs a try just like an answer we can't use, and when the three are gone: “Size şu anda yardımcı olamıyorum. Sizi ana menüye aktarıyorum.”
- **Digits:** however the caller says them (digit by digit, in pairs, as one big number), we turn them into the four digits, e.g. 4253, and go straight to that card's debt. Wrong digits or "I don't have the card on me": ask again (for the digits, or for the card name if they can't give digits), three tries, then the main menu. If they read out the whole card number we find the card from it. Whatever they said, four digits, six or all sixteen, the assistant does not say it back to them.
- **Switching:** a caller who picks a card and then wants a different one goes back to selection. After a reading, a question about another of their cards also goes back to selection, and we read that second card.
- **Supplementary card only** (`isMainCard` false): tell them there is no eligible card for this and ask them to choose a different one.
- **No product name from the service:** the card is introduced by its last four only, “Sonu 4253 ile biten kartınıza ait …”

## 4. Reading the debt

### 4.1 Order

Kerem and I agreed this order on 7 Oct; it is the order for every reading:

1. Card introduction and the statement closing date
2. Turkish Lira debt
3. Dollar, then Euro, then İngiliz Sterlini debts
4. The currencies with no debt, in one sentence
5. Remaining automatic payment amount (only when it applies, 4.6)
6. Due date
7. "Another card?" question, if the caller has more than one eligible card
8. The offer (section 5), with only the options the caller can actually use

### 4.2 Card introduction and the closing date

Every reading opens with “Sonu [son 4 hane] ile biten [kart adı]”, every time, also on the second card in the same call. The closing date goes at the start of the **first** currency that is read:

“Sonu 9012 ile biten Yıldız Miles Platinum kartınıza ait 21 Ekim 2025 tarihinde kesilen ekstre Türk Lirası borcunuz …”

If there is no Turkish Lira debt, the same opening goes in front of the first foreign currency instead.

### 4.3 Turkish Lira

Pick the sentence by what the caller has paid since the statement (fields from `debtTL`):

| Case | Rule | Sentence |
|---|---|---|
| Nothing paid | `remainingMinPayment` > 0 and equal to or above `minPayment` | “Türk Lirası borcunuz XXX TL, ödenmesi gereken minimum tutar ZZZ TL'dir.” |
| Minimum or more paid | `remainingDebt` > 0 and `remainingMinPayment` is 0 or less | “Türk Lirası borcunuz XXX TL, kalan toplam borcunuz YYY TL'dir. Minimum ödemenizi yaptığınız için teşekkür ederiz.” |
| Less than the minimum paid | `remainingMinPayment` > 0 and below `minPayment` | “Türk Lirası borcunuz XXX TL, ödenmesi gereken minimum tutar ZZZ TL, kalan toplam borcunuz YYY TL, kalan minimum ödeme tutarınız TTT TL'dir.” |
| No Turkish Lira debt | `remainingDebt` is 0.00 or below | Skip Turkish Lira, go to the foreign currencies. Turkish Lira then goes into the no-debt sentence (4.5). |

XXX `statementDebt`, ZZZ `minPayment`, YYY `remainingDebt`, TTT `remainingMinPayment`.

Edges, because Ozan asked: remaining minimum exactly equal to the minimum → "nothing paid". Remaining minimum exactly zero → "minimum paid". Remaining debt 0,00 → no debt in that currency.

### 4.4 Foreign currencies

One pattern, same for all three, read Dolar → Euro → İngiliz Sterlini:

“Dolar borcunuz XXX USD, kalan toplam borcunuz YYY USD, ödenmesi gereken minimum tutar ZZZ USD'dir.”

Euro and İngiliz Sterlini use the same sentence with their own name and code. No paid / not-paid split for foreign currency.

When some foreign currency debt has been moved over into the Turkish Lira debt (`transferAmount` above zero on that currency's block), the caller should hear which currency that was before the Turkish Lira figures. Ozan, could you draft the line? (Kerem to give me the cases where this really happens; I have seen two in production this year.)

### 4.5 Currencies with no debt

One sentence for all of them together, after the foreign currency lines. If all four have debt, nothing is said here. If none of the four has statement debt, this sentence is not used at all: it is the no-debt reading (4.7).

A currency whose block is missing or empty in `cards.balance` (the card simply doesn't have it) is **left out** of this sentence.

Burcu's menu only had six of these. Grouped by how many currencies are clear:

| No debt in | Assistant says |
|---|---|
| (none, all four owe) | nothing |
| one: Türk Lirası | “Türk Lirası borcunuz bulunmamaktadır.” |
| one: Dolar | “Dolar borcunuz bulunmamaktadır.” |
| one: Euro | “Euro borcunuz bulunmamaktadır.” |
| one: İngiliz Sterlini | “İngiliz Sterlini borcunuz bulunmamaktadır.” |
| two: Türk Lirası, Dolar | “Türk Lirası ve Dolar borcunuz bulunmamaktadır.” |
| two: Türk Lirası, Euro | “Türk Lirası ve Euro borcunuz bulunmamaktadır.” |
| two: Türk Lirası, İngiliz Sterlini | “Türk Lirası ve İngiliz Sterlini borcunuz bulunmamaktadır.” |
| two: Dolar, Euro | “Dolar ve Euro borcunuz bulunmamaktadır.” |
| two: Dolar, İngiliz Sterlini | “Dolar ve İngiliz Sterlini borcunuz bulunmamaktadır.” |
| two: Euro, İngiliz Sterlini | “Euro ve İngiliz Sterlini borcunuz bulunmamaktadır.” |
| three: Türk Lirası, Dolar, Euro | “Türk Lirası, Dolar ve Euro borcunuz bulunmamaktadır.” |
| three: Türk Lirası, Dolar, İngiliz Sterlini | “Türk Lirası, Dolar ve İngiliz Sterlini borcunuz bulunmamaktadır.” |
| three: Türk Lirası, Euro, İngiliz Sterlini | “Türk Lirası, Euro ve İngiliz Sterlini borcunuz bulunmamaktadır.” |
| three: Dolar, Euro, İngiliz Sterlini | “Dolar, Euro ve İngiliz Sterlini borcunuz bulunmamaktadır.” |

Fifteen rows, fourteen sentences. It is "Türk Lirası" in these, never "TL" (see 4.9).

### 4.6 Remaining automatic payment

Only when the due date has passed, the card has an automatic payment instruction (`automaticPaymentFlag` "Y") and `remainAutomaticPaymentAmount` is above zero: the assistant tells the caller how much of the automatic payment is still to be taken, in Turkish Lira. Comes after the no-debt sentence and before the due date.

### 4.7 No statement debt

When `statementPaymentStatus` is NO_DEBT:

“Sonu [son 4 hane] ile biten [kart adı] kartınızın [hesap kesim tarihi] tarihli ekstresinden borcunuz bulunmamaktadır. Gelecek dönemler dahil toplam borcunuz GGG TL'dir. Son ödeme tarihiniz [son ödeme tarihi] olacaktır.”

Then, if the caller has another eligible card: “Başka bir kartınızın borcunu öğrenmek ister misiniz?” Yes → card selection. No, or no other card → main menu.

(Open with Kerem: do we also read the future-period total in foreign currency here, or Turkish Lira only? Today's sentence only has GGG TL. Deniz also suggested making the offer before the main menu in this branch; not agreed yet.)

### 4.8 Due date

“Borçlarınız için son ödeme tarihiniz [son ödeme tarihi]'dir.” (suffix follows the date: 26 Ekim'dir, 1 Kasım'dır …)

If the due date is today, say "bugün" instead of the date: “Borçlarınız için son ödeme tarihiniz bugündür.”

### 4.9 How to say things

- Currency names in full, never the code: TL → Türk Lirası, USD → Dolar, EUR → Euro, GBP → İngiliz Sterlini. This also covers the TL inside the sentences above.
- Turkish Lira amounts: lira and kuruş in full. 1.234.567,89 → “bir milyon iki yüz otuz dört bin beş yüz altmış yedi lira seksen dokuz kuruş”. Big amounts with kuruş are no exception.
- Zero kuruş is not said: 2.500,00 → “İki bin beş yüz Türk Lirası”, never "sıfır kuruş".
- Foreign currency decimals as cent (Dolar, Euro) and peni (İngiliz Sterlini): 7.666,50 USD → “Yedi bin altı yüz altmış altı dolar elli sent”.
- Dates as day, month name, year: 21.10.2025 → “21 Ekim 2025”.
- Last four digits one by one: 4253 → “dört iki beş üç”, 1003 → “bir sıfır sıfır üç”. Not "çift sıfır", not "kırk iki elli üç".
- The full card number is never said, under any circumstance.
- Every amount and date read is exactly what `cards.balance` returned. 1.000 is not rounded to anything, kuruş is not dropped, currencies are not mixed up. If a figure did not come from a service, the assistant does not say it.

### 4.10 Odd values and odd days

- A minus figure means the bank owes the customer; it is never read out as debt. That currency counts as clear, and so does one at exactly 0,00 (it goes into the "borcunuz bulunmamaktadır" sentence).
- A card so new that no statement has been cut yet: tell them there is no debt, and don't invent a date to go with it.
- Phoning on the day the statement is cut: tell them the cut is today and happens at 00.00, then give the total debt. Something like “Hesap kesim tarihiniz bugün, ekstreniz saat 00.00 itibarıyla kesilecek.”
- From the cut date up to the due date: the normal statement reading (4.2 to 4.8).
- After the due date: say it has passed, then give the total debt.
- Due date today: the "bugün" sentence in 4.8.

## 5. After the reading

### 5.1 Another card first

Callers with more than one eligible card get “Başka bir kartınızın borcunu öğrenmek ister misiniz?” **before** the offer. Yes → card selection (3.1) and read that card. When there are no cards left or they say no, go to the offer.

### 5.2 The offer

Only offer what this caller can do. For that we call `contact.email.get` **before** the offer (not after the caller asks for the mail, which is how I had it in September).

| Registered e-mail | Statement week change still possible this year | Offer |
|---|---|---|
| yes | yes | “Hesap kesim tarihinizi değiştirebilirim ya da ekstrenizi kayıtlı mail adresinize gönderebilirim.” |
| no | yes | “Hesap kesim tarihinizi değiştirebilirim.” |
| yes | no | “Ekstrenizi kayıtlı mail adresinize gönderebilirim.” |
| no | no | no offer |

"No registered e-mail" = `ibanEmail` empty, or `communicationType` is phone only. In every case the caller can still say they want nothing else, which takes them to the main menu.

(Whether the yearly change right is already used: Mert has asked the card platform for a flag, no answer yet. See open points.)

### 5.3 What the caller answers

| Answer | Goes to |
|---|---|
| wants the statement mailed | 6 |
| wants to move the statement week | 7 |
| nothing else, thanks, that's all | main menu, “Sizi ana menüye yönlendiriyorum.” |
| wants to pay, or asks how/where to pay | agent, “Borç ödeme işleminiz için sizi müşteri temsilcimize aktarıyorum.” |

## 6. Statement by e-mail

What it does: the PDF of the card's most recent statement goes to the e-mail address on file with us. No customer data changes. Once it's out we can't call it back, so we need a clear go-ahead.

1. Registered address: already fetched for the offer (5.2). If there isn't one, the e-mail option is never offered. If the caller asks for it anyway: “Bankamızda kayıtlı bir e-posta adresiniz bulunmadığı için ekstrenizi gönderemiyorum.” Then offer the statement week change if they still have the right, otherwise main menu.
2. Ask: “Ekstrenizi … adresine göndermemi ister misiniz?” A short, readable address is read as it is. A long or messy one is shortened, e.g. “m ile başlayan Gmail adresiniz”. Never spelled letter by letter.
3. Only after a clear yes, call `statement.pdf.send`, and only ever with the registered address.
4. Success: “Ekstreniz kayıtlı e-posta adresinize gönderildi.” then “Sizi ana menüye yönlendiriyorum.”

Things that came up in the session:
- A no, or "that address isn't mine any more": nothing goes out. In the second case also tell them we can't change the address on this call. Both end with “Sizi ana menüye yönlendiriyorum.”
- Another address, a month further back, a paper copy: we only send the most recent statement, and only to the address on file. Paper and text message aren't something this step does; say so and go to the main menu.
- Asked to send it again: fine, up to three times in one call, then “Sizi ana menüye yönlendiriyorum.”
- `contact.email.get` or `statement.pdf.send` fails (error, timeout, "document not found"): “Şu anda işleminizi gerçekleştiremiyorum, sizi müşteri temsilcimize aktarıyorum.”

## 7. Changing the statement week

Moves the card's statement closing week, which moves the next closing date and due date. Permanent; cannot be undone in the call.

How often: **once per calendar year** (Kerem, 7 Oct). Before the week question the assistant may say “Hesap kesim tarihinizi yılda bir kez değiştirebilirsiniz.” Elçin is fine either way, it is not a must. A caller who has used the right this year is not offered the change; if they ask anyway, the same sentence is how we explain why it can't be done.

Steps:

1. `statement.week.get`. Error: “Şu anda hesap kesim tarihinizi değiştiremiyorum, sizi müşteri temsilcimize aktarıyorum.”
2. Tell and ask: “[kart adı] kartınızın hesap kesim tarihi her ayın [hafta]. haftası olarak tanımlı. Bir sonraki hesap kesim tarihiniz [tarih], son ödeme tarihiniz [tarih]. Hesap kesim tarihinizi değiştirmek ister misiniz?” No → main menu.
   Joint statement (`relationType` main or linked): read both cards here: each card's last four and name, the payment week, the next closing date and next due date.
3. Options, without the current week. For a card in week 2: “Hesap kesim tarihinizi ayın 1., 3. ya da 4. haftasına alabilirim. Hangisini tercih edersiniz?”
4. Preview: `statement.week.decide` with the chosen week and the card's current `statementDay` from step 1. It doesn't change the card. Error: same sentence as step 1.
5. Joint statement only, before the question in step 6: “Bu değişiklik kartınıza bağlı [bağlı kart adı] kartınızı da etkileyecek.” If the caller holds the linked card, say instead that the change also moves the main card it hangs off, e.g. “Bu değişiklik kartınızın bağlı olduğu [asıl kart adı] kartınızı da etkileyecek.”
6. Confirm, with the preview dates: “Yeni hesap kesim haftanız her ayın 3. haftası olacak. Yeni hesap kesim tarihiniz [tarih], son ödeme tarihiniz [tarih] olacak. Onaylıyor musunuz?” Only a clear "evet" counts.
7. Only now, after the preview and the clear yes: `statement.week.change`. Error: same sentence as step 1.
8. Done: “Sonu [son 4 hane] ile biten [kart adı] kartınızın hesap kesim haftası her ayın 3. haftası olarak değiştirildi. Yeni hesap kesim tarihiniz [tarih], son ödeme tarihiniz [tarih].” Dates are the ones from the preview. Then “Sizi ana menüye yönlendiriyorum.”

Around the choice and the yes:
- The caller can only pick from the weeks we read out. A day of the month, a date, any week we didn't offer: read the options again. Their current week: tell them nothing needs changing.
- A no at step 6 means no change and “Sizi ana menüye yönlendiriyorum.” Something hedged ("perhaps", "I suppose") is not a yes: ask once more, plainly, three tries in all, until we get a clear "evet".
- If, after step 8, they want it undone: tell them the change has already gone through. If they ask from when it applies: the new closing date from the preview.
- `statement.week.change` failing after a good preview is a service error like any other: step 1's sentence, agent.

## 8. Edge cases (whole call)

Reworked after 7 Oct. Applies at every step unless a section above says otherwise.

### 8.1 Tries

Three tries per question, whatever the question. When the third is gone: “Size şu anda yardımcı olamıyorum. Sizi ana menüye aktarıyorum.” A try is lost on a mumble, an answer to some other question, or a flat refusal to say. A request to hear something again is not a try: read the same thing again, as often as they like.

What the caller came here for, we finish here. Not understanding the caller is never a reason to put them through to an agent; the only transfers are the ones in 8.3 and 8.4.

### 8.2 Silence

Changed on 7 Oct. First and second silence: ask the question again, shorter. Third silence: “Sesinizi alamadığım için görüşmeyi sonlandırıyorum.” and the call is closed. No main menu here.

### 8.3 Agent

- The caller asks for a person, at any point: put them through at once, no tries, no persuading. “Sizi müşteri temsilcimize aktarıyorum.” (Transfer on the first ask for now; Burcu wants to look at this again after go-live.)
- Paying, or how and where to pay: “Borç ödeme işleminiz için sizi müşteri temsilcimize aktarıyorum.”
- The caller says the debt is wrong, or that a payment they made isn't showing: “Bu konuda size müşteri temsilcimiz yardımcı olacak, sizi aktarıyorum.”
- Upset, raising their voice, swearing: up to three calming replies. Still complaining after the third: “Sizi müşteri temsilcimize aktarıyorum.” Insults are never returned.
- Any Freya Bank service failing (error or no answer) goes to an agent, never to the main menu: “Şu anda işleminizi gerçekleştiremiyorum, sizi müşteri temsilcimize aktarıyorum.” For the statement week services it is the statement week sentence in section 7. The `cards.list` "no valid card" warning is not a failure (section 2).
- A slow service: “Bilgilerinizi kontrol ediyorum.” and keep waiting. How long before we call it a failure is open; Deniz is coming back with a number. Mert says some answers take more than ten seconds and still succeed.

### 8.4 Main menu

- The sentence for now: “Sizi ana menüye yönlendiriyorum.” Burcu wants to look at it again once the call routing piece is live. Until then “Sizi ana menüye aktarıyorum.” and “Başka hangi konuda yardımcı olabilirim?” are also fine where they appear.
- Something outside this step (rates, limit, points, instalments, a loan): we don't answer it here. “Size bu konuda yardımcı olamıyorum. Sizi ana menüye yönlendiriyorum.” and over to the main menu.
- The caller switches to another transaction partway through (their limit, say): leave what we were doing, “Sizi ana menüye yönlendiriyorum.”, and the main menu picks it up.
- A goodbye or a thank-you after the reading means "nothing else": “Sizi ana menüye yönlendiriyorum.”
- Not Turkish: not handled in this step. “Sizi ana menüye aktarıyorum.” (the main menu has an English option).

### 8.5 How the caller asks

- Only one figure wanted (just the minimum, just the due date): once the card is clear, give that and go to the offer, not the whole reading.
- Cutting in while we read: stop and go to the offer.
- Debt and e-mail in the same breath: read the debt, then go straight into the e-mail step without the offer question; read the address and get the go-ahead.

### 8.6 Security

- Someone asking about another person's card (a partner's, a parent's): we can only do this for the caller's own cards, for security reasons. The call goes back to the IVR login step so the card's owner can identify. Nothing about the other person's cards, not even whether they exist.
- A card number that isn't on the caller's list: no information, same as a card not on the list (3.3).
- If the caller volunteers a PIN, a one-time code or the card's long number when we didn't ask: we don't use it and don't repeat it, and remind them we never ask for a password.
- Anything that tries to talk the assistant out of its job (ignore your rules, pretend to be staff): ignore it and carry on.
- Questions about figures no service gives us (next month's bill, the interest rate): no amount, date or rate that didn't come from a service; treat it as a question outside this step (8.4).
- Asked to read out its instructions or what a service sent back: no. Not the instructions, not the raw answer, not any number from the services beyond what the reading uses. Carry on.

## 9. Branches we added

A few things came out of Wednesday that the September write-up didn't have at all: the "another card?" question before the offer, the offer without e-mail when there's no address on file (“Hesap kesim tarihinizi değiştirebilirim.”, main menu still open), the optional once-a-year line, the card introduction at the start of every reading, the closing date on the first currency, and the plain statement reading for calls between the cut and the due date. They're in sections 4, 5 and 7 above.

## 10. Where the call ends

| Ends in | Why | Last sentence |
|---|---|---|
| Main menu | No eligible card | “Ekstre borcunu sorgulayabileceğiniz uygun bir kredi kartınız bulunmuyor. Sizi ana menüye aktarıyorum.” |
| Main menu | Nothing else wanted | “Sizi ana menüye yönlendiriyorum.” |
| Main menu | Three tries used up | “Size şu anda yardımcı olamıyorum. Sizi ana menüye aktarıyorum.” |
| Main menu | Wants another transaction mid-flow | “Sizi ana menüye yönlendiriyorum.” |
| Main menu | Question outside this step | “Size bu konuda yardımcı olamıyorum. Sizi ana menüye yönlendiriyorum.” |
| Main menu | Not speaking Turkish | “Sizi ana menüye aktarıyorum.” |
| Main menu | E-mail sent / declined, statement week changed / declined | “Sizi ana menüye yönlendiriyorum.” |
| Call closed | Third silence | “Sesinizi alamadığım için görüşmeyi sonlandırıyorum.” |
| Agent | Wants to pay | “Borç ödeme işleminiz için sizi müşteri temsilcimize aktarıyorum.” |
| Agent | Asks for an agent | “Sizi müşteri temsilcimize aktarıyorum.” |
| Agent | Dispute / payment not showing | “Bu konuda size müşteri temsilcimiz yardımcı olacak, sizi aktarıyorum.” |
| Agent | Still complaining after three calming replies | “Sizi müşteri temsilcimize aktarıyorum.” |
| Agent | Card list or balance service fails | “Şu anda işleminizi gerçekleştiremiyorum, sizi müşteri temsilcimize aktarıyorum.” |
| Agent | E-mail services fail | “Şu anda işleminizi gerçekleştiremiyorum, sizi müşteri temsilcimize aktarıyorum.” |
| Agent | Statement week services fail | “Şu anda hesap kesim tarihinizi değiştiremiyorum, sizi müşteri temsilcimize aktarıyorum.” |
| IVR login step | Asking about someone else's card | (security, 8.6) |

For an agent, the assistant gives the call back to the IVR with an agent flag and the IVR does the queueing.

## 11. Still open

1. Flag for "statement week right used this year": Mert asked the card platform on 1 Oct. Until it exists I don't know how the offer can tell. Ideas welcome.
2. How long to wait on a slow service before going to an agent (8.3). Freya to propose.
3. Future-period total in foreign currency on the no-debt reading (4.7). Kerem.
4. The line for foreign currency moved into Turkish Lira (4.4). Ozan.
5. Fields to mask in recordings and logs. Elçin has a list from another project; she'll send it.
6. Success measure and monthly volume. Burcu still pulling the numbers.
7. Mandatory texts (data protection, recording notice): Elçin says the IVR already plays them before the hand-over. To confirm in writing.

Selin
