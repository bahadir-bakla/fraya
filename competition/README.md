# Yarışma builder’ı

Bu klasör gerçek yarışma akışını uygular: **bankanın belgeleri + o brief’in araç API şeması → Codex builder → Freya dry-run → aynı workflow slot’una kayıt ve yayın → brief’e ait resmi müşteri simülasyonu → hata/transcript temelli onarım → platformdan export + iz**.

Önceki `demo/` klasörü ayrı bir yerel açıklama prototipidir. Yarışma için `competition/builder.py` ve bunun gerçek Freya export’u kullanılır.

## 11 Ekim diyalog onarımı

Yeni otomatik aday `releases/minilm-v2-dialogue-recovery-a-r2-20261011/` içinde. Tam ödeme kabulü/hazır döngüsü, yarım koşul, eski teklifin yeni tutarı ezmesi, rakam rakam doğum yılı ve başka işleme ait onayın ödeme onayı sayılması için bağımsız yerel kontroller **18/18 + 27/27**, builder/harness testleri **153/153** geçti.

Canlı yeterlilik doğrulanmadı: üç public tekrarda **0/30**; aynı anda kontrol edilen değiştirilmemiş eski adayda **0/2**. Çağrılar ilk kullanıcı cevabından sonra yaklaşık 60 saniye sessizlikle kapandı; extraction/routing devam etmedi. Ortak platform/model hattı şüpheli, kesin servis kök nedeni bilinmiyor. Resmi başarısız skorlar korunur; bu aday için canlı iyileşme veya teslim başarısı iddiası yoktur. Klasik A10/B14 yedeği korunur.

[Onarım, test ve teslim durumu](../analysis/dialogue-recovery/REPORT.txt) ve [ham ölçüm özeti](../analysis/dialogue-recovery/hosted-diagnostics.json). Tam sürüm sabitlemeli tekrarlar için `scripts/evaluate_shared_candidate.py --help` kullanılabilir.

## Doğrulanmış public demo

Son uygun hazırlık koşuları: Brief A `20261010-173717-1b9196`, Freya sürüm 7, **10/10**; Brief B `20261010-173746-6ed19b`, Freya sürüm 6, **3/3**. İkisi de 30 dakikalık UTC sınırı içinde tamamlandı. Bunlar ayrı public pratik koşularıdır; tek bir karma 13 müşterilik koşu veya gizli final başarısı değildir. Önceki başarısız ve süre aşmış koşular provenance olarak korunur.

## Başlatma

Python 3.11+ ve giriş yapılmış Codex CLI gerekir. Klasik builder ek Python paketi istemez. İsteğe bağlı MiniLM yardımcısı, yerelde hash ile sabitlenmiş encoder ve torch/transformers içeren ayrı Python kullanır. Builder mevcut Codex girişini kullanır; başka bir model anahtarı istemez. Freya anahtarı ortamdan alınır veya terminalde gizli girişle sorulur; kaynak, prompt, log ya da frontend içine yazılmaz. Sunucu kapatıldığında bellekten çıkar.

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

## MiniLM ile belge navigasyonu ve klasik karşılaştırma

`--semantic-assist auto` varsayılandır. Builder, mevcut MiniLM encoder ile bütün
brief girdilerini satır ve karakter aralıklarını koruyarak indeksler. Kimlik,
ürün kapsamı, ödeme teklifi, güncel onay/geri çekme, tarih, istisna ve başarılı
araç cevabı için ilgili pasajları bulur. `work/semantic-evidence.json` ve `.txt`
her pasajın kaynak SHA-256'sını ve sırasını içerir. Builder yine bütün belgeleri
okur; benzerlik puanı politika önceliği veya izin anlamına gelmez.

Encoder ve mevcut 77 konulu head'in tüm dosyaları hash ile doğrulanır, yalnız
yerel safetensors yüklenir. Yardımcı alt süreç banka/diğer API anahtarlarını
devralmaz ve en çok 60 saniye harcar; bu süre toplam builder bütçesinden düşer.
`auto` eksik model/paket/süre durumunda bunu izde kaydedip klasik akışa döner.
`required` eksik bağlantıda çalışmayı durdurur. `off` MiniLM çalıştırmaz.
`MINILM_PYTHON` veya `--semantic-python` ML paketlerinin kurulu olduğu Python'u
seçer. Encoder ağırlıkları repo'ya eklenmez; arkadaşın aynı sabit model snapshot'ını
yereline kurmalıdır. Kaynak model/revizyon ve dosya hash'leri
`integrations/learned-dialogue/day2_pretrained_head.json` içindedir.

```sh
python3 competition/setup_minilm.py  # yalnız sabit public model dosyalarını indirir
python3 competition/setup_minilm.py --verify-only
```

