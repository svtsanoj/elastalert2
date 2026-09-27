"""Seed synthetic, "now"-relative test data into a local Elasticsearch.

Usage (from the repo venv, stack running):
    python seed.py --list
    python seed.py --scenario messy-multi-source --password <ELASTIC_PASSWORD>
    python seed.py --scenario category-rollup --password ... --live      # stream future events in real time
    python seed.py --scenario late-data --dry-run                         # print the _bulk body, send nothing
    python seed.py --setup-only --password ...                            # just create templates + lookup index
    python seed.py --scenario simple-frequency --export-json sample.json  # offline data for elastalert-test-rule --data

Times in scenarios are minute offsets from "now" (negative = past, positive = future).
With --live, future events are sent when their time arrives, so a running elastalert sees them arrive
like real traffic. Without --live, future events are skipped.
All data is synthetic. Never put real company logs in here.
"""
import argparse
import datetime
import json
import sys
import time

import requests

# ---------------------------------------------------------------------------
# Index templates: explicit mappings so `term` queries behave predictably.
# app-b is deliberately left without a template to show the text-vs-keyword trap.
# ---------------------------------------------------------------------------
TEMPLATES = {
    "app-a-logs": {  # structured JSON logs (the "nice" source)
        "index_patterns": ["app-a-logs-*"],
        "template": {"mappings": {"properties": {
            "@timestamp": {"type": "date"},
            "level": {"type": "keyword"},
            "service": {"properties": {"name": {"type": "keyword"}}},
            "http": {"properties": {"status": {"type": "integer"}}},
            "latency_ms": {"type": "integer"},
            "message": {"type": "text"},
        }}},
    },
    "app-c-logs": {  # different team, different conventions: epoch-ms time field, string status, other names
        "index_patterns": ["app-c-logs-*"],
        "template": {"mappings": {"properties": {
            "event_time": {"type": "date", "format": "epoch_millis"},
            "svc": {"type": "keyword"},
            "sev": {"type": "keyword"},
            "status_code": {"type": "keyword"},
            "msg": {"type": "text"},
        }}},
    },
    "category-status": {  # category-level health, published by another system
        "index_patterns": ["category-status-*"],
        "template": {"mappings": {"properties": {
            "@timestamp": {"type": "date"},
            "cat_name": {"type": "keyword"},
            "is_down": {"type": "integer"},
            "reason": {"type": "text"},
        }}},
    },
    "heartbeat": {
        "index_patterns": ["heartbeat-*"],
        "template": {"mappings": {"properties": {
            "@timestamp": {"type": "date"},
            "host": {"type": "keyword"},
        }}},
    },
}

# Sub-category -> category mapping, stored in a lookup-mode index (usable by ES|QL LOOKUP JOIN on 8.19+/9.1+).
CATEGORY_MAP = [
    {"subcategory": "card-auth", "category": "payments"},
    {"subcategory": "wallet", "category": "payments"},
    {"subcategory": "upi", "category": "payments"},
    {"subcategory": "search", "category": "catalog"},
    {"subcategory": "pricing", "category": "catalog"},
]


def a_err(svc, status=502, msg="upstream failure"):
    return {"level": "ERROR", "service": {"name": svc}, "http": {"status": status}, "message": "%s svc=%s" % (msg, svc)}


def a_ok(svc):
    return {"level": "INFO", "service": {"name": svc}, "http": {"status": 200}, "latency_ms": 40, "message": "ok"}


def b_err(svc):  # plain-text only: the sub-category is buried in the message
    return {"message": "2026 ERROR PaymentGateway - payment failed svc=%s code=502 retry=3" % svc}


def c_err(svc):
    return {"svc": svc, "sev": "E", "status_code": "502", "msg": "gateway timeout"}


# A group = `count` copies of `doc`, starting at `start` (minutes from now), every `every_s` seconds.
# time_field / time_format let a source use odd timestamp conventions.
def group(index, doc, count, start, every_s=10, time_field="@timestamp", time_format="iso"):
    return {"index": index, "doc": doc, "count": count, "start": start, "every_s": every_s,
            "time_field": time_field, "time_format": time_format}


