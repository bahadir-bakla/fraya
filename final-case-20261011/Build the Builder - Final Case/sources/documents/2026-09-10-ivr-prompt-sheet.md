# IVR prompt sheet: debt inquiry and statement week change

Burcu Tan, IVR operations, 10 Sep 2026

Selin asked for "whatever the menu says today" before the kickoff, so here it is. I copied these out of the prompt list in our IVR designer this morning, card self-service branch, debt inquiry and statement week nodes only. Variable names are the ones the TTS template uses, not the service fields. Amounts and dates go through the number-to-speech module; everything else is recorded or plain TTS.

I haven't cleaned it up much. Some of these were written years ago and nobody has touched them since, so please don't read them as "how it should be". Questions to me, wording questions to Kerem.

## Debt inquiry

| Prompt id | When it plays | Turkish line | Variables |
|---|---|---|---|
| DBT-010 | Card has no unpaid statement debt | Son dört hanesi {last4} olan {card_name} kartınızda ödenmemiş bir borç görünmüyor. Bir sonraki ekstreniz {next_cut_date} tarihinde kesilecek, son ödeme gününüz {next_due_date} olacak. | last4, card_name, next_cut_date, next_due_date |
| DBT-020 | Opening of the debt reading, before the per-currency lines | Son dört hanesi {last4} olan {card_name} kartınız için bilgiler şöyle: | last4, card_name |
| DBT-031 | TL debt, caller has paid nothing yet | Türk Lirası cinsinden toplam borcunuz {tl_total} Türk Lirası; yapmanız gereken en düşük ödeme {tl_min} Türk Lirası. | tl_total, tl_min |
| DBT-032 | TL debt, caller paid the minimum or more | Türk Lirası cinsinden toplam borcunuz {tl_total} Türk Lirası, geriye kalan borcunuz {tl_remaining} Türk Lirası. Asgari ödemenizi yaptınız, teşekkür ederiz. | tl_total, tl_remaining |
| DBT-033 | TL debt, caller paid something but less than the minimum | Türk Lirası cinsinden toplam borcunuz {tl_total} Türk Lirası, yapmanız gereken en düşük ödeme {tl_min} Türk Lirası. Geriye kalan borcunuz {tl_remaining} Türk Lirası, ödemeniz gereken kalan asgari tutar ise {tl_remaining_min} Türk Lirası. | tl_total, tl_min, tl_remaining, tl_remaining_min |
| DBT-040 | Dollar debt (own sentence, plays after the TL line) | Dolar cinsinden toplam borcunuz {usd_total} USD, geriye kalan borcunuz {usd_remaining} USD, en düşük ödeme tutarı {usd_min} USD. | usd_total, usd_remaining, usd_min |
| DBT-041 | Euro debt (own sentence, plays after the dollar line) | Euro cinsinden toplam borcunuz {eur_total} Euro, geriye kalan borcunuz {eur_remaining} Euro, en düşük ödeme tutarı {eur_min} Euro. | eur_total, eur_remaining, eur_min |
| DBT-051 | No debt in TL | Türk Lirası cinsinden bir borcunuz yok. | none |
| DBT-052 | No debt in dollar | Dolar cinsinden bir borcunuz yok. | none |
| DBT-053 | No debt in euro | Euro cinsinden bir borcunuz yok. | none |
| DBT-054 | No debt in TL and dollar | Türk Lirası ve Dolar cinsinden bir borcunuz yok. | none |
| DBT-055 | No debt in TL and euro | Türk Lirası ve Euro cinsinden bir borcunuz yok. | none |
| DBT-056 | No debt in dollar and euro | Dolar ve Euro cinsinden bir borcunuz yok. | none |
| DBT-060 | After the currency lines | Tüm borçlarınız için son ödeme gününüz {due_date}. | due_date |
| DBT-071 | After the debt info, debt or no debt: overall TL total | Bekleyen provizyonlar, faiz ve masraflar hesaba katılmadan kartınızın toplam Türk Lirası borcu {tl_overall} Türk Lirası. | tl_overall |
| DBT-072 | Same, overall dollar total | Bekleyen provizyonlar, faiz ve masraflar hesaba katılmadan toplam dolar borcu {usd_overall} dolar. | usd_overall |

