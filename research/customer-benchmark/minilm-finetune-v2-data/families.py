"""Authored engineering targets, not publisher payment labels or human gold.

Every rule and its Turkish/English variants remain in one closure family.
CAL rules are reserved at authoring time, never selected using predictions.
"""
DOMAIN = ['proposal','dispute','correction','current_affirm','current_withdraw','uncertain','reported_third_party']
AUX = ['AFFIRM','NEGATE','INFORM','REQUEST']
FAMILIES = []

def add(split, key, positive, tr_context, en_context, tr, en, unknown=(), aux=()):
    assert len(tr) == 3 and len(en) == 2
    FAMILIES.append(dict(split=split, family=key, rule_type=key, positive=positive.split(),
        unknown=list(unknown), aux=list(aux), contexts={'tr':tr_context,'en':en_context},
        patterns=[{'language':lang,'text':text} for lang,arr in [('tr',tr),('en',en)] for text in arr]))

def train(*args, **kwargs): add('TRAIN', *args, **kwargs)
def cal(*args, **kwargs): add('CAL', *args, **kwargs)

train('own-installment-schedule','proposal',
 'Kalan bakiye için kendi ödeme planınız nedir?', 'What is your own plan for the remaining balance?',
 ['Ben {date} günü {amount} yatıracağım, kalanını sonra konuşuruz.', 'Şöyle yapalım, {date} tarihinde {amount} ödeyeyim.', 'Taksit olarak {amount} göndereceğim; gün de {date} olsun.'],
 ['I will send an installment of {amount} on {date}.', 'My payment plan is {amount} on {date}, then we can discuss the rest.'])
train('principal-only-offer','proposal dispute',
 'Ana para ve itiraz ettiğiniz masraf ayrı görünüyor.', 'The principal and the contested fee are separate.',
 ['Masrafa itirazım var ama ana paraya {date} günü {amount} ödeyeceğim.', 'O ek ücreti kabul etmiyorum; asıl bakiye için {amount} yatıracağım.', 'Faiz kalemi yanlış, ana paradan {amount} göndereyim {date} günü.'],
 ['I contest the extra fee, but will pay {amount} toward the principal on {date}.', 'The fee is wrong; my offer for the principal is {amount} on {date}.'])
train('own-bank-transfer','proposal',
 'Kendiniz havale yapacak mısınız?', 'Will you make the transfer yourself?',
 ['{date} günü ben havaleyle {amount} göndereceğim.', 'Havaleyi ben yapacağım, {amount} ve tarih {date}.', '{date} için sözüm şu: kendi hesabımdan {amount} aktaracağım.'],
 ['I will make the bank transfer myself: {amount} on {date}.', 'I commit to transferring {amount} from my account on {date}.'])
train('counteroffer-downsize','proposal',
 'Biz {old_amount} istedik. Sizin teklifiniz nedir?', 'We requested {old_amount}. What is your counteroffer?',
 ['{old_amount} yerine {amount} vereyim, {date} günü.', 'Benim karşı teklifim {date} için {amount}.', 'O tutar bana fazla; {date} tarihinde {amount} ödemeyi teklif ediyorum.'],
 ['My counteroffer is {amount} on {date}.', 'Instead of the requested {old_amount}, I offer to pay {amount} on {date}.'])
train('deny-liability','dispute',
 'Bu bakiye size borç olarak bildirildi.', 'This balance was presented as a debt you owe.',
 ['Benim böyle bir borcum yok, bana ait değil.', 'Bu borcun bana çıkarılmasına itiraz ediyorum.', 'Yok kardeşim, söz konusu borcu ben üstlenmedim.'],
 ['I do not owe this debt; I dispute responsibility for it.', 'That liability is not mine. I contest the claim.'])
train('unrecognized-charge','dispute',
 '{product} için bir işlem görünüyor.', 'There is a charge associated with {product}.',
 ['{product} işlemini ben yapmadım, itirazım var.', 'Ben {product} satın almadım; o kalem bana ait değil.', 'O alışverişi tanımıyorum, bu ücrete itiraz ediyorum.'],
 ['I did not make the {product} purchase and dispute the charge.', 'The {product} transaction is unfamiliar; I contest it.'])
train('duplicate-fee-dispute','dispute',
 'Aynı hizmetin ücreti iki satırda görünüyor.', 'The service fee appears twice.',
 ['Aynı ücret iki kere yazılmış, ikincisine itiraz ediyorum.', 'İki kez masraf olmaz; mükerrer olan kalem yanlış.', 'Yinelenen ücreti kabul etmiyorum, bu kayıt hatalı.'],
 ['I dispute the duplicate fee; the second entry is wrong.', 'The same fee was charged twice. I contest the repeated entry.'])
