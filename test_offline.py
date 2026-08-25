"""
Offline validation: fabricate CSVs that mimic the exact Ken French layout
(description preamble; stacked, titled sub-tables; monthly + annual blocks;
-99.99 / -999 sentinels; quintile + decile + tercile columns), zip them the way
French does, and run the real pipeline against them.
"""
import io, os, zipfile, tempfile, shutil, atexit
import numpy as np, pandas as pd
import french_portfolios as fp

# Isolate the self-test in a private temp dir so it can NEVER overwrite real
# downloaded data / results living in ./data and ./output. Cleaned up on exit.
_TMP = tempfile.mkdtemp(prefix="ff_offline_")
atexit.register(shutil.rmtree, _TMP, ignore_errors=True)
DATA = os.path.join(_TMP, "data"); OUT = os.path.join(_TMP, "output")
os.makedirs(DATA, exist_ok=True)

COLS = ("Lo 30,Med 40,Hi 30,Lo 20,Qnt 2,Qnt 3,Qnt 4,Hi 20,"
        "Lo 10,2-Dec,3-Dec,4-Dec,5-Dec,6-Dec,7-Dec,8-Dec,9-Dec,Hi 10")
NC = len(COLS.split(","))


def month_block(title, months, seed, missing_first=0):
    rng = np.random.default_rng(seed)
    lines = [f"  {title}", "," + COLS]
    for i, m in enumerate(months):
        vals = rng.normal(1.0, 5.0, NC).round(2)
        if i < missing_first:                 # emulate early missing history
            vals = np.array([-99.99] * NC)
        lines.append(str(m) + "," + ",".join(f"{v:8.2f}" for v in vals))
    return "\n".join(lines)


def year_block(title, years, seed, kind="ret"):
    rng = np.random.default_rng(seed)
    lines = [f"  {title}", "," + COLS]
    for y in years:
        if kind == "firms":
            vals = rng.integers(20, 900, NC)
            row = ",".join(f"{v:6d}" for v in vals)
        elif kind == "size":
            vals = rng.uniform(50, 90000, NC).round(2)
            row = ",".join(f"{v:10.2f}" for v in vals)
        else:
            vals = rng.normal(11, 20, NC).round(2)
            row = ",".join(f"{v:8.2f}" for v in vals)
        lines.append(str(y) + "," + row)
    return "\n".join(lines)


def make_csv(stem, seed, missing_first=0):
    months = [y * 100 + m for y in range(1926, 1929) for m in range(7 if y == 1926 else 1, 13)]
    years = list(range(1926, 1929))
    desc = (f"This file was created using the 100 CRSP database for {stem}.\n"
            f"  The portfolios are constructed at the end of June.\n"
            f"  Missing data are indicated by -99.99 or -999.\n"
            f"  Copyright 2026 Kenneth R. French\n")
    parts = [
        desc.rstrip(),
        "",
        month_block("Average Value Weighted Returns -- Monthly", months, seed + 1, missing_first),
        "",
        month_block("Average Equal Weighted Returns -- Monthly", months, seed + 2, missing_first),
        "",
        year_block("Average Value Weighted Returns -- Annual", years, seed + 3),
        "",
        year_block("Average Equal Weighted Returns -- Annual", years, seed + 4),
        "",
        year_block("Number of Firms in Portfolios", years, seed + 5, kind="firms"),
        "",
        year_block("Average Firm Size", years, seed + 6, kind="size"),
        "",
        "  Copyright 2026 Kenneth R. French",
    ]
    text = "\n".join(parts) + "\n"
    zpath = fp.zip_path(stem, DATA)
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(stem + ".CSV", text)
    return zpath


for i, (key, (stem, label)) in enumerate(fp.DATASETS.items()):
    # give BM/OP some negative-BE-style early missing months to exercise sentinels
    make_csv(stem, seed=100 * (i + 1), missing_first=3 if key != "size" else 0)

print("Synthetic zips written. Running pipeline (allow_download=False)...\n")
parsed, wides = fp.run(data_dir=DATA, out_dir=OUT, allow_download=False)
wide = wides["quintile"]

print("\n=== ASSERTIONS ===")
# 1) each dataset parsed 6 sub-tables
for ds in parsed:
    assert len(ds.tables) == 6, (ds.stem, ds.table_names())
    assert ds.description and "Kenneth R. French" in ds.description
print("OK: 6 sub-tables + description retained per dataset")

# 2) monthly VW returns table is monthly PeriodIndex, numeric, sentinels -> NaN
for ds in parsed:
    t = fp._find_monthly_vw_returns(ds)
    df = ds.tables[t]
    assert isinstance(df.index, pd.PeriodIndex) and df.index.freqstr == "M"
    assert df.select_dtypes("number").shape[1] == df.shape[1]  # all numeric
    if ds.key != "size":
        assert df.iloc[:3].isna().all().all()  # first 3 months were -99.99
print("OK: monthly index, numeric coercion, -99.99 -> NaN")

# 3) all three sort groups line up: 3 factors x (3 + 5 + 10) buckets
counts = {"tercile": 3, "quintile": 5, "decile": 10}
for group, per in counts.items():
    w = wides[group]
    assert w.shape[1] == 3 * per, (group, w.shape)
    assert set(w.columns.get_level_values("factor")) == \
        {"Size (ME)", "Book-to-Market (BE/ME)", "Operating Profitability (OP)"}
print(f"OK: terciles/quintiles/deciles aligned -> "
      f"{wides['tercile'].shape[1]}/{wides['quintile'].shape[1]}/{wides['decile'].shape[1]} series")

# economic tags at the extremes, per group
for group, (lo, hi) in {"tercile": ("T1", "T3"), "quintile": ("Q1", "Q5"),
                        "decile": ("D1", "D10")}.items():
    bm = wides[group]["Book-to-Market (BE/ME)"]
    tg = dict(zip(bm.columns.get_level_values("bucket"),
                  bm.columns.get_level_values("tag")))
    assert tg[lo] == "Growth" and tg[hi] == "Value", (group, tg)
# tercile middle bucket tag
bm_t = wides["tercile"]["Book-to-Market (BE/ME)"]
midtag = dict(zip(bm_t.columns.get_level_values("bucket"),
                  bm_t.columns.get_level_values("tag")))["T2"]
assert midtag == "Neutral", midtag
print("OK: extreme + middle buckets tagged per factor (Growth/Neutral/Value etc.)")

# 4) files retained on disk
for group in ("tercile", "quintile", "decile"):
    assert os.path.exists(os.path.join(OUT, f"{group}s_monthly_vw_returns.csv"))
    assert os.path.exists(os.path.join(OUT, f"{group}s_monthly_vw_returns.parquet"))
assert os.path.exists(os.path.join(OUT, "size", "00_average_value_weighted_returns_monthly.csv"))
print("OK: CSV + parquet retained for all sub-tables and all three lined-up groups")

print("\nLined-up terciles (head):")
with pd.option_context("display.width", 220, "display.max_columns", 30):
    print(wides["tercile"].head())
print("\nALL TESTS PASSED")
