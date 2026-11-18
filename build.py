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
WITHDRAWN, CLOSED_EARLY, PENDING, EXCUSED, OWN_AREA, DECLINED, UNASKED, MENTIONED = 1, 2, 4, 8, 16, 32, 64, 128


def is_bot(login: str) -> bool:
    return not login or login in BOTS or login.endswith("[bot]") or login.endswith("-bot")


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


LABEL_USE: dict[str, int] = {}   # how many areas list each label


def primary_label(name: str, area: dict) -> str | None:
    """The label that stands for the area itself: the one named after the
    area, else the one the fewest areas list (an area often also lists the
    label of the group it belongs to)."""
    labels = area.get("labels") or []
    if not labels:
        return None
    wanted = {name.lower(), name.split(":")[-1].strip().lower()}
    for label in labels:
        if label.split(":", 1)[-1].strip().lower() in wanted:
            return label
    return min(labels, key=lambda label: LABEL_USE.get(label.lower(), 0))


class PR:
    def __init__(self, raw: dict):
        self.n = raw["n"]
        self.author = raw["a"]
        self.created, self.closed, self.merged = raw["c"], raw["cl"], raw["m"]
        self.draft_now = raw["d"]
        # None when the record predates the fetching of assignees
        self.assignees = raw.get("as")
        # GitHub treats label names without regard to case, and MAINTAINERS.yml
        # does not always spell them as the repository does.
        self.labels = {label.lower() for label in raw["l"]}
        self.title = raw["t"]
        # a review is [time, login, state] or, from newer fetches,
        # [time, login, state, association]
        self.reviews = [(r[0], r[1], r[2]) for r in raw["rv"]
                        if not is_bot(r[1]) and r[1] != self.author and r[2] != "P"]
        self.standing = {r[1]: r[3] for r in raw["rv"] if len(r) > 3}
        self.comments = [(t, w) for t, w in raw["cm"] if not is_bot(w) and w != self.author]
        self.requests: dict[str, list] = {}
        # a request is [time, login, 1]; a removal [time, login, 0] or, from
        # newer fetches, [time, login, 0, removed themselves]
        for ev in raw["rq"]:
            t, w, asked = ev[0], ev[1], ev[2]
            if not is_bot(w) and w != self.author:
                self.requests.setdefault(w, []).append((t, asked, ev[3] if len(ev) > 3 else 0))
        self.mentions = {w: t for t, w in reversed(raw.get("mn", []))}
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


def build_area(name: str, area: dict, prs: list[PR], maintains: dict, now: int,
               standing: dict) -> dict:
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
        # The assignee whose approval a merge needs: -2 not known, -1 none
        # (or the author, who cannot approve), else the first assignee.
        others = None if pr.assignees is None else [w for w in pr.assignees if w != pr.author]
        assignee = -2 if others is None else (idx(others[0]) if others else -1)
        assignee_approval = 0 if not others else min(
            (t for t, w in approvals if w in others), default=0)
        # Assignees get added and switched by hand, so "the assignee" is
        # whoever is assigned now, and any of them may give the approval. The
        # last field says whether one of this area's Maintainers is among them.
        own = 1 if others and any(w in maintainers for w in others) else 0
        rows.append([pr.n, idx(pr.author) if pr.author else -1, pr.created, pr.first_ready,
                     pr.merged, pr.closed, first_review,
                     approvals[1][0] if len(approvals) > 1 else 0, pr.draft_now,
                     assignee, assignee_approval, len(approvals), own])
        end = pr.closed or now
        for who in roster:
            events = sorted(pr.requests.get(who, []))
            asked = next((ev[0] for ev in events if ev[1]), 0)
            flags = 0
            if not asked and who in pr.mentions:
                # Not a repository collaborator: the assigner cannot request
                # the review and asks in a comment instead.
                asked = pr.mentions[who]
                flags |= MENTIONED
            if not asked:
                # The assigner does not request someone who has reviewed
                # already. A listed person's review without a request still
                # is taking part: count it as asked and answered.
                first = min((t for t, w, _ in pr.reviews if w == who), default=0)
                if not first:
                    continue
                asked = first
                flags |= UNASKED
            if events and not events[-1][1]:
                flags |= WITHDRAWN
                if events[-1][2]:
                    flags |= DECLINED
            ready = pr.ready_time(asked, end)
            if pr.closed and ready < CLOSED_GRACE:
                flags |= CLOSED_EARLY
            if not pr.closed and ready < PENDING_GRACE:
                flags |= PENDING
            others = sum(1 for t, w in approvals if w != who and t <= asked + EXCUSE)
            if (pr.closed and pr.closed - asked < EXCUSE) or others >= 2:
                flags |= EXCUSED
            other_areas = maintains.get(who, set()) - {primary_label(name, area).lower()}
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
            "meta": 1 if area.get("meta") else 0,
            "maintainers": maintainers, "collaborators": collaborators,
            "logins": logins,
            # 2 public member of the organization, 1 outside collaborator,
            # 0 neither as far as the fetching token can see (a private
            # member looks like this too), -1 not known yet
            "standing": [{"M": 2, "C": 1, "N": 0}.get(standing.get(w), -1) for w in logins],
            "prs": rows, "asks": asks, "revs": revs}


