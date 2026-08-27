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
```

(The drag-two-CSVs HTML comparison report lives in `report/`, which is local-only
and gitignored — see the untracked `CLAUDE.local.md`.)

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
- **Tests:** `python test_offline.py` (parser, synthetic), `python bucket_te.py`
  (TE + contributions self-check). (The report's `node _selftest.js` lives in the
  local-only `report/` — see `CLAUDE.local.md`.)

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

## Conventions & gotchas

- **Paths anchor to `__file__`** (`REPO_DIR`), never cwd — defaults for `data/`,
  `output/`, and the returns file resolve off the module. No shared `paths.py`
  (overkill for this size).
- **Gitignored** (regenerable or local-only, never tracked): `data/`, `output/`,
  the whole `report/` folder, `__pycache__/`, `CLAUDE.local.md`. Track code + READMEs.
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
python test_offline.py && python bucket_te.py
```

(Report build/preview/test commands are in the local-only `CLAUDE.local.md`.)
