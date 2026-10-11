"""Replay frozen SGD v1 into bounded hash sinks, never overwriting the packet."""
from collections import Counter
import hashlib
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
FULL = HERE / 'full-v1'
MANIFEST_SHA = '7176ce8bf20c7e6adce899a276f7de0c042e0e33eb63999462264ca6c1843513'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    assert sha(FULL / 'manifest.json') == MANIFEST_SHA
    manifest = json.loads((FULL / 'manifest.json').read_bytes())
    assert sha(HERE / 'process.py') == manifest['processor']['sha256']
    spec = importlib.util.spec_from_file_location('sgd_frozen_replay', HERE / 'process.py')
    processor = importlib.util.module_from_spec(spec); spec.loader.exec_module(processor)

    class DigestShards:
        """Same byte/row shard boundaries, only digest state is retained."""
        def __init__(self, directory):
            self.directory = directory
            self.opened = {}; self.outputs = []; self.serial = Counter()

        def close(self, split):
            if split not in self.opened:
                return
            digest, rows, size, path = self.opened.pop(split)
            self.outputs.append({'path': processor.rel(path), 'split': split, 'sha256': digest.hexdigest(), 'bytes': size, 'rows': rows})

        def add(self, split, row):
            data = processor.line(row)
            assert len(data) <= processor.MAX_SHARD
            if split in self.opened and self.opened[split][2] + len(data) > processor.MAX_SHARD:
                self.close(split)
            if split not in self.opened:
                self.serial[split] += 1
                path = self.directory / (split.lower() + '-' + str(self.serial[split]).zfill(5) + '.jsonl')
                self.opened[split] = [hashlib.sha256(), 0, 0, path]
            entry = self.opened[split]
            entry[0].update(data); entry[1] += 1; entry[2] += len(data)

        def finish(self):
            for split in list(self.opened):
                self.close(split)
            return sorted(self.outputs, key=lambda x: x['path'])

    assert processor.self_test()['status'] == 'passed'
    items = processor.source_files(None)
    plan, counts, source_pins = processor.index_sources(items)
    assert source_pins == manifest['source_files']
    # JSON object keys in the histogram are strings on disk.
    assert json.loads(processor.encode(counts)) == manifest['counts']
    saved_plan = json.loads((FULL / 'split-plan.json').read_bytes())
    assert plan == saved_plan['dialogues']
    plan_bytes = processor.encode({'seed': processor.SEED, 'algorithm': saved_plan['algorithm'], 'dialogues': plan, 'summary': counts})
    assert hashlib.sha256(plan_bytes).hexdigest() == manifest['split_plan']['sha256']
    schema = json.loads((HERE / 'service-schema.json').read_bytes())
    assert sha(HERE / 'service-schema.json') == manifest['service_schema']['sha256']
    # The pinned processor functions and source bytes are unchanged. Only the
    # writer is replaced in memory; each encoded row feeds SHA256 immediately.
    processor.Shards = DigestShards
    outputs, target_counts = processor.emit(items, plan, {s['service_name']: s for s in schema}, processor.LOCAL / 'full-v1')
    assert outputs == manifest['outputs']
    assert target_counts == manifest['target_counts']
    assert sha(FULL / 'manifest.json') == MANIFEST_SHA
    report = {
        'status': 'passed', 'manifest_sha256': MANIFEST_SHA,
        'frozen_processor_sha256': manifest['processor']['sha256'],
        'reproduction_launcher_sha256': sha(Path(__file__)),
        'raw_primary_TRAIN_files_reverified_and_replayed': len(items),
        'raw_primary_TRAIN_dialogues': counts['source_counts']['dialogues'],
        'raw_primary_TRAIN_USER_turns': counts['source_counts']['USER_turns'],
        'raw_file_sha256_and_publisher_blob_ancestry_equal': True,
        'recomputed_group_closure_counts_equal': True,
        'recomputed_split_plan_byte_sha256_equal': True,
        'replayed_shard_count': len(outputs),
        'replayed_shard_bytes': sum(x['bytes'] for x in outputs),
        'replayed_all_shard_byte_hashes_rows_and_sizes_equal': True,
        'replayed_target_counts_equal': True,
        'writer_substitution': 'In-memory hash sink, same byte boundaries; no corpus output files opened for writing.',
        'source_or_frozen_packet_rewritten': False,
        'official_dev_test_read': False, 'model_fits': 0,
        'model_evaluation_outcomes_read': 0,
        'paths_metadata': 'Existing repository paths retained for digest specification only; initial manifest remains byte-exact.'
    }
    path = FULL / 'reproduction-report.json'
    content = processor.encode(report)
    if path.exists():
        assert path.read_bytes() == content, 'Existing reproduction report differs; use a new version.'
    else:
        path.write_bytes(content)
    print(json.dumps({'status': 'passed', 'manifest_sha256': MANIFEST_SHA, 'reproduction_report': processor.rel(path), 'reproduction_report_sha256': sha(path), 'replayed_shards': len(outputs)}, sort_keys=True))


if __name__ == '__main__':
    main()
