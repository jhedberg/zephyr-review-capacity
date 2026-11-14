#!/usr/bin/env python3

# SPDX-FileCopyrightText: Copyright (c) 2026 Silicon Laboratories Inc.
# SPDX-License-Identifier: Apache-2.0

"""
Turn the pull request cache into the data files of the page: one JSON file
per MAINTAINERS.yml area and an index.

An area file holds no statistics. It holds one compact record per pull
request, per review request to a listed person and per reviewer, so that the
page can count any date range and any way of counting by itself.

All times are minutes since the epoch; 0 means never.
"""

from __future__ import annotations

import argparse
import datetime as dt
import gzip
import json
import re
from pathlib import Path

import yaml

DAY = 24 * 60
CLOSED_GRACE = 3 * DAY     # ready time a reviewer had before the PR closed
PENDING_GRACE = 7 * DAY    # ready time a reviewer has had on an open PR
EXCUSE = 7 * DAY           # "closed, or approved by two others, within a week"

BOTS = {"copilot-pull-request-reviewer", "github-actions", "dependabot", "zephyrbot",
        "zephyrbot-renesas", "Copilot", "copilot", "codecov", "github-advanced-security",
        "sonarqubecloud", "sonarcloud"}

# flags of a request record
WITHDRAWN, CLOSED_EARLY, PENDING, EXCUSED, OWN_AREA = 1, 2, 4, 8, 16


def is_bot(login: str) -> bool:
    return not login or login in BOTS or login.endswith("[bot]") or login.endswith("-bot")


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def primary_label(name: str, area: dict) -> str | None:
    labels = area.get("labels") or []
    if f"area: {name}" in labels:
        return f"area: {name}"
    return labels[0] if labels else None


class PR:
    def __init__(self, raw: dict):
        self.n = raw["n"]
        self.author = raw["a"]
        self.created, self.closed, self.merged = raw["c"], raw["cl"], raw["m"]
        self.draft_now = raw["d"]
        self.labels = set(raw["l"])
        self.title = raw["t"]
        self.reviews = [(t, w, s) for t, w, s in raw["rv"]
                        if not is_bot(w) and w != self.author and s != "P"]
        self.comments = [(t, w) for t, w in raw["cm"] if not is_bot(w) and w != self.author]
        self.requests: dict[str, list] = {}
        for t, w, asked in raw["rq"]:
            if not is_bot(w) and w != self.author:
                self.requests.setdefault(w, []).append((t, asked))
        changes = raw["dr"]
        initial = (not changes[0][1]) if changes else bool(raw["d"])
        self.draft_changes = [(self.created, initial)] + [(t, bool(d)) for t, d in changes]
        self.first_ready = next((t for t, d in self.draft_changes if not d), 0)

    def ready_time(self, start: int, end: int) -> int:
        total = 0
        changes = self.draft_changes + [(end, True)]
        for (t, draft), (nxt, _) in zip(changes, changes[1:]):
            if not draft:
                total += max(0, min(nxt, end) - max(t, start))
        return total

    def approvals(self) -> list[tuple[int, str]]:
        seen, out = set(), []
        for t, w, s in self.reviews:
            if s == "A" and w not in seen:
                seen.add(w)
                out.append((t, w))
        return out


