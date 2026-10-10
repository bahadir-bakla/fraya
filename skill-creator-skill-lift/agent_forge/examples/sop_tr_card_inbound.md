# Örnek Banka A.Ş. Kart Hizmetleri Gelen Çağrı Prosedürü

## 1. Kapsam

1.1 Bu prosedür, kart hizmetleri hattını arayan bireysel müşterileri kapsar.

## 2. Açılış

2.1 Temsilci ilk cümlede görüşmenin kayıt altına alındığını belirtmelidir.

## 3. Kimlik doğrulama

3.1 Müşterinin kimliği doğum tarihi ve T.C. kimlik numarasının son dört hanesi ile verify_identity kullanılarak doğrulanmalıdır.
3.2 Kimlik doğrulanmadan hesap veya kart bilgisi paylaşılmaz.
3.3 Kimlik doğrulama üç kez başarısız olursa çağrı müşteri temsilcisine aktarılır.

## 4. Çalıntı kart

4.1 Müşteri kartının çalındığını bildirirse önce kart block_card ile bloke edilir, ardından reissue_card ile yeni kart talep edilir.

## 5. Kapanış

5.1 Görüşmenin sonunda müşteriye teşekkür edilir.
