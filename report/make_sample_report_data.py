"""
make_sample_report_data.py
--------------------------
Fabricate two dated portfolio CSVs to develop and demo the bucket comparison
report against. Each row is a portfolio (vehicle); each file is one date.

Schema written (real files will carry MORE columns — the report must ignore any
it doesn't recognise, so we deliberately intersperse several junk columns here):

    VehicleCode, FundName, PMName, PMDeputy, StrategyName,
    <15 active bucket weights: Value_2..6, Size_2..6, Profit_2..6>,
    bucket_distance,
    + ignored extras: AsOfDate, Currency, AUM, Region, Benchmark,
      InceptionDate, RiskComment

The 15 weights are ACTIVE (relative) and sum to ~0 within each factor block.
bucket_distance is computed from our own equal-weighted Σ (covariance.py) via the
same alignment bucket_te uses, so the sample is internally consistent with the
rest of the repo.

Planted scenarios (so the report's "rising distance" view has something to show):
  * one PM's whole book (K. Adler) clearly RISES from date 1 -> date 2
  * one PM's book (D. Verhoeven) clearly FALLS
  * a few scattered risers/fallers
  * ENTRIES (funds only on date 2) and EXITS (only on date 1)

Run:  python report/make_sample_report_data.py   (from the repo root)
Writes: report/sample_portfolios_YYYYMMDD.csv  (x2)
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

# report/ lives under the repo root; put the repo root on the path so the
# sibling modules import regardless of where this dev script is launched from.
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

import covariance as cv          # noqa: E402
import bucket_te as bt           # noqa: E402
import french_portfolios as fp   # noqa: E402

OUT_DIR = Path(__file__).resolve().parent          # write CSVs into report/
FACTORS = ["Value", "Size", "Prof"]   # real data names profitability buckets "Prof_*"
BUCKETS = [2, 3, 4, 5, 6]
WEIGHT_COLS = [f"{f}_{b}" for f in FACTORS for b in BUCKETS]

DATE1, DATE2 = "20260331", "20260630"
ISO = {"20260331": "2026-03-31", "20260630": "2026-06-30"}

SEED = 20260825


# --------------------------------------------------------------------------- #
# Covariance (for a realistic, self-consistent bucket_distance)
# --------------------------------------------------------------------------- #
def ordered_sigma() -> np.ndarray:
    """15x15 annualized Σ aligned to WEIGHT_COLS order (Value_2..Profit_6)."""
    if not cv.DEFAULT_RETURNS.exists():
        print("Quintile returns not found; running french_portfolios.run() first...")
        fp.run(verbose=False)
    cov = cv.equal_weighted_cov(cv.load_returns(), annualize=True)
    agg_cols = pd.MultiIndex.from_tuples(
        [(f, b) for f in FACTORS for b in BUCKETS], names=["factor", "bucket"])
    Sig, _ = bt._align_sigma(cov, agg_cols, bt.DEFAULT_FACTOR_MAP)
    return Sig


def distance(weights_row: np.ndarray, Sig: np.ndarray) -> float:
    q = float(weights_row @ Sig @ weights_row)
    return float(np.sqrt(max(q, 0.0)))


# --------------------------------------------------------------------------- #
# Org hierarchy: PMDeputy -> PMName -> StrategyName -> funds
# --------------------------------------------------------------------------- #
DEPUTY_PMS = {
    "M. Osei":        ["J. Rivera", "K. Adler", "S. Baptiste"],
    "L. Nakamura":    ["P. Okonkwo", "D. Verhoeven"],
    "R. Castellanos": ["A. Fenwick", "T. Gronnegaard", "H. Villanueva"],
}
STRATEGIES = ["Global Value", "US Quality", "EM Small Cap", "Developed Momentum",
              "Global Min Vol", "US SMID Value", "Intl Profitability", "Core Equity"]
FUND_SUFFIX = ["Alpha", "Beta", "Gamma", "Delta", "Sigma", "Omega"]
CCY = ["USD", "USD", "USD", "EUR", "GBP"]
REGION = ["Global", "US", "EM", "Developed", "Intl"]


def build_universe(rng):
    """Return list of fund dicts (org identity only; weights added per date)."""
    funds, vh = [], 1
    for deputy, pms in DEPUTY_PMS.items():
        for pm in pms:
            n_strats = rng.integers(1, 3)  # 1-2 strategies per PM
            for strat in rng.choice(STRATEGIES, size=n_strats, replace=False):
                n_funds = int(rng.integers(2, 5))  # 2-4 funds per strategy
                for k in range(n_funds):
                    funds.append({
                        "VehicleCode": f"VH{vh:04d}",
                        "FundName": f"{strat} {FUND_SUFFIX[k % len(FUND_SUFFIX)]}",
                        "PMName": pm,
                        "PMDeputy": deputy,
                        "StrategyName": strat,
                        "Currency": CCY[vh % len(CCY)],
                        "Region": REGION[vh % len(REGION)],
                        "AUM": round(float(rng.lognormal(mean=6.0, sigma=1.0)) * 1e6, 0),
                    })
                    vh += 1
    return funds


def block_active(rng, activeness):
    """5 active weights for one factor block, demeaned so they sum to ~0."""
    v = rng.normal(0.0, activeness, size=5)
    return v - v.mean()


def weights_for(rng, activeness):
    return np.concatenate([block_active(rng, activeness) for _ in FACTORS])


# --------------------------------------------------------------------------- #
# Build both dated snapshots
# --------------------------------------------------------------------------- #
def build():
    rng = np.random.default_rng(SEED)
    Sig = ordered_sigma()
    funds = build_universe(rng)

    # scenario tags
    RISING_PM, FALLING_PM = "K. Adler", "D. Verhoeven"
    codes = [f["VehicleCode"] for f in funds]
    exits = set(rng.choice(codes, size=2, replace=False))          # only on date 1

    rows1, rows2 = [], []
    for f in funds:
        a1 = float(rng.uniform(0.02, 0.10))          # date-1 activeness
        if f["PMName"] == RISING_PM:
            mult = float(rng.uniform(1.7, 2.5))
        elif f["PMName"] == FALLING_PM:
            mult = float(rng.uniform(0.35, 0.65))
        else:
            mult = float(rng.uniform(0.85, 1.25))    # scattered drift
        a2 = a1 * mult

        w1 = weights_for(rng, a1)
        # date-2 weights: partly persistent, partly fresh at the new activeness
        w2 = 0.6 * w1 + 0.8 * weights_for(rng, a2)
        # re-demean each block so date-2 still sums to ~0 per factor
        w2 = np.concatenate([blk - blk.mean() for blk in np.split(w2, len(FACTORS))])

        base = {k: f[k] for k in ("VehicleCode", "FundName", "PMName", "PMDeputy",
                                  "StrategyName", "Currency", "Region", "AUM")}
        # every universe fund is present on date 1
        r1 = dict(base); r1.update(zip(WEIGHT_COLS, np.round(w1, 4)))
        r1["bucket_distance"] = round(distance(w1, Sig), 4)
        rows1.append(r1)
        # EXITS: dropped by date 2 (present date 1, absent date 2)
        if f["VehicleCode"] not in exits:
            r2 = dict(base); r2.update(zip(WEIGHT_COLS, np.round(w2, 4)))
            r2["bucket_distance"] = round(distance(w2, Sig), 4)
            rows2.append(r2)

    # ENTRIES: three brand-new funds that appear only on date 2
    for j in range(3):
        a = float(rng.uniform(0.05, 0.14))
        w = weights_for(rng, a)
        rows2.append({
            "VehicleCode": f"VH9{j:03d}", "FundName": f"New Opportunities {FUND_SUFFIX[j]}",
            "PMName": "S. Baptiste", "PMDeputy": "M. Osei", "StrategyName": "Core Equity",
            "Currency": "USD", "Region": "Global",
            "AUM": round(float(rng.lognormal(6.0, 1.0)) * 1e6, 0),
            **dict(zip(WEIGHT_COLS, np.round(w, 4))),
            "bucket_distance": round(distance(w, Sig), 4),
        })

    return _frame(rows1, DATE1), _frame(rows2, DATE2)


def _frame(rows, date_key):
    df = pd.DataFrame(rows)
    df["AsOfDate"] = ISO[date_key]
    df["Benchmark"] = "MSCI ACWI"
    df["InceptionDate"] = "2018-01-01"
    df["RiskComment"] = ""
    # messy, interspersed column order (key cols not contiguous; junk mixed in)
    order = (["VehicleCode", "AsOfDate", "FundName", "StrategyName", "PMName",
              "PMDeputy", "Currency", "AUM", "Region", "Benchmark"]
             + WEIGHT_COLS + ["bucket_distance", "InceptionDate", "RiskComment"])
    return df[order]


def main():
    df1, df2 = build()
    p1 = OUT_DIR / f"sample_portfolios_{DATE1}.csv"
    p2 = OUT_DIR / f"sample_portfolios_{DATE2}.csv"
    df1.to_csv(p1, index=False)
    df2.to_csv(p2, index=False)

    # ---- report ----
    s1 = df1.set_index("VehicleCode")["bucket_distance"]
    s2 = df2.set_index("VehicleCode")["bucket_distance"]
    common = s1.index.intersection(s2.index)
    delta = (s2[common] - s1[common])
    print(f"Wrote {p1.name}: {len(df1)} funds")
    print(f"Wrote {p2.name}: {len(df2)} funds")
    print(f"  matched={len(common)}  entries={len(s2.index.difference(s1.index))}"
          f"  exits={len(s1.index.difference(s2.index))}")
    print(f"  bucket_distance date1 range: {s1.min():.2f} .. {s1.max():.2f} "
          f"(median {s1.median():.2f})")
    print(f"  bucket_distance date2 range: {s2.min():.2f} .. {s2.max():.2f} "
          f"(median {s2.median():.2f})")
    print(f"  rising (delta>0): {(delta > 0).sum()} / {len(common)}   "
          f"biggest riser delta={delta.max():.2f}  biggest faller delta={delta.min():.2f}")

    # sanity: each factor block sums ~0 (tolerance reflects 4-decimal rounding
    # of 5 weights in the written CSV, ~1e-4)
    for f in FACTORS:
        blk = df2[[f"{f}_{b}" for b in BUCKETS]].sum(axis=1).abs().max()
        assert blk < 1e-3, (f, blk)
    print("  OK: active blocks sum to ~0 (within rounding); distances >= 0")


if __name__ == "__main__":
    main()