def build_area(name: str, area: dict, prs: list[PR], maintains: dict, now: int) -> dict:
    maintainers = list(area.get("maintainers") or [])
    collaborators = [c for c in (area.get("collaborators") or []) if c not in maintainers]
    roster = maintainers + collaborators
    logins: list[str] = []
    index: dict[str, int] = {}

    def idx(login: str) -> int:
        if login not in index:
            index[login] = len(logins)
            logins.append(login)
        return index[login]

    for who in roster:
        idx(who)
    rows, asks, revs = [], [], []
    for row, pr in enumerate(sorted(prs, key=lambda p: p.n)):
        approvals = pr.approvals()
        first_review = min((t for t, _, _ in pr.reviews), default=0)
        rows.append([pr.n, idx(pr.author) if pr.author else -1, pr.created, pr.first_ready,
                     pr.merged, pr.closed, first_review,
                     approvals[1][0] if len(approvals) > 1 else 0, pr.draft_now])
        end = pr.closed or now
        for who in roster:
            events = sorted(pr.requests.get(who, []))
            asked = next((t for t, a in events if a), 0)
            if not asked:
                continue
            flags = 0
            if events and not events[-1][1]:
                flags |= WITHDRAWN
            ready = pr.ready_time(asked, end)
            if pr.closed and ready < CLOSED_GRACE:
                flags |= CLOSED_EARLY
            if not pr.closed and ready < PENDING_GRACE:
                flags |= PENDING
            others = sum(1 for t, w in approvals if w != who and t <= asked + EXCUSE)
            if (pr.closed and pr.closed - asked < EXCUSE) or others >= 2:
                flags |= EXCUSED
            other_areas = maintains.get(who, set()) - {primary_label(name, area)}
            if any(label in pr.labels for label in other_areas):
                flags |= OWN_AREA
            reviewed = min((t for t, w, _ in pr.reviews if w == who and t >= asked), default=0)
            commented = min((t for t, w in pr.comments if w == who and t >= asked), default=0)
            asks.append([idx(who), row, asked, reviewed, commented, flags])
        by_reviewer: dict[str, list] = {}
        for t, w, s in pr.reviews:
            rec = by_reviewer.setdefault(w, [t, 0, t])
            rec[2] = max(rec[2], t)
            if s == "A" and not rec[1]:
                rec[1] = t
        for who, (first, approved, last) in by_reviewer.items():
            revs.append([idx(who), row, first, approved, last])
    return {"name": name, "status": area.get("status"), "label": primary_label(name, area),
            "maintainers": maintainers, "collaborators": collaborators,
            "logins": logins, "prs": rows, "asks": asks, "revs": revs}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cache", type=Path, default=Path("cache/prs.json.gz"))
    parser.add_argument("--maintainers", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=Path("public/data"))
    parser.add_argument("--repo", default="zephyrproject-rtos/zephyr")
    args = parser.parse_args()

    with gzip.open(args.cache, "rt") as f:
        cache = json.load(f)
    areas = {k: v for k, v in yaml.safe_load(args.maintainers.read_text()).items()
             if isinstance(v, dict)}
    prs = [PR(raw) for raw in cache["prs"].values()]
    fetched = cache["state"].get("fetched_at")
    now = int(dt.datetime.fromisoformat(fetched).timestamp() // 60)

    # the primary labels of the areas each person maintains
    maintains: dict[str, set] = {}
    for name, area in areas.items():
        label = primary_label(name, area)
        for who in area.get("maintainers") or []:
            if label:
                maintains.setdefault(who, set()).add(label)
    by_label: dict[str, list] = {}
    for pr in prs:
        for label in pr.labels:
            by_label.setdefault(label, []).append(pr)

    args.out.mkdir(parents=True, exist_ok=True)
    for old in args.out.glob("*.json"):
        old.unlink()
    index = []
    for name, area in sorted(areas.items(), key=lambda kv: kv[0].lower()):
        label = primary_label(name, area)
        if not label:
            continue
        data = build_area(name, area, by_label.get(label, []), maintains, now)
        file = slug(name) + ".json"
        (args.out / file).write_text(json.dumps(data, separators=(",", ":")))
        index.append({"name": name, "file": file, "status": area.get("status"),
                      "people": len(data["maintainers"]) + len(data["collaborators"]),
                      "prs": len(data["prs"])})
    (args.out / "index.json").write_text(json.dumps({
        "repo": args.repo, "generated": fetched, "now": now,
        "oldest": cache["state"].get("oldest"), "complete": cache["state"].get("complete"),
        "pull_requests": len(prs), "truncated": sum(1 for r in cache["prs"].values() if r.get("x")),
        "areas": index}, separators=(",", ":")))
    print(f"{len(index)} areas from {len(prs)} pull requests")


if __name__ == "__main__":
    main()
