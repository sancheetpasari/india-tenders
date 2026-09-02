# India State Tenders — Live Dashboard

A dashboard of **currently active tenders across Indian state e-procurement portals**,
scraped directly from each state's official NIC portal.

## Quick start

```bat
pip install -r requirements.txt
python -m playwright install chromium
python scraper.py
python live.py --serve-only
```

The Playwright step is needed only for Gujarat and Bihar. Skip it (and pass
`--no-browser`) if you don't want a ~150 MB bundled Chromium.

Or just double-click **`open-dashboard.bat`**.

The dashboard opens at <http://127.0.0.1:8777/dashboard.html>.

> Serve it — don't double-click `dashboard.html`. Browsers block a `file://`
> page from reading `tenders.json`, so the dashboard would come up empty.

## What you get

| File | Purpose |
|---|---|
| `dashboard.html` | The dashboard — filters, charts, sortable table, CSV export |
| `scraper.py` | Fetches tenders from every supported portal |
| `adapters.py` | HTTP adapters for non-GePNIC sources (AP, Telangana, Chhattisgarh, GeM, ONGC) |
| `browser_adapters.py` | Playwright adapters for Gujarat and Bihar |
| `portals.py` | Registry of state portals (edit to add/remove) |
| `sector.py` | Defines what counts as CA / audit / tax work — **edit this to tune the filter** |
| `retag.py` | Re-applies `sector.py` to existing data without re-scraping |
| `serve.py` | Tiny local web server |
| `live.py` | Serves the dashboard, and can refresh on a schedule itself |
| `refresh-tenders.bat` | What Windows Task Scheduler runs at 00:00 and 12:00 |
| `open-dashboard.bat` | Double-click to open the dashboard |
| `build_artifact.py` | Rebuilds the shareable single-file page |
| `share/` | The shareable page and its template |
| `status.json` | Tiny freshness file the dashboard polls |
| `tenders.json` | Data the dashboard reads |
| `tenders.csv` | Same data for Excel |
| `tenders.db` | Same data as SQLite, for SQL queries |
| `scrape.log` | Per-portal results of the last run |

## How it works

Every state portal below runs NIC's **GePNIC** platform. Its main tender search is
behind a captcha, but the **"Tenders by Closing Date"** listing
(`FrontEndListTendersbyDate`) is not — it is a public listing page.

The scraper, per portal:

1. loads that page and reads the Tapestry form,
2. POSTs it with `submitname=LinkSubmit_1` to switch the window to
   **"Closing within 14 days"**,
3. walks the pager (`sp=2…N`) within the same session,
4. parses each row into state, tender ID, reference no., title, department,
   published / closing / opening dates, and corrigendum flag,
5. repeats the walk with a fresh session and unions the results (see below),
6. de-duplicates on tender ID.

Only public listing pages are read — no login, no captcha solving, no bidding
interaction. Requests run 3-at-a-time per host.

### Why it walks each portal several times

GePNIC sorts this listing by closing date **with no stable tiebreaker**. Tenders
sharing a closing time — and many share "05:00 PM" on the same date — come back
in a different order on every request. So a single walk of the pager silently
repeats some tenders and *misses others entirely*: about **75% coverage**.

The scraper therefore walks each portal up to 5 times and unions the results,
stopping early once a pass adds nothing new. That lifts coverage to
**97–99%**, which `scrape.log` reports per portal:

```
OK  Uttarakhand   453 tenders / 46 pages / 5 passes, ~98% of ~460 in 16s
```

The `~460` is pages × 10, i.e. what the portal claims it holds. Use
`--passes 1` for a fast, incomplete sweep, or raise it to chase the last
fraction of a percent.

### Window

"Active" defaults to **closing within 14 days**, which is the widest window the
portals offer without a date-range captcha. Narrow it if you want:

```bat
python scraper.py --window 7
python scraper.py --window today
```

### Other options

```bat
python scraper.py --states Maharashtra "Tamil Nadu"   :: just these states
python scraper.py --max-pages 5                       :: quick smoke run
python scraper.py --passes 1                          :: fast, ~75% coverage
python scraper.py --workers 12 --conc 4               :: push harder
python scraper.py --no-browser                        :: skip Gujarat + Bihar
python scraper.py --no-custom                         :: GePNIC portals only
python scraper.py --deadline 300                      :: cap each portal at 5 min
python scraper.py --deadline 0                        :: no per-portal cap
```

### Slow portals can't stall the run

Two safeguards, both added after Uttar Pradesh took 95 minutes one evening
when its server slowed ~8x and held up the other 32 sources:

