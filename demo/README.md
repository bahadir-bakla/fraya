# Freya Builder Lab — küçük demo

Kickoff’taki **brief → builder → telefon ajanı → müşteri testi → kayıt izi** döngüsünü yerelde gösterir. Başlangıç kitine dokunmaz.

**En kolay kullanım:** `demo.html` dosyasını Chrome’da açın. Kurulum, sunucu, internet veya API anahtarı gerekmez. Kaynak dosyaları düzenledikten sonra `npm run package` ile tek HTML’yi yenileyin.

Yerel sunucu seçeneği için Node.js 20+ yeterlidir:

```sh
cd /Users/yusuf/Documents/freya/demo
npm start
```

Tarayıcı: http://127.0.0.1:4173

1. **Ajanı oluştur**: örnek Türkçe brief’ten beş düğümlü Freya workflow JSON’u üretir.
2. **Müşteri senaryosu seç**: kimlik kontrolü, üçüncü kişi, injection, kayıt hatası, reddetme, iş kaybı, asgari tutar ve tarih kontrolü davranışlarını gösterir.
3. **Yeni görüşme**: müşteri olarak cevap verin. Doğum tarihi `1990-05-14`, telefon son dört hanesi `4821`. Tarihler `YYYY-MM-DD`; tutar değiştirmek için `tutar: 200 bugün`.
4. **Daha sıkı kurallar**: yanlış cevap, ikna, tarih ve tekrar deneme limitlerini değiştirir. Yeniden oluşturduktan sonra görüşmeler yeni kurallarla çalışır.
5. **JSON indir / İzi indir**: workflow’u ve yerel testlerin araç çağrılarını dışarı aktarır.

Arayüz olmadan dosya üretmek ve kontrol etmek için:

```sh
npm run build:agent
npm test
# Aynı biçimde yazılmış kendi demo brief’iniz:
node build.mjs /absolute/path/to/demo-brief.txt
```

Üretilen dosyalar `output/demo.workflow.json` ve `output/demo.trace.json`.

## Gerçekte ne yapıyor?

- **Builder** kural tabanlıdır; bir model çağırmaz. Banka adı, kimlikte yanlış cevap limiti, ikna limiti, tekrar deneme limiti, son tarih ve tatilleri örnek brief’in açık biçiminden çıkarır. Tanım eksikse hata verir. Brief’in tamamını ayrıca workflow prompt’una ekler.
- **Workflow** başlangıç kitindeki `docs/workflow-format.md`, `docs/tools-and-code.md` ve `tools/openapi.json` temelinde üretilir. Hesap düğümüne geçiş backend’in `all_verified` sonucuna bağlıdır; kimlik düğümünde hesap okuma veya ödeme kaydetme araçları yoktur. API alanları kitin gerçek şemasından kopyalanır; `agent_config` eklenmez.
- **Yerel telefon simülatörü** çıkarılan politikayı uygulayan ayrı bir durum makinesidir. Üretilen JSON’u Freya motorunda veya LLM ile çalıştırmaz. Sentetik banka, bağımsız güvenlik kontrolleri ve bellekte ödeme/kapanış kaydı tutar. Her senaryo, beklenen kayıt ve konuşma kontrolleriyle karşılaştırılır. Bunlar hackathon’un resmi testleri değildir.
- **İz** başlangıç/bitiş zamanını, kullanılan builder’ı, boş model çağrısı listesini, yerel kontrolleri, konuşmayı ve araç sonuçlarını içerir.

## Sınırlar ve sonraki adım

Bu küçük demo, bilinmeyen bankacılık/sigorta belgelerini anlayan genel bir AI builder değildir. Brief A’nın 47 kuralının tamamını veya Brief B’nin çoklu ürün akışını uygulamaz. Tek sentetik kredi kartı, sabit `now=2026-10-14T11:00` ve sınırlı Türkçe mesaj kalıpları kullanır. Arayüzdaki son tarih basitleştirilmiş sabit bir tarihtir; kitteki gecikme bandına göre 7/12 iş günü hesabının yerini temsil eder. Serbest metin anlayışı için önerilen cevaplar, ISO tarihler ve açık tutar biçimi kullanın.

JSON, Freya formatına yönelik bir prototiptir; platforma gönderilmedi, yayınlanmadı ve resmi simülasyonda doğrulanmadı. Prompt ile uygulanan tutar, onay ve teklif kuralları, yerel simülatörün katı kontrolleriyle eşdeğer değildir. Canlı kullanıma hazır değildir. `test_variables.customer_id` bilinçli olarak demo yer tutucusudur; gerçek platform testi için kitin sentetik müşteri ID’si gerekir.

Hackathon sürümü için bir modelin brief + API şemasından politika çıkarması, tutar/tarih/teklif/onay kurallarını code node ve hook’larla uygulaması, `freya.save_workflow` ile yayınlaması ve resmi `tools/run_cases.py` sonuçlarına göre düzeltmesi gerekir. Bu demo bu akışı küçük, incelenebilir bir prototip olarak sunar.

Kaynaklar: [Hackathon](https://www.freyavoice.ai/hackathon), klasördeki v3 başlangıç kiti ve paylaşılan kickoff metni.
