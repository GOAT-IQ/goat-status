"""Builds site/index.html, GOAT's public status page, from the Goat Tracker board.

The page is public. It shows each feature's tasks by title, with their board
Status, Size, Priority, Release and Area, and the totals built from them.
Descriptions, people and "Waiting on" reasons never leave the board.
Standard library only, so the workflow needs no install step.

Environment:
  GOAT_BOARD_TOKEN  token that can read the GOAT-IQ project and goat-tracker issues
"""

import datetime as dt
import json
import os
import pathlib
import urllib.request
from collections import Counter, defaultdict

ORG = "GOAT-IQ"
PROJECT_NUMBER = 1
RECENT_DAYS = 14
ROOT = pathlib.Path(__file__).resolve().parent.parent
AREAS = ["Frontend", "Backend", "DevOps", "Docs"]
RELEASES = ["Beta", "General Availability", "Marketplace", "Later"]

QUERY = """
query($org: String!, $num: Int!, $cursor: String) {
  organization(login: $org) {
    projectV2(number: $num) {
      items(first: 100, after: $cursor) {
        pageInfo { hasNextPage endCursor }
        nodes {
          content { ... on Issue { number title state createdAt closedAt issueType { name } parent { number title } } }
          status: fieldValueByName(name: "Status") { ... on ProjectV2ItemFieldSingleSelectValue { name } }
          area: fieldValueByName(name: "Area") { ... on ProjectV2ItemFieldSingleSelectValue { name } }
          release: fieldValueByName(name: "Release") { ... on ProjectV2ItemFieldSingleSelectValue { name } }
          priority: fieldValueByName(name: "Priority") { ... on ProjectV2ItemFieldSingleSelectValue { name } }
          size: fieldValueByName(name: "Size") { ... on ProjectV2ItemFieldSingleSelectValue { name } }
          iteration: fieldValueByName(name: "Iteration") { ... on ProjectV2ItemFieldIterationValue { title startDate duration } }
        }
      }
    }
  }
}
"""


def fetch(token):
    cards, cursor = [], None
    while True:
        body = json.dumps({"query": QUERY, "variables": {"org": ORG, "num": PROJECT_NUMBER, "cursor": cursor}}).encode()
        req = urllib.request.Request("https://api.github.com/graphql", data=body,
                                     headers={"Authorization": f"bearer {token}", "Content-Type": "application/json"})
        with urllib.request.urlopen(req) as resp:
            data = json.load(resp)
        if data.get("errors"):
            raise SystemExit(f"GitHub refused the board query: {data['errors']}")
        page = data["data"]["organization"]["projectV2"]["items"]
        for node in page["nodes"]:
            c = node["content"]
            if not c:
                continue
            cards.append({
                "number": c["number"], "title": c["title"], "open": c["state"] == "OPEN",
                "closed": dt.datetime.fromisoformat(c["closedAt"].replace("Z", "+00:00")) if c["closedAt"] else None,
                "created": c["createdAt"][:10],
                "type": (c["issueType"] or {}).get("name"),
                "parent": (c["parent"] or {}).get("number"),
                "status": (node["status"] or {}).get("name"),
                "area": (node["area"] or {}).get("name"),
                "release": (node["release"] or {}).get("name"),
                "priority": (node["priority"] or {}).get("name"),
                "size": (node["size"] or {}).get("name"),
                "iteration": node["iteration"],
            })
        if not page["pageInfo"]["hasNextPage"]:
            return cards
        cursor = page["pageInfo"]["endCursor"]


STATES = ("done", "review", "progress", "blocked", "ready", "backlog")


def state(card):
    """The page's six states, one per board Status. A closed card is done whatever its Status says."""
    if not card["open"] or card["status"] == "Done":
        return "done"
    return {"In Review": "review", "In Progress": "progress", "Blocked": "blocked", "Ready": "ready"}.get(card["status"], "backlog")


def counts(cards):
    c = Counter(state(x) for x in cards)
    return {k: c.get(k, 0) for k in STATES}


