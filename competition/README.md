# Yarışma builder’ı

Bu klasör gerçek yarışma akışını uygular: **bankanın belgeleri + o brief’in araç API şeması → Codex builder → Freya dry-run → aynı workflow slot’una kayıt ve yayın → brief’e ait resmi müşteri simülasyonu → hata/transcript temelli onarım → platformdan export + iz**.

Önceki `demo/` klasörü ayrı bir yerel açıklama prototipidir. Yarışma için `competition/builder.py` ve bunun gerçek Freya export’u kullanılır.

## Doğrulanmış public demo

Son uygun hazırlık koşuları: Brief A `20261010-173717-1b9196`, Freya sürüm 7, **10/10**; Brief B `20261010-173746-6ed19b`, Freya sürüm 6, **3/3**. İkisi de 30 dakikalık UTC sınırı içinde tamamlandı. Bunlar ayrı public pratik koşularıdır; tek bir karma 13 müşterilik koşu veya gizli final başarısı değildir. Önceki başarısız ve süre aşmış koşular provenance olarak korunur.

## Başlatma

Python 3.11+ ve giriş yapılmış Codex CLI gerekir. Ek Python paketi gerekmez. Builder mevcut Codex girişini kullanır; başka bir model anahtarı istemez. Freya anahtarı ortamdan alınır veya terminalde gizli girişle sorulur; kaynak, prompt, log ya da frontend içine yazılmaz. Sunucu kapatıldığında bellekten çıkar.

```sh
cd /Users/yusuf/Documents/freya
python3 competition/builder.py \
  'build-the-builder 2/briefs/brief-a.md' \
  'build-the-builder 2/briefs/brief-b.md' \
  --slot competition-main
```

Çalıştırma, en fazla 30 dakika ve varsayılan en fazla üç üretim/onarım turudur; `--skip-tests` ile test koşulmadığında varsayılan altı turdur, böylece kısa turlar 30 dakikalık bütçeyi boşa bırakmaz. `--rounds` en fazla altı tur seçebilir; turlar artırılsa da özgün 30 dakikalık bütçe sıfırlanmaz. Süre sınırına test süresi de dahildir. İlk model adımında workflow, kaynaklı politika ve kural kapsamı oluşturulur. Host kodu yapısal doğrulama, gerçek dry-run, `freya.save_workflow` + yayın, resmi `tools/run_cases.py`, hata çağrılarının okunması ve export işlemlerini yürütür. Model alt süreci bankaya erişim anahtarlarını devralmaz. Slot kilidi aynı workflow’un iki süreç tarafından değiştirilmesini engeller. Farklı slot’larda belgeler üretilebilir; Freya’nın workspace kuralı testleri sıraya alır ve aynı anda tek simülasyon çalışır.

Model alt adımı süreye takılırsa host, toplam bütçe kaldığı sürece aynı çalışma içindeki üretilmiş dosyaları otomatik olarak sonraki onarım adımına taşır. Süre/harness hatasıyla tamamen durmuş bir çalışma da `--resume-run <id>` ile aynı kanıtlar, model ve slot korunarak sürdürülebilir. Süre hem monotonic sayaç hem UTC saatle sınırlanır; bilgisayar uyursa/saat ilerlerse uykuda geçen süre de bütçeye dahil edilir. macOS’ta yalnızca builder süresi boyunca geçici `caffeinate` koruması kullanılır; kalıcı güç ayarı değiştirilmez. Geçen süre sıfırlanmaz; özgün çalışma bütçesi artırılamaz. Devam ettirme ve değişen harness kaynaklarının SHA-256’ları izde tutulur. Üretilen ajanı elle düzenlemek bu mekanizmanın parçası değildir.

Durmuş veya `evaluation=not_evaluated` olarak tamamlanmış bir **public pratik** çalışması için `--practice-repair <id>` ayrı bir hazırlık döngüsü başlatır. Bu yeni döngü kendi en fazla 30 dakikalık süresini ve önceki çalışmadan gelen dosyaların SHA-256 izini kaydeder; `--repair-first` mevcut kanıtları doğrudan onarıma verir; önceki çalışmanın süre aşımı gizlenmez. Yalnızca kitin aynı public brief ve API dosyaları kabul edilir. Başarılı olarak değerlendirilmiş bir koşu bu seçenekle yeniden başlangıç sayılmaz. Görülmemiş/final brief’lerde seçenek reddedilir ve üretim baştan yapılır.

