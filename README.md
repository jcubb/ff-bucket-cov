# French univariate-sort portfolios — parser & aligner

Downloads, parses, and retains Ken French's three **univariate sort** portfolio
files, and lines up the historical **terciles, quintiles, and deciles** for all
three factors on one shared monthly index.

| key    | French file                    | factor                  |
|--------|--------------------------------|-------------------------|
| `size` | `Portfolios_Formed_on_ME`      | Size (market equity)    |
| `bm`   | `Portfolios_Formed_on_BE-ME`   | Book-to-market equity   |
| `op`   | `Portfolios_Formed_on_OP`      | Operating profitability |

Source: https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html

## Status
Parser is written and **validated end-to-end** on synthetic files built to the
exact French layout (free-text preamble; stacked, titled sub-tables; monthly +
annual blocks; `-99.99`/`-999` sentinels; tercile/quintile/decile columns).
It still needs the real zips — see below.

## Get the data (either one works)
1. **Allowlist the host** so downloads work, then `python french_portfolios.py`
   (auto-downloads to `./data/`).
2. **Drop the zips in by hand** — download the three `*_CSV.zip` files and place
   them in `./data/`, then:
   ```python
   import french_portfolios as fp
   fp.run(data_dir="data", out_dir="output", allow_download=False)
   ```

## Quick start
```bash
pip install -r requirements.txt
python test_offline.py        # sanity check -> ALL TESTS PASSED (uses synthetic data)
python french_portfolios.py   # real run (needs the data in ./data/ or network)
```

## What it produces (`output/`)
- **Headline** — monthly value-weighted returns, all three factors aligned on one
  monthly index, one file per group:
  - `terciles_monthly_vw_returns.csv` / `.parquet`  (`T1..T3`)
  - `quintiles_monthly_vw_returns.csv` / `.parquet` (`Q1..Q5`)
  - `deciles_monthly_vw_returns.csv` / `.parquet`   (`D1..D10`)

  Columns are a MultiIndex `(factor, bucket, tag)`, tag = economic meaning of the
  extremes (and tercile middle): Size Small…Big, BM Growth…Value (mid Neutral),
  OP Weak…Robust (mid Neutral).
- `output/<key>/` — **everything else retained**: every sub-table (VW/EW returns
  monthly & annual, number of firms, average firm size) as CSV + parquet, plus
  the file's `_description.txt`.

## Fidelity notes
- Missing values (`-99.99`, `-999`) become `NaN`.
- Dates: `YYYYMM` -> monthly `PeriodIndex`, `YYYY` -> annual.
- Parsing is **format-driven** (detects title/header/data rows) so it survives
  header wording changes across French vintages.
- Bucket columns use the French labels; matching is whitespace/case-insensitive.

## Covariance (`covariance.py`)
Equal-weighted (uniform) sample covariance of the lined-up bucket returns — the
"Route B" 15-series panel. *Equal-weighted* here is the **observation** weighting
(every month counts the same; ordinary sample covariance, `ddof=1`), which is
independent of the value/equal-weighted **portfolio** choice made upstream.

```python
import covariance as cv
cov, corr, vols, diag = cv.run_cov()   # defaults to output/quintiles_monthly_vw_returns.csv
```
or drive the pieces directly:
```python
returns = cv.load_returns("output/quintiles_monthly_vw_returns.csv")
cov  = cv.equal_weighted_cov(returns, lookback_months=None, annualize=True)
vols = cv.vols_from_cov(cov)            # sqrt of the diagonal
corr = cv.corr_from_cov(cov)
```
- The three factors start on different dates (OP only from 1963), so
  `complete_case=True` (default) uses the common window where every series is
  present → one PSD matrix. `lookback_months=N` uses the trailing N months
  instead; `min_months` (default 120 = 10y) guards against too-short windows.
- French returns are in **percent**: monthly covariance is %², and `annualize=True`
  multiplies variance by 12 (vol by √12).
- `run_cov` also writes `output/cov_<...>_ew_<ann|monthly>.csv` and
  `output/corr_<...>_ew.csv`, and prints per-bucket vols + rank/conditioning.

## Per-vehicle tracking error (`bucket_te.py`)
Aggregates a **disaggregated** per-vehicle bucket-weight frame into the 15 factor
buckets and appends `bucket_distance` = √(xᵀ Σ x) — the factor tracking error of
each vehicle's active weights.

Input: a DataFrame indexed by `VehicleCode` with columns named
`{Factor}_{Bucket}_{Type}` (e.g. `Value_3_3`). There are 6 buckets per factor;
**bucket 1** (nulls / unmapped) is dropped and the *type* variants are **summed**,
leaving 15 columns — `Value_2..6`, `Size_2..6`, `Profit_2..6`.

```python
import bucket_te as bt
out = bt.add_bucket_distance(df)        # -> 15 weight cols + bucket_distance + 3 contributions
```
- Weights are treated as **active** (relative to a benchmark; each factor block
  ~sums to zero), so the distance *is* tracking error — no benchmark subtraction.
  Pass them as **decimals** (0.05 = 5%); with returns in percent, `bucket_distance`
  is **annualized TE in percent**.
- Also appends the **marginal (Euler) TE contribution of each factor group** —
  `value_distance, size_distance, prof_distance` — where contribution_g =
  Σ_{i∈g} x_i(Σx)_i / TE. These are additive: the three **sum to `bucket_distance`**
  (a group can go negative when it hedges overall TE). Disable with `contributions=False`.
- Σ is recomputed over a window you choose: `lookback_months=`, or `start=`/`end=`
  (default = full common history).
- Bucket direction: suffix `2→6` maps to `Q1→Q5` (bucket 2 = the low end:
  small / growth / weak). Flip a factor with `reverse_factors=("Size",)`.
- Factor tokens resolve to the covariance factors via `factor_map`
  (`Value→BM, Size→Size, Profit→OP` by default).
- `python bucket_te.py` runs a synthetic self-check.

## Pipeline order
`french_portfolios.run()` → `output/quintiles_monthly_vw_returns.csv` →
`covariance.equal_weighted_cov()` (the 15×15 Σ) → `bucket_te.add_bucket_distance()`
(per-vehicle TE). `bucket_te` recomputes Σ internally, so you can also go straight
from the returns file to per-vehicle distances.

## Files
- `french_portfolios.py` — parse/align the French files (the data layer)
- `covariance.py` — equal-weighted covariance of the lined-up bucket returns
- `bucket_te.py` — per-vehicle bucket aggregation + tracking-error distance
- `test_offline.py` — synthetic-data validation of the parser
- `requirements.txt`