Ops notes, debt inquiry:
- The three TL lines are picked by the IVR from the paid amount vs. the minimum. Ask Mert for the exact comparison, I only know it works.
- Dollar and euro are separate prompts on purpose; the recording studio would not do one sentence with two slots. "USD" is read out by the TTS as written. Yes, people have complained.
- There is no Sterling prompt at all. Never came up on the menu.
- The script I was handed in 2023 had the dollar total line (DBT-072) written twice and no euro total line. We recorded it once. So no euro total plays today.
- DBT-051 to DBT-056 cover only six combinations. If a card has no debt in any currency it goes to DBT-010 and never reaches these.

## Statement week change

| Prompt id | When it plays | Turkish line | Variables |
|---|---|---|---|
| STW-010 | Current payment week, ordinary card (after statement.week.get) | Son dört hanesi {last4} olan {card_name} kartınızın ödeme günü her ayın {week_ordinal} haftasına ayarlı. Önümüzdeki dönemde ekstreniz {next_cut_date} tarihinde kesilecek, son ödeme gününüz {next_due_date} olacak. | last4, card_name, week_ordinal, next_cut_date, next_due_date |
| STW-011 | Current payment week, main card with a linked card on the same statement | Son dört hanesi {last4} olan {card_name} kartınız ile buna bağlı {linked_card_name} kartınızın ödeme günü her ayın {week_ordinal} haftasına ayarlı. Önümüzdeki dönemde ekstreniz {next_cut_date} tarihinde kesilecek, son ödeme gününüz {next_due_date} olacak. | last4, card_name, linked_card_name, week_ordinal, next_cut_date, next_due_date |
| STW-012 | Current payment week, the linked card itself (caller holds the card that hangs off a main card) | Son dört hanesi {last4} olan {card_name} kartınız ile bu kartın bağlı olduğu {main_card_name} kartınızın ödeme günü her ayın {week_ordinal} haftasına ayarlı. Önümüzdeki dönemde ekstreniz {next_cut_date} tarihinde kesilecek, son ödeme gününüz {next_due_date} olacak. | last4, card_name, main_card_name, week_ordinal, next_cut_date, next_due_date |
| STW-020 | Caller picked a week; IVR reads what the change will mean (after statement.week.decide) | Son dört hanesi {last4} olan {card_name} kartınızın ödeme günü her ayın {week_ordinal} haftasına alınacak. Bundan sonra ekstreniz {cut_date_after} tarihinde kesilecek, son ödeme gününüz {due_date_after} olacak. | last4, card_name, week_ordinal, cut_date_after, due_date_after |
| STW-021 | Same, card with a linked card | Son dört hanesi {last4} olan {card_name} kartınız ile buna bağlı {linked_card_name} kartınızın ödeme günü her ayın {week_ordinal} haftasına alınacak. Bundan sonra ekstreniz {cut_date_after} tarihinde kesilecek, son ödeme gününüz {due_date_after} olacak. | last4, card_name, linked_card_name, week_ordinal, cut_date_after, due_date_after |
| STW-030 | Right after STW-020 / STW-021 | Bu değişikliği onaylar mısınız? | none |
| STW-040 | Caller confirmed and statement.week.change succeeded | Onayınızla ödeme gününüz her ayın {week_ordinal} haftasına alındı. Ekstreniz artık {cut_date_after} tarihinde kesilecek, son ödeme gününüz {due_date_after} olacak. | week_ordinal, cut_date_after, due_date_after |
| STW-091 | statement.week.change refuses: already changed this month | Ekstre tarihinizi değiştiremedik. Ekstre tarihi ayda yalnızca bir kez değiştirilebiliyor. | none |
| STW-092 | statement.week.change refuses: yearly limit reached | Ekstre tarihinizi değiştiremedik. Ekstre tarihi yılda en çok üç kez değiştirilebiliyor. | none |
| STW-099 | statement.week.change errors or times out | Şu an sisteme ulaşamıyoruz, ekstre tarihiniz değişmedi. Birkaç dakika sonra tekrar arayabilirsiniz. | none |

Ops notes, statement week:
- week_ordinal is a word ("birinci", "ikinci" ...), not a number. The TTS says "1." badly.
- There is no linked-card variant of STW-020 for the case where the caller holds the linked card. It falls back to STW-021 with the names swapped, which sounds slightly off. Known.
- STW-091 and STW-092 only play after the caller has already confirmed, because we only find out from the change call. Callers find that annoying ("why did you ask me then"). I don't know of a way to check before; maybe Mert does.
- The limits in STW-091/092 are what the card system answered when these were recorded. I have not checked them against the product side recently, Kerem would know.
