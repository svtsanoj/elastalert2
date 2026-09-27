# ElastAlert 2: repository guide

A walkthrough of this codebase: what is where, how a rule runs from start to finish, the design patterns it uses, how to extend it, and the conventions a PR must follow. Line references are to the fork as of commit `b6c9f192` (just after release 2.31.0).

---

## 1. What ElastAlert 2 is

A long-running Python service that, on a schedule, **queries Elasticsearch/OpenSearch with each rule's filter**, passes the results to a **rule type** that decides what counts as a "match", and sends each match to one or more **alerters** (Slack, Jira, email, and about 45 others). It remembers what it did in its own **writeback indices** so it can resume after restarts, avoid repeat alerts, and retry failed alerts.

- Supports Elasticsearch 7, 8 and 9, and OpenSearch 1, 2 and 3 ([docs/source/running_elastalert.rst](../../docs/source/running_elastalert.rst#L147)).
- Python 3.13/3.14; 3.12 still works but is deprecated ([setup.py](../../setup.py)).
- About 6,900 lines of Python in `elastalert/` plus about 45 alerter modules.
- Community-maintained (lead maintainer Jason Ertel, `@jertel`), and a continuation of the original Yelp ElastAlert.

---

## 2. Directory map

```
elastalert/                     the package
  elastalert.py                 ElastAlerter: the scheduler, run loop, alerting, writeback (the heart, ~1,900 lines)
  loaders.py                    RulesLoader/FileRulesLoader: read YAML, validate, set defaults, instantiate rule types & alerters
  ruletypes.py                  the 12 built-in rule types (frequency, spike, flatline, any, change, new_term, ...)
  alerts.py                     Alerter base class + BasicMatchString (default alert body text)
  alerters/                     one module per alerter (slack.py, jira.py, servicenow.py, email.py, ...)
  enhancements.py               BaseEnhancement + DropMatchException
  config.py                     load_conf(): global config.yaml, env-var overrides, choose the rules loader
  schema.yaml                   JSON Schema (draft-07) that every rule file is validated against
  util.py                       helpers: time conversion, lookup_es_key, get_module, elasticsearch_client, ...
  __init__.py                   ElasticSearchClient: version-aware wrapper around elasticsearch-py 7.10.1
  create_index.py               `elastalert-create-index`: creates the writeback indices + mappings
  test_rule.py                  `elastalert-test-rule`: MockElastAlerter, dry-runs a rule against ES or a JSON file
  eql.py / esql.py              EQL and ES|QL support (translate the filter, reshape results into hits)
  es_mappings/7, es_mappings/8  writeback index mappings per ES major (8 is also used for 9)
  kibana_discover.py, opensearch_discover.py, *_external_url_formatter.py   "open in Discover" links in alerts
  prometheus_wrapper.py         optional /metrics
  auth.py                       AWS SigV4 / basic auth helpers
  yaml.py                       YAML reading with env-var substitution
tests/                          pytest suite (mirrors the package; tests/alerters/* per alerter)
docs/source/                    Sphinx (reStructuredText) docs published on ReadTheDocs
  ruletypes.rst, alerts.rst     reference for every rule option and alerter
  recipes/                      how-tos: adding_rules, adding_alerts, adding_enhancements, adding_loaders, writing_filters
examples/                       config.yaml.example + example rules
chart/elastalert2/              Helm chart (values.yaml, templates/)
Dockerfile                      official image (python:3.14-slim, runs create-index then elastalert)
.github/workflows/              CI: master_build_test (make test-docker), publish_image, python-publish, upload_chart
Makefile, tests/tox.ini         test entry points
setup.py, requirements*.txt     packaging (setuptools; NOT pyproject.toml)
CHANGELOG.md, CONTRIBUTING.md, SECURITY.md, LICENSE (Apache-2.0)
```

---

## 3. The three console commands

Defined in [setup.py](../../setup.py) `entry_points`:

| Command | Module | What it does |
|---|---|---|
| `elastalert` | `elastalert.elastalert:main` | Runs the service. Useful flags: `--config`, `--verbose`, `--debug` (print alerts instead of sending), `--rule <file>` (run one rule), `--start/--end` (backfill a period), `--silence`, `--es_debug` |
| `elastalert-test-rule` | `elastalert.test_rule:main` | Validates a rule and dry-runs it: `--schema-only`, `--days N`, `--data file.json` (mock data), `--formatted-output` (JSON), `--alert` (really send) |
| `elastalert-create-index` | `elastalert.create_index:main` | Creates the writeback indices. With `--config` it reads host and credentials from config.yaml and doesn't prompt |

---

## 4. How a rule runs, end to end

```
elastalert --config config.yaml
  │
  ├─ config.load_conf()                      config.py:38
  │    global config.yaml, env overrides, required globals (run_every, es_host, es_port,
  │    writeback_index, buffer_time), pick rules loader ("file" → FileRulesLoader)
  │
  ├─ RulesLoader.load() → for each rule file: load_configuration()        loaders.py:172, 245
  │    load_yaml()     read YAML + resolve `import:` chains
  │    load_options()  jsonschema-validate against schema.yaml, convert timedeltas,
  │                    set defaults (realert=1 min, timestamp_field=@timestamp, ...), add query_key etc. to `include`
  │    load_modules()  enhancements → objects; `type:` → RuleType instance; `alert:` → Alerter instances
  │
  ├─ ElastAlerter.start()                                   elastalert.py:1147
  │    APScheduler BackgroundScheduler: one interval job per rule (run_every),
  │    plus jobs for pending/aggregated alerts and rule-file change detection
  │
  └─ each tick: handle_rule_execution(rule) → run_rule(rule, endtime, starttime)     elastalert.py:1251, 851
       1. set_starttime(): resume from elastalert_status (last run), bounded by buffer_time / old_query_limit
       2. split the window into segments; for each segment:
            run_query() → get_hits / get_hits_count / get_hits_terms / get_hits_aggregation
                        → rule['type'].add_data / add_count_data / add_terms_data / add_aggregation_data
            rule['type'].garbage_collect(segment_end)       ← called every run, even with no data
       3. drain rule['type'].matches:                        elastalert.py:917
            realert/silence check (per query_key)  → skip if silenced
            aggregation?  → store for later : alert([match])
       4. alert() → send_alert():                            elastalert.py:1362
            top_count_keys, Kibana/OpenSearch discover URL, enhancements (DropMatchException drops)
            --debug → DebugAlerter prints it; otherwise each alerter.alert(matches) in order
            writeback('elastalert', alert_body)  ← record of every alert, sent or failed (for retry)
       5. writeback('elastalert_status', {...hits, matches, time_taken, endtime})   elastalert.py:976
```

### Writeback indices (ElastAlert's memory)

All index names derive from `writeback_index` ([elastalert/__init__.py:68](../../elastalert/__init__.py#L68)). With the common setting `writeback_index: elastalert_status` you get:

| Doc type | Index | Contents | Why it matters for debugging |
|---|---|---|---|
| `elastalert` | `elastalert_status` | one doc per alert: `alert_sent`, `match_body`, `alert_exception` | "Did it fire? Did sending fail?" |
| `elastalert_status` | `elastalert_status_status` | one doc per rule run: hits, matches, `time_taken`, `endtime` | "Did it run, and how many docs did it see?" |
| `silence` | `elastalert_status_silence` | `until` timestamps per rule / query_key | "Was it suppressed by realert?" |
| `elastalert_error` | `elastalert_status_error` | exceptions with traceback and rule name | "Did it crash?" |
| `past_elastalert` | `elastalert_status_past` | aggregated alerts waiting to be sent | "Is it sitting in an aggregation window?" |

These five indices are exactly what the elastalert2-llm debug agent will read to answer questions like *"why didn't my alert fire?"*.

---

## 5. Design patterns used in the code

| Pattern | Where | What it means for you |
|---|---|---|
| **Registry (name → class map)** | `RulesLoader.rules_mapping`, `alerts_mapping` ([loaders.py:92-152](../../elastalert/loaders.py#L92)), `loader_mapping` (config.py) | A built-in rule type or alerter becomes available by adding **one line** here |
| **Plugin loading by dotted path** | `util.get_module()` ([util.py:23](../../elastalert/util.py#L23)); used when `type:`, `alert:` or `match_enhancements:` contain a `.` | **Anything pip-installable can extend ElastAlert without forking it.** This is how elastalert2-llm plugs in |
| **Template method / base class hooks** | `RuleType` ([ruletypes.py:13](../../elastalert/ruletypes.py#L13)): override `add_data`, `add_count_data`, `add_terms_data`, `garbage_collect`, `get_match_str`; `Alerter` ([alerts.py:137](../../elastalert/alerts.py#L137)): override `alert`, `get_info` | The engine calls the hooks and you fill them in. Call `self.add_match(event)` to emit a match |
| **Declared requirements** | `required_options = frozenset([...])` on rule types and alerters | The loader refuses to start a rule that is missing them, so errors show up at load time rather than at 3am |
| **Schema validation** | [schema.yaml](../../elastalert/schema.yaml), `oneOf` per rule type, plus a "Custom Rule from Module" branch (line 239) that accepts any `type` containing a dot | New options must be added to the schema or rule files fail validation |
| **Pipeline / chain of responsibility** | `match_enhancements` run in order and may mutate or drop a match; `alert.pipeline` dict passes data between alerters (e.g. Jira ticket URL into the email) | Add behaviour without touching alerters |
| **Adapter around a pinned client** | `ElasticSearchClient` extends elasticsearch-py **7.10.1**, detects the server version and adjusts calls (doc types, mappings) | One client library talks to ES 7–9 and OpenSearch. Don't upgrade the pin casually |
| **State in the data store** | writeback indices (above) | ElastAlert itself is almost stateless between restarts |
| **Test doubles for ES** | `MockElastAlerter` in [test_rule.py](../../elastalert/test_rule.py), fixtures in [tests/conftest.py](../../tests/conftest.py) (`ea` fixture with a mocked ES client) | Unit tests never need a real cluster |

Also worth knowing:
- **Rule state lives in memory** inside the `RuleType` instance (e.g. `EventWindow` for frequency counts), so a restart loses in-flight windows. That's why `buffer_time` and `scan_entire_timeframe` exist.
- **`realert`** (default 1 minute) silences repeat alerts per `query_key` value. **Aggregation** batches matches into one alert per window.
- **`test_rule --data` does not apply `filter`** ([test_rule.py:303](../../elastalert/test_rule.py#L303)). The mock returns every document in the time range, which is a known gap and a good small upstream PR.
- **EQL and ES|QL** are "filters" with special keys (`- eql: ...`, `- esql: ...`) that `eql.py`/`esql.py` translate. ES|QL landed in 2.31.0 and can't be used with aggregation, blacklist/whitelist, percentage_match or `use_count_query` ([writing_filters.rst](../../docs/source/recipes/writing_filters.rst)).

---

## 6. Extending ElastAlert 2 (no fork needed)

All four extension points use dotted paths, so the code can live in any importable package. That can be a folder next to your config (the docs use `elastalert_modules/`) or a pip-installed package.

| Extension | Base class | Config key | Recipe |
|---|---|---|---|
| Rule type | `elastalert.ruletypes.RuleType` | `type: pkg.module.MyRule` | [adding_rules.rst](../../docs/source/recipes/adding_rules.rst) |
| Alerter | `elastalert.alerts.Alerter` | `alert: [pkg.module.MyAlerter]` | [adding_alerts.rst](../../docs/source/recipes/adding_alerts.rst) |
| Enhancement | `elastalert.enhancements.BaseEnhancement` | `match_enhancements: [pkg.module.MyEnh]` | [adding_enhancements.rst](../../docs/source/recipes/adding_enhancements.rst) |
| Rules loader | `elastalert.loaders.RulesLoader` | `rules_loader: pkg.module.MyLoader` (config.yaml) | [adding_loaders.rst](../../docs/source/recipes/adding_loaders.rst) |

A minimal custom rule type:

```python
from elastalert.ruletypes import RuleType

class ErrorRatioRule(RuleType):
    required_options = frozenset(['max_ratio'])

    def add_data(self, data):
        errors = sum(1 for d in data if d.get('level') == 'ERROR')
        if data and errors / len(data) > self.rules['max_ratio']:
            self.add_match(data[-1])          # emit one match

    def get_match_str(self, match):
        return 'Error ratio exceeded %.0f%%' % (self.rules['max_ratio'] * 100)
```

```yaml
type: my_modules.rules.ErrorRatioRule
max_ratio: 0.05
```

A useful trick: `garbage_collect(timestamp)` is called **every run**, even when the main query returns nothing ([elastalert.py:897-913](../../elastalert/elastalert.py#L897)). A custom rule type can run its own extra queries there (NewTermsRule already queries ES from inside the rule, [ruletypes.py:695](../../elastalert/ruletypes.py#L695)), for example to compare several indices. elastalert2-llm's multi-source rule builds on this.

---

## 7. Conventions a PR must follow

From [CONTRIBUTING.md](../../CONTRIBUTING.md) and the tooling:

- **Tests required** for every new logic path. Alerter tests live in `tests/alerters/<name>_test.py` and mock HTTP with `unittest.mock.patch('requests.post')`. Look at `slack_test.py` or `servicenow_test.py` before writing one.
- **Test file naming** is `*_test.py` (pre-commit's `name-tests-test` hook enforces it).
- **flake8**, max line length 140 ([setup.cfg](../../setup.cfg)). CI runs `flake8 --config ../setup.cfg .` from `tests/`.
- **Don't reformat existing code.** Keep diffs minimal.
- **Every new option is documented**: `docs/source/ruletypes.rst` (rule options) or `docs/source/alerts.rst` (alerter options), in RST.
- **schema.yaml** is updated for new options.
- **CHANGELOG.md**: add a line under the top `2.TBD.TBD` section, e.g. `- [Jira] Add foo option - [#1234](https://github.com/jertel/elastalert2/pull/1234) - @svtsanoj`.
- **Helm chart / examples**: if the feature adds global settings, update `chart/elastalert2/values.yaml` + chart README, and `examples/config.yaml.example`.
- Imports are absolute (`flake8-absolute-import` is in requirements-dev).

### Checklist: adding a new alerter

1. `elastalert/alerters/myalerter.py`: subclass `Alerter`, set `required_options`, implement `alert(matches)` and `get_info()`. Raise `EAException` on failure.
2. Register it in `alerts_mapping` in [loaders.py](../../elastalert/loaders.py) (and import it at the top).
3. Add its options to [schema.yaml](../../elastalert/schema.yaml).
4. Document it in [docs/source/alerts.rst](../../docs/source/alerts.rst) (and the alerter list at the top of that page).
5. Add tests in `tests/alerters/myalerter_test.py`: success, missing required option, HTTP error, `get_info`.
6. Add a CHANGELOG line and run `make test-docker` (or pytest + flake8 locally).

### Checklist: adding an option to an existing rule type

Code in `ruletypes.py` → `schema.yaml` → `docs/source/ruletypes.rst` → tests in `tests/rules_test.py` → CHANGELOG.

---

## 8. Tests, CI and docs builds

| What | Command | Notes |
|---|---|---|
| Full suite, as CI does it | `make test-docker` | Builds `tests/Dockerfile-test`, runs `tox` (pytest with coverage + flake8). Needs Docker and `make` |
| Direct pytest | `pytest tests -n 4` | Uses pytest-xdist; `tests/pytest.ini` defines the `elasticsearch` marker |
| Integration tests vs real ES | `pytest tests --runelasticsearch` | Only tests marked `@pytest.mark.elasticsearch` |
| Lint | `flake8 --config setup.cfg elastalert tests` | |
| Docs | `tox -c tests/tox.ini -e docs` | Sphinx with `-W`, so warnings fail the build |

CI ([master_build_test.yml](../../.github/workflows/master_build_test.yml)) runs `make test-docker` on every push and PR to `master`. Windows specifics are in [../setup/local-dev-setup-windows.md](../setup/local-dev-setup-windows.md).

---

## 9. Releases (maintainers only)

From [CONTRIBUTING.md](../../CONTRIBUTING.md#releases), for understanding only. Contributors don't do this.

1. Bump the version in `setup.py`, the chart's `Chart.yaml`/`values.yaml`/README, and `docs/source/running_elastalert.rst`, and finalise the CHANGELOG section.
2. Publish a GitHub Release. The tag (e.g. `2.32.0`) triggers:
   - `python-publish.yml`: PyPI via trusted publishing (only runs in `jertel`'s repo)
   - `publish_image.yml`: Docker Hub image `jertel/elastalert2`
   - `upload_chart.yml`: the Helm chart
3. Each release gets a GitHub Discussion.

So a merged PR reaches users only in the next release. Until then people install from git.

---

## 10. Good first contributions (ideas from reading the code)

- `elastalert-test-rule --data` ignores the rule's `filter` ([test_rule.py:303](../../elastalert/test_rule.py#L303)). Applying at least `term`/`terms`/`range`/`query_string` would make offline testing trustworthy.
- `setup.py` classifiers list 3.12–3.14, while the docs say 3.12 support "will be removed". Keeping those consistent is a tidy docs PR.
- `elastalert --rule <name>` only filters by file name when `scan_subdirectories` is on. Otherwise a bare name that isn't an existing file path loads **every** rule ([loaders.py:599-627](../../elastalert/loaders.py#L599)). Either apply the filter in both branches or document it.
- Four tests fail on native Windows (timezone-dependent and path-separator-dependent; see [local-dev-setup-windows.md §4](../setup/local-dev-setup-windows.md#4-run-the-tests)). Making them platform-independent is a good first PR.
- ServiceNow alerter only creates incidents. Optional `parent_incident` / update support would help teams that dedupe tickets.

Open an issue or discussion upstream before starting any of these.
