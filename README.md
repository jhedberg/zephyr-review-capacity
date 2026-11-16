<!-- SPDX-FileCopyrightText: Copyright (c) 2026 Silicon Laboratories Inc. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Zephyr review capacity

A page that shows, for every area of Zephyr's `MAINTAINERS.yml`, who answers
when a pull request asks for review: https://jhedberg.github.io/zephyr-review-capacity/

It is a prototype for discussion. The way of counting is a proposal, not
project policy.

## What the page shows

There are two views.

**All areas** compares the areas with each other, for whoever looks after the
project as a whole: how many people are listed and how many of them review,
how many pull requests arrive for each of those, how much of the approving is
done by listed people, how many requests are answered, how many pull requests
get no answer from the list, how long the first review takes and how many pull
requests are waiting. Sort by any column, or use "Show first" to bring up the
areas that need reviewers, answer least, or wait longest. A strip shows where
every area sits on the column the table is sorted by. This view offers four
fixed periods and one way of counting; its figures come from
`data/summary.json`.

**One area** is for the area's own maintainers:

Pick an area and a period. For each Maintainer and Collaborator of the area
the page shows the share of review requests they answered, and a line you can
move: Collaborators below it would come off the list at that level. Below that
it shows the flow through the area (pull requests opened and merged, time to
the first review and to the merge) and who brings review work against who
gives it.

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
- A request counts once per person and pull request, at the first request. It
  is answered when the person reviews at or after the request and before the
  end of the period (or comments, if that option is on).
- Not counted for or against anyone: the person's own pull requests, requests
  withdrawn without an answer, pull requests closed with less than three ready
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
  (time, login), review requests (time, login, asked or withdrawn) and draft
  changes. Times are minutes since the epoch. Pull requests not updated for a
  year are dropped.
- `data/index.json` lists the areas, and `data/<area>.json` holds an area's
  roster, a table of logins and three arrays of integer rows: pull requests,
  review requests to listed people, and reviewers.

Each run replaces the previous deployment, so no older versions are kept. The
cache is disposable: without it the fetcher rebuilds the year from GitHub in a
few runs.

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