### Yeni ve görülmemiş brief

```sh
python3 competition/builder.py /path/to/email.md /path/to/policy.md /path/to/amendment.md \
  --tool-api /path/to/new-openapi.json \
  --slot final-one --skip-tests
```

Dosyaların verilme sırası kanıtların sırasıdır; son açık kapsamlı değişiklik önceki kuralı geçersiz kılabilir. Builder, yeni kurallar ve enum’ları bu girdilerden çıkarır. Yeni brief’e ait sayılar, tatiller, doğrulama soruları, banka adları veya kapanış kodları builder kaynaklarına elle eklenmez. A ile B ayrı spesifikasyonlardır: B, A’nın üzerine verilen değişikliktir ve tek ürün için de not kuralını değiştirir. A ajanına A’nın 10 müşterisi, B ajanına B’nin 3 müşterisi uygulanır. Kitin tam metinleri verilince grup otomatik seçilir; özel bir test setinde `--brief <grup>` açıkça verilebilir. Önceki karma 13 müşterilik koşular tanı amaçlıdır, tek bir brief için geçerli başarı puanı değildir.

İlgili resmi test seti sağlanmışsa `--skip-tests` yerine `--cases /path/to/cases.json` kullanılır. Yeni belgeler için varsayılan public A/B testleri reddedilir; yanlış spesifikasyondan başarı puanı üretilmez. Finalde açıklanan test limiti kadar test çalıştırmak katılımcının sorumluluğudur; `--rounds` bunu sınırlar. `--skip-tests` resmi başarım iddiası üretmez.

```sh
# Konuşma biçimi varyasyonu; bir builder çalıştırmasında yine en fazla 30 dakika:
python3 competition/builder.py 'build-the-builder 2/briefs/brief-a.md' \
  'build-the-builder 2/briefs/brief-b.md' --slot pieces-agent --style pieces

# Kod kontrolleri:
python3 -m unittest discover -s competition/tests -v
```

## Yerel konsol

```sh
python3 competition/server.py
```

http://127.0.0.1:4180 adresini açın. Çalıştırma seçicisi önceki A/B ajanlarının sonuçlarını ve export’unu da gösterir. Konsol gerçek üretim aşamalarını, üretilen düğümleri, Freya workflow/agent/sürüm kimliklerini, resmi sonuçları ve indirilebilir dosyaları gösterir. Brief ve OpenAPI dosyaları yüklenebilir. **Freya’da oluştur ve yayınla** yeni bir gerçek builder çalıştırması başlatır. Brief A için 10, A+B’den üretilen Brief B ajanı için 3 resmi müşteri kullanılır; özel belge/API yükleyince test seçeneği kapatılır. Model/ajan başarımı tarayıcıdaki yerel senaryolarla uydurulmaz.

Konsol yalnızca loopback’e bağlanır. Anahtar backend belleğindedir. Oluşturma istekleri aynı origin ve oturumun CSRF belirteciyle sınırlandırılır. Belgeler sentetik olmalıdır. Freya uygulamasındaki diğer workflow’lar değiştirilmez; her `--slot` kendi kaydını tekrar kullanır.

## Çıktılar ve teslim

Her çalışma `competition/runs/<timestamp-id>/` altında kalır:

