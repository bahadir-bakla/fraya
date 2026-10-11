This packet contains actual BANKING77 publisher TRAIN utterances and their original support-intent labels. It is ready for auxiliary 77-class source-intent training. It contains no bank policy or action gold.

Load UTF-8 train.jsonl; use `text` as input and `source_label_id` as the supervised target. taxonomy.json retains the publisher label order. Use calibration.jsonl for source-intent confidence/threshold selection only. Freeze model/settings before eval.jsonl. Both held-out splits derive from publisher TRAIN and are internal evaluation, not fresh public test or blind policy OOD.

The publisher TEST already exists in the repository and has inspired other data. It is read only as a contamination guard. Any detected train root matching an exposed-test exact/delexicalized key is quarantined before splitting; test utterances and labels never enter this corpus.

Group before split: normalized/delexicalized template roots collect all literal case/punctuation/value variants. Conflicting-label roots are quarantined. One representative per retained root is emitted; all original row aliases and conversation_root_ids stay with it. BANKING77 provides single utterances, not conversation IDs. Each original row is its own unknown conversation root; this does not assert detection of actual shared conversations or all semantic paraphrases. New descendants/translations must inherit group_id and split.

All digit spans and detected contacts, explicit names/addresses, identifier and secret values are redacted. Exact pattern definitions are in the processor. Redaction auditing publishes only indices, hashes and counts; raw bytes stay under ignored .cache/. Regex scrubbing is heuristic and does not guarantee absence of all indirect identifiers or names.

Independent bank-domain approval of bank-adaptation-plan.json is pending. The plan prohibits transfer-intent-to-debt-payment mappings, supplies no invented policy labels, and reserves blind policy OOD separately with the parent. No model training has been run by this processor.

Reproduce from repository root, with Python 3.11+ and no third-party packages:
  python integrations/customer-datasets/day2_training_data.py --collect-only
  python integrations/customer-datasets/day2_training_data.py --process-only
  python integrations/customer-datasets/day2_training_data.py --verify
Cached offline collection: append --offline to --collect-only. Processing and verification perform no network calls. Run --self-test for focused scrub/group/hash regression checks. --verify recomputes every derived artifact from pinned raw bytes and requires byte-identical files and manifest.

The collector uses official immutable publisher raw URLs, byte/SHA256 pins, no redirects or environment proxy discovery, 10-second socket timeout, 45-second per-file and 120-second total download checks, and at most 2 MB per source. Derived corpus plus notices/audits is capped at 16 MB. Read manifest.json and validation.json for exact accounting and checks. Review NOTICE.txt and the retained publisher license/README before sharing.
