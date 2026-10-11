"""Publish a checked offline release and concise reproducible handoff."""
import datetime
import hashlib
import json
import shutil
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    local=ROOT/'local-runs/minilm-finetune-v2/local-run2'
    fit=json.loads((local/'training.json').read_text(encoding='utf8'))
    comparison=json.loads((ROOT/'local-runs/minilm-finetune-v2/evaluation-v2/comparison.json').read_text(encoding='utf8'))
    assert fit['status']=='COMPLETED' and fit['TRAIN_rows']==168821 and fit['completed_epochs']==2
    assert comparison['status']=='ACTUAL_FROZEN_ONCE_COMPARISON_COMPLETE'
    release=ROOT/'integrations/learned-dialogue/minilm_ft_v2';dest=release/'model'
    assert not dest.exists()
    shutil.copytree(local/'model',dest)
    assert sha(dest/'manifest.json')==comparison['v2_manifest_sha256']
    manifest=json.loads((dest/'manifest.json').read_text(encoding='utf8'))
    for name,digest in manifest['files'].items():assert sha(dest/name)==digest
    for rel,digest in fit['source_sha256'].items():assert sha(ROOT/'integrations/learned-dialogue'/rel)==digest
    pin={'schema':'minilm.real_encoder_finetune.v2','status':'EXPERIMENTAL_BUILDER_REPAIR_PROPOSALS','manifest_sha256':sha(dest/'manifest.json'),
         'runtime_sha256':{n:sha(release/'runtime'/n) for n in ['minilm_ft_core.py','minilm_ft_eval.py']},
         'default_enabled':comparison['default_enabled'],'TRAIN_rows':168821,'added_TRAIN_rows':12480,'epochs':2,
         'encoder_fine_tuned':True,'bank_authority':False,'financial_authorization':'UNKNOWN','hosted_evaluated':False,'in_voice_runtime':False,
         'comparison':'analysis/minilm-v2-results.json','scope':comparison['scope']}
    (release/'release.json').write_text(json.dumps(pin,indent=2)+'\n',encoding='utf8')
    report={'training':fit,'comparison':comparison,'release':pin,'finished_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat()}
    (ROOT/'analysis/minilm-v2-results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    v1=comparison['arms']['v1'];v2=comparison['arms']['v2']
    text=f'''MiniLM V2 / klasik builder teslim notu — 11 Ekim 2026

Gerçek eğitim: yerel {fit['local_GPU']}; 168.821 TRAIN örneği x 2 tur,
{fit['optimizer_steps']} optimizer adımı; {fit['encoder_changed_tensors']} encoder tensörü değişti.
Eğitim+CAL/export ölçülen süre: {fit['seconds']:.1f} saniye.
156.341 eski TRAIN aynen korundu; 12.480 yeni örnek eklendi.
Yeni örneklerin 7.488'i Türkçe; 4.160'ı geç gelen anlam/düzeltme içeriyor.
11.514 MASSIVE Türkçe TRAIN kaydı kaynak/lisans/hash ile toplandı.
Genel intentleri banka izin etiketi olarak kullanmadık; 39 tanık Türkçe kelime
eğitimde ilgisiz konuşma çeşitliliği sağlıyor. Finans etiketleri açık sentetik
ödeme/itiraz/düzeltme/izin tariflerinden geliyor. 480 yeni CAL, 12 ayrı aile.
Toplam CAL 16.896; CAL eğitimde kullanılmadı. Seçim eşikleri yalnız CAL'dan.

Mimari: güncel konuşmanın tüm pencerelerinden ortalama + son pencere +
son iki gözlenen USER/ASSISTANT turu. Uzun konuşmada son düzeltme ayrı kanalda.
Kırpılan konuşma yok; en fazla48 pencere/encoder çağrısı, büyük örneklerde
checkpoint ve tam gradient. 7 anlam +4 genel konuşma eylemi; öneri katmanı.
Kimlik, izin, para/tarih/politika/başarılı banka receipt yetkisi deterministik.
MiniLM builder'ın başarısız konuşma analizine bağlandı; Freya canlı ses modeline
harici GPU inference aracı eklenmedi. Yalnız kaynak değiştirme/onarım rehberi.

Eğitimden önce ayrı yazarca hazırlanan96 yeni EVAL vakası mühürlendi.
V1 yeni96: macroF1={v1['fresh']['raw']['domain_macro_F1']:.4f},
ortak bilinen etiketler doğru={v1['fresh']['joint_raw']['correct']}/{v1['fresh']['joint_raw']['denominator']}.
V2 yeni96: macroF1={v2['fresh']['raw']['domain_macro_F1']:.4f},
ortak bilinen etiketler doğru={v2['fresh']['joint_raw']['correct']}/{v2['fresh']['joint_raw']['denominator']}.
Önceden tanımlanan varsayılan release kapısı: {comparison['default_enabled']}.
Eski32 yeniden kullanılan tanı: V1 {v1['reused32']['joint_raw']['correct']}/32,
V2 {v2['reused32']['joint_raw']['correct']}/32. Yeni bağımsız96 ile karıştırılmaz.
Eski384 macroF1: V1 {v1['reused384']['raw']['domain_macro_F1']:.4f},
V2 {v2['reused384']['raw']['domain_macro_F1']:.4f}; bu da regresyon tanısıdır.
Uzun konuşma, önceki kendi yanıtı ve no-tail/no-context sonuçları JSON'da.
EVAL görüldükten sonra bu ağırlıklar/eşikler/test beklentileri değiştirilmedi.
Sonuçlar mühendislik amaçlı sentetik ailelerdir; IID/insan altın etiket,
bankacılık yetkisi, gerçek ASR/aksan veya Freya geçme oranı değildir.

Arkadaş branch'i origin/tau-hardening ca1565bd35ab4773ecd8afd13ee23a729c1b169d
önceki6706017 merge'inde korunarak birleşti. Son fetch'te yeni push yoktu.
Raw mock C5/30,D0/26; ayarlı gayriresmi C8/30 ayrı. Yeni hosted başarı iddiası yok.
Gerçek Opus5.5 rehber incelemesi ve103 literal CPU çağrısı: altı genel rehber
onarımı; isim/unvan bağlamı, kolektif tarih, sıralı düzeltmeler, toparlanan yeni
teklif, işleme özgü tekrar ve ödeme sözü iptali ile zorunlu not ayrımı.
Yeni otomatik klasik C/D yerel üretim kayıtları ve ayrı kaynak incelemesi
analysis/classic-v2-*.json altında; failed/expired original durumlar değişmez.
Klasik A10/B14 yedekleri ve V1 model hashleri değişmedi.

Çalıştırma:
  python competition/builder.py <briefler> --finetuned-version v2 --finetuned-assist required --semantic-python <torch-python> --local-only
  --finetuned-version v1 eski modeli açıkça seçer.
  --semantic-assist off tüm MiniLM yardımcılarını kapatır, klasik üretimi seçer.
  auto, yalnız predefined karşılaştırma kapısı açıksaV2; aksi haldeV1 kullanır.
  Eğitilmiş eylem yardımcısı, önceki başarısız konuşma bulunduğunda devreye girer.
  İlk brief üretiminde belge retrieval MiniLM'i ayrı model olarak korunur.
  --practice-repair <durmuş-public-run> --repair-first yerel onarım karşılaştırır.
  Arkadaş workspace'i kullandığı için bu sprintte Freya publish/test yapılmadı.

Bütçe: yeni Modal başlatması0, yeni bulut harcaması0. Önceki üç koşunun
ihtiyatlı muhasebe toplam üst zarfı30USD; hard35USD. Gerçek fatura doğrulanmadı.
Yerel kaynak91 test, bağımsız17 mekanik test, actualCUDA8 kontrol geçti.
Model/adapter/packet/hash, credential ve orijinal ZIP kontrolleri son kayıtta.
Kit16 dosya değişmez; actor/judge/scorer/expected değişmedi, gizli test erişimi yok.
'''
    (ROOT/'analysis/MINILM-V2-HANDOFF-20261011.txt').write_text(text,encoding='utf8')
    readme=ROOT/'competition/README.md';old=readme.read_bytes()
    section=f'''\n\n## MiniLM V2: Türkçe ve son düzeltmeler\n\nV2, gerçek encoder güncellemesiyle eski156.341 ve yeni12.480 örneğin tamamında\niki tur eğitildi. Güncel konuşmanın tamamı, son penceresi ve önceki iki\ngözlenen konuşma turu ayrı özelliklerdir. V1 ve klasik A10/B14 korunur.\nYeni96 bağımsız sentetik vakada V1 ortak doğru etiketler\n{v1['fresh']['joint_raw']['correct']}/96, V2 {v2['fresh']['joint_raw']['correct']}/96;\nmacroF1 {v1['fresh']['raw']['domain_macro_F1']:.4f} → {v2['fresh']['raw']['domain_macro_F1']:.4f}.\nÖnceden sabitlenen varsayılan yükseltme kapısı: `{comparison['default_enabled']}`.\nTam eğitim, seçilmiş eşik, ablation, regresyon ve sınırlamalar\n[teslim notunda](../analysis/MINILM-V2-HANDOFF-20261011.txt) ve\n[gerçek sonuçlarda](../analysis/minilm-v2-results.json) bulunur.\n\n`--finetuned-version v2 --finetuned-assist required` V2'yi açıkça seçer;\n`--finetuned-version v1` önceki modeli seçer. `auto`, ölçülen kapı açıksaV2,\naksi haldeV1 kullanır. `--semantic-assist off` klasik sürümü seçer.\nEylem modeli, başarısız gözlenen konuşmalar olduğunda builder onarımına\nbağlanır; ilk brief üretiminin belge retrieval modeli ayrı korunur.\nFreya ses ajanının sabit LLM/banka araç sözleşmesi değişmez.\n\nBu sprintte arkadaşın workspace'i kullanırken yalnız yerel test yapıldı.\nC/D yeni üretimleri son model cevabı zaman aşımıyla FAILED kaldı; ayrı\nyapısal kontroller C0 hata/D1 coverage belirsizliği ve C kaynak audit'i\nüç gerçek guard sorununu gösterdi. Bunlar temiz submission değildir.\nRehberdeki yeni genel onarımlar sonraki otomatik üretim içindir.\nYeni Modal harcaması0; önceki ihtiyatlı üst muhasebe30USD/hard35USD.\n'''
    assert b'## MiniLM V2:' not in old
    readme.write_bytes(old+section.replace('\n','\r\n').encode('utf8'))
    print(json.dumps({'manifest_sha256':pin['manifest_sha256'],'default_enabled':pin['default_enabled'],'fresh_joint':v2['fresh']['joint_raw'],'old32_joint':v2['reused32']['joint_raw']}))

if __name__=='__main__':main()
