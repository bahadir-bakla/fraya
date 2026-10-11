"""Bounded official SGD TRAIN collection, pinned by publisher Git blob ancestry."""
import argparse
import concurrent.futures
import hashlib
import json
from pathlib import Path
import time
import urllib.request

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / ".cache"
REV = "e852981ae34990f4358979625854259302feaa78"
REPO = "google-research-datasets/dstc8-schema-guided-dialogue"
BASE = "https://raw.githubusercontent.com/" + REPO + "/" + REV + "/"
MAX_TOTAL = 450_000_000


def digest(data):
    return hashlib.sha256(data).hexdigest()


def encode(value):
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError("Redirect forbidden")


def checked(data, item):
    if len(data) != item["size"]:
        raise ValueError("Publisher byte count mismatch: " + item["path"])
    blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
    if blob != item["sha"]:
        raise ValueError("Publisher blob ancestry mismatch: " + item["path"])
    return data


def fetch(item, offline, deadline):
    target = CACHE / item["path"].replace("/", "__")
    if target.exists():
        data = checked(target.read_bytes(), item)
    else:
        if offline:
            raise FileNotFoundError(target)
        started = time.monotonic()
        if started >= deadline or item["size"] > 8_000_000:
            raise ValueError("Time/size bound exceeded")
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        request = urllib.request.Request(BASE + item["path"], headers={"User-Agent": "fraya-public-sgd-collection/1"})
        chunks, count = [], 0
        with opener.open(request, timeout=15) as response:
            if response.geturl() != BASE + item["path"]:
                raise ValueError("Unexpected URL")
            while True:
                if time.monotonic() > min(started + 90, deadline):
                    raise TimeoutError(item["path"])
                chunk = response.read(65536)
                if not chunk:
                    break
                count += len(chunk)
                if count > item["size"]:
                    raise ValueError("Source exceeded pinned size")
                chunks.append(chunk)
        data = checked(b"".join(chunks), item)
        CACHE.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return {"path": item["path"], "url": BASE + item["path"], "bytes": len(data), "sha256": digest(data), "publisher_blob_sha1": item["sha"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    inventory = json.loads((ROOT / "source-inventory.json").read_bytes())
    if inventory["revision"] != REV or inventory["declared_total_bytes"] > MAX_TOTAL:
        raise ValueError("Unexpected inventory/revision")
    items = inventory["files"]
    if any(not (x["path"] in ("README.md", "LICENSE.txt", "train/schema.json") or x["path"].startswith("train/dialogues_") and x["path"].endswith(".json")) for x in items):
        raise ValueError("Only official TRAIN and notices allowed")
    completed = []
    deadline = time.monotonic() + 600
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(fetch, item, args.offline, deadline) for item in items]
        for future in concurrent.futures.as_completed(futures):
            completed.append(future.result())
            report = {"stage": "collection", "status": "complete" if len(completed) == len(items) else "partial",
                      "revision": REV, "license": "CC-BY-SA-4.0", "official_split": "train", "official_dev_test": "untouched",
                      "inventory_sha256": digest((ROOT / "source-inventory.json").read_bytes()),
                      "size_ceiling_bytes": MAX_TOTAL,
                      "over_400MB_necessity_evidence": {"requested_goal": "full official TRAIN", "pinned_publisher_files": len(items), "uncompressed_source_bytes": inventory["declared_total_bytes"]},
                      "files_completed": len(completed), "files_expected": len(items), "bytes_verified": sum(x["bytes"] for x in completed),
                      "files": sorted(completed, key=lambda x: x["path"])}
            (ROOT / "collection-progress.json").write_bytes(encode(report))
            if len(completed) % 10 == 0 or len(completed) == len(items):
                print(json.dumps({key: report[key] for key in ("status", "files_completed", "files_expected", "bytes_verified")}), flush=True)
    (ROOT / "sources.json").write_bytes(encode(report))


if __name__ == "__main__":
    main()
