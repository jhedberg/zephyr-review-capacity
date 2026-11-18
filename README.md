<!-- SPDX-FileCopyrightText: Copyright (c) 2026 Silicon Laboratories Inc. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Zephyr review capacity

A page that shows, for every area of Zephyr's `MAINTAINERS.yml`, who answers
when a pull request asks for review: https://jhedberg.github.io/zephyr-review-capacity/

It is a prototype for discussion. The way of counting is a proposal, not
project policy.

## What the page shows

"Listed" and "the list" always mean the Maintainers and Collaborators of an
area in `MAINTAINERS.yml`. The page sorts them into four groups for a period:

- a **regular reviewer** answers at least half of five or more review requests;
- an **occasional reviewer** took part, but less than that;
- a **silent** one did not take part;
- with fewer than five requests there is **too little to tell**.

A pull request needs two approvals from people other than its author. It is
**covered** when two regular reviewers are left besides its author; otherwise
it relies on occasional or unlisted reviewers for an approval. An area whose
two regular reviewers also write much of its code is not covered for their
pull requests, so it takes three.

There are two views.

**All areas** compares the areas with each other, for whoever looks after the
project as a whole. Each area has:

- its review cover in words (no regular reviewer, one, thin, covered);
- the make-up of its list (regular, occasional and silent reviewers);
- how the Maintainer's reviewing compares with everyone else's;
- the pull requests arriving per week for each regular reviewer;
- the share of pull requests not covered;
- the share of the reviews that came from people who are not listed for the
  area, with the number of people behind it: cover describes the list, not
  how much review an area receives;
- the number of open pull requests, its change over the period and a small
  line of its course;
- the time to the second approval;
- the pull requests waiting two weeks for a first review, and those that have
  two approvals but wait for their assignee;
- the candidates for the list: people who are not listed but reviewed more of
  the area's pull requests than at least half of the listed people did.

Sort by any column, filter by cover, or use "Show first"; a legend above the
table defines each term and choice. The two states carry fixed colours. In the
columns with a real spread a mark shows the worst and the best tenth of the
areas in scope; the percentage column is not coloured, because most areas sit
at 0% or 100% there. A strip shows where every area sits on the column the
table is sorted by. Pointing at a figure, or tapping it, shows the names and
counts behind it. This view offers four fixed periods and one way of counting;
its figures come from `data/summary.json`.

A merge also needs an approval from an assignee, usually a Maintainer. The
page therefore shows how the Maintainer's reviewing compares with everyone
else's (reviews the most, second, writes most of the code, behind, or no
Maintainer), always next to the share of the area's pull requests the
Maintainer wrote, since nobody reviews their own. Only reviews are counted:
triage, design and release work do not show. Assignees are added and changed
by hand, so the page takes whoever is assigned now, counts any current
assignee's approval, and counts a wait for an area only where one of its own
Maintainers is assigned.

**One area** is for the area's own maintainers. For each Maintainer and
Collaborator it shows the share of review requests they answered, their group,
and a line you can move: Collaborators below it would come off the list at
that level. Pointing at a row of any table there shows what is behind it, such
as how a person's requests were answered or left out. Below that: the
Maintainer's standing and the wait for the assignee; the review cover as a bar with a sentence naming who
is counted and whose pull requests are short; where the two approvals of the
merged pull requests actually came from; the most active reviewers who are not
on the list as candidates for it, marked where GitHub shows them as public
members of the organization; and the
flow through the area: the number of open pull requests over time, what came
in and went out each week (opened, merged, closed without merging), the time
to the first review, the second approval and the merge, and who brings review
work against who gives it.

Everything is counted in the browser from per-request records, so any date
range and any combination of the counting options works without a new run.
The address bar holds the current view and can be shared.

## How it is counted

- An area's pull requests are those carrying the area's own label: the label
  named after the area, or else the one of its labels that the fewest areas
  list. An area that has only a label named after another area (many West
  projects) sees that area's pull requests; the view of all areas hides those
  unless asked. Label names are compared without regard to case,
  as GitHub does.
