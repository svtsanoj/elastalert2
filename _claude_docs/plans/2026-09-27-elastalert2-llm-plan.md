# elastalert2-llm: an agentic assistant for creating and debugging ElastAlert 2 alerts

## Context
ElastAlert 2 is powerful, but writing and fixing rules needs YAML, query DSL and ElastAlert-internals expertise. In practice the logs are messy (application teams won't change their logging), and real alert logic is often more than a threshold: multi-index aggregation, comparisons, and category/sub-category dedup. The goal is an **agentic LLM assistant** that non-technical users can talk to. It should:
- **Create alerts** from plain language. It inspects the real indices (mappings, sample docs, field stats), asks for missing details, writes the rule, and backtests it on real data.
- **Debug alerts:** "why didn't this fire at 3pm?" or "why is this so noisy?". It reads the rule, ElastAlert's status/error/silence indices and the actual data, reruns the rule over the period, and explains the cause in plain words.
- **Find logical gaps** such as field renamed or missing, text vs keyword, timezone, late data vs `buffer_time`/`query_delay`, `realert` suppression, an index pattern that matches nothing, or overlapping/duplicate rules.
- **Write custom wrapper functions** (ElastAlert enhancements, rule types, alerters) when YAML alone can't express the logic, with tests, and only after the user approves the diff.

**No changes to ElastAlert 2 core are needed.** Everything uses the official extension points:
- Custom rule types and alerters are loaded by dotted path; the schema has a "Custom Rule from Module" branch ([schema.yaml:239](../../elastalert/schema.yaml#L239)) and allows extra keys.
- `garbage_collect()` runs every cycle ([elastalert.py:897](../../elastalert/elastalert.py#L897)).

Optional generic improvements can go upstream as small separate PRs, e.g. making `elastalert-test-rule --data` apply `filter`, which it ignores today ([test_rule.py:303](../../elastalert/test_rule.py#L303)).

### Decisions
- Repos: **rename this fork `elastalert3` → `elastalert2`**. The user does this in GitHub Settings; it stays linked to jertel/elastalert2, and GitHub redirects the old URL. After that, `git remote set-url origin https://github.com/svtsanoj/elastalert2.git` and `git remote add upstream https://github.com/jertel/elastalert2.git`. The fork is used for upstream PRs only. The **add-on goes in a new repo `elastalert2-llm`** (`C:\Users\Sanoj\Projects\elastalert2-llm`), published to PyPI and installed with `pip` next to a stock elastalert2.
- **Docs stay in this fork's `_claude_docs/` for now**, and every generated doc goes there. Reference/learning guides go in `_claude_docs/reference_guides/`.
- **Commits:** Claude commits under the user's git identity (from `git config`), with **no Co-Authored-By/Claude trailer** and brief, plain, human-style messages (e.g. `Add learning docs and project plan`). Save this to memory. The user's instruction overrides the default attribution reminder.
- Local stack: Elasticsearch + Kibana **9.5.3** (prod version unknown; stay compatible with 8.x). ES heap 1GB. Use Qwen3.5-9B while the stack runs, and Gemma 4 26B-A4B / Qwen3.6-35B-A3B when it's stopped (these are better for agentic work).
- LLM backends: Ollama (default, with tool calling), OpenAI-compatible (llama-server/LM Studio), and optional Claude. GUI: Tkinter.

## Step 1 (now): docs + first commit, then stop for review
Create these files in this repo (docs only, no code):
```
_claude_docs/
  README.md                                   index, reading order, and "docs live here" rule
  plans/2026-09-27-elastalert2-llm-plan.md    copy of this plan
  reference_guides/
    open-source-best-practices.md             general OSS guide (below)
    elastalert2-repo-guide.md                 this repo: layout, design patterns, how to extend, conventions, CI, releases
    upstream-contribution-workflow.md         fork/upstream remotes, branch-per-PR from upstream/master, keeping the fork in sync, PR checklist from CONTRIBUTING.md, review etiquette
    local-llm-models.md                       the model table, RAM budgeting, Ollama pull commands, EXPO tip
  setup/
    local-dev-setup-windows.md                Python 3.13 venv, `pip install -e .` + requirements-dev, pytest/tox, `make test-docker` via Docker Desktop/WSL2, flake8
    elasticsearch-kibana-local.md             ES/Kibana 9.5.3 with Docker compose (security on, 1GB heap, kibana_system password), config.yaml for local, elastalert-create-index, running elastalert --verbose, elastalert-test-rule; 8.x/OpenSearch notes
    mock-data-and-scenarios.md                index templates, messy-log examples (JSON, plain text, odd timestamp field), a lookup-mode index, seeding with `_bulk` via curl/Kibana Dev Tools (copy-paste ready, no code needed), time-shifting to "now", scenario ideas (threshold, spike, flatline, multi-index compare, category roll-up, late data)
  design/
    agentic-alert-assistant.md                product/design doc for elastalert2-llm (sections A–E below, hierarchy only as one example capability)
```
Contents of the two main reference guides:
- **open-source-best-practices.md:**
  - Licences (Apache-2.0 and what it permits, NOTICE).
  - Forks vs new repos, and add-on vs upstream contribution.
  - Issues before PRs, small focused PRs, commit message style.
  - Semantic versioning, Keep-a-Changelog.
  - Tests and CI as the entry bar, code review etiquette.
  - CODE_OF_CONDUCT / CONTRIBUTING / SECURITY policies.
  - Docs-as-code.
  - Publishing to PyPI with trusted publishing, and naming a package that extends another project (`elastalert2-*`, don't imply official status).
  - Maintaining a project: triage, labels, releases, deprecations.
  - Building a community.
- **elastalert2-repo-guide.md:**
  - Directory map.
  - Entry points (`elastalert`, `elastalert-test-rule`, `elastalert-create-index` in [setup.py](../../setup.py)).
  - The run loop (`ElastAlerter.run_rule`: query → rule type → matches → enhancements → alerters → writeback).
  - Design patterns:
    - Registries: `rules_mapping`/`alerts_mapping` in [loaders.py](../../elastalert/loaders.py).
    - Plugin loading by dotted path (`get_module`).
    - Template-method base classes (`RuleType.add_data/add_match/garbage_collect`; `Alerter.alert/get_info`, `required_options`).
    - Enhancement pipeline.
    - JSON-schema validation (`schema.yaml`).
    - Writeback index as a state store (status/silence/error/past).
    - `realert`/aggregation.
    - The version-aware ES client wrapper ([elastalert/__init__.py](../../elastalert/__init__.py)).
    - `MockElastAlerter` for testing.
  - Conventions: flake8 140 columns, "don't reformat existing code", pytest with mocks, `tests/alerters/*`.
  - Docs: Sphinx RST + ReadTheDocs.
  - Helm chart, Docker image.
  - CI workflows: `master_build_test.yml`, and publishing on tag.
  - Release process (from CONTRIBUTING).
  - Checklists: "add a new alerter" and "add a new rule option" end-to-end (code + schema.yaml + docs + tests + CHANGELOG + chart/examples).

Then **commit** on `master` (brief message, the user's identity, no trailer). Do not push unless asked.

## Step 2+: the add-on (in the new `elastalert2-llm` repo, after the user reviews the docs)

### A. Agent core
- **Agent loop** with tool calling (Ollama `/api/chat` `tools`, OpenAI-compatible `tools`, Claude tool use). Max steps and per-step timeouts. Tool results are truncated or summarised so the context stays small for CPU inference. The transcript shows each tool call (collapsible) so users can see what the agent looked at.
- **Read-only data tools** (default ES permissions: read-only API key):
  - `list_indices`, `get_mapping`, `sample_docs`
  - `field_stats` (top terms, cardinality, missing %, min/max)
  - `date_histogram`
  - `run_query` (DSL or ES|QL, size-capped)
  - `read_elastalert_state` (elastalert_status / error / silence / past for a rule)
  - `list_rules` / `read_rule`
- **Test tools:**
  - `validate_rule`: FileRulesLoader `load_options`/`load_modules`/`load_alerts` ([loaders.py:314-560](../../elastalert/loaders.py#L314)).
  - `simulate_rule`: offline scenarios through the real engine via `MockElastAlerter` mocks + a local `filter_eval`.
  - `backtest_rule`: `elastalert-test-rule` over the last N days of real data, answering "would this have fired, when, and how often".
  - `compare_backtests`: before/after for a proposed change, e.g. "41 alerts last week → 3".
- **Write tools (always require user approval in the GUI, shown as a diff):** `propose_rule_change`, `write_custom_module` (a Python enhancement/rule type/alerter in `custom_modules/` following the upstream recipes, plus pytest tests), `run_module_tests` (subprocess with a timeout). Generated code is AST-checked for disallowed imports and calls (subprocess, socket, eval…), never runs against prod automatically, and is never saved without approval.
- **Completeness guard:** deterministic checks turn gaps into questions for the user (missing index or destination settings, placeholders, unmapped fields, no dedup choice) even if the model says it's done.

### B. Modes (GUI tabs / conversation starters)
1. **Create:** describe the alert → the agent explores the indices → asks questions → produces the rule, a plain-English summary, scenarios (PASS/FAIL), edge cases and a backtest.
2. **Debug:** pick a rule + describe the symptom → the agent investigates (state indices, reruns, data checks) → a root-cause explanation + a proposed fix + a before/after backtest.
3. **Review:** audit all rules: zero-match rules, overlapping or duplicate rules, fragile filters, missing dedup, and field drift since the rule was written.
4. **Explain:** turn any existing YAML into plain English for non-technical owners.

### C. Reusable building blocks shipped in the add-on
These let the agent compose logic instead of writing code each time:
- `MultiSourceRule` / correlation: aggregate and compare across indices, with per-source field normalisation (regex, map, lookup, coalesce, ES|QL GROK/DISSECT/LOOKUP JOIN when available). Category → sub-category roll-up is one configuration of it.
- `IncidentReconciler` alerter: opens, updates and resolves tickets against the current state each run, so there are no duplicate active tickets. Parent + linked children policy. Jira, ServiceNow and webhook adapters, and a memory adapter for tests.
- A safe expression evaluator for conditions (AST whitelist, no `eval`).

### D. GUI (Tkinter)
- Left: conversation, a question form, and the tool-call trace.
- Right tabs: Rule YAML (editable, with a diff view for proposals), Tests, Backtest, Edge cases, Validation, Custom modules.
- Toolbar: backend, model (listed from the backend), thinking on/off, context size, ES connection (config.yaml picker), and a tok/s display.

### E. Dev environment, packaging and OSS (in the new repo)
- `dev/docker-compose.yml` (ES/Kibana 9.5.3), `elastalert2-llm-seed` (scenario YAML → templates + time-shifted bulk data + `--live` streaming), scenario packs.
- `pyproject.toml` (src layout, `elastalert2>=2.31,<3`, extra `[claude]`), Apache-2.0, README, CHANGELOG, CONTRIBUTING, CODE_OF_CONDUCT, SECURITY, GitHub Actions CI (flake8 + pytest on 3.12–3.14), PyPI trusted publishing on tag. Nothing is published without the user asking.

### Phases after Step 1
1. Repo skeleton + dev stack + seeder.
2. Validator/simulator/backtest tools + read-only ES tools.
3. Agent loop + backends + completeness guard.
4. GUI (Create / Debug / Explain).
5. Building blocks (multi-source rule, reconciler).
6. Custom-module writing with approval and tests.
7. Review mode, docs, release.

## Verification
- **Step 1:**
  - All files exist under `_claude_docs/` and the Markdown renders; links to repo files resolve.
  - Commands in the setup docs are checked where feasible (e.g. `python -m venv`, `pip install -e .`, `pytest tests -q -x`, and `docker compose config` on the compose snippet).
  - `git log -1` shows the user as author with no Claude trailer, and `git status` is clean.
- **Later phases:**
  - Unit tests per module with no network.
  - End-to-end on the local stack: seed a scenario, ask the agent "why didn't payments-errors fire?" (seeded with a renamed field), and it should find the field drift and propose a fix with a before/after backtest.
