"""
bucket_te.py
------------
Aggregate a *disaggregated* per-vehicle bucket-weight frame into the 15 factor
buckets, then attach a per-vehicle ``bucket_distance`` = factor tracking error
sqrt(xᵀ Σ x), where Σ is the equal-weighted covariance of the French quintile
return histories (``covariance.py``) recomputed over a chosen window.

Input frame
-----------
Indexed by VehicleCode. Disaggregated columns are named ``{Factor}_{Bucket}_{Type}``
e.g. ``Value_3_3`` = Value factor, bucket 3, type 3. There are 6 buckets per
factor; bucket 1 is nulls / unmapped and is dropped. Multiple "types" (differing
bucketing definitions) are collapsed by summing the weights, so ``Value_3_*`` ->
one ``Value_3`` column. Result: 3 factors x 5 buckets = 15 columns.

The passed weights are already **active** (relative to a benchmark; each factor
block ~sums to zero), so the tracking error is sqrt(xᵀ Σ x) directly on them.

Units: French returns are in **percent** and Σ is annualized (%²/yr), so pass the
active weights as **decimals** (0.05 = 5%). ``bucket_distance`` then comes out as
**annualized tracking error in percent** (e.g. 0.66 = 0.66%/yr).

Assumptions (overridable — see parameters):
- Type aggregation is a **sum** (weights add).
- Within a factor, the 5 kept bucket suffixes in **ascending** order map to Q1..Q5
  (pass ``reverse_factors`` to flip a factor whose suffixes run high->low).
- Factor-token -> covariance-factor via ``factor_map`` (default below).
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

import covariance as cv

# Input factor token -> factor label used in the lined-up covariance frame.
# Aliases included so Profit / Prof / OP all resolve to the OP factor.
DEFAULT_FACTOR_MAP = {
    "Value":  "Book-to-Market (BE/ME)",
    "Size":   "Size (ME)",
    "Profit": "Operating Profitability (OP)",
    "Prof":   "Operating Profitability (OP)",
    "OP":     "Operating Profitability (OP)",
}

_COL_RE = re.compile(r"^(?P<factor>.+?)_(?P<bucket>\d+)_(?P<type>\d+)$")


# --------------------------------------------------------------------------- #
# Step 1-2: disaggregated -> 15 aggregated bucket weights
# --------------------------------------------------------------------------- #
def aggregate_buckets(df: pd.DataFrame, drop_bucket: int = 1, agg: str = "sum"):
    """Collapse ``{factor}_{bucket}_{type}`` columns to one weight per
    (factor, bucket), dropping bucket ``drop_bucket``.

    Returns (aggregated_frame, passthrough_cols):
      - aggregated_frame: columns MultiIndex (factor, bucket), same index as df.
      - passthrough_cols: columns that didn't match the pattern (left untouched).
    """
    groups: "dict[tuple[str,int], list]" = {}
    passthrough = []
    for c in df.columns:
        m = _COL_RE.match(str(c))
        if not m:
            passthrough.append(c)
            continue
        b = int(m.group("bucket"))
        if b == drop_bucket:
            continue
        groups.setdefault((m.group("factor"), b), []).append(c)

    if not groups:
        raise ValueError(
            "No columns matched '{factor}_{bucket}_{type}'. Example expected: "
            "'Value_3_3'. Got columns like: " + ", ".join(map(str, list(df.columns)[:6]))
        )

    data = {key: df[cols].sum(axis=1) if agg == "sum" else df[cols].agg(agg, axis=1)
            for key, cols in groups.items()}
    out = pd.DataFrame(data, index=df.index)
    out.columns = pd.MultiIndex.from_tuples(out.columns, names=["factor", "bucket"])
    return out.sort_index(axis=1), passthrough


# --------------------------------------------------------------------------- #
# Step 3: align to Σ and compute sqrt(xᵀ Σ x) per row
# --------------------------------------------------------------------------- #
def _align_sigma(cov: pd.DataFrame, agg_cols: pd.MultiIndex,
                 factor_map: dict, reverse_factors=()):
    """Return (Sigma_ordered ndarray, order_keys) so that Sigma_ordered[i,j] lines
    up with agg_cols[i], agg_cols[j]. Maps each (factor_token, bucket_suffix) to a
    (cov_factor, Q-code) by ranking the factor's kept buckets ascending -> Q1..Qn."""
    # Σ column position keyed by (cov_factor, bucket_code e.g. 'Q3')
    sig_pos = {}
    for pos, (fac, bkt, _tag) in enumerate(cov.columns):
        sig_pos[(fac, bkt)] = pos

    # Per input factor: sorted kept buckets -> Q1..Qn (or reversed).
    by_factor: "dict[str, list[int]]" = {}
    for fac, b in agg_cols:
        by_factor.setdefault(fac, []).append(b)
    q_of = {}  # (factor_token, bucket_int) -> 'Qk'
    for fac, buckets in by_factor.items():
        ordered = sorted(set(buckets), reverse=(fac in reverse_factors))
        for k, b in enumerate(ordered, start=1):
            q_of[(fac, b)] = f"Q{k}"

    order = []
    for fac, b in agg_cols:
        cov_fac = factor_map.get(fac)
        if cov_fac is None:
            raise KeyError(f"No factor_map entry for input factor '{fac}'. "
                           f"Known: {list(factor_map)}")
        key = (cov_fac, q_of[(fac, b)])
        if key not in sig_pos:
            raise KeyError(f"Covariance has no column {key} for input ({fac},{b}). "
                           f"Σ factors/buckets: {list(sig_pos)}")
        order.append(sig_pos[key])

    idx = np.array(order)
    return cov.values[np.ix_(idx, idx)], list(agg_cols)


