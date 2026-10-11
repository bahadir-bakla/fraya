"""Automatically generate a portable local candidate; no Freya publication.

Uses the unchanged historical practice seed and observed speech packet from the
earlier paired run. The component is a generator input, never a manual patch.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('final_pair', ROOT / 'scripts/run_local_builder_pair.py')
pair = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pair)
builder = pair.builder


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=('recipient', 'v2-student'), required=True)
    parser.add_argument('--student', type=Path)
    parser.add_argument('--student-sha256')
    parser.add_argument('--student-use',choices=('shadow','clarify'),default='shadow')
    parser.add_argument('--minutes', type=float, default=12)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('Never overwrite generation evidence')
    command = ['builder.py', str(builder.KIT / 'briefs/brief-a.md'),
               '--practice-repair', pair.SEED, '--repair-first', '--local-only',
               '--slot', 'local-final-a-' + args.mode, '--minutes', str(args.minutes),
               '--rounds', '2', '--semantic-assist', 'off', '--dialogue-assist', 'off',
               '--finetuned-assist', 'off', '--live-layer', args.mode, '--model', 'gpt-6.1-sol']
    if args.student:
        command += ['--live-student', str(args.student)]
    if args.student_sha256:
        command += ['--live-student-sha256', args.student_sha256]
    command += ['--live-student-use',args.student_use]
    old = sys.argv
    try:
        sys.argv = command
        parsed = builder.arguments()
    finally:
        sys.argv = old
    for name in tuple(os.environ):
        if any(word in name.upper() for word in ('API_KEY', 'TEAM_KEY', 'TOKEN', 'SECRET', 'PASSWORD')):
            os.environ.pop(name)
    with builder.slot_lock(builder.ROOT / '.state/slots' / (parsed.slot + '.lock')):
        run = pair.ComparisonRun(parsed)
        completed, error = False, None
        try:
            completed = run.execute()
        except Exception as exc:
            error = type(exc).__name__
            if run.status.get('phase') != 'failed':
                run.phase('failed', ended=builder.stamp(), error=run.clean(str(exc)))
        result = dict(status='COMPLETED_LOCAL_GENERATION' if completed else 'INCOMPLETE_OR_FAILED',
                      run_id=run.id, mode=args.mode, source_seed=pair.SEED,
                      original_status=run.status, failure_type=error, published=False,
                      Freya_calls=0, bank_authority=False, full_MiniLM_live=False,
                      scope='Automatic generated code-node component. Local source invocation needs replay; hosted execution is unverified.')
        # The source tree may progress while this frozen child is generating.
        # Record the actual builder snapshot rather than later working bytes.
        events=[json.loads(line) for line in run.trace.read_text(encoding='utf-8').splitlines()]
        result['builder_source_snapshot_sha256']=[e['sha256'] for e in events if e.get('kind')=='builder_source']
        result['live_component_inputs']=[e for e in events if e.get('kind')=='live_layer_input']
        result['live_component_embedding']=[e for e in events if e.get('kind')=='live_layer_embedding']
        if completed:
            result['artifact_sha256'] = {name: pair.sha(run.work/name) for name in ('workflow.json','policy.json','coverage.json')}
            result['live_component_sha256'] = run.live_layer_contract['files']['live-layer-code.py']
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        print(json.dumps({k: result[k] for k in ('status','run_id','mode')}), flush=True)
        return 0 if completed else 1


if __name__ == '__main__':
    raise SystemExit(main())
