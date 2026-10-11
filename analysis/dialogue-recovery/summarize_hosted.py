"""Read saved official evaluations; report stalls without changing any verdict."""
import argparse
import json
import statistics
from pathlib import Path


def summarize(folder):
    summary = json.loads((folder / 'summary.json').read_text())
    calls = []
    for path in sorted((folder / 'calls').glob('*.json')):
        call = json.loads(path.read_text())
        users, assistants, events = [], [], []
        for message in call['messages']:
            role = message.get('role')
            if role == 'user':
                users.append(message)
            elif role == 'assistant':
                assistants.append(message)
            elif role == 'system':
                try:
                    event = json.loads(message.get('message', ''))
                except (ValueError, TypeError):
                    continue
                if isinstance(event, dict):
                    events.append((message.get('secondsFromStart', 0), event))
        last_user = users[-1].get('secondsFromStart', 0) if users else None
        unanswered = last_user is not None and not any(m.get('secondsFromStart', 0) > last_user for m in assistants)
        after_user = [event for seconds, event in events if last_user is not None and seconds > last_user]
        calls.append({
            'id': call['id'], 'user_messages': len(users), 'assistant_messages': len(assistants),
            'ended_reason': call.get('endedReason'), 'duration_s': call.get('duration'),
            'unanswered_final_user': unanswered,
            'unanswered_until_end_s': round(max(0, call.get('duration', 0) - last_user), 1) if unanswered else None,
            'system_events_after_final_user': len(after_user),
            'opening_only_stall': len(users) == 1 and len(assistants) == 1 and unanswered and not after_user,
        })
    waits = [c['unanswered_until_end_s'] for c in calls if c['unanswered_until_end_s'] is not None]
    return {'official_summary_unchanged': summary, 'call_count': len(calls),
            'opening_only_stalls': sum(c['opening_only_stall'] for c in calls),
            'median_unanswered_until_end_s': statistics.median(waits) if waits else None,
            'unanswered_metric_is_diagnostic_not_official_score': True, 'calls': calls}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runs', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = {folder.name: summarize(folder) for folder in sorted(args.runs.iterdir())
              if folder.is_dir() and (folder / 'summary.json').exists()}
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({name: {key: data[key] for key in ('call_count', 'opening_only_stalls', 'median_unanswered_until_end_s')}
                      for name, data in result.items()}))
