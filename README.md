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

## Files
- `french_portfolios.py` — the module
- `test_offline.py` — synthetic-data validation
- `requirements.txt`