* **Results publish as they arrive.** `tenders.json` / `.csv` / `.db` are
  rewritten after every portal finishes, not once at the end, so the dashboard
  fills in progressively instead of staying empty until the slowest portal is
  done. Each file is written to a temp path and swapped in atomically, so the
  dashboard never reads a half-written file. While a run is in progress the
  JSON carries `"partial": true` and the dashboard header says
  *"refreshing now — more still loading"*.

* **A refresh never loses data.** Mid-run writes merge fresh results *over* the
  previous run rather than replacing it, so a state shows yesterday's tenders
  until its own re-scrape lands. That matters because an interrupted run —
  machine sleeps, process killed — would otherwise leave a truncated dataset
  behind. States that fail outright keep their previous data and are listed in
  the coverage panel as `stale`.

* **Each portal gets a deadline** (`--deadline`, default **900 s**). Past it,
  the scraper keeps whatever that portal has returned so far and moves on,
  logging `[DEADLINE HIT - partial]` with the coverage actually achieved:

  ```
  OK  Maharashtra  1239 tenders / 376 pages / 1 passes, ~33% of ~3760 in 25s [DEADLINE HIT - partial]
  ```

  Losing a slice of one state beats losing the whole run. Raise it for a
  thorough overnight refresh, or set `--deadline 0` to disable the cap.

## Using the dashboard

- **Work type** offers your sector as two groups — *audit / tax / accounting*
  and *other consultancy / PMC* — plus both together, or everything else.
  See "Tuning the sector filter" below.
- **Search** matches title, department, reference number and tender ID.
- **Location (state)** is the geographic filter and spans every source —
  see "Location vs source" below. **Source portal** filters by the portal itself.
- **Department** narrows to the departments in the chosen state, not all ~3,000.
- **Filters** for closing window; quick chips for
  *closing in 48 h*, *published in 24 h*, *has corrigendum*, and works /
  goods / services.
- **Click any state bar** in the chart to filter to it.
- **Sort** by clicking a column header.
- **Export CSV** exports exactly what is currently filtered, not the whole set.
- Tender titles link back to the source portal.

## Tuning the sector filter

`sector.py` decides what counts as your work. It applies two tags:

| Tag | Group | Roughly |
|---|---|---|
| `ca` | **1** — chartered accountancy, audit, taxation, accounting, financial advisory | 120 |
| `consult` | **2** — every other consulting engagement: PMC / PMU, DPRs, feasibility and market studies, value-chain analysis, PPP, capacity building, third-party inspection | 726 |
| *(blank)* | Works, goods, supply | 105,300 |

Group 2 is deliberately wide: a consultant bids engineering-adjacent work too,
so DPRs and PMC roles belong there rather than being filtered out. Group 1
wins when a title fits both.

Two design rules, both learned from false positives in the real data:

* **It reads the title only.** Department names are buyers, not the work.
  "Excise and Taxation Department" buying fire extinguishers is not a tax
  engagement; the "Accountant General" hiring cabs is not an audit.
* **Every pattern is word-boundary anchored.** "audit**orium**" contains
  "auditor" — unanchored, the filter pulls in every auditorium construction
  tender in the country.

Excluded on purpose: security / safety / energy / structural / ISO audits,
auditor *training courses*, and anything matching a quality-standard number
(AS 9100, ISO 9001).

One trap in group 2: **"PMC" is also how Ponda Municipal Corporation writes
its name**, and it turns up in ordinary road-repair tenders. The pattern
therefore requires a following noun — `PMC services`, `PMC firm`,
`PMC consultancy` — never a bare `PMC`. Covered by a test.

To widen or narrow it, edit `INCLUDE` / `EXCLUDE` in `sector.py`, then:

```bat
python sector.py     :: run the built-in tests (30 cases)
python retag.py      :: re-tag existing data, no re-scrape needed
```

The tag is written to `tenders.json`, `tenders.csv` and `tenders.db` as a
`sector` column, so you can also query it directly:

```sql
SELECT state, region, title, closing FROM tenders
WHERE sector = 'ca' ORDER BY closing;        -- group 1
-- sector = 'consult'  -> group 2
-- sector <> ''        -> both groups
```

## Coverage

**39 sources: 35 of 36 states and UTs, plus central portals and GeM.**
Three tiers, in increasing order of effort:

**1. GePNIC portals (32)** — `scraper.py`, plain HTTP: Arunachal Pradesh, Assam,
Chandigarh, Delhi, DNH & Daman Diu, Goa, Haryana, Himachal Pradesh,
Jammu & Kashmir, Jharkhand, Kerala, Ladakh (shares the J&K portal),
Madhya Pradesh, Maharashtra, Manipur, Meghalaya, Mizoram, Nagaland, Odisha,
Puducherry, Punjab, Rajasthan, Sikkim, Tamil Nadu, Tripura, Uttar Pradesh,
Uttarakhand, West Bengal.