train('paid-versus-unpaid-record','dispute',
 'Faturanız ödenmemiş olarak görünüyor.', 'The invoice is shown as unpaid.',
 ['Ben onu {date} günü ödedim, ödenmedi kaydına itiraz ediyorum.', 'O bakiye kapandı; hâlâ borç görünmesi yanlış.', 'Parayı zaten yatırdım. Ödenmemiş demeniz hatalı.'],
 ['I already paid on {date}; I dispute the unpaid status.', 'That balance was settled. The outstanding-debt record is wrong.'])
train('past-payment-information','',
 'Geçmişte ne yaptığınızı anlatın; yeni bir taahhüt sormuyorum.', 'Tell me what you did previously; this is not a request for a new commitment.',
 ['{date} günü {amount} yatırdım.', 'Geçen işlemde {amount} ödedim, bilgi olarak söylüyorum.', 'Ödemeyi yaptım, tutar {amount} idi.'],
 ['I paid {amount} on {date}.', 'For your information, I completed a payment of {amount}.'],aux=['INFORM'])
train('repair-amount-commitment','proposal correction',
 'Önce {old_amount} ödeyeceğinizi söylediniz.', 'You previously said you would pay {old_amount}.',
 ['Tutarı düzelteyim: {old_amount} değil {amount} ödeyeceğim {date} günü.', 'Az önce yanlış söyledim, ödeyeceğim para {amount}.', 'Pardon, teklifim {old_amount} değil; {date} için {amount}.'],
 ['I misspoke: I will pay {amount}, not {old_amount}, on {date}.', 'Correct my offer to {amount} on {date}; the earlier amount was wrong.'])
train('repair-date-commitment','proposal correction',
 'Ödeme günü olarak {old_date} dediniz.', 'You gave {old_date} as the payment day.',
 ['Günü yanlış dedim, {old_date} değil {date} ödeyeceğim.', 'Takvimde düzeltme var: ödemeyi {date} günü yapacağım.', 'Pardon, ödeme teklifimdeki tarih {date} olacak.'],
 ['The date was wrong: I will pay on {date}, not {old_date}.', 'Correct the payment day to {date}; I will pay then.'])
train('repair-contact-detail','correction',
 'Geri arama istediğinizi yazdım.', 'I wrote that you requested a callback.',
 ['Arama demedim, yazılı yanıt istemiştim.', 'Beni yanlış anladınız; telefon değil e-posta olsun.', 'O kaydı düzeltin: geri aranmak değil, mesaj almak istiyorum.'],
 ['I meant a written reply, not a callback. Please correct that.', 'You misunderstood: I asked for email rather than a phone call.'])
train('repair-account-reference','correction',
 'Konu eski hesabınız diye kaydettim.', 'I recorded this as an issue with your old account.',
 ['Eski değil yeni hesap, onu düzeltin.', 'Yanlış hesabı söyledim; yenisini kastediyorum.', 'Hayır, kastım yeni hesaptı, eski hesap değil.'],
 ['I meant the new account rather than the old one.', 'Correct the account reference: it is the new account.'])
train('admin-explanation-assent','current_affirm',
 'Yalnızca hesap dökümünü açıklamamı ister misiniz?', 'Would you like me to explain the statement only?',
 ['Evet, açıklayın lütfen.', 'Olur, dökümü anlatın.', 'Tamam, açıklamayı dinleyeyim.'],
 ['Yes, please explain the statement.', 'Sure, I would like the explanation.'],aux=['AFFIRM'])
train('admin-address-assent','current_affirm',
 'Yazışma adresini kontrol edelim mi?', 'Shall we check the correspondence address?',
 ['Evet, adresi kontrol edelim.', 'Olur, o bilgiyi gözden geçirelim.', 'Tamamdır, adres kontrolü uygun.'],
 ['Yes, let us check the address.', 'Agreed, we can review the correspondence details.'],aux=['AFFIRM'])
train('initial-debit-refusal','',
 'Daha önce izin vermediniz. İlk kez soruyorum: tahsilat yapabilir miyiz?', 'You have given no permission. May we make a debit for the first time?',
 ['Hayır, buna izin vermiyorum.', 'Yok, tahsilat için onayım yok.', 'Olmaz, hesabımdan para çekmenizi kabul etmiyorum.'],
 ['No, I do not grant debit permission.', 'I decline this first request to debit my account.'],aux=['NEGATE'])
train('revoke-prior-debit','current_withdraw',
 'Önceki konuşmada otomatik tahsilata izin verdiniz.', 'In the preceding conversation you permitted an automatic debit.',
 ['O verdiğim tahsilat iznini geri alıyorum.', 'Önceki onayımı iptal edin, otomatik para çekmeyin.', 'Daha önce evet demiştim ama şimdi o izni kaldırıyorum.'],
 ['I revoke the debit permission I gave earlier.', 'Cancel my previous authorization for the automatic debit.'])
train('revoke-prior-contact','current_withdraw',
 'Bu numaradan aranmaya daha önce izin verdiniz.', 'You previously allowed calls to this number.',
 ['O arama iznimi geri çekiyorum.', 'Beni aramanız için verdiğim onayı iptal edin.', 'Önceden izin vermiştim; artık o telefon izni geçerli olmasın.'],
 ['I withdraw the permission I gave for phone calls.', 'Revoke my prior consent to calls at this number.'])
