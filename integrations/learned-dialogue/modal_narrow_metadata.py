"""Public-only pinned encoder metadata + offline installed SDK capabilities.

No token/config/client reads. --fetch-public downloads only metadata/tokenizer,
not the 470MB weights. No cloud application or training is invoked.
"""
import argparse
import hashlib
import importlib.metadata
import inspect
import json
import sys
import urllib.request
from pathlib import Path

from modal_narrow_core import canonical, digest
from modal_narrow_teacher import MODEL_ID, REVISION

FILES = ("README.md", "config.json", "model.safetensors", "tokenizer.json", "tokenizer_config.json", "special_tokens_map.json", "sentencepiece.bpe.model")


def sdk_report():
    import modal
    version = importlib.metadata.version("modal")
    params = inspect.signature(modal.App.function).parameters
    required = ("startup_timeout", "retries", "max_containers", "single_use_containers", "include_source", "cpu", "memory")
    return {"sdk_version":version, "python_executable":sys.executable,
            "startup_timeout_since":"1.1.4", "required_function_parameters":{k:k in params for k in required},
            "cancel_terminate_containers":"terminate_containers" in inspect.signature(modal.FunctionCall.cancel).parameters,
            "function_call_from_id":callable(modal.FunctionCall.from_id),
            "get_timeout":"timeout" in inspect.signature(modal.FunctionCall.get).parameters,
            "app_stop_method":hasattr(modal.App, "stop"),
            "app_stop_fallback":"python -m modal app stop --yes <exact ap-ID>",
            "sdk_stop_has_been_exercised_remotely":False, "auth_material_read":False,
            "installed_dependencies":{name:importlib.metadata.version(name) for name in ("torch", "transformers", "safetensors", "huggingface_hub")}}


def fetch_public():
    api = f"https://huggingface.co/api/models/{MODEL_ID}/revision/{REVISION}?blobs=true"
    with urllib.request.urlopen(api, timeout=20) as response:
        metadata = json.load(response)
    if metadata["sha"] != REVISION or metadata.get("cardData", {}).get("license") != "mit":
        raise ValueError("Pinned repository/license metadata changed")
    siblings = {r["rfilename"]:r for r in metadata["siblings"]}
    files = {}
    for name in FILES:
        item = siblings[name]
        if "lfs" in item:
            files[name] = {"size":item["size"], "sha256":item["lfs"]["sha256"], "hash_source":"official repository LFS pointer"}
        else:
            with urllib.request.urlopen(f"https://huggingface.co/{MODEL_ID}/resolve/{REVISION}/{name}", timeout=20) as response:
                blob = response.read(600000)
            if len(blob) != item["size"]:
                raise ValueError("Metadata file size mismatch")
            files[name] = {"size":len(blob), "sha256":digest(blob), "hash_source":"downloaded pinned public metadata"}
    return {"model_id":MODEL_ID, "revision":REVISION, "declared_license":"mit",
            "license_evidence":"Pinned official README front matter license: mit and official repository cardData; no separate LICENSE file is published in this revision",
            "origin":"intfloat repository; model card states initialized from microsoft/Multilingual-MiniLM-L12-H384",
            "source":f"https://huggingface.co/{MODEL_ID}/tree/{REVISION}",
            "metadata_api":api, "embedding_dimensions":384, "layers":12,
            "files":files, "bytes_total":sum(info["size"] for info in files.values()),
            "weights_downloaded_by_preparation":False, "upstream_benchmark_results_are_not_dialogue_or_bank_policy_evidence":True}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fetch-public", action="store_true")
    args = parser.parse_args()
    if args.fetch_public:
        path = Path(__file__).with_name("modal_narrow_model.json")
        with path.open("xb") as handle:
            handle.write(canonical(fetch_public()))
        print(json.dumps({"model_manifest":str(path), "sha256":digest(path.read_bytes())}))
    else:
        print(json.dumps(sdk_report(), indent=2))


if __name__ == "__main__":
    main()
