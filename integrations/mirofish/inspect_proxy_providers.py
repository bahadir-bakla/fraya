"""Inspect only the designated proxy's provider types and enablement metadata.

No token, account name, filename, email, or free-form auth message is emitted.
Disk enablement is not evidence that a provider can perform inference.
"""
from collections import Counter
from datetime import datetime, timezone
import argparse
import hashlib
import json
from pathlib import Path

import yaml

from authenticated_runtime import ROOT, RUNTIME, proxy_settings, request_json

PROVIDERS = {"claude", "anthropic", "codex", "gemini", "antigravity", "kimi", "xai", "vertex", "openai"}


def aggregate(records):
    counts = Counter()
    for record in records:
        provider = str(record.get("type", record.get("provider", "unknown"))).lower()
        if provider not in PROVIDERS:
            provider = "unknown"
        disabled = record.get("disabled") is True
        counts[(provider, "disabled" if disabled else "enabled")] += 1
    return [
        {"provider": provider, "enablement": enablement, "count": count}
        for (provider, enablement), count in sorted(counts.items())
    ]


def inspect(settings):
    config = yaml.safe_load(settings["config_path"].read_text(encoding="utf-8-sig"))
    configured_auth_dir = config.get("auth-dir")
    if not isinstance(configured_auth_dir, str) or not configured_auth_dir:
        raise ValueError("No explicit auth-dir in the designated proxy configuration")
    auth_dir = Path(configured_auth_dir).expanduser()
    if not auth_dir.is_absolute():
        raise ValueError("Refusing to guess a relative credential directory")
    records, unreadable = [], 0
    for path in auth_dir.glob("*.json"):
        try:
            document = json.loads(path.read_text(encoding="utf-8-sig"))
            if not isinstance(document, dict):
                unreadable += 1
                continue
            # Retain only the two whitelisted fields; never expose raw documents.
            records.append({"type": document.get("type", "unknown"), "disabled": document.get("disabled") is True})
            del document
        except (OSError, ValueError):
            unreadable += 1
    rows = aggregate(records)
    _, inventory = request_json(settings["base_url"] + "/models", settings["key"], timeout=15)
    model_ids = sorted(entry["id"] for entry in inventory.get("data", []) if isinstance(entry.get("id"), str))
    claude_count = sum(row["count"] for row in rows if row["provider"] in {"claude", "anthropic"})
    configured = config.get("claude-api-key") or []
    management = (config.get("remote-management") or {}).get("secret-key")
    evidence = {
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "base_url": settings["base_url"], "auth_directory_source": "designated_config_auth-dir_only",
        "provider_enablement": rows, "auth_file_count": len(records), "unreadable_file_count": unreadable,
        "status_basis": "persisted enablement metadata; authentication validity not inferred",
        "claude_auth_file_count": claude_count, "claude_api_key_entry_count": len(configured),
        "model_ids": model_ids, "exact_claude_opus_5_5_available": "claude-opus-5-5" in model_ids,
        "exact_claude_opus_5_5_completion_verified": False,
        "supported_enablement_endpoint": "PATCH /v0/management/auth-files/status",
        "management_secret_configured": bool(management),
        "management_auth_tested": False, "auth_values_output": False,
        "proxy_config_modified": False, "auth_files_modified": False,
        "config_sha256": hashlib.sha256(settings["config_path"].read_bytes()).hexdigest(),
        "activation_performed": False,
        "activation_result": "no_existing_claude_auth_to_enable" if not claude_count and not configured else "requires_live_provider_status_check",
    }
    RUNTIME.mkdir(parents=True, exist_ok=True)
    (RUNTIME / "provider-inventory.json").write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    shared = ROOT / ".local-secrets" / "cli-proxy-connection.json"
    if shared.is_file():
        metadata = json.loads(shared.read_text(encoding="utf-8"))
        if metadata.get("base_url") != settings["base_url"]:
            raise ValueError("Shared connection does not describe the designated proxy")
        metadata.update(model_ids=model_ids, provider_inventory=evidence,
                        opus_model_ids=[model for model in model_ids if "opus" in model.lower()],
                        exact_claude_opus_5_5_available=evidence["exact_claude_opus_5_5_available"])
        shared.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return evidence


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--proxy-config", required=True)
    args = parser.parse_args()
    print(json.dumps(inspect(proxy_settings(args.proxy_config)), ensure_ascii=True))
