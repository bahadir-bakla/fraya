# Traceability: ornek_banka_a_s_kart_hizmetleri_gelen_cagri_pros__block_card

4/6 normative clauses implemented, 1/6 exercised by a simulated caller or the audit oracle.

| Clause | Binding | Text | Implemented by | Tested by |
|---|---|---|---|---|
| §1.1 | info | Bu prosedür, kart hizmetleri hattını arayan bireysel müşterileri kapsar. | — | — |
| §2.1 | must | Temsilci ilk cümlede görüşmenin kayıt altına alındığını belirtmelidir. | — | — |
| §3.1 | must | Müşterinin kimliği doğum tarihi ve T.C. kimlik numarasının son dört hanesi ile verify_identity kullanılarak doğrulanmalıdır. | node:verify<br>edge:verify->block_card[event:identity_verified]<br>edge:verify->verify[tool_failed]<br>slot:dob<br>slot:id_last4<br>tool:verify_identity | — |
| §3.2 | must_not | Kimlik doğrulanmadan hesap veya kart bilgisi paylaşılmaz. | intent:ask_info<br>instruction:*:gate:identity_verified<br>guard:VC-3.2 | — |
| §3.3 | must | Kimlik doğrulama üç kez başarısız olursa çağrı müşteri temsilcisine aktarılır. | edge:verify->human_agent[attempts>=3]<br>node:human_agent | — |
| §4.1 | must | Müşteri kartının çalındığını bildirirse önce kart block_card ile bloke edilir, ardından reissue_card ile yeni kart talep edilir. | node:block_card<br>edge:block_card->block_card__reissue_card[event:block_card_done]<br>edge:block_card->block_card_declined[tool_failed]<br>node:block_card__reissue_card<br>edge:block_card__reissue_card->done[event:reissue_card_done]<br>edge:block_card__reissue_card->block_card_declined[tool_failed]<br>node:block_card_declined<br>node:done<br>slot:details<br>tool:block_card<br>tool:reissue_card | — |
| §5.1 | must | Görüşmenin sonunda müşteriye teşekkür edilir. | — | — |