# Version of the data files' layout. The page carries the same number and
# refuses to mix a page of one version with data of another.
FORMAT = 6
WINDOWS = (30, 90, 180, 365)
WAITING = 14 * DAY
REGULAR = 0.5      # a regular reviewer answers at least this share of requests
MIN_REQUESTS = 5   # with fewer requests there is too little to tell
THIN = 0.2         # share of pull requests not covered that makes cover thin
MIN_CANDIDATE = 5  # reviews below which nobody is a candidate


def median(values: list) -> float | None:
    if not values:
        return None
    values = sorted(values)
    mid = len(values) // 2
    return values[mid] if len(values) % 2 else (values[mid - 1] + values[mid]) / 2


def tier(requests: int, answered: int, reviewed: int) -> str:
    """Where a listed person stands in a period: a regular reviewer answers
    at least half of five or more requests; with fewer requests there is too
    little to tell; the rest are occasional if they took part at all."""
    if requests < MIN_REQUESTS:
        return "unrated"
    if answered / requests >= REGULAR:
        return "regular"
    return "occasional" if answered or reviewed else "silent"


def status_of(regular: int, cover: list) -> str:
    """The state of an area's review cover, from worst to best."""
    total = sum(cover)
    if regular == 0:
        return "none"
    if regular == 1:
        return "single"
    if total and (cover[0] + cover[1]) / total >= THIN:
        return "thin"
    return "covered"