def add_bucket_distance(
    df: pd.DataFrame,
    returns=None,
    *,
    lookback_months: int | None = None,
    start=None, end=None,
    annualize: bool = True,
    factor_map: dict | None = None,
    reverse_factors=(),
    drop_bucket: int = 1,
    agg: str = "sum",
    keep_disaggregated: bool = False,
    out_col: str = "bucket_distance",
    contributions: bool = True,
) -> pd.DataFrame:
    """Aggregate `df`'s disaggregated bucket columns to the 15 factor buckets and
    append `out_col` = sqrt(xᵀ Σ x) per vehicle.

    Σ is the equal-weighted sample covariance of the quintile return histories,
    recomputed over the requested window (`lookback_months`, or `start`/`end`).

    When `contributions=True` (default) also appends one column per factor group —
    `<factor>_distance` (e.g. `value_distance`, `size_distance`, `prof_distance`) —
    the group's **marginal (Euler) contribution to TE**:
        contribution_g = Σ_{i in g} x_i (Σx)_i / TE
    These are additive: the three group contributions sum exactly to `bucket_distance`
    (a group can be negative if it hedges overall tracking error).

    Returns a new frame indexed like `df`: the 15 flat `Factor_Bucket` weight
    columns + any passthrough columns + `out_col` (+ the contribution columns).
    Original disaggregated columns are dropped unless `keep_disaggregated=True`.
    """
    factor_map = DEFAULT_FACTOR_MAP if factor_map is None else factor_map

    # --- Σ over the chosen window ---
    if returns is None:
        returns = cv.load_returns()
    elif isinstance(returns, str):
        returns = cv.load_returns(returns)
    if start is not None or end is not None:
        returns = returns.loc[start:end]
    cov = cv.equal_weighted_cov(returns, lookback_months=lookback_months,
                               annualize=annualize)

    # --- aggregate + align ---
    agg, passthrough = aggregate_buckets(df, drop_bucket=drop_bucket, agg=agg)
    Sig, _ = _align_sigma(cov, agg.columns, factor_map, reverse_factors)

    X = agg.to_numpy(dtype=float)
    X = np.nan_to_num(X, nan=0.0)
    quad = np.einsum("ni,ij,nj->n", X, Sig, X)      # xᵀΣx per row
    dist = np.sqrt(np.clip(quad, 0.0, None))        # clip tiny negatives from fp

    # --- assemble output ---
    flat = agg.copy()
    flat.columns = [f"{fac}_{b}" for fac, b in agg.columns]
    out = pd.concat([df[passthrough], flat], axis=1) if passthrough else flat.copy()
    if keep_disaggregated:
        out = pd.concat([df, out[[c for c in out.columns if c not in df.columns]]], axis=1)
    out[out_col] = dist

    # --- marginal (Euler) TE contribution per factor group ---
    # component_i = x_i (Σx)_i / TE ; row-sum of all 15 = TE, so grouping by factor
    # yields an additive split of bucket_distance into value/size/prof pieces.
    if contributions:
        XS = X @ Sig                                   # (Σx) per row, n x 15
        comp = X * XS                                  # x_i (Σx)_i
        with np.errstate(divide="ignore", invalid="ignore"):
            comp_te = np.where(dist[:, None] > 0, comp / dist[:, None], 0.0)
        factors = list(agg.columns.get_level_values("factor"))
        for fac in dict.fromkeys(factors):             # unique, order-preserving
            idx = [i for i, f in enumerate(factors) if f == fac]
            key = fac.lower()
            if key.startswith("prof"):
                key = "prof"
            out[f"{key}_distance"] = comp_te[:, idx].sum(axis=1)

    out.attrs["cov_window"] = f"{cov.attrs['start']}..{cov.attrs['end']}"
    out.attrs["cov_n_obs"] = cov.attrs["n_obs"]
    out.attrs["annualized"] = annualize
    return out