Plus four central sources on the same platform: the **CPPP** portal
(`eprocure.gov.in`, which also carries Andaman & Nicobar and Lakshadweep),
**Defence / MoD** (`defproc.gov.in`), **Coal India** and **NTPC**.

**2. Custom platforms over HTTP (5)** — `adapters.py`:

| State | Platform | How |
|---|---|---|
| Andhra Pradesh | APeProcurement | DataTables JSON endpoint; the `hdnEncrypt*` fields are literal placeholders, not real crypto |
| Telangana | TS eProcurement | same platform, plain JSON instead of base64 |
| Chhattisgarh | CHIPS CHEPS | hidden `loadAlldata=Y` form re-renders the page with the full list |
| GeM | Government e-Marketplace | swept per state through the advanced search, so every bid carries its consignee state |
| ONGC | Liferay portlet | public "Current NITs" list; ~15 rows, no closing dates published |
| **GeM** | Government e-Marketplace | Public `/all-bids-data` JSON API (Solr-backed), 10 bids a page. Its `...Z` timestamps are **already IST** despite the Z — do not shift them. |
| ONGC | Liferay portlet | Public "Current NITs" list. Shallow: ~15 rows, and it publishes **no closing date**, so those rows carry no "time left" and drop out of closing-window filters. |

**3. Browser-driven (2)** — `browser_adapters.py`, needs Playwright:

| State | Platform | Why a browser is required |
|---|---|---|
| Gujarat | nProcure | Request bodies are AES-encrypted client-side and the tender endpoint is replay-protected — it answers the page's own script once and 404s on any repeat, even from the same browser. The adapter drives the table's own pagination (24 pages at 150 rows). |
| Bihar | EPSV2Web | Angular over a REST API that rejects non-browser callers with "Expected Fishing or Hacking attack". The adapter reads the tender list straight out of the page's Angular scope. |

Gujarat, Bihar, AP, Telangana and Chhattisgarh all publish **estimated contract
value**, which GePNIC does not. It shows in the dashboard row and in the `ecv`
column of the CSV/SQLite exports.

### Central platforms not covered

These are separate systems, not GePNIC, and each would need its own adapter:

| Source | Why |
|---|---|
| **IREPS** (Railways) | Its `robots.txt` is `User-agent: * / Disallow: /`. Indian Railways asks crawlers not to index the site, so this project does not scrape it. |
| **MSTC** | Overwhelmingly a *forward auction* platform (scrap, coal, customs) — selling, not procurement. Its e-procurement side is DSC/PKI-gated with no public listing. |

### State not covered (1)

| State | Portal | Why |
|---|---|---|
| Karnataka | kppp.karnataka.gov.in | Its "Search Tenders" page is **captcha-gated**. The portal reports ~5,500 live tenders, but reaching them means solving a captcha, which this project does not do. The old `eproc.karnataka.gov.in` portal is superseded and reports zero. |

A state showing zero is not an error — small states genuinely have no tenders
closing in the window some days. Check `scrape.log` to tell "zero" from "failed".

## Keeping it fresh

The dashboard **updates itself**. Two independent pieces:

### 1. Scheduled refreshes at 00:00 and 12:00

A Windows scheduled task named **`IndiaTendersRefresh`** runs
`refresh-tenders.bat` twice a day, at **00:00** and **12:00**. It survives
reboots, and `StartWhenAvailable` means a run missed because the PC was off
happens as soon as it next starts. Output is appended to
`refresh-history.log`.

`scraper.py` also takes a lock (`.scrape.lock`), so a scheduled run that fires
while another scrape is still going steps aside instead of doubling the load
on every portal. A lock left behind by a crashed run is ignored after 3 hours.

```powershell
Get-ScheduledTaskInfo -TaskName "IndiaTendersRefresh"   # when it last/next runs
Start-ScheduledTask   -TaskName "IndiaTendersRefresh"   # refresh right now
Unregister-ScheduledTask -TaskName "IndiaTendersRefresh" -Confirm:$false   # remove
```

To change the times:

```powershell
Set-ScheduledTask -TaskName "IndiaTendersRefresh" -Trigger @(
  (New-ScheduledTaskTrigger -Daily -At 06:00),
  (New-ScheduledTaskTrigger -Daily -At 18:00))
```

### The server starts itself at logon

`%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\india-tenders-dashboard.vbs`
launches `live.py --serve-only` with `pythonw` (no console window) every time
you log in, so <http://127.0.0.1:8777/dashboard.html> is simply always there.

