"""Bind an authored catalog to its exact file without changing actor or scoring rules."""
import hashlib
import json
from pathlib import Path

import benchmark_runner
import speech_stress_adapter

ROOT = Path(__file__).resolve().parents[2]
PACK_HASH_METHOD = "sha256_canonical_json_utf8_sorted_keys_compact_ensure_ascii_false"
SOURCE_HASH_METHOD = "utf8_lf_normalized_v1"
REQUIRED_SOURCES = frozenset({
    "competition-v3/build-the-builder/briefs/brief-a.md",
    "competition-v3/build-the-builder/briefs/brief-b.md",
    "competition-v3/build-the-builder/tools/openapi.json",
    "competition-v3/build-the-builder/public-test-set.json",
    "integrations/customer-datasets/speech_stress_adapter.py",
})


def raw_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_sha(path):
    data = Path(path).read_bytes()
    data.decode("utf-8")
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def source_path(name):
    if (not isinstance(name, str) or not name or "\\" in name or ":" in name
            or any(part in {"", ".", ".."} for part in name.split("/"))):
        raise ValueError("manifest source path traversal or invalid path")
    path = (ROOT / name).resolve()
    if not path.is_relative_to(ROOT.resolve()):
        raise ValueError("manifest source path escapes repository")
    return path


class BoundStressCatalog:
    KIT = speech_stress_adapter.KIT
    PUBLIC = speech_stress_adapter.b.PUBLIC
    validate_hosted = staticmethod(speech_stress_adapter.validate_hosted)
    persona_for = staticmethod(speech_stress_adapter.persona_for)
    score = staticmethod(speech_stress_adapter.score)

    def __init__(self, path, *, expected_sha256, manifest=None, manifest_sha256=None):
        if (manifest is None) != (manifest_sha256 is None):
            raise ValueError("manifest and manifest_sha256 must be supplied together")
        self.path = Path(path).resolve()
        self.expected_sha256 = expected_sha256
        self.manifest_path = Path(manifest).resolve() if manifest is not None else None
        self.manifest_sha256 = manifest_sha256
        self.source_path = Path(__file__).resolve()
        self.source_sha256 = raw_sha(self.source_path)
        self.verify_pack()

    def _verify_manifest(self):
        if self.manifest_path is None:
            return {}
        if self.path.resolve() != self.path or self.manifest_path.resolve() != self.manifest_path:
            raise ValueError("bound pack or manifest resolved path changed")
        if self.manifest_path.parent != self.path.parent or self.manifest_path == self.path:
            raise ValueError("manifest must be a separate sibling of the bound pack")
        raw = self.manifest_path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != self.manifest_sha256:
            raise ValueError("bound manifest file hash mismatch")
        manifest = json.loads(raw.decode("utf-8"))
        if not isinstance(manifest, dict) or manifest.get("pack") != self.path.name:
            raise ValueError("manifest pack basename mismatch")
        if manifest.get("normalized_pack_hash_method") != PACK_HASH_METHOD:
            raise ValueError("unsupported manifest pack hash method")
        canonical = benchmark_runner.digest(json.loads(self.path.read_text(encoding="utf-8")))
        if manifest.get("normalized_pack_sha256") != canonical:
            raise ValueError("manifest canonical pack hash mismatch")
        if manifest.get("raw_pack_sha256", self.expected_sha256) != self.expected_sha256:
            raise ValueError("manifest raw pack hash mismatch")
        binding = manifest.get("catalog_binding")
        if binding is not None:
            if (not isinstance(binding, dict)
                    or source_path(binding.get("pack_path")) != self.path
                    or source_path(binding.get("manifest_path")) != self.manifest_path
                    or binding.get("canonical_pack_sha256") != canonical):
                raise ValueError("manifest catalog binding mismatch")
        entries = manifest.get("source_hashes")
        if not isinstance(entries, list):
            raise ValueError("manifest source hashes must be a list")
        seen = set()
        for entry in entries:
            if not isinstance(entry, dict):
                raise ValueError("invalid manifest source hash entry")
            name = entry.get("path")
            path = source_path(name)
            if name in seen or entry.get("hash_method") != SOURCE_HASH_METHOD:
                raise ValueError("duplicate source or unsupported manifest source hash method")
            seen.add(name)
            if source_sha(path) != entry.get("sha256"):
                raise ValueError("manifest source hash mismatch: " + name)
        if not REQUIRED_SOURCES.issubset(seen):
            raise ValueError("manifest missing required source hashes")
        return {"bound_manifest_file_sha256": self.manifest_sha256,
                "bound_manifest_path": str(self.manifest_path),
                "bound_canonical_pack_sha256": canonical}

    def verify_pack(self):
        if raw_sha(self.source_path) != self.source_sha256:
            raise ValueError("bound catalog adapter source changed")
        if raw_sha(self.path) != self.expected_sha256:
            raise ValueError("bound catalog file hash mismatch")
        binding = self._verify_manifest()
        manifest = speech_stress_adapter.verify_pack(self.path)
        rows = speech_stress_adapter.catalog(self.path).to_rows()
        row_digest = benchmark_runner.digest(rows)
        if (manifest["catalog_sha256"] != row_digest
                or row_digest != benchmark_runner.digest(json.loads(self.path.read_text(encoding="utf-8")))):
            raise ValueError("bound catalog semantic digest mismatch")
        return {**manifest, "bound_pack_file_sha256": self.expected_sha256,
                "bound_adapter_sha256": self.source_sha256, **binding}

    def rows(self):
        self.verify_pack()
        rows = speech_stress_adapter.catalog(self.path).to_rows()
        if benchmark_runner.digest(rows) != benchmark_runner.digest(json.loads(self.path.read_text(encoding="utf-8"))):
            raise ValueError("bound catalog semantic digest mismatch")
        return rows
