"""
covariance.py
-------------
Equal-weighted (uniform) sample covariance of the French bucket-portfolio return
series produced by ``french_portfolios.py``.

"Equal-weighted" here refers to the *observation* weighting in the estimator:
every month in the window contributes equally (ordinary sample covariance,
ddof=1), as opposed to an exponentially-weighted / decayed estimator. It is
independent of whether the underlying French returns are value- or equal-weighted
portfolios (that choice lives upstream in which lined-up file you feed in).

Input: a lined-up returns frame (rows = months, columns = MultiIndex
(factor, bucket, tag)) — e.g. ``output/quintiles_monthly_vw_returns.csv`` — which
is exactly the "Route B" panel: the 15 quintile return histories whose covariance
drives factor tracking error.

Notes on the sample window:
- The three factors start on different dates (OP only from 1963-07), so a single
  coherent NxN matrix uses the **common** window where every series is present
  (complete-case rows). With the VW quintiles that is ~1963-07..present (>60y).
- French returns are in **percent**. Monthly covariance is therefore in percent^2;
  annualized figures multiply variance by 12 (vol by sqrt(12)).
"""
from __future__ import annotations

import os

import numpy as np
import pandas as pd

MONTHS_PER_YEAR = 12
MIN_MONTHS = 120  # estimation-window floor (10 years) unless overridden
DEFAULT_RETURNS = os.path.join("output", "quintiles_monthly_vw_returns.csv")


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #
def load_returns(path: str = DEFAULT_RETURNS) -> pd.DataFrame:
    """Read a lined-up returns CSV (3 header rows: factor/bucket/tag) back into a
    numeric monthly frame with a PeriodIndex."""
    df = pd.read_csv(path, header=[0, 1, 2], index_col=0)
    # Rebuild the monthly PeriodIndex that to_csv flattened to strings.
    try:
        df.index = pd.PeriodIndex(df.index.astype(str), freq="M")
        df.index.name = "date"
    except Exception:
        pass
    return df.apply(pd.to_numeric, errors="coerce")


# --------------------------------------------------------------------------- #
# Estimation
# --------------------------------------------------------------------------- #
def select_window(returns: pd.DataFrame, lookback_months: int | None = None,
                  complete_case: bool = True) -> pd.DataFrame:
    """Trim `returns` to the estimation window.

    complete_case=True keeps only months where *every* series is observed, so the
    resulting covariance is over one common sample (and stays PSD). lookback_months
    then keeps the trailing N of those; None uses all available history.
    """
    R = returns.copy()
    if complete_case:
        R = R.dropna(how="any")
    if lookback_months is not None:
        R = R.iloc[-int(lookback_months):]
    return R


def equal_weighted_cov(returns: pd.DataFrame, lookback_months: int | None = None,
                       min_months: int = MIN_MONTHS, annualize: bool = True,
                       complete_case: bool = True) -> pd.DataFrame:
    """Ordinary (equal per-observation weight) sample covariance matrix.

    min_months guards against silently estimating a big matrix from too little
    history (default 120 = 10 years, the floor you asked for).
    """
    R = select_window(returns, lookback_months, complete_case)
    n = len(R)
    if n < min_months:
        raise ValueError(
            f"Only {n} usable months in window (< min_months={min_months}). "
            f"Widen the window or lower min_months."
        )
    cov = R.cov()  # equal weight per month, ddof=1
    if annualize:
        cov = cov * MONTHS_PER_YEAR
    # Stash window metadata for reporting.
    cov.attrs.update(start=str(R.index[0]), end=str(R.index[-1]),
                     n_obs=n, annualized=annualize)
    return cov


def vols_from_cov(cov: pd.DataFrame) -> pd.Series:
    """Standard deviations (sqrt of diagonal), same units as cov^(1/2)."""
    return pd.Series(np.sqrt(np.diag(cov.values)), index=cov.index, name="vol")


def corr_from_cov(cov: pd.DataFrame) -> pd.DataFrame:
    d = np.sqrt(np.diag(cov.values))
    with np.errstate(divide="ignore", invalid="ignore"):
        corr = cov.values / np.outer(d, d)
    return pd.DataFrame(corr, index=cov.index, columns=cov.columns)


def diagnostics(cov: pd.DataFrame) -> dict:
    """Rank / conditioning of the matrix. The lined-up quintile panel is known to
    be near-rank-deficient (each factor's buckets are close to a partition of the
    market), so a low min-eigenvalue / high condition number is expected, not a bug."""
    vals = np.linalg.eigvalsh(cov.values)
    vmin, vmax = float(vals.min()), float(vals.max())
    return {
        "n_series": cov.shape[0],
        "rank": int(np.linalg.matrix_rank(cov.values)),
        "min_eig": vmin,
        "max_eig": vmax,
        "cond": (vmax / vmin) if vmin > 0 else float("inf"),
    }


# --------------------------------------------------------------------------- #
# Runner / report
# --------------------------------------------------------------------------- #
def run_cov(returns_path: str = DEFAULT_RETURNS, out_dir: str = "output",
            lookback_months: int | None = None, min_months: int = MIN_MONTHS,
            annualize: bool = True, verbose: bool = True):
    """Load a lined-up returns file, compute the equal-weighted sample covariance
    over the longest common window (or a trailing lookback), print a summary, and
    save the covariance + correlation matrices next to the input."""
    returns = load_returns(returns_path)
    cov = equal_weighted_cov(returns, lookback_months=lookback_months,
                             min_months=min_months, annualize=annualize)
    corr = corr_from_cov(cov)
    vols = vols_from_cov(cov)
    diag = diagnostics(cov)

    base = os.path.splitext(os.path.basename(returns_path))[0]
    tag = "ann" if annualize else "monthly"
    cov_path = os.path.join(out_dir, f"cov_{base}_ew_{tag}.csv")
    corr_path = os.path.join(out_dir, f"corr_{base}_ew.csv")
    os.makedirs(out_dir, exist_ok=True)
    cov.to_csv(cov_path)
    corr.to_csv(corr_path)

    if verbose:
        yrs = cov.attrs["n_obs"] / MONTHS_PER_YEAR
        unit = "annualized" if annualize else "monthly"
        print(f"Equal-weighted sample covariance  ({unit})")
        print(f"  window : {cov.attrs['start']} .. {cov.attrs['end']}  "
              f"({cov.attrs['n_obs']} months, {yrs:.1f} yrs)")
        print(f"  series : {diag['n_series']}   rank={diag['rank']}   "
              f"cond={diag['cond']:.1f}   min_eig={diag['min_eig']:.4g}")
        vol_unit = "%/yr" if annualize else "%/mo"
        print(f"\n  Volatilities ({vol_unit}):")
        for (fac, bkt, tg), v in vols.items():
            print(f"    {fac:30s} {bkt:>4s} {tg:<8s} {v:6.2f}")
        print(f"\n  saved: {cov_path}")
        print(f"         {corr_path}")

    return cov, corr, vols, diag


if __name__ == "__main__":
    run_cov()
