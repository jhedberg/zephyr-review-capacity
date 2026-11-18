#!/usr/bin/env python3

# SPDX-FileCopyrightText: Copyright (c) 2026 Silicon Laboratories Inc.
# SPDX-License-Identifier: Apache-2.0

"""
Keep a local cache of the review history of a repository's pull requests.

Each run first catches up with the pull requests updated since the last run,
then continues the walk back in time from where the previous run stopped,
until the history limit or the API budget is reached. A run can therefore be
short and repeated: the cache fills over several runs and stays current.

Every pull request is fetched with a query of its own. GitHub answers queries
that ask for the timelines of many pull requests at once with empty lists for
part of them, without an error.

Needs the gh CLI with a token in its environment (GH_TOKEN in a workflow).
"""

from __future__ import annotations

import argparse
import datetime as dt
import gzip
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

LIST_QUERY = """
query($owner: String!, $name: String!, $cursor: String) {
  rateLimit { remaining resetAt }
  repository(owner: $owner, name: $name) {
    pullRequests(first: 100, after: $cursor,
                 orderBy: {field: UPDATED_AT, direction: DESC}) {
      pageInfo { hasNextPage endCursor }
      nodes { number updatedAt }
    }
  }
}
"""

PR_QUERY = """
query($owner: String!, $name: String!, $number: Int!) {
  rateLimit { remaining resetAt }
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      number title isDraft createdAt updatedAt closedAt mergedAt
      author { login }
      assignees(first: 5) { nodes { login } }
      labels(first: 40) { nodes { name } }
      reviews(first: 100) {
        totalCount
        nodes { id author { login } authorAssociation state submittedAt }
      }
      reviewsTail: reviews(last: 100) {
        nodes { id author { login } authorAssociation state submittedAt }
      }
      comments(first: 100) { nodes { author { login } createdAt } }
      timelineItems(first: 200, itemTypes: [REVIEW_REQUESTED_EVENT,
                                            REVIEW_REQUEST_REMOVED_EVENT,
                                            READY_FOR_REVIEW_EVENT,
                                            CONVERT_TO_DRAFT_EVENT]) {
        nodes {
          __typename
          ... on ReviewRequestedEvent {
            createdAt
            requestedReviewer { ... on User { login } }
          }
          ... on ReviewRequestRemovedEvent {
            createdAt
            requestedReviewer { ... on User { login } }
          }
          ... on ReadyForReviewEvent { createdAt }
          ... on ConvertToDraftEvent { createdAt }
        }
      }
    }
  }
}
"""

REVIEW_STATE = {"APPROVED": "A", "CHANGES_REQUESTED": "R", "COMMENTED": "C",
                "DISMISSED": "D", "PENDING": "P"}
# The reviewer's standing in the repository: M a member (or owner) of its
# organization, C an outside collaborator, N neither.
ASSOCIATION = {"MEMBER": "M", "OWNER": "M", "COLLABORATOR": "C"}
# Version of the cached record; older records are fetched again.
SCHEMA = 3


class Budget:
    """The API points and the time left; a run stops before either runs out."""

    def __init__(self, floor: int, max_minutes: float, wait: bool):
        self.floor = floor
        self.deadline = time.monotonic() + max_minutes * 60 if max_minutes else None
        self.wait = wait
        self.remaining = None
        self.reset_at = None

    def seen(self, rate: dict) -> None:
        self.remaining = rate["remaining"]
        self.reset_at = dt.datetime.fromisoformat(rate["resetAt"].replace("Z", "+00:00"))

    @property
    def out_of_time(self) -> bool:
        return self.deadline is not None and time.monotonic() >= self.deadline

    @property
    def spent(self) -> bool:
        if self.out_of_time:
            return True
        if self.remaining is None or self.remaining > self.floor:
            return False
        if not self.wait or self.reset_at is None:
            return True
        # Out of API points: wait for the hourly reset if the time allows.
        pause = (self.reset_at - dt.datetime.now(dt.timezone.utc)).total_seconds() + 15
        if self.deadline is not None and time.monotonic() + pause >= self.deadline:
            return True
        print(f"  API points used up, waiting {pause / 60:.0f} minutes for the reset", flush=True)
        time.sleep(max(pause, 0))
        self.remaining = None
        return False