- `<slot>.workflow.json`: `freya.export_workflow` ile **platformdan okunan export**. Yarışmaya ajan olarak bu dosya verilir.
- `trace.jsonl`: başlangıç/bitiş, her model çağrısının modeli ve amacı, komutlar, Freya kimlikleri/yayın sürümü ve resmi test sonuçları.
- `model-*.jsonl`: modelin işlem izi; `prompt-*.txt` ve `answer-*.json`: çağrının girdisi ve yapılandırılmış cevabı.
- `work/inputs/`: bu çalıştırmaya verilen kanıtlar ve API şeması.
- `work/policy.json`, `work/coverage.json`: çıkarılan politika, kaynaklar ve kural kapsamı.
- `work/workflow.json`: builder’ın ürettiği ham tanım. Platform export’unun yerine teslim edilmez.
- `results-*.json`, `simulation-*.log`: bankanın ledger’ı ve resmi konuşma hakemiyle ölçülen pratik sonuçlar.
- `work/failed-calls.json`: onarım için indirilen başarısız çağrıların gerçek mesaj/araç/routing olayları; tekrar eden snapshot ve kod gövdeleri sadeleştirilir. Tam kayıtlar `call-transcripts/` altında korunur.
- `status.json`: gerçek son durum; `completed`, `needs_attention` veya `failed`.

Teslim paketi builder kaynaklarını, `skills/build-phone-agent.md` bilgi dosyasını, ilgili çalıştırmanın izini ve platform export’unu içermelidir. Anahtarlar ve `.state/` gönderilmez. `.gitignore` run verilerini repo dışında tutar; teslim edeceğiniz dosyaları ayrıca paketleyin. Final brief’leri yayımlanmadan oluşturulmuş pratik ajan, final teslimi değildir.

```sh
# Son tamamlanmış çalışma için kaynak, kit, export ve iz içeren ZIP:
python3 competition/package_submission.py
# Belirli bir çalışma için:
python3 competition/package_submission.py --run <timestamp-id>
# Ayrı A ve B çalıştırmalarını tek pakette birleştirmek için:
python3 competition/package_submission.py --run <a-run-id> <b-run-id>
```

Pratik onarım kullanılmışsa paketleyici önceki kaynak çalışmaları da bütün model izleri ve sonuçlarıyla ekler; başlangıçtaki başarısızlık kaybolmaz. Paketleyici `.state/` ve anahtarları eklemez; uzun Freya anahtarı kalıbı görürse paketi durdurur. `manifest.json` dosya SHA-256’larını ve teslimde kullanılacak platform export’unun yolunu içerir. `needs_attention` paketi hazırlanabilir, ancak bu durum başarılı sonuç diye sunulmaz.

## Kontrollerin sınırı

Yapısal doğrulama endpoint, API body alanı/enum’ları, düğüm tipleri, sonuç mapping’leri, Python snippet sözdizimi ve model ayarını kontrol eder. Freya dry-run gerçek platform şema kontrolüdür. Politikaya uyulduğunun ölçümü resmi simülasyondur; yalnızca JSON’un geçerli olması politika başarısı değildir. Üç tekrarın tamamından geçme koşulu kitin final değerlendirmesine aittir. Tek pratik koşu final başarısını garanti etmez.

Entegrasyon v3 kitteki doğrulanmış API/JSON formatına dayanır; workspace’e verilen API anahtarıyla erişir. Kullanıcı Freya hesabındaki tarayıcı erişimini de bu oturumda yetkilendirdi.

Windows’ta slot kilidi ve alt süreç süre sınırı desteklenir. Model alt süreci, üst Codex oturumunun `CODEX_PERMISSION_PROFILE` yerleşik izin profilini açıkça devralır; profil yoksa `:workspace` kullanır. Salt okunur üst oturum yükseltilmez. Bu oturumdaki açık full-access yetkisiyle çalışan profil, OneDrive dizinindeki Windows sandbox ACL hatasını giderdi; banka anahtarları model ortamından yine çıkarılır. Global kullanıcı ayarı değiştirilmez. `--skip-tests` çıktısı `evaluation=not_evaluated` olarak kaydedilir. İzin profilleri: [Codex yapılandırması](https://learn.chatgpt.com/docs/config-file/config-basic).

Kaynaklar: [Freya hackathon](https://www.freyavoice.ai/hackathon), yerel v3 kit, [Codex otomatik çalıştırma](https://learn.chatgpt.com/docs/non-interactive-mode), [Codex onarım döngüsü örneği](https://developers.openai.com/cookbook/examples/codex/build_iterative_repair_loops_with_codex).
