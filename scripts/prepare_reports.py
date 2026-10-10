"""Refresh local milestone/benchmark evidence without any network calls."""
import collections
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    kit = ROOT / 'competition-v3' / 'build-the-builder'
    cases = json.loads((kit / 'public-test-set.json').read_text(encoding='utf-8'))
    inventory = {
        'source': 'competition-v3/build-the-builder/public-test-set.json',
        'total': len(cases), 'by_brief': dict(collections.Counter(c['brief'] for c in cases)),
        'cases': [{k: c[k] for k in ('id', 'brief', 'family', 'level', 'title', 'checks', 'expected')} for c in cases],
        'final': {'briefs': 2, 'customers_per_brief': 30, 'repeats_per_customer': 3,
                  'scored_customers': 60, 'call_trials': 180, 'partial_credit': False},
        'evaluation': ['ledger outcome and all records', 'transcript policy checks', 'honesty checks'],
        'coverage_limits': ['13 public cases do not estimate hidden score.',
                            '50 synthetic planning cases are not registered hosted fixtures.',
                            'A correct bank write does not prove policy or conversation-order compliance.',
                            'One green run does not prove repeatability.'],
        'development_layers': ['deterministic local policy/calendar/state tests',
                               'independent oracle and mutation/metamorphic tests',
                               'hosted public cases, repetitions and speaking-style variants'],
        'final_build_budget_seconds': 1800,
        'simulation_parallelism': 1,
        'budget_policy': 'Use targeted smoke/regression tests within each final build; broad repeated evaluation is development work.',
    }
    (ROOT / 'analysis' / 'benchmark-plan.json').write_text(json.dumps(inventory, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    text = '''FINAL BENCHMARK VE GELİŞTİRME PLANI

Final: iki görülmemiş brief; her biri kendi OpenAPI dosyasıyla gelir. Temiz şartname
ve ham banka materyali (mail/policy/memo/code list) biçimleri beklenir. Alanlar,
enumlar, doğrulama soruları, limitler, takvim ve sonuç tablosu girdiden türetilir.
Final açıldıktan sonra yeni değer/politika builder koduna veya prompta elle eklenemez.

30 müşteri/brief, toplam 60 müşteri, her müşteri 3 kez: 180 çağrı denemesi.
Bir müşteri yalnız üç koşunun da tamamında başarılıysa sayılır. Sonuç/ödeme
sözleri/notlar/callback/transfer banka ledger'ından; politika ve dürüstlük
konuşmadan kontrol edilir. Kısmi puan yok. Eşitlik sırası: geçen müşterilerde
toplam söz tutarı, kısa build süresi, erken teslim. API ok:true politika kanıtı değildir.

Public ZIP benchmark: A için 10, B için 3 müşteri. JSON beklenen kayıtları ve
konuşma checks alanlarını, tools/score.py ledger oracle'ını, run_cases.py fixture
kurma + persona + simülasyon + iki sonucu birleştirme yolunu içerir. Kaynak kit
değiştirilmedi. Vakaların ayrıntısı benchmark-plan.json dosyasındadır.

ÜÇ TEST KATMANI
1. Yerel: source-linked kural/floor/date/business-day/now/identity/retry ve
   proposed-confirmed-recorded state ayrımı. Bunları canlı LLM beklemeden denetle.
2. Bağımsız oracle: ledger ve konuşma sırasını birlikte doğrula. Test beklentisini
   workflow'un kendi iddiasından türetme; kaynakla tekrar karşılaştır. Mutasyonlar
   yanlış guard, eksik confirmation, note-before-transfer ve yanlış close'u yakalasın.
3. Freya: önce hedefli public smoke, sonra public 13 ve tekrarlar; pieces, corrects,
   talkative, asks_back, in_words varyasyonları. Simülatörün fact/speech fidelity'sini
   de denetle. API/altyapı, yavaşlık, timeout ve gerçek politika hatasını ayrı raporla.

GELİŞTİRME SIRASI VE BİTİŞ ÖLÇÜTLERİ
A. Kaynak/API inventory: tamamlandı; 47 A + 11 B numaralı kural kayıpsız, tool
   isimleri OpenAPI allowlist'inden. Semantic override/contradiction çözümü henüz yok.
B. Policy compiler: brief'ten parametreli IR + provenance + explicit override;
   bağımsız kaynak denetçisi; belirsizliği görünür tut. Sabit A/B değerleri builder
   çekirdeğine gömülmesin. Değiştirilmiş brief/API ile genelleme testi bitiş şartı.
C. Freya compiler: official nodes/transitions, tools/result mapping, code/hook
   guard'ları, kimlik gate'leri, ürün state ve not erteleme. Dry-run + saklanan ve
   yayımlanan sürümün geri okunması bitiş şartı. Legacy exporter henüz uygun değil.
D. Oracle/runner: bağımsız beklenen ledger ve konuşma sırası; public 13, üç tekrar,
   kritik edge/style testleri; başarısız simülatör ve infra ayrı durumlar. 50 case
   kataloğu tasarım girdisidir; keyfi bank fixture kayıt endpoint'i belgelenmemiştir.
E. Otomatik build-check-repair: tek komut, 1800 sn toplam bütçe; kendi testleri
   dahil. 30 dk'ya sığan hedefli test seçimi, sınırlı düzeltme, en iyi doğrulanmış
   sürümü saklama. Geniş 13x3/style taraması geliştirme sırasında yapılmalı.
F. Teslim: platform export'u + builder repo/commit/run_command + her brief için
   trace. Trace start/end, her model/purpose, Freya object/version/step/tool sayısı
   ve tüm testleri içermeli. İki workflow JSON tek başına teslimin tamamı değildir.

PARALEL İŞ BÖLÜMÜ
Compiler/provenance; Freya emitter/state/hooks; bağımsız oracle/local fixtures;
integration/trace/budget olmak üzere ayrı dosya sahipliği. Kod işleri paralel,
aynı workspace'teki hosted simülasyonlar seri. Her kişinin slotu ayrı olsun.

MIROFISH
Henüz kurulmadı veya çalıştırılmadı. Plan: yalnız persona/konuşma varyasyonu
üreten optional adapter; fact fixture ve oracle ayrı tutulacak. Hosted test
sonucunu MiroFish'in başarı iddiası belirlemeyecek. Önce Freya test döngüsü ve
compiler; sonra MiroFish ile farklı persona/style/correction kombinasyonları.

CANLI DURUM
MCP 22 araç; authenticated health/list/dry-run/save/publish/practice/simulation,
transcript/ledger okuma ve export çalıştı. Dış koşu bitince smoke başlatıldı.
PUB-01 tek koşuda ledger geçti, conversation judge SMS teyidi eksik olduğu için
kaldı. Bu, kayıt doğru olsa bile policy'nin puanı sıfırladığını canlı gösteriyor.
Baseline, otomatik builder'ın ürettiği final ajan veya yarışma hazır oluş kanıtı değil.

KAYNAKLAR
competition-v3/build-the-builder/README.md; public-test-set.json; tools/score.py;
tools/run_cases.py; docs/api.md. Resmî final takvimi/detayları:
https://www.freyavoice.ai/hackathon (yerel snapshot analysis/official-hackathon.txt).
Literatür: analysis/literature-review.txt; guide merge: analysis/guide-merge.txt.
'''
    (ROOT / 'analysis' / 'benchmark-plan.txt').write_text(text, encoding='utf-8')
    path = ROOT / 'analysis' / 'competition-contract.json'
    contract = json.loads(path.read_text(encoding='utf-8'))
    contract['status'] = 'source/API inventory and live MCP bridge verified; general semantic/Freya compiler pending'
    contract['milestone'] = {'branch': 'codex/builder-contract', 'main_tests': {'passed': 230, 'skipped': 2},
                             'bridge_tests': {'passed': 18}, 'mcp_tools': 22,
                             'live_verified': ['authenticated workspace access', 'remote workflow dry-run', 'isolated workflow save+publish', 'official practice session preparation', 'simulation completion on fixed model/version', 'transcript and ledger retrieval/scoring', 'secret-redacted platform export'],
                             'smoke_status': 'completed: reference baseline ledger passed; transcript failed missing SMS confirmation',
                             'guide_merge': 'analysis/guide-merge.json', 'literature': 'analysis/literature-review.json',
                             'benchmark': 'analysis/benchmark-plan.json'}
    contract['submission'] = {'code_repository': 'https://github.com/bahadir-bakla/fraya', 'visibility': 'private',
                              'requested_collaborator': 'yusuf-said', 'collaborator_status': 'write invitation created',
                              'final_run_command_inputs': ['brief_path', 'tool_api_path'], 'ready': False}
    path.write_text(json.dumps(contract, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print('Benchmark inventory, staged development plan and milestone contract refreshed.')


if __name__ == '__main__':
    main()
