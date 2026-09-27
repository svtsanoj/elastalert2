# elastalert2-llm: an agentic assistant for ElastAlert 2

Status: **design, not started**. Last updated 2026-09-27. Implementation plan: [../plans/2026-09-27-elastalert2-llm-plan.md](../plans/2026-09-27-elastalert2-llm-plan.md).

## 1. Problem

ElastAlert 2 can express a lot, but only for people who know:
- its YAML (12 rule types, about 45 alerters, `realert`, `query_key`, aggregation)
- the Elasticsearch query DSL
- how ElastAlert behaves internally (buffer windows, silences, writeback indices)

In practice:
- **Creating an alert** takes a back-and-forth between the person who knows the business rule and the person who knows ElastAlert.
- **Debugging an alert** ("why didn't it fire?", "why is it so noisy?") means reading ElastAlert's state indices, rerunning queries and knowing where to look.
- **Logs are messy and won't be fixed.** Application teams don't restructure their logging for the monitoring team, so rules must adapt to inconsistent field names, free-text messages and odd timestamp formats.
- **Real business logic is more than thresholds.** For example: aggregate across indices and compare, or roll many sub-category problems up into one category incident instead of a flood of duplicates.

## 2. Goal

A tool that lets a **non-technical owner** create, change and debug alerts by talking to it. An **agent** does the technical work. It inspects the actual indices, writes and tests the rule, explains the result in plain language, and, when YAML can't express the logic, writes a small custom module for approval.

