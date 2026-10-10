# Traceability: ornek_banka_a_s_kart_hizmetleri_gelen_cagri_pros

6/6 normative clauses implemented, 6/6 exercised by a simulated caller or the audit oracle.

| Clause | Binding | Text | Implemented by | Tested by |
|---|---|---|---|---|
| §1.1 | info | Bu prosedür, kart hizmetleri hattını arayan bireysel müşterileri kapsar. | — | — |
| §2.1 | must | Temsilci ilk cümlede görüşmenin kayıt altına alındığını belirtmelidir. | node:greet<br>edge:greet->verify[always]<br>guard:VC-2.1 | cooperative |
| §3.1 | must | Müşterinin kimliği doğum tarihi ve T.C. kimlik numarasının son dört hanesi ile verify_identity kullanılarak doğrulanmalıdır. | node:verify<br>edge:verify->close[event:identity_verified]<br>edge:verify->verify[tool_failed]<br>slot:dob<br>slot:id_last4<br>tool:verify_identity | cooperative |
| §3.2 | must_not | Kimlik doğrulanmadan hesap veya kart bilgisi paylaşılmaz. | intent:ask_info<br>instruction:*:gate:identity_verified<br>guard:VC-3.2 | impatient |
| §3.3 | must | Kimlik doğrulama üç kez başarısız olursa çağrı müşteri temsilcisine aktarılır. | edge:verify->human_agent[attempts>=3]<br>node:human_agent | wrong_identity |
| §4.1 | must | Müşteri kartının çalındığını bildirirse önce kart block_card ile bloke edilir, ardından reissue_card ile yeni kart talep edilir. | capability:block_card<br>order:block_card<reissue_card | block_card |
| §5.1 | must | Görüşmenin sonunda müşteriye teşekkür edilir. | node:close | cooperative |
