"""Bounded, read-only corpus access; owned SQLite offset index, no data edits."""
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import sqlite3

ROOT = Path(__file__).resolve().parents[2]
PACKET = ROOT / "research/customer-benchmark/day2-training-data/sgd"
MANIFEST = PACKET / "full-v1/manifest.json"
SEED = 20261011


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as f:
        for b in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(b)
    return digest.hexdigest()


def order_key(kind, text):
    return hashlib.sha256((str(SEED) + ":" + kind + ":" + text).encode()).hexdigest()


def verify_shards(split=None):
    manifest = json.loads(MANIFEST.read_text())
    for item in manifest["outputs"]:
        if split is None or item["split"] == split:
            path = ROOT / item["path"]
            assert path.stat().st_size == item["bytes"] and sha(path) == item["sha256"], item["path"]
    return True


def make_index(split, schema):
    path = ROOT / ("analysis/day2-sgd-model-index-" + split + ".sqlite3")
    assert not path.exists(), "Owned index exists; no silent reuse/rebuild"
    manifest = json.loads(MANIFEST.read_text())
    plan = json.loads((PACKET / "full-v1/split-plan.json").read_text())["dialogues"]
    assert manifest["status"] == "ready_for_streaming_publisher_head_minibatch_training"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE records(dialogue TEXT,turn INTEGER,shard INTEGER,offset INTEGER,length INTEGER,PRIMARY KEY(dialogue,turn))")
    db.execute("CREATE TABLE dialogues(dialogue TEXT PRIMARY KEY,group_id TEXT,events INTEGER)")
    db.execute("CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT)")
    acts, support, reasons, samples = set(), Counter(), Counter(), {}
    counts = Counter()
    shards = [s for s in manifest["outputs"] if s["split"] == split]
    for si, shard in enumerate(shards):
        digest, count, size = hashlib.sha256(), 0, 0
        with (ROOT / shard["path"]).open("rb") as f:
            while True:
                offset = f.tell()
                b = f.readline()
                if not b:
                    break
                digest.update(b)
                size += len(b)
                count += 1
                row = json.loads(b)
                a = row["ancestry"]
                meta = plan[a["dialogue_id"]]
                assert a["split"] == split == meta["split"] and a["group_id"] == meta["group_id"]
                assert row["input"]["speaker"] == "USER" and len(row["input"]["earlier_context"]) <= 8
                assert not row["bank_policy_target_mask"] and not row["ledger_target_mask"]
                db.execute("INSERT INTO records VALUES (?,?,?,?,?)", (a["dialogue_id"], a["source_turn_index"], si, offset, len(b)))
                counts[a["dialogue_id"]] += 1
                if split == "TRAIN":
                    for frame in row["targets"]["frames"]:
                        samples.setdefault(frame["service"], row)
                        if any(u["update_mask"] for u in frame["belief_updates"]):
                            samples.setdefault("recoverable_update", row)
                        flags = frame["head_masks"]
                        if flags.get("publisher_actions"):
                            acts.update(action["act"] for action in frame["actions"])
                        for head, known in flags.items():
                            support[head] += bool(known)
                        if flags.get("active_intent"):
                            support["intent:" + frame["service"] + "::" + frame["active_intent"]] += 1
                        for u in frame["belief_updates"]:
                            if u["update_mask"]:
                                support["update:" + u["publisher_map_update"]] += 1
                            else:
                                reasons[u["reason"]] += 1
        assert count == shard["rows"] and size == shard["bytes"] and digest.hexdigest() == shard["sha256"], shard["path"]
        print(f"indexed {split} shard {si + 1}/{len(shards)} rows={count}", flush=True)
    assert sum(counts.values()) == manifest["counts"]["split_USER_examples"][split]
    for dialogue, events in counts.items():
        assert events == plan[dialogue]["user_turns"]
        db.execute("INSERT INTO dialogues VALUES (?,?,?)", (dialogue, plan[dialogue]["group_id"], events))
    db.execute("CREATE INDEX ordered_rows ON records(dialogue,turn)")
    db.execute("INSERT INTO metadata VALUES (?,?)", ("manifest_sha256", sha(MANIFEST)))
    db.commit()
    db.close()
    return {"path": path.relative_to(ROOT).as_posix(), "sha256": sha(path), "rows": sum(counts.values()), "dialogues": len(counts), "acts": sorted(acts), "support": dict(support), "masked_update_reasons": dict(reasons), "smoke_rows": list(samples.values())}


class DialogStream:
    def __init__(self, split, selection=None):
        # Every private index reuse revalidates actual input bytes, not just metadata.
        verify_shards(split)
        self.split, self.files = split, {}
        manifest = json.loads(MANIFEST.read_text())
        self.shards = [s for s in manifest["outputs"] if s["split"] == split]
        path = ROOT / ("analysis/day2-sgd-model-index-" + split + ".sqlite3")
        self.db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
        assert dict(self.db.execute("SELECT key,value FROM metadata"))["manifest_sha256"] == sha(MANIFEST)
        groups = defaultdict(list)
        for dialogue, group, events in self.db.execute("SELECT dialogue,group_id,events FROM dialogues"):
            if selection is None or selection(group):
                groups[group].append((dialogue, events))
        self.groups = sorted(groups, key=lambda g: order_key("group", g))
        self.dialogues = []
        for group in self.groups:
            items = sorted(groups[group], key=lambda r: order_key("dialogue", r[0]))
            for dialogue, events in items:
                weight = 132615 / (len(self.groups) * len(items) * events) if split == "TRAIN" else 1.
                self.dialogues.append((dialogue, group, weight))

    def rows(self, dialogue):
        result, previous = [], -1
        for turn, si, offset, length in self.db.execute("SELECT turn,shard,offset,length FROM records WHERE dialogue=? ORDER BY turn", (dialogue,)):
            assert type(si) is int and 0 <= si < len(self.shards)
            assert type(offset) is int and offset >= 0 and type(length) is int and length > 0
            assert turn > previous
            previous = turn
            if si not in self.files:
                self.files[si] = (ROOT / self.shards[si]["path"]).open("rb")
            f = self.files[si]
            f.seek(offset)
            result.append(json.loads(f.read(length)))
        return result

    def batches(self, batch_size=32):
        if type(batch_size) is not int or batch_size != 32:
            raise ValueError("This pinned pilot requires integer batch_size=32")
        queue, active = iter(self.dialogues), [None] * 32
        while True:
            for i in range(32):
                if active[i] is None:
                    item = next(queue, None)
                    if item:
                        dialogue, group, weight = item
                        active[i] = [dialogue, group, weight, self.rows(dialogue), 0]
            if all(a is None for a in active):
                break
            keys = [a[0] if a else None for a in active]
            steps = []
            for _ in range(4):
                rr, ww = [], []
                for a in active:
                    if a and a[4] < len(a[3]):
                        rr.append(a[3][a[4]])
                        ww.append(a[2])
                        a[4] += 1
                    else:
                        rr.append(None)
                        ww.append(0.)
                steps.append((rr, ww))
            yield keys, steps
            active = [a if a and a[4] < len(a[3]) else None for a in active]

    def close(self):
        for f in self.files.values():
            f.close()
        self.db.close()