train('revoke-yes-answer','current_affirm current_withdraw',
 'Önceden verdiğiniz tahsilat iznini şimdi geri mi alıyorsunuz?', 'Are you now revoking your earlier debit permission?',
 ['Evet, geri alıyorum.', 'Aynen, önceki izni iptal ediyorum.', 'Doğru, o onayımı kaldırıyorum.'],
 ['Yes, I am revoking it.', 'Correct, I withdraw that earlier permission.'],aux=['AFFIRM'])
train('revoke-no-retention','current_withdraw',
 'Önceden verdiğiniz ödeme izni yürürlükte kalsın mı?', 'Should your previously granted payment permission remain active?',
 ['Hayır, o izin artık kalsın istemiyorum.', 'Yok, eski onay yürürlükte kalmasın.', 'Olmaz, daha önceki izni kaldırın.'],
 ['No, that earlier permission should not remain active.', 'No; remove my previous authorization.'],aux=['NEGATE'])
train('switch-debit-to-manual','proposal current_withdraw',
 'Otomatik tahsilata daha önce onay verdiniz.', 'You previously approved an automatic debit.',
 ['Otomatik çekim iznimi kaldırın; {date} ben {amount} yatıracağım.', 'Önceki tahsilat onayımı geri aldım. Kendim {amount} ödeyeceğim.', 'Eski çekim izni iptal olsun, {date} manuel olarak {amount} göndereceğim.'],
 ['Revoke my debit permission; I will pay {amount} manually on {date}.', 'Cancel the previous automatic authorization. I will send {amount} myself.'])
train('maintain-permission-negated-stop','',
 'Önceki ödeme izninizi iptal etmemi mi istiyorsunuz?', 'Are you asking me to cancel your earlier payment permission?',
 ['Hayır, iptal etmeyin; önceki iznim sürüyor.', 'Yok, durdurun demedim, eski onay devam etsin.', 'İzni geri almıyorum, olduğu gibi kalsın.'],
 ['No, do not cancel it; the earlier permission remains.', 'I am not withdrawing the existing permission. Leave it in place.'],aux=['NEGATE'])
train('wages-conditional-offer','proposal uncertain',
 'Kesinleşmiş bir ödeme mi öneriyorsunuz?', 'Is this a definite payment plan?',
 ['Maaş yatarsa {date} günü {amount} ödeyebilirim, kesin değil.', 'Belki {amount} veririm ama maaş gelmesine bağlı.', 'Gelir olursa {date} {amount} yatırmayı düşünüyorum; söz veremem.'],
 ['If my wages arrive, I might pay {amount} on {date}; it is uncertain.', 'I could offer {amount} if I get paid, but I cannot promise it.'])
train('hypothetical-payment-example','uncertain',
 'Gerçek kararınızı mı yoksa örnek bir durumu mu anlatıyorsunuz?', 'Are you describing a real decision or an example?',
 ['Diyelim {amount} ödesem ne değişir? Sadece varsayımsal soruyorum.', 'Örnek olsun diye {date} ödeme yaptığımı düşünün; karar vermedim.', 'Farz edelim ödeme var; bu gerçek bir teklif değil, varsayım.'],
 ['Suppose I paid {amount}; what would change? This is only hypothetical.', 'Imagine a payment on {date}; I am giving an example, not a real offer.'])
train('undecided-budget','uncertain',
 'Ödeme konusunda kararınız nedir?', 'What have you decided about payment?',
 ['Henüz karar vermedim, bütçeye bakmam lazım.', 'Emin değilim ya, önce durumumu hesaplayacağım.', 'Şu an net bir kararım yok, düşünmem gerekiyor.'],
 ['I have not decided; I need to review my budget.', 'I am unsure and need time to think.'])
train('sibling-quoted-payment','reported_third_party',
 'Kardeşiniz ne söyledi?', 'What did your sibling say?',
 ['Kardeşim "{date} {amount} ödeyeceğim" dedi, ben sadece aktarıyorum.', 'Ödeyecek olan kardeşim, onun {amount} sözünü anlatıyorum.', 'Onun dediği şu: "{amount} yatırırım". Bu benim teklifim değil.'],
 ['My sibling said, "I will pay {amount} on {date}"; I am only reporting it.', 'The offer of {amount} came from my sibling, not from me.'])
train('quoted-yes-without-adoption','reported_third_party',
 'Başka birinin yanıtını aktarıyor musunuz?', 'Are you relaying someone else\'s response?',
 ['{name} "evet, kabul ediyorum" dedi; ben onay vermiyorum, aktarıyorum.', 'O kişinin cevabı "tamam" olmuş; bu benim kabulüm değil.', '"Evet" diyen {name}, ben onun cümlesini söylüyorum.'],
 ['{name} said "yes, I agree"; I am quoting, not agreeing myself.', 'The "yes" was {name}\'s answer. I am only relaying it.'])