ML Python ortamında `torch`, `transformers`, `numpy` ve `safetensors` kurulu olmalıdır.
İndirme ayrı kurulum adımıdır; builder koşusu ağdan model indirmez.

```sh
# Platform kuyruğu boşalmasını beklerken gerçek builder üretimi + yerel doğrulama:
python3 competition/builder.py 'build-the-builder 2/briefs/brief-a.md' \
  'build-the-builder 2/briefs/brief-b.md' --slot minilm-comparison \
  --local-only --semantic-assist required --semantic-python /path/to/ml-python

# Bağımsız klasik üretim; aynı girdiler ve model ile karşılaştırılır:
python3 competition/builder.py 'build-the-builder 2/briefs/brief-a.md' \
  'build-the-builder 2/briefs/brief-b.md' --slot classic-comparison \
  --local-only --semantic-assist off
```

`--local-only` anahtar sormaz, Freya'ya yayın/test yapmaz. Üretilen workflow
`work/workflow.json` içindedir; `local_validation_only` sonucu platform başarısı
veya teslim export'u değildir. Platform testinde seçenek kaldırılır; farklı
adaylar aynı workspace'te sırayla ve sabit sürümle ölçülür. Klasik A10/B14
yedek kaynakları `competition/releases/classic-baseline/` içinde korunur.

Bu entegrasyon builder'ın kanıt okumasına yardım eder. MiniLM'in 91 MB encoder'ı
Freya ses ajanına gömülmez; yeni ödeme konuşması modellerinin ham önerileri
kimlik, tutar/tarih/ürün kapsamı, açık onay ve banka makbuzu kontrollerini aşamaz.

Onarım turlarında `--dialogue-assist auto` gerçek `failed-calls.json` içindeki
kullanıcı sözü ve hemen önceki asistan sözünü ayrı, 132.615 SGD TRAIN örneğiyle
eğitilmiş kaynağa ait eylem modeline verir. `dialogue-evidence.json` dört genel
eylem için hipotezleri, çağrı/mesaj konumunu ve kaynak/model hash'lerini taşır.
Ham konuşma bu ek dosyaya kopyalanmaz. AFFIRM, NEGATE, INFORM ve REQUEST bir
bankacılık izni değildir; finansal yetki daima UNKNOWN kalır. İlk üretimde hata
çağrısı yoksa bu aşama çalışmaz. `--dialogue-assist off` kapatır;
`--semantic-assist off` bütün bu yardımları kapatıp klasik akışı korur.

Ödeme konuşmasına ait yeni MiniLM başlığı ve iki küçük öğrenci modeli ayrıca
`integrations/learned-dialogue/repayment_API.txt` üzerinden yerelde denenebilir.
İlk 134 sentetik örnekli deney yeterli genelleme sağlamadı; varsayılan builder
ve ses ajanında finansal karar vermek için kullanılmaz. Kaynak konuşma eylemi
başlıklarının iyi sonucu bu yeni görev başlığına aktarılmış başarı sayılmaz.

Önceki sabit encoder / CPU deneylerinin durumu:

| Görev | Gerçekte eğitilen veri | Ölçülen sonuç ve sınırı |
| --- | --- | --- |
| MiniLM B77 konu başlığı | 7.943 TRAIN | Ham doğruluk %89,83; seçilmiş tahminlerde precision %95,14, coverage %89,12. Ödeme izni ölçümü değildir. |
| Kaynağa ait genel konuşma eylemleri | 132.615 TRAIN; ayrı 16.072 CAL ve 16.295 EVAL | AFFIRM/NEGATE/INFORM/REQUEST için seçilmiş precision %94,24–96,82. Her başlığın coverage ve recall'u raporda ayrıca verilir. Bu model MiniLM gövdesi değildir. |
| Ödeme/itiraz/düzeltme/izin prototipi | 134 toplam; 86 TRAIN, 24 CAL, 24 heldout | MiniLM başlığında macro F1 %44,76; iki küçük öğrencide %7,79. Güçlü bir ödeme modeli olarak kullanılmaz. |
| τ kaynak planlama prototipi | 103 resmi TRAIN senaryosu; 65 FIT, 28 CAL, 10 iç tanılama | İç tanılamada macro F1 %26,69. Referans araç listesini tahmin eder; geçerli bütün işlemler veya banka yetkisi değildir. |

τ paketinde ayrıca 716 politika parçası hazırlanmıştır; bu parçalar yukarıdaki
planlama başlığının eğitim örnekleri değildir. Paket gözlenmiş τ konuşması
içermez. Resmi TEST görevleri eğitime alınmamıştır. Politika metni, senaryo
talimatı ve konuşma etiketi aynı hedef gibi birleştirilmez. TRAIN öğrenme,
CAL eşik seçme, heldout/EVAL ayrı ölçüm içindir. Bu sonuçlar tek birleşik
modelin veya Freya ajanının geçme oranı değildir.