# --------------------------------------------------------------------------- #
# Self-check on synthetic data
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    rng = np.random.default_rng(0)
    factors = ["Value", "Size", "Profit"]
    types = [1, 2, 3]
    cols = [f"{f}_{b}_{t}" for f in factors for b in range(1, 7) for t in types]

    df = pd.DataFrame(index=pd.Index(["VEH_A", "VEH_B", "VEH_C"], name="VehicleCode"),
                      columns=cols, dtype=float)
    df.loc["VEH_A"] = 0.0                                  # flat = zero active -> TE 0
    df.loc["VEH_B"] = rng.normal(0, 0.02, len(cols))       # random small tilts
    df.loc["VEH_C"] = 0.0
    # VEH_C: a clean +5% Value-Q5 / -5% Value-Q1 active tilt (buckets 6 vs 2, type 1)
    df.loc["VEH_C", "Value_6_1"] = 0.05
    df.loc["VEH_C", "Value_2_1"] = -0.05

    res = add_bucket_distance(df, keep_disaggregated=False)
    print(f"Cov window: {res.attrs['cov_window']}  ({res.attrs['cov_n_obs']} months, "
          f"{'annualized' if res.attrs['annualized'] else 'monthly'})\n")
    contrib_cols = ["value_distance", "size_distance", "prof_distance"]
    weight_cols = [c for c in res.columns if c not in ("bucket_distance", *contrib_cols)]
    print("Aggregated to", len(weight_cols), "weight columns:", weight_cols)
    print("\nResult (bucket_distance & group contributions = annualized TE in %):")
    print(res[["bucket_distance", *contrib_cols]].round(3))
    assert abs(res.loc["VEH_A", "bucket_distance"]) < 1e-12, "flat vehicle must be 0"
    assert res.loc["VEH_C", "bucket_distance"] > 0
    # contributions sum to total TE, and VEH_C's is essentially all Value
    csum = res[contrib_cols].sum(axis=1)
    assert np.allclose(csum, res["bucket_distance"]), "contributions must sum to TE"
    assert res.loc["VEH_C", "value_distance"] > 0.99 * res.loc["VEH_C", "bucket_distance"]
    print("\nOK: flat -> 0.00%; Value Q5/Q1 spread -> "
          f"{res.loc['VEH_C','bucket_distance']:.2f}% TE, ~all from value_distance "
          f"({res.loc['VEH_C','value_distance']:.2f}); contributions sum to TE.")