train('reported-and-own-offer','proposal reported_third_party',
 'Hem sizin hem diğer kişinin planını anlatın.', 'Describe your plan and the other person\'s plan.',
 ['{name} sonra öderim dedi; ben ise {date} {amount} ödeyeceğim.', 'Onun ödeme sözünü aktardım. Kendi teklifim {date} için {amount}.', '{name} kendi borcunu ödeyecekmiş, ben kendi bakiyeme {amount} yatıracağım.'],
 ['{name} said they would pay later; I will personally pay {amount} on {date}.', 'I am reporting {name}\'s promise and separately offering {amount} myself.'])
train('reported-denial','reported_third_party',
 'Diğer hesap sahibinin itirazı neydi?', 'What was the other account holder\'s objection?',
 ['{name} "borcum yok" dedi; onun itirazını aktarıyorum.', 'Borcun kendisine ait olmadığını söyleyen {name}, ben değilim.', 'O kişi bu işlemi yapmadığını söyledi, ben sadece haber veriyorum.'],
 ['{name} said "I owe nothing"; I am reporting their objection.', 'The denial of the charge came from {name}; I am only relaying it.'])
train('reported-revoke','reported_third_party',
 'Diğer kişinin izin konusundaki mesajı ne?', 'What is the other person\'s message about permission?',
 ['{name} "önceki iznimi geri aldım" dedi; mesajını aktarıyorum.', 'O eski onayını iptal etmiş, ben onun sözlerini anlatıyorum.', 'İznini kaldıran {name}; kendi iznimden söz etmiyorum.'],
 ['{name} said "I revoke my earlier permission"; I am relaying that message.', 'It was {name} who withdrew consent. I am only reporting their words.'])
train('reject-quoted-own-offer','correction reported_third_party',
 'Az önce sizin {amount} ödeyeceğinizi yazdım.', 'I just recorded that you would pay {amount}.',
 ['Ben ödeyeceğim demedim, {name} ödeyecek diye alıntı yaptım.', 'O benim teklifim değildi; başka kişinin sözünü aktarmıştım, düzeltin.', 'Yanlış kaydettiniz, ödeme cümlesi bana değil {name} kişisine aitti.'],
 ['Correct that: I was quoting {name}, not offering to pay myself.', 'You attributed the offer to me incorrectly; it was another person\'s statement.'])
train('question-not-commitment','',
 'Size ödeme koşullarını açıklıyorum.', 'I am explaining the payment options.',
 ['{amount} ödersem kalan ne olur?', 'Ödeme günü {date} olsa masraf ne çıkar?', 'Bu taksit seçeneği nasıl işliyor?'],
 ['What would remain if I paid {amount}?', 'How does that installment option work?'],unknown=['uncertain'],aux=['REQUEST'])
train('capability-without-offer','uncertain',
 'Kendi ödeme kararınızı bildirir misiniz?', 'Can you state your own payment decision?',
 ['Belki gücüm {amount} ödemeye yeter ama karar vermedim.', 'Ödeyebilirim gibi, ama henüz sözüm yok.', 'Bütçem uygun olabilir; ödeme kararı kesinleşmedi.'],
 ['I may be able to afford {amount}, but I have not decided.', 'Payment might be possible; I am not committed yet.'])
train('request-statement-not-payment','',
 'Ne konuda yardımcı olayım?', 'What assistance do you need?',
 ['Bana {product} dökümünü gönderin lütfen.', 'Önce hesap hareketlerini görmek istiyorum.', '{date} tarihli kayıtların bir kopyasını rica ediyorum.'],
 ['Please send the statement for {product}.', 'I would like a copy of the account entries from {date}.'],aux=['REQUEST'])
train('negated-payment-intention','',
 'Yeni bir ödeme teklifiniz var mı?', 'Do you have a new payment offer?',
 ['Şu an ödeme teklif etmiyorum.', 'Yok, bugün bir ödeme sözü vermiyorum.', 'Bir tutar veya tarih önermiyorum.'],
 ['I am not making a payment offer now.', 'I am giving no new payment commitment.'],aux=['NEGATE'])
train('withdraw-and-dispute','dispute current_withdraw',
 'Önceki tahsilat izniniz var ve ücret kalemi tartışmalı.', 'There is prior debit permission and a contested fee.',
 ['Ücret yanlış, itiraz ediyorum; ayrıca eski tahsilat iznimi geri alın.', 'O masrafı kabul etmiyorum. Önceki çekim onayım da iptal olsun.', 'Hem bu borca itirazım var hem verdiğim otomatik ödeme iznini kaldırıyorum.'],
 ['I dispute the fee and revoke my previous debit permission.', 'The charge is wrong. Also cancel my earlier automatic-payment authorization.'])
