# skill-creator

An evidence-grounded meta-skill built for the [Skill Lift](https://www.kaggle.com/competitions/skill-lift) hackathon (Track 2 — Meta-Skills), on top of [BenchFlow's SkillsBench](https://github.com/benchflow-ai/skillsbench).

The submission itself lives at [`skills/skill-creator/`](skills/skill-creator/) — a single meta-skill that authors task-specific skills at solve time, under a contract-first authoring protocol, an executable pre-solver validator, and a mandatory 5-guard safety template.

See [`kaggle_writeup.md`](kaggle_writeup.md) for the full writeup, and [`TEST_LEDGER.md`](TEST_LEDGER.md) for the running record of every local practice-task run that produced each rule.

## Layout

```
skills/skill-creator/          the meta-skill itself (the actual submission)
├── SKILL.md                   authoring protocol
├── scripts/validate_skill.py  executable pre-solver validator
├── scripts/skill_graph.py     dependency/coverage graph helper
└── references/                contract-first core layer + 8 domain family adapters

submission.zip                 packaged submission (skills/skill-creator/, built via scripts/build_submission.ps1)
scripts/build_submission.ps1   reproducible build script for submission.zip
kaggle_writeup.md              full project writeup
TEST_LEDGER.md                 evidence ledger: every local task run, root cause, and the rule it produced
artifacts/                     thumbnail + gallery images for the Kaggle writeup
voice_contract/                the same contract-first approach for voice agents: policy -> live guard, audit, generated tests
agent_forge/                   an agent that builds voice agents: SOP -> workflow, prompts, guard, tests; simulate, repair, mutation-test
```

`skillsbench/` (the organizers' benchmark harness, task corpus, and sandbox runner) is not included here — it's a separate clone of [`benchflow-ai/skillsbench`](https://github.com/benchflow-ai/skillsbench), pulled in locally to run practice evaluations against.

## Build the Builder input contract

The `agent_forge inspect` command inventories multiple Markdown/text briefs and
their supplied OpenAPI document. It preserves rule IDs, source lines, table rows
and input hashes; tool names and request schemas come from OpenAPI. Explicit
amendments still need semantic compilation. This inventory is a development
artifact, and does not constitute a generated or tested Freya workflow.

```powershell
python -X utf8 -m agent_forge inspect base.md amendment.txt --tool-api openapi.json --out run/input-contract.json
```

The older `build` command currently emits the legacy offline workflow format.
Its green tests do not establish compatibility with the competition's Freya
workflow format. The platform bridge is under `integrations/freya-mcp/`.

## Reproducing the submission package

```powershell
git clone https://github.com/benchflow-ai/skillsbench.git
.\scripts\build_submission.ps1 -BuildLabel <label>
```

## Validating the skill pack standalone

```bash
python skills/skill-creator/scripts/validate_skill.py skills/skill-creator
```