SCENARIOS = {
    "simple-frequency": {
        "about": "card-auth throws 12 errors in 2 minutes (a frequency rule with num_events: 10 / 5m should fire once).",
        "groups": [
            group("app-a-logs-%Y.%m", a_ok("card-auth"), 30, start=-20, every_s=30),
            group("app-a-logs-%Y.%m", a_err("card-auth"), 12, start=-4, every_s=10),
        ],
    },
    "flatline": {
        "about": "heartbeat every 30s for 20 min, then silence for the last 8 min (a flatline rule should fire).",
        "groups": [group("heartbeat-%Y.%m", {"host": "pay-01"}, 24, start=-20, every_s=30)],
    },
    "messy-multi-source": {
        "about": "The same card-auth outage seen in 3 differently-shaped sources: structured JSON (app-a), "
                 "plain text (app-b, dynamic mapping), and epoch-ms with other field names (app-c).",
        "groups": [
            group("app-a-logs-%Y.%m", a_err("card-auth"), 8, start=-5, every_s=20),
            group("app-b-logs-%Y.%m", b_err("card-auth"), 6, start=-5, every_s=30),
            group("app-c-logs-%Y.%m", c_err("card-auth"), 5, start=-5, every_s=40,
                  time_field="event_time", time_format="epoch_ms"),
        ],
    },
    "category-rollup": {
        "about": "t-15..: card-auth and wallet fail (sub-category level). t-8: category-status says payments is down. "
                 "Expect ONE category-level incident with the two sub-categories linked under it, not three separate alerts.",
        "groups": [
            group("app-a-logs-%Y.%m", a_err("card-auth"), 40, start=-15, every_s=20),
            group("app-a-logs-%Y.%m", a_err("wallet"), 30, start=-12, every_s=20),
            group("app-a-logs-%Y.%m", a_ok("upi"), 30, start=-15, every_s=30),
            group("category-status-%Y.%m", {"cat_name": "payments", "is_down": 1, "reason": "PSP outage"},
                  8, start=-8, every_s=60),
        ],
    },
    "partial-recovery": {
        "about": "Payments category was down and recovers at t-5, but wallet keeps failing. "
                 "Expect: category incident resolved, wallet incident re-activated on its own.",
        "groups": [
            group("category-status-%Y.%m", {"cat_name": "payments", "is_down": 1}, 10, start=-15, every_s=60),
            group("category-status-%Y.%m", {"cat_name": "payments", "is_down": 0}, 5, start=-5, every_s=60),
            group("app-a-logs-%Y.%m", a_err("card-auth"), 20, start=-15, every_s=30),   # stops at ~t-5
            group("app-a-logs-%Y.%m", a_err("wallet"), 45, start=-15, every_s=20),      # continues to now
        ],
    },
    "late-data": {
        "about": "Errors whose @timestamp is 25 min old (a slow shipper). With buffer_time: 15m the rule never "
                 "sees them; debugging should point at buffer_time / query_delay.",
        "groups": [group("app-a-logs-%Y.%m", a_err("search", 500), 15, start=-26, every_s=10)],
    },
    "field-drift": {
        "about": "At t-10 the app renamed service.name -> svc_name. A rule filtering on service.name silently stops "
                 "matching. A good 'why did my alert stop firing?' debugging case.",
        "groups": [
            group("app-a-logs-%Y.%m", a_err("pricing", 500), 20, start=-30, every_s=60),
            group("app-a-logs-%Y.%m", {"level": "ERROR", "svc_name": "pricing", "http": {"status": 500},
                                       "message": "error"}, 30, start=-10, every_s=20),
        ],
    },
    "live-burst": {
        "about": "Streams card-auth errors over the NEXT 5 minutes (use --live and watch elastalert pick them up).",
        "groups": [group("app-a-logs-%Y.%m", a_err("card-auth"), 30, start=0, every_s=10)],
    },
}


def fmt_ts(dt, time_format):
    if time_format == "epoch_ms":
        return int(dt.timestamp() * 1000)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def build_events(scenario, now):
    events = []
    for g in scenario["groups"]:
        for i in range(g["count"]):
            at = now + datetime.timedelta(minutes=g["start"], seconds=i * g["every_s"])
            doc = json.loads(json.dumps(g["doc"]))
            doc[g["time_field"]] = fmt_ts(at, g["time_format"])
            events.append((at, at.strftime(g["index"]), doc))  # index names like app-a-logs-%Y.%m follow the event month
    events.sort(key=lambda e: e[0])
    return events


def bulk_body(events):
    lines = []
    for _, index, doc in events:
        lines.append(json.dumps({"index": {"_index": index}}))
        lines.append(json.dumps(doc))
    return "\n".join(lines) + "\n"