def feature_status(c, total):
    """A feature's own Status card is not kept up on the board, so its state comes from its tasks."""
    if c["done"] == total:
        return "done"
    if c["progress"] or c["review"]:
        return "progress"
    if c["blocked"] and not c["ready"] and not c["done"]:
        return "blocked"
    return "started" if c["done"] else "todo"


def feature_row(feature, tasks):
    c = counts(tasks)
    open_tasks = [t for t in tasks if state(t) != "done"]
    return {
        "name": feature["title"], "total": len(tasks), "counts": c, "status": feature_status(c, len(tasks)),
        # One row per task: the page filters and recounts these by release, and lists them by title.
        "tasks": [[state(t), t["release"] or "", t["size"] or "", t["priority"] or "", t["area"] or "", t["number"], t["title"]]
                  for t in sorted(tasks, key=lambda t: t["number"])],
        "openByArea": [{"name": a, "open": n} for a in AREAS if (n := sum(1 for t in open_tasks if t["area"] == a))],
    }


def release_row(name, tasks):
    """A release's tasks by state, and the size and priority mix of the ones still open."""
    open_tasks = [t for t in tasks if state(t) != "done"]
    mix = lambda key: dict(Counter(t[key] or "none" for t in open_tasks))
    return {"name": name, "total": len(tasks), "open": len(open_tasks), "counts": counts(tasks),
            "sizes": mix("size"), "priorities": mix("priority")}


def summarize(cards, now):
    features = {c["number"]: c for c in cards if c["type"] == "Feature"}
    work = [c for c in cards if c["type"] != "Feature"]
    open_work = [c for c in work if state(c) != "done"]

    by_feature = defaultdict(list)
    for c in work:
        if c["parent"] in features:
            by_feature[c["parent"]].append(c)
    # Board order (the feature's issue number), so a feature keeps its place between refreshes.
    feature_rows = [feature_row(f, by_feature[n]) for n, f in sorted(features.items()) if by_feature[n]]

    week = {"planned": 0}
    today = now.date()
    for c in work:
        it = c["iteration"]
        if it:
            start = dt.date.fromisoformat(it["startDate"])
            if start <= today < start + dt.timedelta(days=it["duration"]):
                planned = [x for x in work if x["iteration"] and x["iteration"]["title"] == it["title"]]
                week = {"title": it["title"], "planned": len(planned), "done": counts(planned)["done"], "counts": counts(planned)}
                break

    recent = [c for c in work if c["closed"] and (now - c["closed"]).days < RECENT_DAYS]
    recent_by = Counter(features[c["parent"]]["title"] if c["parent"] in features else "Other work" for c in recent)

    totals = counts(work)
    totals.update(tasks=len(work), bugs=sum(1 for c in open_work if c["type"] == "Bug"))
    return {
        "updated": now.isoformat(),
        # The board lists the work still ahead; what was built before it existed is not on it.
        # The page says so with this date, so "0 done" is not read as "nothing is built".
        "since": min(c["created"] for c in cards),
        "totals": totals,
        "featureStatus": dict(Counter(f["status"] for f in feature_rows)),
        "features": feature_rows,
        "week": week,
        "areas": [{"name": a, "open": sum(1 for c in open_work if c["area"] == a),
                   "counts": counts([c for c in open_work if c["area"] == a])}
                  for a in AREAS if any(c["area"] == a for c in open_work)],
        "releases": [release_row(r, [c for c in work if (c["release"] or "Not set") == r]) for r in RELEASES + ["Not set"]
                     if any((c["release"] or "Not set") == r for c in work)],
        "recent": {"total": len(recent), "byFeature": [{"name": k, "count": v} for k, v in recent_by.most_common()]},
    }


def main():
    token = os.environ.get("GOAT_BOARD_TOKEN")
    if not token:
        raise SystemExit("GOAT_BOARD_TOKEN is not set")
    status = summarize(fetch(token), dt.datetime.now(dt.timezone.utc))
    template = (ROOT / "scripts" / "template.html").read_text()
    out = ROOT / "site" / "index.html"
    out.parent.mkdir(exist_ok=True)
    out.write_text(template.replace("/*__STATUS__*/", json.dumps(status, ensure_ascii=False).replace("</", "<\\/")))
    (ROOT / "site" / "status.json").write_text(json.dumps(status, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