Delete that .vbs to stop it starting automatically. To start it by hand in the
meantime, double-click `open-dashboard.bat`.

A logon *scheduled task* would need admin rights; the Startup folder does the
same job without elevation.

### 2. The open page picks it up on its own

Leave `open-dashboard.bat` (or `python live.py --serve-only`) running and the
page keeps itself current — no reload needed:

* every **30 s** it polls `status.json`, a ~100-byte file, and only downloads
  the ~33 MB `tenders.json` when `generated_at` has actually changed;
* your search text, state/department filters, sort and page **survive** a
  data refresh;
* every **60 s** it re-renders, so "time left" stays accurate and tenders that
  just closed drop out of the open-only view without any new scrape;
* the header shows *updated 4 min ago* with a green pulse, or
  *refreshing now — more still loading* while a scrape is mid-flight.

### If you'd rather not use Task Scheduler

`live.py` can do both jobs itself:

```bat
python live.py --at 00:00        :: serve + refresh nightly at midnight
python live.py --at 00:00,12:00  :: twice a day
python live.py --interval 120    :: every 2 hours instead
python live.py --quick 30        :: cheap 7-day sweep between full runs
```

Only run one refresher. If the scheduled task is registered, use
`--serve-only` so you don't get two scrapes at once.

### Why not truly real-time?

These portals publish no feed, webhook or change API, so the only way to learn
about a new tender is to re-scrape. A full sweep is a few thousand requests
across 30-odd government servers and takes 15-30 minutes; running it
continuously would hammer public infrastructure for no real gain, since
tenders appear over hours, not seconds. Twice daily is the sensible default,
`--quick` covers time-critical work, and anything already published stays
accurate to the second in your browser.

## The shared copy

Your partner has a read-only hosted copy at
<https://claude.ai/code/artifact/136f83e9-d21f-4afd-bede-3d229675e38c>
(private until shared from the page's own share menu).

It is a **self-contained snapshot** - the complete dataset embedded in one
~6.6 MB file, no server, no install. The payload ships gzipped and base64-encoded
(21 MB of JSON compresses to ~5 MB) and the page inflates it with
`DecompressionStream`; without that it would not fit the 16 MB page limit and
the shared copy would have to be trimmed to a shorter closing window. It cannot update itself, so it is republished
rather than refreshed:

1. `refresh-tenders.bat` runs `build_artifact.py` right after every scrape, so
   `share/tender-registry.html` always matches the newest data.
2. A Claude scheduled task, **`republish-tender-registry`** (00:45 daily,
   stored in `~/.claude/scheduled-tasks/`), pushes that file to the **same
   URL**, so the link already shared stays valid.

That task runs only while the Claude app is open; if it is closed at 00:45 it
fires on next launch. So the shared page is never more than a day behind, and
usually a few hours.

To rebuild it by hand:

```bat
python build_artifact.py
```

`build_artifact.py` still guards the 16 MB hosting cap: if the compressed page
ever outgrows it, the builder narrows the closing window step by step until it
fits and says so both in its output and on the page itself. At ~6.6 MB for
106,000 tenders there is a lot of headroom.

### Differences from the local dashboard

* No CSV download - the artifact sandbox blocks page-initiated downloads, so
  there is a **Copy page as TSV** button instead.
* Needs a current browser: the compressed payload is inflated with
  `DecompressionStream` (Chrome/Edge 80+, Safari 16.4+, Firefox 113+). Older
  browsers get a clear message rather than a blank page.
* Rows carry a red/amber/green stripe for time-to-close, and contract value is
  its own column formatted in crore/lakh.
* The page is pure ASCII, so it renders correctly no matter what character set
  the host declares.

## Caveats

- **Not a legal source of record.** Always confirm on the state portal before
  bidding — the tender detail page, corrigenda, and documents are authoritative.
- **Tender links need a live portal session.** GePNIC deep links carry an
  `sp=S...` token that only resolves inside a session, so a cold click lands on
  "Your session has timed out". The dashboard handles this: clicking a tender
  opens the state portal first (which issues a JSESSIONID), then sends that tab
  to the deep link ~1.6 s later. The anchor's own `href` is the portal, so
  middle-click and "open in new tab" still go somewhere useful. If a link ever
  dead-ends, search the tender ID on the portal.
- Tender value / EMD are not in the listing page, so they are not captured.
- Portals go down for maintenance. A failed portal is logged and the rest of
  the run continues.
- Coverage is ~97-99%, not 100% — see "Why it walks each portal several times".
  Treat the dashboard as a discovery tool, not an exhaustive register.