class ES(object):
    def __init__(self, url, user, password):
        self.url = url.rstrip("/")
        self.s = requests.Session()
        self.s.auth = (user, password)
        self.s.headers["Content-Type"] = "application/json"

    def req(self, method, path, body=None, ok=(200, 201)):
        data = body if isinstance(body, str) or body is None else json.dumps(body)
        r = self.s.request(method, self.url + path, data=data, timeout=30)
        if r.status_code not in ok:
            sys.exit("%s %s -> %s %s" % (method, path, r.status_code, r.text[:500]))
        return r.json() if r.text else {}

    def bulk(self, events):
        if not events:
            return
        res = self.req("POST", "/_bulk?refresh=true", bulk_body(events))
        if res.get("errors"):
            bad = [i for i in res["items"] if i["index"].get("error")][:3]
            sys.exit("bulk errors: %s" % json.dumps(bad, indent=2))


def setup(es):
    for name, tpl in TEMPLATES.items():
        es.req("PUT", "/_index_template/%s" % name, tpl)
        print("template   %s -> %s" % (name, tpl["index_patterns"]))
    mappings = {"properties": {"subcategory": {"type": "keyword"}, "category": {"type": "keyword"}}}
    mode = "lookup"
    if es.s.head(es.url + "/category_map", timeout=30).status_code != 200:
        r = es.s.put(es.url + "/category_map", data=json.dumps(
            {"settings": {"index.mode": "lookup"}, "mappings": mappings}), timeout=30)
        if r.status_code == 400:  # ES older than 8.18 has no lookup index mode
            mode = "standard (this ES version has no lookup mode)"
            es.req("PUT", "/category_map", {"mappings": mappings})
        elif r.status_code not in (200, 201):
            sys.exit("PUT /category_map -> %s %s" % (r.status_code, r.text[:500]))
    # _id = subcategory, so re-running the seeder updates rows instead of duplicating them
    lines = []
    for row in CATEGORY_MAP:
        lines.append(json.dumps({"index": {"_index": "category_map", "_id": row["subcategory"]}}))
        lines.append(json.dumps(row))
    es.req("POST", "/_bulk?refresh=true", "\n".join(lines) + "\n")
    print("lookup     category_map (%d rows, index.mode=%s)" % (len(CATEGORY_MAP), mode))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--scenario", choices=sorted(SCENARIOS))
    p.add_argument("--list", action="store_true", help="list scenarios")
    p.add_argument("--es", default="http://localhost:9200")
    p.add_argument("--user", default="elastic")
    p.add_argument("--password", default="")
    p.add_argument("--live", action="store_true", help="also send future events, in real time")
    p.add_argument("--dry-run", action="store_true", help="print the _bulk body instead of sending")
    p.add_argument("--setup-only", action="store_true", help="only create templates and the lookup index")
    p.add_argument("--export-json", metavar="FILE",
                   help="write past events as a JSON array (for elastalert-test-rule --data) instead of sending")
    a = p.parse_args()

    if a.list or not (a.scenario or a.setup_only):
        for name in sorted(SCENARIOS):
            print("%-20s %s" % (name, SCENARIOS[name]["about"]))
        return

    now = datetime.datetime.now(datetime.timezone.utc)
    events = build_events(SCENARIOS[a.scenario], now) if a.scenario else []
    past = [e for e in events if e[0] <= now]
    future = [e for e in events if e[0] > now]

    if a.export_json:
        with open(a.export_json, "w", encoding="utf-8") as f:
            json.dump([doc for _, _, doc in past], f, indent=2)
        print("wrote      %d events to %s (index names dropped; one rule = one source)" % (len(past), a.export_json))
        return

    if a.dry_run:
        sys.stdout.write(bulk_body(past + (future if a.live else [])))
        print("# %d past events, %d future events%s" % (len(past), len(future), "" if a.live else " (skipped, no --live)"))
        return

    es = ES(a.es, a.user, a.password)
    setup(es)
    if not a.scenario:
        return
    es.bulk(past)
    print("seeded     %s: %d events up to now" % (a.scenario, len(past)))
    if future and not a.live:
        print("skipped    %d future events (use --live to stream them)" % len(future))
    if a.live:
        for at, index, doc in future:
            wait = (at - datetime.datetime.now(datetime.timezone.utc)).total_seconds()
            if wait > 0:
                time.sleep(wait)
            es.bulk([(at, index, doc)])
            print("live       %s -> %s" % (fmt_ts(at, "iso"), index))


if __name__ == "__main__":
    main()
