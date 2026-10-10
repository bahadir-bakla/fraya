"""Read only documented config key names and designated auth-directory metadata.

Never parse/display token values or open auth files. This cannot determine the
identity/provider of generically named auth files; that limitation is explicit.
No config writes, provider logins, service restarts or management mutations.
"""
from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import re

from proxy_provider import CONNECTION
from run import RUNTIME, ROOT, json_write, write_reports


def inspect() -> dict:
    metadata = json.loads(CONNECTION.read_text(encoding="utf-8-sig"))
    config = Path(metadata["provenance"]["config_path"])
    repository = Path(metadata["provenance"]["repository_path"])
    if config.name != "config.yaml" or config.parent.parent != repository.parent:
        raise ValueError("Not the designated normal bin/config.yaml")
    keys = []
    auth_directory = None
    # Inspect key names only; skip every credential/provider value. auth-dir is
    # the sole documented nonsecret path value read to locate directory metadata.
    with config.open(encoding="utf-8-sig") as source:
        for line in source:
            match = re.match(r"^([a-zA-Z][a-zA-Z0-9_-]*):", line)
            if match:
                keys.append(match[1])
                if match[1] == "auth-dir":
                    value = line.split(":", 1)[1].strip().strip('"\'')
                    auth_directory = Path(value).expanduser()
                    if not auth_directory.is_absolute():
                        auth_directory = (config.parent / auth_directory).resolve()
    counts = Counter()
    if auth_directory and auth_directory.is_dir():
        for path in auth_directory.iterdir():
            if not path.is_file() or path.suffix.lower() != ".json":
                continue
            lower = path.name.lower()
            counts["claude_named" if lower.startswith(("claude", "anthropic"))
                   else "codex_named" if lower.startswith("codex") else "other_or_generic"] += 1
    evidence = {"config_path": str(config), "repository_path": str(repository),
                "top_level_config_keys": keys, "auth_directory": str(auth_directory) if auth_directory else None,
                "auth_file_name_class_counts": dict(counts),
                "claude_api_key_section_present": "claude-api-key" in keys,
                "openai_compatible_section_present": "openai-compatibility" in keys,
                "oauth_exclusion_section_present": "oauth-excluded-models" in keys,
                "oauth_alias_section_present": "oauth-model-alias" in keys,
                "auth_file_contents_read": False, "credential_values_inspected_or_displayed": False,
                "proxy_configuration_modified": False, "existing_service_restarted": False,
                "limitation": "Filename classes do not establish provider identity for generic auth files or prove token validity. No auth file was opened."}
    RUNTIME.mkdir(exist_ok=True)
    json_write(RUNTIME / "proxy-readiness.json", evidence)
    report_path = ROOT / "analysis/opus-redteam.json"
    if report_path.is_file():
        report = json.loads(report_path.read_text(encoding="utf-8"))
        report["proxy_provider_readiness"] = evidence
        write_reports(report)
    return evidence


if __name__ == "__main__":
    print(json.dumps(inspect(), indent=2))
