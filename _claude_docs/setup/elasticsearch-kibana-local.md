# Elasticsearch + Kibana locally, with ElastAlert 2 pointed at it

The goal is a single-node **Elasticsearch 9.5.3 + Kibana 9.5.3** on `localhost`, with security on (username and password) but no TLS, since it's local only. ElastAlert 2 then runs rules against it.

## Which version?

| Situation | Use |
|---|---|
| You know your work cluster's version | **The same major.minor** (e.g. 8.17.x or 9.2.x). Behaviour, mappings and ES|QL features differ between versions |
| You don't know yet (our case) | **9.5.3**, the latest in Sept 2026. It has every feature, including ES|QL `LOOKUP JOIN` (GA since 8.19/9.1) |
| Work runs OpenSearch | OpenSearch 2.x/3.x + OpenSearch Dashboards instead. There is no ES|QL, so DSL queries only |

Kibana **must** be the same version as Elasticsearch. To find your work version, run `GET /` in Kibana Dev Tools there and look at `version.number`.

ElastAlert 2 talks to ES 7, 8 and 9 using the old elasticsearch-py 7.10.1 client, wrapped in a version-aware class ([elastalert/__init__.py](../../elastalert/__init__.py)). Its writeback mappings for 8 are reused for 9.

---

## 1. Give Docker (WSL2) a memory budget first

Docker Desktop runs inside WSL2, and WSL2 takes **up to 50% of your RAM (16GB)** by default. Cap it so VS Code, the browser and a local LLM still fit.

Create `C:\Users\Sanoj\.wslconfig`:

```ini
[wsl2]
# ES (2GB limit) + Kibana (1.5GB) + headroom
memory=6GB
processors=4
swap=4GB
```

Then run `wsl --shutdown` in PowerShell and restart Docker Desktop.

Budget on a 32GB machine: about 16GB for VS Code and the browser, about 4GB for the ES stack, which leaves about 8–10GB for a local model. That's why [local-llm-models.md](../reference_guides/local-llm-models.md) recommends **Qwen3.5-9B while the stack runs**.

---

## 2. Start the stack

A ready-made compose file is in [es-local/](es-local/). **Copy it outside the repo**, because your `.env` will contain passwords:

```bash
cp -r ~/Projects/elastalert3/_claude_docs/setup/es-local ~/es-local
cd ~/es-local
cp .env.example .env
# edit .env: set ELASTIC_PASSWORD, KIBANA_PASSWORD, and KIBANA_ENCRYPTION_KEY
python -c "import secrets; print(secrets.token_hex(16))"   # a good encryption key
docker compose up -d
docker compose ps           # wait until elasticsearch is "healthy" and setup has exited (0)
```

What the compose file does:

| Service | Purpose |
|---|---|
| `elasticsearch` | Single node, `xpack.security.enabled=true`, HTTP without TLS, 1GB heap (`ES_HEAP`), 2GB container limit, data in the `esdata` volume, bound to 127.0.0.1 only |
| `setup` | Waits for ES to be healthy, then sets the `kibana_system` user's password (Kibana is not allowed to use the `elastic` superuser) |
| `kibana` | Connects as `kibana_system`, UI on http://localhost:5601 |

Check it:

```bash
curl -u elastic:$ELASTIC_PASSWORD http://localhost:9200            # shows "number" : "9.5.3"
curl -u elastic:$ELASTIC_PASSWORD "http://localhost:9200/_cluster/health?pretty"   # "yellow" is normal for single-node
```

(In Git Bash, `source .env` first so `$ELASTIC_PASSWORD` is set, or type the password.)

Open **http://localhost:5601** and log in as `elastic` with your `ELASTIC_PASSWORD`. Kibana takes 1–2 minutes to become ready the first time.

Daily use:

```bash
docker compose stop      # frees the RAM, keeps the data
docker compose start
docker compose down -v   # deletes everything, including the data volume
docker compose logs -f elasticsearch
```

### Alternative: Elastic's `start-local` script

Elastic ships a one-liner, `curl -fsSL https://elastic.co/start-local | sh` (with `-s -- -v 9.5.3` to pin a version), that creates a similar setup plus a one-month trial licence. On Windows it must run **inside WSL**. Our compose file is preferred here because it caps memory explicitly and is easier to read and learn from.

---

## 3. Kibana tour (what you'll use)

| Where | Use it for |
|---|---|
| **Dev Tools → Console** (`/app/dev_tools#/console`) | Run any ES API request: create indices, bulk-load data, test queries and ES|QL |
| **Discover** | Browse documents. Create a **data view** (e.g. `app-a-logs-*`, time field `@timestamp`) first |
| **Stack Management → Index Management** | See indices, mappings and templates |
| **Discover → ES|QL mode** | Try `FROM app-a-logs-* \| STATS count(*) BY service.name` |

