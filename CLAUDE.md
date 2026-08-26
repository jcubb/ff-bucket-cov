# ff-bucket-cov — working notes

Bucket-level factor risk from Ken French's ready-made univariate-sort portfolios,
plus a per-vehicle tracking-error report. Public repo `jcubb/ff-bucket-cov`
(branch `main`, HTTPS remote; the repo dir *is* the project — git init in place).

## Pipeline

```
french_portfolios.run()            data layer: parse/align French files
  -> output/quintiles_monthly_vw_returns.csv   (15 series: 3 factors x Q1..Q5)
covariance.equal_weighted_cov()    15x15 equal-weighted sample Σ (annualized %)
bucket_te.add_bucket_distance()    per-vehicle TE = sqrt(xᵀΣx) + Euler contributions
report/Bucket_Report.html          drag two dated CSVs -> compare across dates
```

Downstream of the top-level tracking-error problem in the workspace `CLAUDE.md`
(the "Route B" quintile-return-history approach). This repo is the *ready-made
French portfolio* path; the Barra cross-sectional model is a separate project
(`ff-risk-model`).

## Module map

- **`french_portfolios.py`** — format-driven parser for the three French files
  (`Portfolios_Formed_on_ME` / `_BE-ME` / `_OP`). State-machine on row *shape*
  (title / header / date-led data / blank), so it survives header-wording changes.
  `-99.99`/`-999` → NaN; `YYYYMM` → monthly PeriodIndex. `run()` retains every
  sub-table and emits the lined-up tercile/quintile/decile monthly VW returns.
- **`covariance.py`** — `equal_weighted_cov()` = ordinary (equal per-observation)
  sample covariance of the lined-up returns. Common-window (complete-case) default
  → one PSD matrix over 1963-07..present (OP starts 1963). `MIN_MONTHS = 120` floor.
- **`bucket_te.py`** — `add_bucket_distance(df, ...)`: the core deliverable (below).
- **`report/`** — the self-contained HTML comparison report + its sample-data
  generator and tests. See `report/README.md`.
- **Tests:** `python test_offline.py` (parser, synthetic), `python bucket_te.py`
  (TE + contributions self-check), `node report/_selftest.js` (report data layer).

## Data & math conventions (the contract)

- **Factors / buckets:** `Value`, `Size`, `Prof` (profitability). Real data spells
  profitability **`Prof_*`** — code accepts `Prof_*` and `Profit_*`. Buckets are the
  5 quintiles; column names `{Factor}_{2..6}`. **Suffix `2→6` maps to `Q1→Q5`**
  (low→high: small/growth/weak → big/value/robust). Flip a factor with
  `reverse_factors=`.
- **factor_map:** `Value→Book-to-Market (BE/ME)`, `Size→Size (ME)`, `Prof→OP`.
- **Weights are ACTIVE** (relative to benchmark; each factor block ~sums to 0) and
  passed as **decimals** (0.05 = 5%). With French returns in percent, distances come
  out as **annualized TE in percent**.
- **`add_bucket_distance` input** is *disaggregated* `{Factor}_{Bucket}_{Type}`
  (e.g. `Value_3_3`): 6 buckets/factor, **bucket 1 dropped** (nulls/unmapped),
  **summed over Type** → 15 columns. Output adds:
  - `bucket_distance` = sqrt(xᵀΣx).
  - `value_distance, size_distance, prof_distance` — marginal (Euler) TE
    contribution per factor group, `Σ_{i∈g} x_i(Σx)_i / TE`. **Additive: the three
    sum to `bucket_distance`**; a group can be **negative** when it hedges.
- Keep the cap-weighting / centering / window coherent end-to-end (workspace theme).

## Report (`report/Bucket_Report.html`)

Single self-contained page, all client-side, **no data leaves the browser**. Drag
two dated CSVs → dates parsed from **filenames** → merge on **`VehicleCode`**. Two
candidate versions via a tab bar (we'll keep one): **V1 = 15-bucket weight heatmap**,
**V2 = 3-component heatmap** (`value_/size_/prof_distance`, redder = bigger part of
TE, blue = hedges; hover → % share, Δ-vs-prior trend, underlying buckets; adjustable
outlier-trim on the color scale). Hierarchy pivot **PMDeputy › PM › Strategy › Fund**
with **no metric roll-ups** (metrics only on fund rows; parents show counts). The
pure data layer (parse/date/merge/tree) is split from the DOM and exported as
`globalThis.__BR` for `report/_selftest.js`.

## Conventions & gotchas

- **Paths anchor to `__file__`** (`REPO_DIR`), never cwd — defaults for `data/`,
  `output/`, and the returns file resolve off the module. No shared `paths.py`
  (overkill for this size).
- **Gitignored** (regenerable, never tracked): `data/`, `output/`,
  `report/sample_portfolios_*.csv`, `__pycache__/`. Track code + READMEs + the
  assembled HTML.
- **Windows console:** `print()` with non-ASCII (Σ, Δ, ▲) raises `UnicodeEncodeError`
  under cp1252 — keep terminal prints ASCII (HTML/files are UTF-8, fine).
- **Downloads work** in-sandbox from `mba.tuck.dartmouth.edu` (no manual zips needed).
- **Git:** HTTPS remote (SSH not configured on this laptop); commits omit
  Co-Authored-By. New-repo creation needs the full-scope GCM login, not the
  fine-grained PAT.

## Dev workflow

```bash
python french_portfolios.py                 # download + build output/ (needs network)
python -c "import covariance as cv; cv.run_cov()"
python report/make_sample_report_data.py    # regenerate the two sample CSVs
python test_offline.py && python bucket_te.py && node report/_selftest.js
```

Preview the HTML report headlessly (screenshot): inject
`window.__PRELOAD=[{name,text},…]` before `</body>` and render with
`chrome --headless=new --screenshot --virtual-time-budget=2000`. The `__PRELOAD`
hook is inert in normal use.
