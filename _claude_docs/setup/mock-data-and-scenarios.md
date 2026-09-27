# Mock data and test scenarios

How to create indices and seed realistic, **messy**, time-relative data into your local Elasticsearch, so you can test rules and, later, the elastalert2-llm debug agent against known situations.

Everything here is **synthetic**. Never copy real company logs, index names or hostnames into this repo.

Prerequisite: the stack from [elasticsearch-kibana-local.md](elasticsearch-kibana-local.md) is running.

---

## 1. Principles

1. **Time-relative data.** ElastAlert only looks at recent windows (`buffer_time`, `timeframe`), so seeded events must have timestamps relative to *now*, in **UTC**. The seeder computes them for you.
2. **Explicit mappings** (index templates) for most sources, so `term` queries behave predictably. One source is left on **dynamic mapping** on purpose, to reproduce the classic text-vs-keyword trap.
3. **Messy on purpose.** Real teams log differently, so the sources below disagree on field names, timestamp field and format, and even whether fields exist at all.
4. **Scenarios with a known expected outcome.** Each one states what *should* happen, so a rule (or the agent) can be judged right or wrong.

---

## 2. The sources (indices)

| Index pattern | Shape | What makes it realistic |
|---|---|---|
| `app-a-logs-YYYY.MM` | Structured JSON: `@timestamp`, `level` (keyword), `service.name`, `http.status`, `latency_ms`, `message` | The "well-behaved" team |
| `app-b-logs-YYYY.MM` | **Only** `@timestamp` + a free-text `message` like `ERROR PaymentGateway - payment failed svc=card-auth code=502` | No structure; the sub-category is buried in text. **No template**: dynamic mapping makes `message` `text` + `.keyword` |
| `app-c-logs-YYYY.MM` | `event_time` (**epoch millis**), `svc`, `sev: "E"`, `status_code: "502"` (a string!), `msg` | Different team conventions: other time field, other names, numbers stored as strings |
| `category-status-YYYY.MM` | `@timestamp`, `cat_name`, `is_down` (0/1), `reason` | Category-level health published by a separate system |
| `heartbeat-YYYY.MM` | `@timestamp`, `host` | For flatline (missing data) tests |
| `category_map` | `subcategory → category` rows, **`index.mode: lookup`** | Reference data for ES|QL `LOOKUP JOIN` (8.19+/9.1+) |

---

## 3. Seeding with the script

[es-local/seed.py](es-local/seed.py) uses only the standard library plus `requests`, which the ElastAlert venv already has. Copy it along with the compose folder (see the ES guide), then:

```bash
source ~/Projects/elastalert3/.venv/Scripts/activate
cd ~/es-local
python seed.py --list                                                   # show scenarios
python seed.py --setup-only --password "$ELASTIC_PASSWORD"              # templates + category_map lookup index
python seed.py --scenario messy-multi-source --password "$ELASTIC_PASSWORD"
python seed.py --scenario live-burst --password "$ELASTIC_PASSWORD" --live   # streams events for the next 5 min
python seed.py --scenario late-data --dry-run | head                   # see the _bulk body, send nothing
python seed.py --scenario simple-frequency --export-json my_rules/sample.json  # offline data for test-rule
```

Every run of a scenario also (re)creates the templates and the lookup index. `category_map` rows use `_id = subcategory`, so re-running doesn't duplicate them. Event indices, on the other hand, keep accumulating, so reset between experiments:

```
DELETE app-a-logs-*,app-b-logs-*,app-c-logs-*,category-status-*,heartbeat-*
```

(Run that in Kibana Dev Tools. On 8.x/9.x wildcard deletes may need `action.destructive_requires_name: false`; otherwise list the concrete index names from `GET _cat/indices/app-*?v`.)

### Scenarios

| Scenario | Situation | Expected outcome |
|---|---|---|
| `simple-frequency` | 30 INFO over 20 min, then 12 card-auth ERRORs in ~2 min | `frequency` with `num_events: 10`, `timeframe: 5m` fires once |
| `flatline` | Heartbeat every 30s, then 8 min of silence | `flatline` with `threshold: 1`, `timeframe: 5m` fires |
| `messy-multi-source` | The same card-auth outage in app-a (JSON), app-b (text) and app-c (epoch ms, other names) | A correct rule counts **all three** sources: 8 + 6 + 5 = 19 errors |
| `category-rollup` | card-auth and wallet fail; then `category-status` says payments is down | **One** category incident with the two sub-categories linked under it, not three separate alerts |
| `partial-recovery` | Payments recovers at t-5 but wallet keeps failing | Category incident resolved; wallet re-activated on its own |
| `late-data` | Errors whose `@timestamp` is ~25 min old | A rule with `buffer_time: 15m` misses them. The fix is `query_delay`/`buffer_time`, or alerting on ingest time |
| `field-drift` | At t-10, `service.name` was renamed to `svc_name` | A rule on `service.name` silently stops matching ("why did my alert stop firing?") |
| `live-burst` | Errors streamed over the next 5 min (`--live`) | Watch a running `elastalert --verbose` pick them up in real time |

Scenarios live in the `SCENARIOS` dict in `seed.py`. Each is a list of `group(index, doc, count, start_minutes, every_s, time_field, time_format)`, so adding one is a few lines.

---

## 4. Seeding by hand (Kibana Dev Tools)

Useful for understanding what the script does, or for a one-off document.