---

## 4. Point ElastAlert 2 at it

In the repo root create `config.yaml`. It's gitignored, so your password stays local:

```yaml
rules_folder: my_rules          # also gitignored
run_every:
  minutes: 1
buffer_time:
  minutes: 15
es_host: localhost
es_port: 9200
use_ssl: false
es_username: elastic
es_password: <your ELASTIC_PASSWORD>
writeback_index: elastalert_status
alert_time_limit:
  days: 2
```

Create ElastAlert's writeback indices:

```bash
source .venv/Scripts/activate
elastalert-create-index --config config.yaml
```

This creates `elastalert_status`, `elastalert_status_status`, `_silence`, `_error` and `_past` (see the table in [elastalert2-repo-guide.md §4](../reference_guides/elastalert2-repo-guide.md#writeback-indices-elastalerts-memory)).

---

## 5. A first rule, end to end

**a) Put some data in.** In Kibana Dev Tools:

```
POST app-a-logs-2026.09/_bulk?refresh=true
{"index":{}}
{"@timestamp":"2026-09-27T10:15:00Z","level":"ERROR","service":{"name":"card-auth"},"message":"payment failed code=502"}
```

Replace the timestamp with the current time **in UTC** (you are UTC+05:30, so subtract 5h30m from your clock). Otherwise the rule's time window won't contain the data. [mock-data-and-scenarios.md](mock-data-and-scenarios.md) has a small script that generates "now"-relative data for you.

**b) Write the rule** in `my_rules/card_auth_errors.yaml`:

```yaml
name: card-auth errors
type: frequency
index: app-a-logs-*
num_events: 3
timeframe:
  minutes: 5
filter:
- term:
    level: ERROR
- term:
    service.name: card-auth
alert:
- debug            # prints to the console instead of sending
```

**c) Dry-run it** without sending anything:

```bash
elastalert-test-rule my_rules/card_auth_errors.yaml --config config.yaml --days 1
elastalert-test-rule my_rules/card_auth_errors.yaml --config config.yaml --days 1 --formatted-output   # JSON output
```

The first command shows the hit count, the fields available in the first hit, and whether it would have alerted.

**d) Run it for real:**

```bash
elastalert --config config.yaml --verbose --rule my_rules/card_auth_errors.yaml
```

Pass the **path**, not just the file name. With the default `scan_subdirectories` setting, a bare name that isn't a path to an existing file runs *all* rules in `rules_folder` ([loaders.py:599-627](../../elastalert/loaders.py#L599)).

Add 3+ ERROR docs within 5 minutes and watch it log `Alert for card-auth errors ...`. Then look in Kibana at the `elastalert_status` index (the alert record) and `elastalert_status_status` (per-run stats).

> Mapping note: with dynamic mapping, `level` and `service.name` become `text` with a `.keyword` sub-field. A `term` query on `level` matches the **analysed** text (lower-cased tokens), so `term: {level: ERROR}` can silently match nothing. Use `level.keyword`, or create explicit mappings with index templates as shown in [mock-data-and-scenarios.md](mock-data-and-scenarios.md). This is exactly the kind of logic gap the elastalert2-llm debug agent is meant to catch.

---

## 6. Troubleshooting

| Symptom | Fix |
|---|---|
| ES container exits with `max virtual memory areas vm.max_map_count [65530] is too low` | Single-node mode normally skips this check. If you see it: `wsl -d docker-desktop -u root sysctl -w vm.max_map_count=262144` |
| `setup` fails with 401 | `.env` password mismatch after a previous run. Run `docker compose down -v` to reset the data, then `up -d` |
| Kibana shows "Kibana server is not ready yet" | Wait 1–2 minutes; check `docker compose logs kibana` |
| ElastAlert `ConnectionError` | Is the stack running (`docker compose ps`)? Is `use_ssl: false` set? Is the port 9200? |
| ElastAlert `AuthenticationException` | Check `es_username`/`es_password` in `config.yaml` |
| PC becomes slow | Lower `ES_HEAP` to `512m`, stop Kibana when not needed (`docker compose stop kibana`), and use a smaller local model |

---

## 7. 8.x or OpenSearch instead

- **8.x:** set `STACK_VERSION=8.19.x` (or whatever matches work) in `.env`; the compose file works unchanged. `LOOKUP JOIN` needs 8.19 or later.
- **OpenSearch:** use the `opensearchproject/opensearch` and `opensearchproject/opensearch-dashboards` images (different env vars; see the OpenSearch docker docs). ElastAlert 2 detects OpenSearch automatically, but there's no ES|QL or EQL.

Next: [mock-data-and-scenarios.md](mock-data-and-scenarios.md).