Distributed as a **pip-installable add-on** (`pip install elastalert2-llm`) that works with a stock ElastAlert 2 (≥ 2.31). **No changes to ElastAlert 2 are required**, because everything plugs in through dotted-path extension points (see [elastalert2-repo-guide.md §6](../reference_guides/elastalert2-repo-guide.md#6-extending-elastalert-2-no-fork-needed)).

### Non-goals (for now)

- Replacing ElastAlert's runtime or scheduler.
- Auto-deploying changes to production. A human always approves, and deployment stays the user's own process (git, Helm, etc.).
- Writing to Elasticsearch data indices. The agent is read-only on data.

## 3. Users and example requests

| User | Says | Assistant does |
|---|---|---|
| Service owner (non-technical) | "Tell me when card payments start failing a lot" | Finds the indices that mention card payments, asks what "a lot" means (suggesting a threshold from the last 7 days), asks where to send it, writes the rule, and shows a backtest: "would have fired 2 times last week" |
| On-call engineer | "Why didn't the pricing alert fire at 14:00?" | Reads the rule, its `elastalert_status_*` history and the data around 14:00. Finds that `service.name` was renamed to `svc_name` at 13:50, and proposes a fix with a before/after backtest |
| Monitoring team | "Are any of our rules broken or duplicated?" | Reviews all rules: zero-match rules, overlapping filters, rules with no dedup, fields that no longer exist |
| Anyone | "What does this rule do?" | Explains the YAML in plain English |
| Monitoring team | "If payments as a whole is down, raise one ticket, not one per sub-service" | Composes the multi-source rule + ticket reconciler building blocks (§6) and tests it on a timeline scenario |

## 4. Architecture

```
┌─────────────── Tkinter GUI ───────────────────────────────────────────────┐
│ Conversation + question forms + tool-call trace │ YAML/diff │ Tests │      │
│                                                 │ Backtest  │ Modules │    │
└───────────────┬───────────────────────────────────────────────────────────┘
                │ user turns / approvals
        ┌───────▼────────┐   tools (JSON-schema)   ┌──────────────────────────┐
        │  Agent loop     │ ───────────────────────►│ read-only ES tools       │──► Elasticsearch
        │  (max steps,    │                         │ ElastAlert state tools   │    (API key: read)
        │   budgets)      │◄─────────────────────── │ validate / simulate /    │
        └───────┬────────┘   small, summarised      │ backtest (engine reuse)  │
                │            results                │ write tools (APPROVAL)   │──► rule files,
        ┌───────▼────────┐                          └──────────────────────────┘    custom_modules/
        │ LLM backend     │  Ollama (default, local) │ OpenAI-compatible │ Claude (optional)
        └────────────────┘
```

### 4.1 Tools the agent can call

| Group | Tools | Notes |
|---|---|---|
| Explore data | `list_indices`, `get_mapping`, `sample_docs`, `field_stats` (top terms, cardinality, % missing, min/max), `date_histogram`, `run_query` (DSL or ES|QL) | Size-capped; results are summarised before they go back to the model |
| ElastAlert state | `list_rules`, `read_rule`, `read_elastalert_state` (status / silence / error / past for a rule and time range) | Reads the writeback indices described in the [repo guide](../reference_guides/elastalert2-repo-guide.md#writeback-indices-elastalerts-memory) |
| Verify | `validate_rule` (ElastAlert's own loader: schema, required options, alerter init), `simulate_rule` (scenarios through the real rule engine, with filters applied locally because `test_rule --data` ignores them), `backtest_rule` (`elastalert-test-rule` over the last N days), `compare_backtests` | Every rule the agent proposes is validated and tested before the user sees it |
| Change (**approval required**) | `propose_rule_change` (shown as a diff), `write_custom_module` (Python + pytest tests), `run_module_tests` | Nothing is written without the user clicking Approve |

A **completeness guard** in plain code, not the LLM, checks every proposed rule for: a missing index, missing destination settings (webhook, project, SMTP), placeholders, unmapped fields and no dedup choice. It turns any gap into a question for the user, even if the model says it's finished. This matters most with small local models.

### 4.2 Modes

1. **Create:** describe → explore → clarify → rule + plain-English summary + scenarios (PASS/FAIL) + edge cases + backtest.
2. **Debug:** pick a rule + symptom → investigate (state, data, reruns) → root cause in plain words + fix + before/after backtest.
3. **Review:** audit all rules for gaps, overlaps and drift.
4. **Explain:** YAML → plain English.

### 4.3 Checks the debug agent knows about

This is a checklist the agent works through, and each item is reproducible with a scenario in [mock-data-and-scenarios.md](../setup/mock-data-and-scenarios.md):

- Field renamed or missing since the rule was written (`field-drift`).
- `term` on an analysed `text` field (the text-vs-keyword trap).
- Timestamp in the wrong timezone or format, or a different time field (`app-c` uses `event_time` in epoch ms).
- Late-arriving data outside `buffer_time`, or `query_delay` needed (`late-data`).
- Suppressed by `realert` / silence (visible in `elastalert_status_silence`).
- Waiting in an aggregation window (`elastalert_status_past`).
- Rule erroring (`elastalert_status_error`).
- An index pattern that matches no indices, or matches too many.
- A threshold that is unrealistic compared with historical data (from `date_histogram` / backtest).

## 5. Custom wrapper modules

When YAML can't express the logic, the agent writes a small **ElastAlert extension**: an enhancement, a rule type or an alerter. These follow the upstream recipes and go in a `custom_modules/` package next to the user's rules.

The workflow:
1. The agent explains *why* YAML isn't enough, and proposes the module and its tests.
2. The code is **statically checked**. Imports are limited to the standard library, `elastalert.*`, `requests` and `dateutil`, and there is no `subprocess`, `socket`, `eval`/`exec` or file writes outside allowed paths.
3. The tests run in a subprocess with a timeout, against synthetic data only.
4. The user sees the diff and test results, and chooses **Approve** or **Reject**.
5. Approved modules are saved. Deploying them stays the user's own process.

## 6. Building blocks shipped with the add-on

These let the agent compose instead of generating code every time:

- **Multi-source rule** (`type: elastalert_llm.rules.MultiSourceRule`). It runs several source queries every cycle (inside `garbage_collect`, which ElastAlert calls on every run), normalises each source's fields, aggregates, and evaluates a condition across sources.
  - Normalisation options: `from`, `regex`, `map`, `lookup`, `coalesce`, and ES|QL `GROK`/`DISSECT`/`LOOKUP JOIN` when the cluster supports them.
  - The condition uses a safe expression language with no `eval`.
- **Incident reconciler** (`alert: elastalert_llm.alerters.IncidentReconciler`).
  - Instead of firing one alert per match, it compares the *desired* set of open incidents with what's already open. It then opens, comments on, links or resolves tickets in Jira, ServiceNow or a webhook, which prevents duplicates.
  - One configuration of this is the **category → sub-category roll-up**. It opens a parent ticket and links the sub-category tickets under it as suppressed. When the category recovers but a sub-category is still failing, it resolves the parent and un-suppresses that child.
  - State is kept in an index (`elastalert_llm_incidents`), so it's visible in Kibana.

## 7. LLM backends and context budget

- **Ollama (default)**, local: tool calling + JSON-schema `format`. Recommended models and RAM budget: [local-llm-models.md](../reference_guides/local-llm-models.md).
- **OpenAI-compatible** servers (llama.cpp `llama-server`, LM Studio).
- **Claude (optional)**, for users who prefer a hosted model. The UI must say clearly that log samples leave the machine.

CPU inference makes prefill expensive, so the budget is:
- A system prompt of about 6K tokens or less: a cheat-sheet generated from `schema.yaml` and the rule and alerter registries.
- Relevant doc sections added only when a rule type is chosen.
- Tool results summarised to a few hundred tokens each.
- A stable prompt prefix, so the backend can reuse its KV cache.

## 8. Repository (separate from the fork)

```
elastalert2-llm/
  pyproject.toml              name elastalert2-llm, import elastalert_llm, deps: elastalert2>=2.31,<3, pydantic>=2; extra [claude]
  src/elastalert_llm/
    agent/                    loop, tools, completeness guard, prompts/reference builder
    llm/                      ollama, openai_compat, anthropic backends
    verify/                   validator, filter_eval, simulator, backtest
    rules/                    MultiSourceRule + normalise/aggregate/expr
    alerters/                 IncidentReconciler + ticket adapters (jira, servicenow, webhook, memory)
    gui/                      Tkinter app
    devtools/                 seeder + scenario packs (evolved from _claude_docs/setup/es-local/seed.py)
  dev/                        docker-compose (ES/Kibana 9.5.3), sample config
  tests/                      unit tests, no network
  README, LICENSE (Apache-2.0), NOTICE, CHANGELOG, CONTRIBUTING, CODE_OF_CONDUCT, SECURITY
  .github/workflows/          ci.yml (flake8 + pytest 3.12–3.14), publish.yml (PyPI trusted publishing on tag)
```

## 9. Milestones

1. Repo skeleton, CI, dev stack, seeder with scenario packs.
2. Verify layer: validator, simulator (with filter evaluation), backtest wrapper; read-only ES tools.
3. Agent loop, backends, completeness guard; Create + Explain in the GUI.
4. Debug mode (state-index tools, reruns, before/after backtests).
5. Building blocks: multi-source rule, incident reconciler + adapters.
6. Custom module writing with approval + tests.
7. Review mode, docs site, first release `0.1.0`.

## 10. Open questions

- Which Elasticsearch version runs at work? It decides whether ES|QL `LOOKUP JOIN` can be relied on.
- Which Jira link type and workflow transitions are used for "resolved" and "duplicate/suppressed"?
- Where do rules live in production (git repo, Helm values, ConfigMap)? This shapes how an approved change is handed off.
- Company policy on publishing: check before the first public push.
