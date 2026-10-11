"""Frozen semantic comparison on sealed probes, separate from bank scoring."""
import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT / 'integrations/learned-dialogue'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--probes', type=Path, required=True)
    parser.add_argument('--probes-sha256', required=True)
    parser.add_argument('--student', type=Path)
    parser.add_argument('--student-sha256')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seconds', type=int, default=150)
    args = parser.parse_args()
    if args.output.exists() or not 1 <= args.seconds <= 300:
        raise ValueError('New bounded diagnostic output required')
    started = time.monotonic()
    deadline = started + args.seconds
    if sha(args.probes) != args.probes_sha256:
        raise ValueError('Sealed EVAL changed')
    rows = json.loads(args.probes.read_text(encoding='utf-8'))
    if not isinstance(rows, list) or not rows or any(r['split'] != 'EVAL' for r in rows):
        raise ValueError('Expected sealed EVAL flat list')
    rows = copy.deepcopy(rows)
    for row in rows:
        previous = row['input']['previous_utterances']
        row['input']['previous_utterances'] = [dict(speaker=t.get('speaker', t.get('role')), text=t['text']) for t in previous]
    import numpy as np
    import torch
    torch.set_num_threads(4)
    sys.path.insert(0, str(HERE/'minilm_ft_v2/runtime'))
    from minilm_ft_core import metrics, targets, DOMAIN, AUX
    from minilm_ft_eval import load_model
    for row in rows:
        targets(row)
    def measure(probabilities, thresholds):
        p = np.asarray(probabilities)
        if p.shape != (len(rows), 11) or not np.isfinite(p).all():
            raise ValueError('Nonfinite or wrong prediction shape')
        logits = np.log(np.clip(p, 1e-7, 1-1e-7)/np.clip(1-p, 1e-7, 1))
        known = np.asarray([targets(r)[1][:7] for r in rows], dtype=bool)
        gold = np.asarray([targets(r)[0][:7] for r in rows], dtype=bool)
        result = dict(raw=metrics(logits, rows), selected=metrics(logits, rows, thresholds))
        for name, th in [('raw', [.5]*7), ('selected', thresholds[:7])]:
            predicted = p[:, :7] >= np.asarray(th)
            keep = known.any(1)
            result['joint_'+name] = dict(correct=int((((predicted==gold)|~known).all(1)&keep).sum()), denominator=int(keep.sum()))
        result['predictions'] = [dict(id=r['id'], scores=[float(x) for x in p[i]],
            raw_wrong_heads=[h for j,h in enumerate(DOMAIN) if known[i,j] and bool(p[i,j]>=.5)!=bool(gold[i,j])]) for i,r in enumerate(rows)]
        return result
    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    modelpath = HERE/'minilm_ft_v2/model'
    pin = '7eca3b016b47ec20f1b1fd9e207c71a0c72ece9bf91f4e2c28ecd411dcb59189'
    if sha(modelpath/'manifest.json') != pin:
        raise ValueError('Frozen V2 changed')
    model, manifest = load_model(modelpath, device)
    arms = {}
    for name, kwargs in [('full_V2', {}), ('V2_no_context_diagnostic', dict(no_context=True))]:
        values = model.predict(rows, 16, deadline=deadline, **kwargs)
        arms[name] = measure(1/(1+np.exp(-np.clip(values,-50,50))), manifest['thresholds'])
    if args.student:
        mp = args.student/'manifest.json'
        if not args.student_sha256 or sha(mp) != args.student_sha256:
            raise ValueError('Explicit frozen student pin required')
        smanifest = json.loads(mp.read_text(encoding='utf-8'))
        for name, digest in smanifest['files'].items():
            if Path(name).name != name or sha(args.student/name) != digest:
                raise ValueError('Student payload changed')
        runtime = load(args.student/'runtime.py', 'portable_student_eval')
        smodel = json.loads((args.student/'model.json').read_text(encoding='utf-8'))
        values = []
        for row in rows:
            if time.monotonic() >= deadline:
                raise TimeoutError('Diagnostic deadline')
            inp = row['input']
            result = runtime.student_predict(inp['current_utterance'], inp['previous_utterances'], smodel)
            if result.get('bank_authority') is not False:
                raise ValueError('Student authority contract')
            values.append(result['scores'])
        arms[smanifest.get('model_kind','portable_student')] = measure(values, smodel['thresholds'])
        if sha(mp) != args.student_sha256 or any(sha(args.student/name)!=digest for name,digest in smanifest['files'].items()):
            raise ValueError('Student source changed during diagnostic')
    if sha(args.probes) != args.probes_sha256 or sha(modelpath/'manifest.json') != pin:
        raise ValueError('Frozen source changed during diagnostic')
    report = dict(status='COMPLETED_LOCAL_SEMANTIC_DIAGNOSTIC', cases=len(rows),
                  groups=len({r['group'] for r in rows}), probes_sha256=args.probes_sha256,
                  V2_manifest_sha256=pin, student_manifest_sha256=args.student_sha256,
                  source_sha256=sha(Path(__file__)), device=device, arms=arms,
                  seconds=time.monotonic()-started, bank_authority=False,
                  Freya_calls=0, Modal_launches=0, classic_ledger_score=None,
                  scope='Synthetic semantic labels; no bank fixtures/ledger or voice qualification. Exposed96 is regression; newly sealed probes have shared author ancestry, not human IID gold.')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({name: {'joint': result['joint_raw'], 'macro_F1': result['raw']['domain_macro_F1']} for name,result in arms.items()}),flush=True)


if __name__ == '__main__':
    main()