```
PUT _index_template/app-a-logs
{
  "index_patterns": ["app-a-logs-*"],
  "template": { "mappings": { "properties": {
    "@timestamp": {"type": "date"},
    "level":      {"type": "keyword"},
    "service":    {"properties": {"name": {"type": "keyword"}}},
    "http":       {"properties": {"status": {"type": "integer"}}},
    "message":    {"type": "text"}
  }}}
}

PUT category_map
{
  "settings": {"index.mode": "lookup"},
  "mappings": {"properties": {"subcategory": {"type": "keyword"}, "category": {"type": "keyword"}}}
}

POST _bulk?refresh=true
{"index": {"_index": "category_map", "_id": "card-auth"}}
{"subcategory": "card-auth", "category": "payments"}
{"index": {"_index": "app-a-logs-2026.09"}}
{"@timestamp": "2026-09-27T10:15:00Z", "level": "ERROR", "service": {"name": "card-auth"}, "http": {"status": 502}, "message": "upstream failure"}
```

The `_bulk` format is **newline-delimited JSON**: one action line, then one document line, and it must end with a newline. Kibana Dev Tools handles this for you.

---

## 5. Exploring the data with ES|QL (Kibana → Discover → ES|QL, or Dev Tools)

These are the queries a human, or the agent, uses to understand messy sources before writing a rule.

```esql
// Errors per service in the well-behaved source
FROM app-a-logs-* | WHERE level == "ERROR" AND @timestamp > NOW() - 15 minutes
| STATS errors = COUNT(*) BY service.name

// Pull structure out of free text (app-b)
FROM app-b-logs-* | WHERE @timestamp > NOW() - 15 minutes
| GROK message "svc=%{NOTSPACE:svc} code=%{NUMBER:code}"
| STATS errors = COUNT(*) BY svc, code

// Normalise several sources into one shape, then roll up to the category level
FROM app-a-logs-*, app-c-logs-*
| EVAL ts = COALESCE(@timestamp, event_time),
       subcategory = COALESCE(service.name, svc),
       is_error = CASE(level == "ERROR" OR sev == "E", 1, 0)
| WHERE ts > NOW() - 15 minutes AND is_error == 1
| LOOKUP JOIN category_map ON subcategory
| STATS errors = COUNT(*) BY category, subcategory
```

- `COALESCE` picks the first non-null field. Fields missing from one index come back as null, which is how you merge sources that name things differently.
- `LOOKUP JOIN` needs the right-hand index in `index.mode: lookup` and a join field with the **same name** on both sides (`subcategory`). It needs ES 8.19+/9.1+.
- ElastAlert 2 accepts an ES|QL query as a filter (`filter: [ {esql: "FROM ..."} ]`, since 2.31.0), with limitations ([writing_filters.rst](../../docs/source/recipes/writing_filters.rst)). Aggregating queries like the last one are what the elastalert2-llm multi-source rule will run for you.

---

## 6. Rules to try against the scenarios

`my_rules/` is gitignored. Point `config.yaml` at it (see the ES guide).

```yaml
# my_rules/frequency_card_auth.yaml   (scenario: simple-frequency)
name: card-auth error burst
type: frequency
index: app-a-logs-*
num_events: 10
timeframe: {minutes: 5}
filter:
- term: {level: ERROR}
- term: {service.name: card-auth}
alert: [debug]
```

```yaml
# my_rules/flatline_heartbeat.yaml    (scenario: flatline)
name: pay-01 heartbeat missing
type: flatline
index: heartbeat-*
threshold: 1
timeframe: {minutes: 5}
filter:
- term: {host: pay-01}
alert: [debug]
```

```yaml
# my_rules/text_trap.yaml             (scenario: messy-multi-source); this one is WRONG on purpose
name: app-b payment failures
type: any
index: app-b-logs-*
filter:
- term: {message: "payment failed"}   # term on an analysed text field never matches a phrase
alert: [debug]
# Fix: - match_phrase: {message: "payment failed"}
```

Run each one:

```bash
elastalert-test-rule my_rules/frequency_card_auth.yaml --config config.yaml --days 1
elastalert --config config.yaml --verbose --rule my_rules/frequency_card_auth.yaml
```

---

## 7. Offline testing with `--data`, and its trap

`elastalert-test-rule --data file.json` runs a rule against a JSON array of documents with no Elasticsearch involved:

```bash
python ~/es-local/seed.py --scenario simple-frequency --export-json my_rules/sample.json
elastalert-test-rule my_rules/frequency_card_auth.yaml --config config.yaml --data my_rules/sample.json
```

**Trap, verified on 2026-09-27:** `--data` mode **ignores the rule's `filter`** ([test_rule.py:303](../../elastalert/test_rule.py#L303)). With `filter: level: ERROR` and the `simple-frequency` data (30 INFO + 12 ERROR), the test still reported 4 matches, and the match it printed was an **`INFO`** document. Offline results only mean something if your sample file already contains only the documents the filter would keep.

- This is why the elastalert2-llm simulator applies filters itself before handing data to the engine.
- It is also a good small upstream PR (see [elastalert2-repo-guide.md §10](../reference_guides/elastalert2-repo-guide.md#10-good-first-contributions-ideas-from-reading-the-code)).

---

## 8. Kibana data views

To browse the seeded data in Discover, go to **Stack Management → Data Views → Create** and add one per source:
- `app-a-logs-*` (`@timestamp`)
- `app-b-logs-*` (`@timestamp`)
- `app-c-logs-*` (**`event_time`**)
- `category-status-*` (`@timestamp`)
- `elastalert_status*` (`@timestamp`), to see what ElastAlert itself recorded