train('correction-and-dispute','dispute correction',
 'İtirazınız {old_amount} tutarına mı?', 'Is your objection about {old_amount}?',
 ['Tutarı yanlış yazmışsınız, {amount} olacaktı; bu ücrete itiraz ediyorum.', 'Düzeltin, itirazım {old_amount} değil {amount} kalemine.', 'İtiraz ettiğim tutar {amount}, önceki sayı yanlış aktarıldı.'],
 ['Correct the amount to {amount}; that is the charge I dispute.', 'My objection concerns {amount}, not {old_amount}. The earlier number was wrong.'])
train('future-paid-tense-repair','proposal correction',
 'Ödeme tamamlandı diye not aldım.', 'I noted that the payment was completed.',
 ['Ödedim değil ödeyeceğim dedim; {date} {amount} göndereceğim.', 'Henüz yatırmadım, yanlış anladınız. {date} günü yatıracağım.', 'Geçmiş ödeme değil, teklifim gelecek için: {amount} ödeyeceğim.'],
 ['I said I will pay, not that I paid. I will send {amount} on {date}.', 'Correct the tense: payment is still ahead; I will pay on {date}.'])
train('past-not-future-repair','correction',
 'Yeni ödeme teklifiniz {amount} diye yazıyorum.', 'I am recording a new offer of {amount}.',
 ['Yeni teklif değil, geçmişte ödediğim {amount} demek istedim.', 'Ödeyeceğim demedim, ödedim dedim; o kısmı düzeltin.', 'Gelecek için söz vermedim, yapılmış ödemeyi anlattım.'],
 ['Correct that: I meant a payment already made, not a future offer.', 'I said I paid, not that I will pay; fix that note.'])
train('unfinished-term-repair','correction uncertain',
 'Önceki teklifiniz {old_amount} olarak kaydedildi.', 'Your previous offer was recorded as {old_amount}.',
 ['O tutar değil, aslında... yeni rakamı daha bilmiyorum.', 'Düzeltmek istiyorum ama ne kadar olacağı kesin değil.', 'Az önceki sayı yanlış, yerine ne diyeceğim henüz netleşmedi.'],
 ['That amount was wrong, but I do not yet know the replacement.', 'I need to correct the figure; the new amount is still undecided.'],unknown=['proposal'])
train('ambiguous-referent-short','uncertain',
 'Birden fazla seçenek konuştuk: döküm, ödeme ve iletişim izni.', 'We discussed several options: statement, payment, and contact permission.',
 ['O şey olsun mu, emin değilim; hangisini dediğimi açıklayamadım.', 'Belki onu yaparız, ama neyi kastettiğim net değil.', 'Şu dediğimiz şey... kararsızım, tam tarif edemiyorum.'],
 ['Maybe that thing; I am unsure and cannot identify which option I mean.', 'I am undecided about it, and my reference is unclear.'],unknown=['proposal','correction','current_affirm','current_withdraw'])
train('rejected-typo-assent','correction',
 'Mesajınızdaki "olur" kelimesini ödeme onayı diye okudum.', 'I read your word "okay" as payment approval.',
 ['"Olur" yanlış yazılmış, ödeme onayı vermek istemedim.', 'O kelime otomatik düzeltmeydi, kabul demedim.', 'Yanlış okundu, yazıdaki tamam benim onayım değildi.'],
 ['That "okay" was a typing error; I did not mean payment approval.', 'Correct that reading: the apparent agreement was an autocorrect mistake.'])
train('condition-not-met-no-proposal','uncertain',
 'Gelirinize bağlı planınız kesinleşti mi?', 'Has the plan depending on your income become definite?',
 ['Şart daha oluşmadı, yeni bir ödeme önermiyorum; kararım açıkta.', 'Gelir durumu belirsiz; herhangi bir ödeme teklifim yok.', 'Şu an teklif yapmıyorum, koşulların nasıl olacağı belli değil.'],
 ['The condition is unresolved; I am making no payment offer and remain undecided.', 'Income is uncertain, and I have no payment proposal right now.'])
train('quoted-yes-own-refusal','reported_third_party',
 'Başkası kabul etmiş. Siz ilk kez izin verecek misiniz?', 'Someone else agreed. Will you personally grant permission for the first time?',
 ['{name} evet dedi ama ben izin vermiyorum.', 'Onun tamam dediğini aktarıyorum; benim cevabım ilk izin için hayır.', 'Kabul eden diğer kişi, ben ilk tahsilat talebini reddediyorum.'],
 ['{name} said yes, but I do not grant permission myself.', 'I report the other person\'s agreement; my answer to this first request is no.'])
train('readback-neutral-ack','current_affirm',
 'Sadece döküm isteğinizi kaydettim; doğru mu?', 'I recorded only your request for a statement; is that correct?',
 ['Evet, doğru kaydetmişsiniz.', 'Aynen öyle, kaydınız doğru.', 'Tamam, yalnızca döküm istemiştim, doğru.'],
 ['Yes, that record is correct.', 'Exactly, I requested only the statement.'],aux=['AFFIRM'])