- Review requests and assignees come from the project's assigner,
  `scripts/ci/set_assignees.py` in the Zephyr tree, and the counting follows
  what it does. Once a pull request is out of draft it asks every Maintainer
  and Collaborator of every area the changed files belong to, without a cap
  (labels are capped at ten, so a person can be asked on a pull request that
  does not carry their area's label). Someone it cannot formally request,
  because they are not a repository collaborator, is asked with an @-mention
  in a comment: that counts as a request here. It does not ask someone who has
  reviewed already, so a listed person's review without a request counts as
  asked and answered. It does not ask again someone who withdrew a request
  themselves: such a request is called declined.
- A declined request counts like a request left unanswered when the pull
  request is the area's own, which is taken to be the case when one of the
  area's Maintainers is its assignee: a listed person is expected to review
  the area's own pull requests. Elsewhere, where the area is touched in
  passing, declining counts neither for nor against the person. The view of
  one area can switch this off. Many declines on an area's own pull requests
  can also mean that the area is drawn too wide for the person (part of it is
  a technology their work does not touch); the remedy then is a finer split
  of the area in MAINTAINERS.yml.
- Areas marked `meta: true` in MAINTAINERS.yml (Documentation, Tests, Samples,
  Release, Benchmarks) get their label and their people asked on any pull
  request that touches their files, while the assigner treats the pull request
  as another area's when it can and never reports them as short of reviewers.
  The view of all areas marks them and hides them unless asked.
- The assigner picks as assignee a Maintainer, other than the author, of the
  non-platform area with the most changed files, platform areas as a fallback
  and meta areas only when nothing else is touched. People change and add
  assignees by hand; the page uses the assignees a pull request has now.
- A request counts once per person and pull request, at the first request. It
  is answered when the person reviews at or after the request and before the
  end of the period (or comments, if that option is on).
- Not counted for or against anyone: the person's own pull requests, requests
  withdrawn by someone else without an answer, pull requests closed with less than three ready
  days after the request, open ones with less than seven ready days since the
  request. Time as a draft is not ready time.
- Optional excuse: a miss is not counted when the pull request closed within
  seven days of the request or two other people approved it within seven days.
- People with fewer than five countable requests are not judged, and the line
  never applies to a Maintainer.
- Bot accounts are left out.

Things to keep in mind when reading a number:

- A period with a holiday season in it lowers everyone's rate.
- One author who opens many pull requests raises everyone's number of
  requests. The page can leave out one author's pull requests to show that.
- People listed in an area because another area's pull requests often touch
  it are asked more than they answer by design. The page can leave out pull
  requests that also carry an area the person maintains.
- Whether a request was withdrawn, closed early or is still pending is judged
  with what is known when the data is built, not as of the end of the chosen
  period.

## How it works

- `fetch.py` keeps a cache of the review history of the repository's pull
  requests updated in the last year (reviews, comments, review requests, draft
  changes, labels). Each
  run catches up with what changed and then continues backwards in time until
  the API or time budget of the run is used, so the history fills over several
  runs.
  Each pull request is fetched with a query of its own: GitHub returns empty
  timelines, without an error, when one query asks for many.
- `build.py` reads the cache and `MAINTAINERS.yml` and writes one data file
  per area plus an index.
- `public/index.html` is the page. It has no dependencies.
- `.github/workflows/update.yml` runs both once a day (03:41 UTC) with the
  workflow's own token and publishes the result with GitHub Pages. The cache is published
  with the site and picked up again by the next run.

## Where the data lives

Nowhere but in the published site; nothing of it is in this repository.

- `cache/prs.json.gz` is the fetcher's cache: one gzip-compressed JSON file,
  `{"state": {...}, "prs": {"<number>": {...}}}`, about 1 KB per pull request
  before compression. A record holds the title, author, labels, the creation,
  close and merge times, and lists of reviews (time, login, state), comments
  (time, login), review requests (time, login, asked or withdrawn, and for a withdrawal
  whether the person did it themselves), the people the assigner asked in a
  comment, draft changes, and the current assignees. A review also carries what GitHub reports as the reviewer's
  association with the repository. The workflow's token is not a member of
  the organization, so it sees only public memberships: private members are
  reported like people who are not members. Times are minutes since the epoch. Pull requests not updated for a
  year are dropped.
- `data/index.json` lists the areas, and `data/<area>.json` holds an area's
  roster, a table of logins and three arrays of integer rows: pull requests,
  review requests to listed people, and reviewers.

Each run replaces the previous deployment, so no older versions are kept. The
cache is disposable: without it the fetcher rebuilds the year from GitHub in a
few runs, or in one when the workflow is started by hand with "full" set, which
lets it wait for the hourly reset of the API budget for up to five hours.

## Running it locally

```sh
gh auth login            # once; the scripts use the gh CLI
python3 fetch.py --max-prs 300
curl -sL https://raw.githubusercontent.com/zephyrproject-rtos/zephyr/main/MAINTAINERS.yml -o MAINTAINERS.yml
python3 build.py --maintainers MAINTAINERS.yml
python3 -m http.server -d public 8000
```

`fetch.py --repo OWNER/NAME` and a matching `MAINTAINERS.yml` make it work
for another repository that uses the same file format.