def summarize(data: dict, now: int) -> dict:
    """Health figures of one area for each fixed period, counted the default
    way: a comment counts, and a miss is excused when the pull request closed
    or collected two other approvals within a week."""
    logins, prs = data["logins"], data["prs"]
    roster = [logins.index(w) for w in data["maintainers"] + data["collaborators"]]
    listed = set(roster)
    waiting = sum(1 for p in prs if not p[5] and not p[8] and not p[6]
                  and p[3] and now - p[3] >= WAITING)
    approvers: dict[int, set] = {}
    for who, row, _first, approved, _last in data["revs"]:
        if approved:
            approvers.setdefault(row, set()).add(who)
    # open pull requests at the end of each of the last 53 weeks, oldest first
    weekly = []
    for back in range(52, -1, -1):
        at = now - back * 7 * DAY
        weekly.append(sum(1 for p in prs if p[2] <= at and (not p[5] or p[5] > at)))
    maintainers = [logins.index(w) for w in data["maintainers"]]
    # open and ready, approved by two others but not yet by an assignee,
    # with one of this area's Maintainers as assignee
    on_assignee = [p[0] for p in prs if not p[5] and not p[8] and p[3]
                   and p[12] and not p[10] and p[11] >= 2]
    out = {"waiting": waiting, "open": weekly, "on_assignee": len(on_assignee),
           "on_assignee_prs": on_assignee[:8], "w": {}}
    for days in WINDOWS:
        start = now - days * DAY
        per_pr: dict[int, int] = {}
        per_person: dict[int, list] = {}
        for who, row, asked, reviewed, commented, flags in data["asks"]:
            if asked < start:
                continue
            hit = bool(reviewed or commented)
            if not hit:
                if flags & (WITHDRAWN | CLOSED_EARLY | PENDING | EXCUSED):
                    continue
                if now - asked < PENDING_GRACE and not prs[row][5]:
                    continue
            per_pr[row] = per_pr.get(row, 0) + hit
            tally = per_person.setdefault(who, [0, 0])
            tally[0] += 1
            tally[1] += hit
        reviewed_by: dict[int, int] = {}
        for who, _row, first, _approved, _last in data["revs"]:
            if first >= start:
                reviewed_by[who] = reviewed_by.get(who, 0) + 1
        tiers = {"regular": [], "occasional": [], "silent": [], "unrated": []}
        regular = set()
        for who in roster:
            n, hits = per_person.get(who, (0, 0))
            kind = tier(n, hits, reviewed_by.get(who, 0))
            tiers[kind].append(logins[who])
            if kind == "regular":
                regular.add(who)

        ready = [p for p in prs if p[3] >= start]
        # pull requests with 0, 1, 2+ regular reviewers besides their author
        cover = [0, 0, 0]
        authors: dict[int, int] = {}
        for p in ready:
            cover[min(2, len(regular - {p[1]}))] += 1
            authors[p[1]] = authors.get(p[1], 0) + 1
        top_author = max(authors, key=authors.get) if authors else -1
        # where the two approvals of the merged pull requests came from:
        # regular reviewers alone, with other listed people, with unlisted
        # people, or fewer than two on record
        outcome = [0, 0, 0, 0]
        for row, p in enumerate(prs):
            if p[4] < start:
                continue
            who = approvers.get(row, set()) - {p[1]}
            if len(who & regular) >= 2:
                outcome[0] += 1
            elif len(who & listed) >= 2:
                outcome[1] += 1
            elif len(who) >= 2:
                outcome[2] += 1
            else:
                outcome[3] += 1
        # The Maintainer's standing: reviews against the most active other
        # person, and how much of the area's code the Maintainer writes.
        m_reviews = [[logins[m], reviewed_by.get(m, 0)] for m in maintainers]
        top_m = max((n for _w, n in m_reviews), default=0)
        other = max(((n, w) for w, n in reviewed_by.items() if w not in maintainers),
                    default=(0, -1))
        m_wrote = sum(authors.get(m, 0) for m in maintainers) / len(ready) if ready else 0
        if not maintainers:
            standing = "none"
        elif top_m >= other[0]:
            standing = "leads"
        elif any(m in regular for m in maintainers):
            standing = "second"
        elif m_wrote >= 0.5:
            standing = "author"
        else:
            standing = "behind"
        # the assignee, whose approval every merge needs
        assigned = [p for p in prs if p[4] >= start and p[9] >= 0]
        to_assignee = [max(0, p[10] - p[3]) / DAY for p in ready if p[12] and p[10]]
        second = [max(0, p[7] - p[3]) / DAY for p in ready if p[7]]
        first_review = [max(0, p[6] - p[3]) / DAY for p in ready if p[6]]
        # Candidates for the list: people who are not listed but reviewed more
        # pull requests here than at least half of the listed people did.
        listed_counts = [reviewed_by.get(w, 0) for w in roster]
        outside = []
        for w, n in reviewed_by.items():
            if w in listed or n < MIN_CANDIDATE:
                continue
            ahead = sum(1 for count in listed_counts if count < n)
            outside.append((n, logins[w], ahead))
        outside.sort(reverse=True)
        candidates = [c for c in outside if 2 * c[2] >= len(roster)]
        out["w"][str(days)] = {
            "ready": len(ready),
            "opened": sum(1 for p in prs if p[2] >= start),
            "merged": sum(1 for p in prs if p[4] >= start),
            "closed": sum(1 for p in prs if p[5] >= start and not p[4]),
            "open_start": sum(1 for p in prs if p[2] <= start and (not p[5] or p[5] > start)),
            "tiers": [len(tiers["regular"]), len(tiers["occasional"]), len(tiers["silent"]),
                      len(tiers["unrated"])],
            "people": [tiers["regular"], tiers["occasional"], tiers["silent"], tiers["unrated"]],
            "status": status_of(len(regular), cover),
            "cover": cover, "outcome": outcome,
            "top_author": logins[top_author] if top_author >= 0 else None,
            "top_author_prs": authors.get(top_author, 0),
            "asked_prs": len(per_pr), "silent_prs": sum(1 for n in per_pr.values() if not n),
            "first_review": None if not first_review else round(median(first_review), 2),
            "second_approval": None if not second else round(median(second), 2),
            "second_n": len(second),
            "maintainer": {"state": standing, "reviews": m_reviews,
                           "wrote": round(m_wrote, 3),
                           "other": None if other[1] < 0 else
                           [logins[other[1]], other[0], other[1] in listed]},
            "assignee_days": None if not to_assignee else round(median(to_assignee), 2),
            "assignee_n": len(to_assignee),
            "assignee_merged": len(assigned),
            "assignee_own": sum(1 for p in assigned if p[12]),
            "candidates": [[w, n, ahead] for n, w, ahead in candidates[:8]],
            "candidate_count": len(candidates),
            "outside": [[w, n, ahead] for n, w, ahead in outside[:5]],
        }
    return out


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
    for area in areas.values():
        for label in area.get("labels") or []:
            LABEL_USE[label.lower()] = LABEL_USE.get(label.lower(), 0) + 1
    prs = [PR(raw) for raw in cache["prs"].values()]
    standing: dict[str, str] = {}
    for pr in prs:
        standing.update(pr.standing)
    fetched = cache["state"].get("fetched_at")
    now = int(dt.datetime.fromisoformat(fetched).timestamp() // 60)

    # the primary labels of the areas each person maintains
    maintains: dict[str, set] = {}
    for name, area in areas.items():
        label = primary_label(name, area)
        for who in area.get("maintainers") or []:
            if label:
                maintains.setdefault(who, set()).add(label.lower())
    by_label: dict[str, list] = {}
    for pr in prs:
        for label in pr.labels:
            by_label.setdefault(label, []).append(pr)

    args.out.mkdir(parents=True, exist_ok=True)
    for old in args.out.glob("*.json"):
        old.unlink()
    index = []
    summary = []
    # An area that uses a label named after another area sees that area's
    # pull requests. The owner of a label is the area named like it.
    users: dict[str, list] = {}
    for name, area in areas.items():
        label = primary_label(name, area)
        if label:
            users.setdefault(label.lower(), []).append(name)

    def claim(name: str, label: str) -> int:
        """How strongly an area owns a label: named exactly like it, named
        after it ("ADI Platforms" for "platform: ADI"), any other area, and
        last a West project, which takes the label of the area it serves."""
        topic = label.split(":", 1)[-1].strip().lower()
        lower = name.lower()
        if lower.startswith("west project"):
            return 0
        if topic in (lower, lower.split(":")[-1].strip()):
            return 3
        return 2 if lower.startswith(topic + " ") else 1

    def borrows(name: str, label: str) -> bool:
        others = users[label.lower()]
        return claim(name, label) < max(claim(other, label) for other in others)

    for name, area in sorted(areas.items(), key=lambda kv: kv[0].lower()):
        label = primary_label(name, area)
        if not label:
            continue
        data = build_area(name, area, by_label.get(label.lower(), []), maintains, now, standing)
        file = slug(name) + ".json"
        (args.out / file).write_text(json.dumps(data, separators=(",", ":")))
        index.append({"name": name, "file": file, "status": area.get("status"),
                      "people": len(data["maintainers"]) + len(data["collaborators"]),
                      "prs": len(data["prs"])})
        summary.append({"name": name, "status": area.get("status"),
                        "meta": 1 if area.get("meta") else 0,
                        "maintainers": len(data["maintainers"]),
                        "collaborators": len(data["collaborators"]),
                        "shares_label": 1 if borrows(name, label) else 0,
                        **summarize(data, now)})
    # Two different things can be unfinished: the walk back to the start of
    # the history window, and, after a change of the record layout, the
    # refresh of records that already cover the whole window.
    state = cache["state"]
    oldest = state.get("oldest")
    reach = now - (state.get("history_days", WINDOWS[-1]) - 2) * DAY
    history = bool(state.get("complete")) or bool(
        oldest and dt.datetime.fromisoformat(oldest.replace("Z", "+00:00")).timestamp() // 60 <= reach)
    current = sum(1 for r in cache["prs"].values() if r.get("v") == state.get("schema"))
    (args.out / "index.json").write_text(json.dumps({
        "format": FORMAT, "repo": args.repo, "generated": fetched, "now": now,
        "oldest": oldest, "complete": state.get("complete"),
        "history": history, "current": round(current / max(len(cache["prs"]), 1), 3),
        "adds": state.get("adds", ""),
        "pull_requests": len(prs), "truncated": sum(1 for r in cache["prs"].values() if r.get("x")),
        "standing_known": round(sum(1 for r in cache["prs"].values() if r.get("v", 1) >= 2)
                                / max(len(cache["prs"]), 1), 3),
        "assignee_known": round(sum(1 for r in cache["prs"].values() if "as" in r)
                                / max(len(cache["prs"]), 1), 3),
        "areas": index}, separators=(",", ":")))
    (args.out / "summary.json").write_text(json.dumps(
        {"format": FORMAT, "now": now, "windows": list(WINDOWS), "areas": summary},
        separators=(",", ":")))
    print(f"{len(index)} areas from {len(prs)} pull requests")


if __name__ == "__main__":
    main()