train('revoke-with-undecided-replacement','current_withdraw uncertain',
 'Önceki ödeme izninizi ve olası yeni planı soruyorum.', 'I am asking about your prior permission and a possible replacement plan.',
 ['Eski iznimi geri alın, yeni plan konusunda henüz kararım yok.', 'Önceki onay iptal; yerine ne yapacağımı bilmiyorum.', 'Verdiğim izni kaldırıyorum, sonrasını düşünmem lazım.'],
 ['Revoke the old permission; I have not decided on a replacement plan.', 'My prior authorization is withdrawn, and I am unsure what to do next.'])
train('proposal-uncertain-date','proposal uncertain',
 'Tutar ve gün konusunda kendi teklifiniz nedir?', 'What is your own proposal for amount and date?',
 ['{amount} ödemeyi teklif ediyorum ama günü henüz bilmiyorum.', 'Tutar olarak {amount} vereyim, tarihten emin değilim.', 'Ödeme teklifim {amount}; hangi gün yapacağım kesin değil.'],
 ['I offer to pay {amount}, but the day is still uncertain.', 'My proposal is {amount}; I have not settled on a date.'])
train('correction-withdraw-date-no-renewal','correction current_withdraw',
 'Eski tahsilat izniniz ve kayıtlı gün {old_date}.', 'Your old debit permission is active, and the recorded day is {old_date}.',
 ['Kayıttaki gün {date} olacaktı, onu düzeltin; yine de eski iznimi kaldırın.', 'Tarihi yanlış yazdınız, {date} idi. Önceki çekim iznim iptal olsun.', 'Gün bilgisini {date} olarak düzeltin ve verdiğim tahsilat onayını geri alın.'],
 ['Correct the recorded day to {date}, and revoke my previous debit permission.', 'The date should have been {date}. Also cancel the earlier authorization.'])

# Reserved compositional rules: their language variants and every descendant are CAL only.
cal('sarcastic-denial-not-assent','dispute',
 'Size bu alışverişin borcu bildirildi.', 'You were informed of a debt for this purchase.',
 ['Tabii tabii, yapmadığım alışverişin borcu da benim olsun! İtiraz ediyorum.', 'He, hiç almadığım şeyin borcu bana yazılsın öyle mi? Kabul etmiyorum.', 'Güya ben almışım! Bu borç bana ait değil.'],
 ['Oh sure, charge me for something I never bought! I dispute it.', 'Apparently I bought it? No, this debt is not mine.'])
cal('double-negation-revocation','current_withdraw',
 'Daha önce tahsilata izin verdiniz.', 'You previously permitted a debit.',
 ['Eski izni geri almıyor değilim; açıkça geri alıyorum.', 'İptal istemiyorum demiyorum, eski onayı iptal istiyorum.', 'İznin kalkmasına karşı değilim: önceki tahsilat iznimi kaldırın.'],
 ['It is not that I refuse to revoke it; I am revoking my earlier permission.', 'I am not saying keep the authorization: cancel my previous consent.'])
cal('two-speaker-quote-adoption','proposal current_affirm reported_third_party',
 'Diğer kişinin teklifini kendi adınıza da kabul ediyor musunuz?', 'Are you adopting the other person\'s offer as your own?',
 ['{name} "{amount} öde" dedi. Evet, ben de {date} o parayı ödemeyi kabul ediyorum.', 'O kişinin önerdiği {amount} için evet; kendi teklifim de {date} ödemek.', '{name} ödeme önerdi, doğru; ben de kabul edip {amount} yatıracağım.'],
 ['{name} suggested {amount}; yes, I adopt that offer and will pay it on {date}.', 'I report {name}\'s suggestion and agree to personally pay {amount} on {date}.'])
cal('self-quote-retracted','correction current_withdraw',
 'Daha önce kendi sözünüzle tahsilata izin verdiniz.', 'You previously granted debit permission in your own words.',
 ['Kendi "çekebilirsiniz" sözümü düzeltiyorum; o izni artık geri aldım.', 'Ben evet demiştim, şimdi o sözümü geri çekiyorum, izin iptal.', 'Önceki cümlem benimdi ama şimdi değiştiriyorum: eski tahsilat onayımı kaldırın.'],
 ['I correct my own earlier "you may debit": I now revoke that permission.', 'My earlier yes was mine, but I am retracting it and withdrawing authorization.'])
cal('nested-report-no-own-consent','reported_third_party',
 'Size ulaşan konuşmayı anlatın.', 'Describe the conversation that reached you.',
 ['{name}, kardeşinin "evet, öderim" dediğini anlattı; ben ikisinin sözünü aktarıyorum.', 'Birinin diğerinden duyduğu ödeme sözünü söylüyorum; kendi onayım yok.', '{name} dedi ki annesi tamam demiş, sadece bu haberi iletiyorum.'],
 ['{name} told me their sibling said "yes, I will pay"; I am relaying both layers.', 'I am reporting a promise someone heard from another person; I give no consent.'])