def minutes(value: str | None) -> int:
    """Timestamp as minutes since the epoch; 0 for none."""
    if not value:
        return 0
    return int(dt.datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() // 60)


def graphql(query: str, **variables) -> dict:
    cmd = ["gh", "api", "graphql", "-f", f"query={query}"]
    for key, value in variables.items():
        if value is None:
            continue
        cmd += ["-F" if isinstance(value, int) else "-f", f"{key}={value}"]
    for attempt in range(5):
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            return json.loads(result.stdout)["data"]
        if "rate limit" in result.stderr.lower():
            raise RuntimeError("rate limit")
        time.sleep(3 * 2**attempt)
    raise RuntimeError(result.stderr.strip()[-300:])


def login(node: dict | None, key: str = "author") -> str:
    return ((node or {}).get(key) or {}).get("login") or ""


def reduce_pr(pr: dict) -> dict:
    """Keep what the statistics need, in a compact form."""
    reviews = {r["id"]: r for r in pr["reviews"]["nodes"]}
    reviews.update({r["id"]: r for r in pr["reviewsTail"]["nodes"]})
    requests, drafts = [], []
    for ev in pr["timelineItems"]["nodes"]:
        kind = ev["__typename"]
        if kind in ("ReviewRequestedEvent", "ReviewRequestRemovedEvent"):
            who = login(ev, "requestedReviewer")
            if who:
                requests.append([minutes(ev["createdAt"]), who,
                                 1 if kind == "ReviewRequestedEvent" else 0])
        else:
            drafts.append([minutes(ev["createdAt"]),
                           1 if kind == "ConvertToDraftEvent" else 0])
    return {
        "n": pr["number"], "t": pr["title"], "a": login(pr),
        "c": minutes(pr["createdAt"]), "cl": minutes(pr["closedAt"]),
        "m": minutes(pr["mergedAt"]), "d": 1 if pr["isDraft"] else 0,
        "u": pr["updatedAt"],
        "as": [n["login"] for n in pr["assignees"]["nodes"]],
        "l": sorted(n["name"] for n in pr["labels"]["nodes"]),
        "rv": sorted([minutes(r["submittedAt"]), login(r), REVIEW_STATE.get(r["state"], "C"),
                      ASSOCIATION.get(r.get("authorAssociation"), "N")]
                     for r in reviews.values() if r.get("submittedAt") and login(r)),
        "v": SCHEMA,
        "cm": sorted([minutes(c["createdAt"]), login(c)]
                     for c in pr["comments"]["nodes"] if login(c)),
        "rq": sorted(requests), "dr": sorted(drafts),
        "x": 1 if pr["reviews"]["totalCount"] > 200 else 0,
    }


def load(path: Path) -> dict:
    if path.is_file():
        with gzip.open(path, "rt") as f:
            return json.load(f)
    return {"state": {"resume": None, "complete": False}, "prs": {}}


def save(path: Path, cache: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with gzip.open(tmp, "wt") as f:
        json.dump(cache, f, separators=(",", ":"))
    tmp.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", default="zephyrproject-rtos/zephyr")
    parser.add_argument("--cache", type=Path, default=Path("cache/prs.json.gz"))
    parser.add_argument("--history-days", type=int, default=365,
                        help="how far back the cache reaches (by last update)")
    parser.add_argument("--floor", type=int, default=60,
                        help="stop when this many API points are left")
    parser.add_argument("--max-minutes", type=float, default=0,
                        help="stop refreshing after this long (0: no limit)")
    parser.add_argument("--wait-for-reset", action="store_true",
                        help="when the API points run out, wait for the hourly reset "
                             "and go on, as long as --max-minutes allows")
    parser.add_argument("--max-prs", type=int, default=0,
                        help="refresh at most this many pull requests (0: no limit)")
    parser.add_argument("--workers", type=int, default=3)
    args = parser.parse_args()

    owner, name = args.repo.split("/", 1)
    cache = load(args.cache)
    prs, state = cache["prs"], cache["state"]
    if state.get("schema") != SCHEMA:
        # Records of an older version are refreshed by the walk back in time.
        state.update(schema=SCHEMA, complete=False, resume=None)
    budget = Budget(args.floor, args.max_minutes, args.wait_for_reset)
    now = dt.datetime.now(dt.timezone.utc)
    cutoff = (now - dt.timedelta(days=args.history_days)).isoformat()
    refreshed = 0

    def refresh(number: int):
        data = graphql(PR_QUERY, owner=owner, name=name, number=number)
        budget.seen(data["rateLimit"])
        return reduce_pr(data["repository"]["pullRequest"])

    def walk(cursor: str | None, catching_up: bool) -> tuple[str | None, bool]:
        """Refresh stale pull requests page by page. Returns the cursor of the
        last finished page and whether the walk reached its end."""
        nonlocal refreshed
        while True:
            data = graphql(LIST_QUERY, owner=owner, name=name, cursor=cursor)
            budget.seen(data["rateLimit"])
            conn = data["repository"]["pullRequests"]
            nodes = [n for n in conn["nodes"] if n["updatedAt"] >= cutoff]
            stale = [n["number"] for n in nodes
                     if prs.get(str(n["number"]), {}).get("u") != n["updatedAt"]
                     or prs[str(n["number"])].get("v") != SCHEMA]
            if args.max_prs:
                stale = stale[:max(args.max_prs - refreshed, 0)]
            done_all = True
            with ThreadPoolExecutor(max_workers=args.workers) as pool:
                for i in range(0, len(stale), 20):
                    if budget.spent:
                        done_all = False
                        break
                    for rec in pool.map(refresh, stale[i:i + 20]):
                        prs[str(rec["n"])] = rec
                        refreshed += 1
                    if refreshed % 500 < 20:
                        print(f"  {refreshed} refreshed, API points left {budget.remaining}",
                              flush=True)
            limit_hit = args.max_prs and refreshed >= args.max_prs
            if not done_all or limit_hit:
                return cursor, False
            cursor = conn["pageInfo"]["endCursor"]
            at_end = len(nodes) < len(conn["nodes"]) or not conn["pageInfo"]["hasNextPage"]
            if at_end:
                return cursor, True
            if catching_up and not stale:
                return cursor, True  # a whole page was current: caught up
            if budget.spent:
                return cursor, False

    try:
        # 1. what changed since the last run
        _, caught_up = walk(None, catching_up=bool(prs))
        # 2. further back in time, from where the last run stopped
        if not state["complete"] and not budget.spent and \
                not (args.max_prs and refreshed >= args.max_prs):
            start = state["resume"] if prs and caught_up else None
            state["resume"], state["complete"] = walk(start, catching_up=False)
    except RuntimeError as err:
        print(f"stopped early: {err}", file=sys.stderr)

    # drop what fell out of the history window
    for number in [k for k, v in prs.items() if v["u"] < cutoff]:
        del prs[number]
    state["fetched_at"] = now.isoformat()
    state["oldest"] = min((v["u"] for v in prs.values()), default=None)
    save(args.cache, cache)
    print(f"refreshed {refreshed}, cached {len(prs)}, oldest update {state['oldest']}, "
          f"complete {state['complete']}, API points left {budget.remaining}")


if __name__ == "__main__":
    main()