MiniLM encoder'ı yukarıdaki eski deneylerde sabitti; görev başlıkları eğitilmişti.
Bu CPU deneylerinde GPU kullanılmadı. Önceki yerel MiniLM ve klasik builder üretim denemeleri model süre sınırında
başarısız kalmıştır. Kod/bağlantı kontrolleri geçmiş olsa da tamamlanmış
üretim karşılaştırması ve yeni platform başarısı henüz gösterilmemiştir.
Kaynak, model, veri ve başarısız koşuların özeti
`analysis/minilm-builder-integration.json` içindedir.

## Büyük setle gerçek MiniLM fine-tuning

Yeni sürüm `integrations/learned-dialogue/minilm_ft_v1/` altında hazırdır.
H100 80 GB üzerinde MiniLM'in altı transformer katmanı ve embedding'leri
gerçekten güncellendi: 156.341 TRAIN örneği, iki epoch, 2.444 optimizer adımı,
101 değişen encoder tensörü. Aynı veriyle encoder'ı sabit kalan bir karşılaştırma
kolu da eğitildi. Önceki B77 retrieval encoder'ı ve klasik A10/B14 yedekleri korunur.

| Yeni veri | Satır ve anlamı |
| --- | --- |
| TRAIN | 132.615 SGD kaynak eylemi + 23.726 ödeme/itiraz/düzeltme/izin örneği = 156.341 |
| CAL | 16.416; yalnız eşik seçimi |
| EVAL | 16.703; ölçüm için ayrı tutuldu, H100'e gönderilmedi |
| Yeni domain EVAL | 384 örnek / 24 aile; eski 134 satırlık deneyden ayrı |

Domain TRAIN içinde 1.120 yeni yazılmış örnek, 86 eski örnek ve τ TRAIN
politika/senaryolarından türetilmiş 22.520 sentetik örnek vardır. τ verileri
gözlenmiş banka konuşması değildir; iki ortak üretim kökü olarak sayılır.
SGD'nin AFFIRM/NEGATE/INFORM/REQUEST etiketleri ayrı dört yardımcı başlıkta
öğrenilir ve ödeme iznine çevrilmez. Bilinmeyen etiketler maskelenir.

Yeni 384 örnekte yedi domain başlığının ham macro F1'i sabit encoder ile
%60,88, fine-tuned encoder ile %83,12; bütün bilinen başlıkları aynı anda doğru
olan satır oranı %35,16'dan %64,06'ya çıktı. CAL eşikleriyle fine-tuned macro F1
%80,21'dir. Düzeltme, izin geri çekme ve üçüncü kişi aktarımı hâlâ hata üretir.
Bunlar sentetik aile ayrımıyla ölçülen model sonuçlarıdır; Freya geçme oranı,
insan etiketli banka politikası doğruluğu veya gerçek ses/aksan doğrulaması değildir.
Tam fit/eval, altı katmanın ağırlık değişimi ve sınıf bazlı hata sayıları
`analysis/minilm-ft-results.json` içindedir.

Sonradan bağımsız bir yazara ürettirilen 32 daha zor örnekte ham macro F1
%58,61; bütün bilinen başlıkların aynı anda doğruluğu 12/32'dir. Bu paket altı
Türkçe OOD örneği, birleşik niyetler ve iki uzun son-düzeltme konuşması içerir.
Model/eşikler bu teste göre değiştirilmedi. `analysis/minilm-ft-adversarial-results.json`
gerçek yanlış başlıkları saklar; model önerisi her zaman ham sözle karşılaştırılır.

Yeni model builder'ın onarım turunda gerçek `failed-calls.json` kullanıcı
sözlerini ve önceki asistan sorusunu yerelde işler. `finetuned-evidence.json`
önerileri model/çalıştırma hash'leriyle üretim prompt'una verilir. İlk üretimde
hata konuşması yoksa bu yardımcı aşama atlanır. Model 46 MB safetensors encoder
ve küçük başlıklardan oluşur; ses ajanının içine gömülmez ve yeni bir dış inference
aracı oluşturmaz. Kimlik, güncel açık izin, ürün/tutar/tarih kapsamı, politika ve
başarılı banka makbuzu kontrolleri işlem yetkisini belirler.