cal('counterfactual-after-failed-condition','uncertain',
 'Gerçekte ödeme kararı verdiniz mi?', 'Have you made a real payment decision?',
 ['Maaş yatsaydı {amount} öderdim ama yatmadı; şu an karar vermedim.', 'Para gelmiş olsaydı ödeme olurdu, gerçekte henüz planım yok.', 'Koşul gerçekleşseydi yatırırdım; gerçekleşmedi, şimdi belirsiz.'],
 ['I would have paid {amount} if wages had arrived; they did not, and I am undecided now.', 'Had the funds arrived I would have paid, but that did not happen; there is no settled plan.'])
cal('alternative-disjunctive-offer','proposal uncertain',
 'Kendi öneriniz nedir?', 'What do you propose yourself?',
 ['Ya {date} {amount} öderim ya da başka gün; hangisi olacağı kesin değil.', 'İki ödeme seçeneği öneriyorum: {amount} şimdi veya sonra, kararım net değil.', 'Teklifim ödeme yapmak ama iki yol arasında kaldım, belirsiz.'],
 ['I offer either {amount} on {date} or payment later; the choice is uncertain.', 'My proposal is to pay, but I am undecided between two schedules.'])
cal('cancel-only-one-permission','current_withdraw',
 'Daha önce hem arama hem tahsilat izni verdiniz.', 'You previously allowed both calls and debits.',
 ['Arama izni kalsın, sadece önceki tahsilat iznimi kaldırın.', 'İki onaydan para çekme olanını geri alıyorum, telefon olanı dursun.', 'Önceki izinlerimin yalnızca ödeme kısmını iptal edin.'],
 ['Keep the call permission but revoke only the earlier debit permission.', 'Of the two earlier authorizations, withdraw the payment one only.'])
cal('debt-denial-with-past-payment','dispute',
 'Yeni borç ve geçmiş işlem ayrı kayıtlarda.', 'The new debt and past transaction are recorded separately.',
 ['Geçmişte {amount} ödedim ama bu yeni borç benim değil, itiraz ediyorum.', 'Eski ödemeyi yaptım; şimdi gösterdiğiniz farklı borcu reddediyorum.', 'Ödenmiş olan başka işlemdi, bu yeni yükümlülüğe itirazım var.'],
 ['I paid {amount} previously, but this new debt is not mine and I dispute it.', 'The completed payment was separate; I contest this newly alleged liability.'])
cal('ellipsis-amount-repair-offer','proposal correction',
 'Ben: {old_amount} mı? Siz önce o tutarı teklif etmiştiniz.', 'I asked: {old_amount}? You previously offered that amount.',
 ['Yok, {amount}. {date} ödeyeceğim tutar o.', 'Hayır, {amount} olacaktı; onu ödeyeceğim.', '{old_amount} değil... {amount}; teklifimi o şekilde düzeltin.'],
 ['No, {amount}. That is what I will pay on {date}.', 'Not {old_amount} ... {amount}; correct my offer to that.'])
cal('readback-question-wrong-polarity','correction',
 'Ödeme yapmayacağınızı mı söylediniz? Ben kayda öyle geçirdim.', 'Did you say you would not pay? I recorded it that way.',
 ['O şekilde söylemedim, kayıt yanlış; henüz karar belirtmedim.', 'Hayır, ne öderim ne ödemem dedim, o yorumu düzeltin.', 'Sözümü ters kaydettiniz; bir karar söylemedim.'],
 ['Correct that interpretation: I stated no decision about paying.', 'You recorded a decision I never expressed; fix the note.'],unknown=['proposal','uncertain'])
cal('revoke-conditionally-not-yet','uncertain',
 'Önceki izninizi şimdi geri alıyor musunuz?', 'Are you revoking your earlier permission now?',
 ['Sorun çözülmezse iznimi geri alabilirim, şimdilik karar vermedim.', 'Belki sonra iptal ederim ama şu an geri almıyorum, kararsızım.', 'İleride izin kaldırma ihtimalim var; şu an karar kesin değil.'],
 ['I might revoke it if the issue remains, but I have not decided and am not revoking it now.', 'Revocation is a future possibility; I am undecided and keep it unchanged for now.'])
cal('administrative-yes-explicit-scope','current_affirm',
 'Dökümü göndermeme ve ödeme almama ayrı cevap verin; henüz tahsilat izni yok.', 'Answer separately about sending a statement and taking a payment; there is no prior debit permission.',
 ['Döküm için evet, ilk tahsilat izni için hayır.', 'Belge göndermenizi kabul ediyorum; para çekmeye izin vermiyorum.', 'Evet sözcüğüm sadece döküme ait, ilk ödeme onayı değil.'],
 ['Yes to the statement, no to this first request for debit permission.', 'I agree to receiving the document and decline initial payment authorization.'])
