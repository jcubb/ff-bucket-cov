# Bucket comparison report

A single self-contained HTML page that compares two dated portfolio snapshots on
their active factor-bucket weights and `bucket_distance` (the per-vehicle tracking
error from `bucket_te.py`). All processing is client-side — **no data leaves the
browser**.

## Use
1. Open **`Bucket_Report.html`** in any modern browser.
2. Drag in the **two** CSV files (one per date). Dates are read from the filenames
   (`YYYYMMDD`, `YYYY-MM-DD`, or `MMDDYYYY`), auto-ordered prior → current, with a
   **Swap** button if needed.

## Expected columns
Per row (one portfolio/vehicle):
`VehicleCode, FundName, PMName, PMDeputy, StrategyName`, the 15 active weights
`Value_2..Value_6, Size_2..Size_6, Prof_2..Prof_6` (the profit prefix may also be
spelled `Profit_*`), and `bucket_distance`. Optionally the three factor-group
contribution columns `value_distance, size_distance, prof_distance` (from
`bucket_te.add_bucket_distance`) — present them and the **Version 2** page unlocks.
**Any other columns are ignored** (detected and listed on load). The weight, distance,
and component columns are auto-detected (matching is case-insensitive).

## What it shows
- **Summary** — matched / entries / exits and counts of rising vs falling distance.
- **Where distance is rising** — funds ranked by Δ`bucket_distance`, threshold slider.
- **Hierarchy** — a pivot **PMDeputy › PMName › StrategyName › Fund**. All metrics
  live on the **fund row** (current distance, Δ distance, and a heatmap); parent rows
  are grouping headers with a fund count and an *n rising* badge (counts only — **no
  metric roll-ups**). A flat sortable view is available too. Two candidate versions
  via the tab bar (we'll keep one):
  - **Version 1 — 15 buckets:** a diverging heatmap of the fund's 15 current active
    weights (grouped Value / Size / Prof), hover a cell for its bucket + weight.
  - **Version 2 — 3 components:** a diverging heatmap of the three factor-group TE
    contributions (`value_/size_/prof_distance`); hover a component to see that
    factor's five underlying bucket weights. (Needs the component columns.)
- **Bucket posture** — click a fund to see its 15 active weights as a diverging bar
  chart (filled = current, marker = prior; up = overweight, down = underweight).

Merge is on `VehicleCode`; funds only on the current date are **entries** (badged
"new"), only on the prior date are **exits**.

## Files
- `Bucket_Report.html` — the report (open this).
- `make_sample_report_data.py` — fabricates two dated sample CSVs to demo/develop
  against (org hierarchy, active weights, `bucket_distance` from the repo's own Σ,
  planted risers/fallers/entries/exits). Run from the repo root:
  `python report/make_sample_report_data.py`.
- `_selftest.js` — Node unit tests for the page's pure data layer (CSV parse,
  filename-date detection, merge, tree). Run: `node report/_selftest.js`.

## Dev notes
- The pure data layer (parse / date / merge / tree) is separated from the DOM and
  exported as `globalThis.__BR` so `_selftest.js` can test it headlessly.
- The page reads an optional `window.__PRELOAD = [{name, text}, …]` to auto-load
  data without drag-drop — used only for automated previews/screenshots; undefined
  (and inert) in normal use.