```sh
# ML Python: torch, transformers, numpy, safetensors kurulu olmalıdır.
# Yerelde bulunan önceki public çalışma, onarım kanıtı olarak kullanılır:
python3 competition/builder.py 'build-the-builder 2/briefs/brief-a.md' \
  --slot minilm-repair --practice-repair <stopped-or-untested-public-run-id> \
  --semantic-python /path/to/ml-python --finetuned-assist required --local-only

# Klasik üretimde bütün MiniLM yardımcılarını kapat:
python3 competition/builder.py 'build-the-builder 2/briefs/brief-a.md' \
  --slot classic-repair --semantic-assist off --local-only
```

`--finetuned-assist auto|off|required` ayrı kontrol edilir; `--semantic-assist off`
üç yardımcıyı da kapatır. Hatalı hash, NaN, yabancı model dosyası veya tutarsız
seçim çıktısı kabul edilmez. Gerçek CPU inference ve builder alt süreç bağlantısı
`analysis/minilm-ft-builder-smoke.json` ile raporlanır. Paketleyici yeni release,
model ve runtime hash'lerini doğrulayıp isteğe bağlı modeli pakete ekler.
Freya workspace kuyruğu arkadaşın tarafından kullanıldığı için bu yeni sürümle
platform koşusu yapılmadı; hosted karşılaştırma ayrıca gereklidir.

H100 işi sona erdi. Üç sınırlı başlatma için toplam ihtiyatlı muhasebe üst zarfı
30 USD, kullanıcı bütçesi 35 USD'dir; 30 USD gerçek fatura olarak sunulmaz.
İlk başlatma disk ayarı, ikinci sonuç aktarımı hatasıyla sonlandı; üçüncü
koşunun eğitim dosyaları başarıyla alındı. Gerçek fatura henüz doğrulanmadı.

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


## MiniLM V2: Türkçe ve son düzeltmeler

V2, gerçek encoder güncellemesiyle eski156.341 ve yeni12.480 örneğin tamamında
iki tur eğitildi. Güncel konuşmanın tamamı, son penceresi ve önceki iki
gözlenen konuşma turu ayrı özelliklerdir. V1 ve klasik A10/B14 korunur.
Yeni96 bağımsız sentetik vakada V1 ortak doğru etiketler
17/96, V2 20/96;
macroF1 0.3244 → 0.4574.
Önceden sabitlenen varsayılan yükseltme kapısı: `False`.
Tam eğitim, seçilmiş eşik, ablation, regresyon ve sınırlamalar
[teslim notunda](../analysis/MINILM-V2-HANDOFF-20261011.txt) ve
[gerçek sonuçlarda](../analysis/minilm-v2-results.json) bulunur.

`--finetuned-version v2 --finetuned-assist required` V2'yi açıkça seçer;
`--finetuned-version v1` önceki modeli seçer. `auto`, ölçülen kapı açıksaV2,
aksi haldeV1 kullanır. `--semantic-assist off` klasik sürümü seçer.
Eylem modeli, başarısız gözlenen konuşmalar olduğunda builder onarımına
bağlanır; ilk brief üretiminin belge retrieval modeli ayrı korunur.
Freya ses ajanının sabit LLM/banka araç sözleşmesi değişmez.

Bu sprintte arkadaşın workspace'i kullanırken yalnız yerel test yapıldı.
C/D yeni üretimleri son model cevabı zaman aşımıyla FAILED kaldı; ayrı
yapısal kontroller C0 hata/D1 coverage belirsizliği ve C kaynak audit'i
üç gerçek guard sorununu gösterdi. Bunlar temiz submission değildir.
Rehberdeki yeni genel onarımlar sonraki otomatik üretim içindir.
Yeni Modal harcaması0; önceki ihtiyatlı üst muhasebe30USD/hard35USD.
# Portable live student experiment

`--live-layer recipient` asks the builder to generate the exact pinned current
recipient assertion helper into a code node. `--live-layer v2-student` is the
backward-compatible CLI name for a distinct portable student, including V3;
it does not load the full MiniLM encoder into the phone agent.

Supply `--live-student DIRECTORY --live-student-sha256 MANIFEST_SHA256`.
Default `--live-student-use shadow` records internal diagnostics only. Explicit
`--live-student-use clarify` permits an experimental clarification suggestion
for a verified customer and unresolved current speech; it does not qualify the
model, change its frozen thresholds, or grant identity/consent/bank authority.
Brief-specific limits still apply: no open amount question, repeated refused
offer, guessed product, or invented date. The bank engine remains authoritative.

Current V3 portable export is in `releases/live-v3-portable-20261011`. It is a
33 KB quantized classifier trained on 168,821 rows, not the MiniLM encoder.
Its CAL risk proposal precision was 91.3%, below the original 95% target.
Experimental clarification use was explicitly requested by the user. The
release remains default-disabled; bank/voice/platform benefit needs separate
actual workflow testing. Original classic backups remain in
`releases/classic-baseline`.