cal('trailing-language-switch-repair','proposal correction',
 'Önce {old_amount} ve {old_date} dediniz.', 'You previously said {old_amount} on {old_date}.',
 ['Bir saniye, correction: tutar {amount}, gün {date}; ben o şekilde ödeyeceğim.', 'Son kısmı düzelteyim, actually {amount} on {date}, ben ödeyeceğim.', 'Wait, önceki rakam yanlış; {date} günü {amount} ödeyeceğim.'],
 ['Bir düzeltme: I will pay {amount} on {date}, replacing the old amount and day.', 'Son kararım: pay {amount} on {date}; correct my earlier offer.'])
cal('nonpersonal-agent-quote','reported_third_party',
 'Temsilcinin söylediklerini anlatın.', 'Tell me what the representative said.',
 ['Temsilci "müşteri kabul etti" dedi; ben yalnızca o iddiayı aktarıyorum.', 'Onay verdiğimi söyleyen görevliydi; onun sözünü anlatıyorum, benim onayım değil.', 'Görevlinin notunda evet yazıyormuş, o notu aktarıyorum.'],
 ['The representative said "the customer agreed"; I am only reporting that claim.', 'I am quoting the agent\'s note saying yes, not giving my own agreement.'])
cal('amount-only-unresolved-context','uncertain',
 'Tutar mı, tarih mi yoksa başka bilgi mi dediğiniz anlaşılmadı.', 'It was unclear whether you meant an amount, a date, or something else.',
 ['Belki {amount}, ne için olduğunu henüz açıklayamıyorum.', 'O sayı olabilir ama kastım net değil, emin değilim.', '{amount} diyeyim mi bilmiyorum, hangi konuya ait olduğu belirsiz.'],
 ['Maybe {amount}; I cannot yet explain what it refers to.', 'I am unsure about that number and its intended subject is unclear.'],unknown=['proposal','correction','current_affirm','current_withdraw'])

CHATTER = {
 'tr': [
  'Bu arada bugün mahallede hava biraz serindi, pencereyi kapatıp çayı masanın öbür ucuna koydum.',
  'Yolda otobüs beklerken duraktaki tabelayı okudum, sonra yan sokaktan yürüyüp parkın çevresinden dolaştım.',
  'Evdeki kitapları renklerine göre dizerken eski bir defter çıktı, kapağında herhangi bir yazı yoktu.',
  'Sabah mutfakta bardakları yerleştirdim, ekmeği dilimledim ve radyoda çalan şarkının adını hatırlamaya çalıştım.',
  'Komşunun kedisi merdivenin kenarında oturuyordu, ben de bahçedeki ağacın yapraklarının ne kadar değiştiğine baktım.',
  'Markette hangi sebzenin daha taze göründüğünü konuştuk, sonra eve dönüp birkaç tarifin fotoğrafını inceledim.',
  'Bir süre pencere önünde bulutları seyrettim, uzaktan gelen bisiklet sesini duyunca sokağa bakıp tekrar içeri döndüm.',
  'Telefonun ekran parlaklığı azalmıştı, ayarı bulana kadar menüler arasında dolaşıp sonunda yazı boyutunu değiştirdim.'
 ],
 'en': [
  'By the way, the neighborhood was chilly today, so I closed the window and moved my tea to the other side of the table.',
  'While waiting at the bus stop I read a sign, then walked through a side street and around the edge of the park.',
  'I was sorting books by color when an old notebook appeared, with no writing anywhere on its plain cover.',
  'This morning I arranged the cups in the kitchen, sliced some bread, and tried to remember the song playing on the radio.',
  'A neighbor\'s cat sat beside the stairs while I looked at how much the leaves on the garden tree had changed.',
  'We discussed which vegetables looked fresh, then I went home and looked through photographs of several recipes.',
  'For a while I watched the clouds, heard a bicycle in the distance, looked outside, and returned to the room.',
  'The phone screen was dim, so I searched the menus and eventually changed the size of the text.'
 ]}

# Conservative closure: resource names, question polarity, ellipsis, and language
# switching do not create independent held-out roots for an existing rule.
# Four initially reserved recipes therefore join TRAIN closure groups.
CLOSURE = {
 'own-term-repair': ['repair-amount-commitment','repair-date-commitment',
     'ellipsis-amount-repair-offer','trailing-language-switch-repair'],
 'repair-and-revoke': ['correction-withdraw-date-no-renewal','self-quote-retracted'],
 'prior-permission-revocation': ['revoke-prior-debit','revoke-prior-contact',
     'revoke-yes-answer','revoke-no-retention','double-negation-revocation'],
 'own-scheduled-payment': ['own-installment-schedule','own-bank-transfer'],
 'administrative-assent': ['admin-explanation-assent','admin-address-assent','readback-neutral-ack'],
}
for family in FAMILIES:
    family['closure_root'] = next((root for root,recipes in CLOSURE.items()
                                  if family['family'] in recipes),family['family'])
    family['rule_type'] = family['closure_root']
    if family['closure_root'] in CLOSURE:
        family['split'] = 'TRAIN'
