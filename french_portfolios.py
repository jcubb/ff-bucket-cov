"""
french_portfolios.py
--------------------
Download, parse, and retain the Ken French *univariate sort* portfolio files for
the three factors:

    size  ->  Portfolios_Formed_on_ME      (market equity / size)
    bm    ->  Portfolios_Formed_on_BE-ME   (book-to-market equity)
    op    ->  Portfolios_Formed_on_OP      (operating profitability)

Source (official):
    https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html

Each French CSV stacks *many* sub-tables vertically inside one file (value- and
equal-weighted returns, monthly and annual, number of firms, average firm size,
etc.), preceded by a free-text description. This module is FORMAT-DRIVEN: it does
not hard-code column names, so it survives header changes across vintages. It
returns every sub-table as a tidy DataFrame with a proper period index, retains
the raw description text, and produces the headline deliverable: the historical
quintiles for all three factors lined up on a shared monthly index.

Missing values in French files are coded -99.99 (returns) and -999 (counts/sizes)
and are converted to NaN.
"""
from __future__ import annotations

import csv
import io
import os
import re
import zipfile
from collections import OrderedDict
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

BASE_URL = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/"

# short key -> (file stem on the French FTP, human label)
DATASETS = OrderedDict([
    ("size", ("Portfolios_Formed_on_ME",    "Size (ME)")),
    ("bm",   ("Portfolios_Formed_on_BE-ME", "Book-to-Market (BE/ME)")),
    ("op",   ("Portfolios_Formed_on_OP",    "Operating Profitability (OP)")),
])

# French univariate sort groups, each as the exact column labels in Lo->Hi order.
# Terciles are the 30/40/30 split; quintiles the 20s; deciles the 10s.
SORT_GROUPS = OrderedDict([
    ("tercile",  ["Lo 30", "Med 40", "Hi 30"]),
    ("quintile", ["Lo 20", "Qnt 2", "Qnt 3", "Qnt 4", "Hi 20"]),
    ("decile",   ["Lo 10", "2-Dec", "3-Dec", "4-Dec", "5-Dec",
                  "6-Dec", "7-Dec", "8-Dec", "9-Dec", "Hi 10"]),
])
_BUCKET_PREFIX = {"tercile": "T", "quintile": "Q", "decile": "D"}

# Per-factor economic meaning of the extreme (Lo, Hi) buckets, plus the middle
# bucket label used for the tercile 'Med 40'.
_EXTREME_TAGS = {
    "size": ("Small", "Big"),
    "bm":   ("Growth", "Value"),
    "op":   ("Weak", "Robust"),
}
_MID_TAG = {"size": "Mid", "bm": "Neutral", "op": "Neutral"}

MISSING_SENTINELS = (-99.99, -999.0, -99.9)


@dataclass
class FrenchDataset:
    """Everything parsed out of one French portfolio file."""
    key: str
    stem: str
    label: str
    description: str = ""
    tables: "OrderedDict[str, pd.DataFrame]" = field(default_factory=OrderedDict)

    def table_names(self):
        return list(self.tables.keys())


# --------------------------------------------------------------------------- #
# Acquisition
# --------------------------------------------------------------------------- #
def zip_path(stem: str, data_dir: str) -> str:
    return os.path.join(data_dir, f"{stem}_CSV.zip")


def fetch_zip_bytes(stem: str, data_dir: str, base_url: str = BASE_URL,
                    allow_download: bool = True) -> bytes:
    """
    Return the raw bytes of <stem>_CSV.zip.

    Resolution order:
      1. Local file in data_dir (if present) -- lets you drop the zips in by hand.
      2. HTTP download from base_url (only if allow_download and network permits).

    Raises FileNotFoundError with actionable guidance if neither works.
    """
    local = zip_path(stem, data_dir)
    if os.path.exists(local):
        with open(local, "rb") as fh:
            return fh.read()

    if allow_download:
        import requests  # local import so the parser works with no network stack
        url = f"{base_url}{stem}_CSV.zip"
        resp = requests.get(url, timeout=60)
        resp.raise_for_status()
        # Guard against proxy deny pages masquerading as 200/403 text.
        if not resp.content[:2] == b"PK":
            raise RuntimeError(
                f"{url} did not return a zip (got {len(resp.content)} bytes, "
                f"starts with {resp.content[:40]!r}). If you see a 'host not in "
                f"allowlist' message, add mba.tuck.dartmouth.edu to the sandbox "
                f"network egress settings, or place {stem}_CSV.zip in {data_dir}."
            )
        os.makedirs(data_dir, exist_ok=True)
        with open(local, "wb") as fh:
            fh.write(resp.content)
        return resp.content

    raise FileNotFoundError(
        f"{local} not found and downloads are disabled. Either enable network "
        f"access to mba.tuck.dartmouth.edu or drop {stem}_CSV.zip into {data_dir}."
    )


def csv_text_from_zip(zip_bytes: bytes) -> str:
    """Extract the single .CSV member from a French zip as decoded text."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        members = [n for n in zf.namelist() if n.lower().endswith(".csv")]
        if not members:
            raise ValueError(f"No CSV inside zip; members were {zf.namelist()}")
        raw = zf.read(members[0])
    # French files are latin-1 / ascii; be forgiving.
    return raw.decode("latin-1")


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #
_DATE_RE = re.compile(r"^\s*\d{4,6}\s*$")


def _split(line: str):
    return next(csv.reader([line]))


def _is_data_row(fields) -> bool:
    return bool(fields) and bool(_DATE_RE.match(fields[0]))


def _is_header_row(fields) -> bool:
    # Header rows in French files begin with an empty first cell followed by
    # column labels, e.g. ",Lo 30,Med 40,...". They are not date rows.
    if not fields:
        return False
    first_empty = fields[0].strip() == ""
    labels = [f for f in fields[1:] if f.strip() != ""]
    return first_empty and len(labels) >= 1 and not _is_data_row(fields)


def _finalize_block(title, header, rows):
    """Turn accumulated header+rows into a tidy, numeric, period-indexed frame."""
    if header is None or not rows:
        return None

    ncol = len(header)
    norm = []
    for r in rows:
        r = [c.strip() for c in r]
        if len(r) < ncol:
            r = r + [""] * (ncol - len(r))
        elif len(r) > ncol:
            r = r[:ncol]
        norm.append(r)

    df = pd.DataFrame(norm, columns=header)
    date_col = df.columns[0]
    dates = df[date_col].str.strip()

    # numeric body
    body = df.drop(columns=[date_col]).apply(pd.to_numeric, errors="coerce")
    for s in MISSING_SENTINELS:
        body = body.mask(np.isclose(body.values, s))

    # index: 6-digit -> monthly, 4-digit -> annual
    lens = dates.str.len().dropna().unique()
    if set(lens) <= {6}:
        idx = pd.PeriodIndex(dates.tolist(), freq="M")
    elif set(lens) <= {4}:
        idx = pd.PeriodIndex(dates.tolist(), freq="Y")
    else:  # mixed / unexpected -> keep raw strings
        idx = pd.Index(dates.tolist(), name="date")
    body.index = idx
    body.index.name = "date"
    body.columns = [c.strip() for c in body.columns]
    return body


def parse_french_csv(text: str):
    """
    Parse a full French portfolio CSV.

    Returns (description:str, tables:OrderedDict[title -> DataFrame]).
    Blocks with duplicate titles are disambiguated with a numeric suffix.
    """
    lines = text.splitlines()
    desc_lines = []
    tables = OrderedDict()

    seen_first = False
    pending_title = None
    title = None
    header = None
    rows = []
    auto = 0

    def emit():
        nonlocal auto
        frame = _finalize_block(title, header, rows)
        if frame is None:
            return
        nonlocal_title = title if title else f"Table {auto + 1}"
        auto += 1
        name = nonlocal_title
        i = 2
        while name in tables:
            name = f"{nonlocal_title} ({i})"
            i += 1
        tables[name] = frame

    for raw in lines:
        line = raw.rstrip("\n").rstrip("\r")
        stripped = line.strip()
        fields = _split(line) if line else [""]

        is_blank = stripped == ""
        is_header = _is_header_row(fields)
        is_data = _is_data_row(fields)

        if not seen_first:
            if is_header:
                seen_first = True
                header = [f.strip() for f in fields]
                header[0] = "date"
                title, pending_title = pending_title, None
                rows = []
            elif is_blank:
                continue
            else:
                desc_lines.append(line)
                pending_title = stripped.rstrip(", ").strip()
            continue

        if is_blank:
            emit()
            header, rows, title = None, [], None
            continue
        if is_header:
            emit()
            header = [f.strip() for f in fields]
            header[0] = "date"
            title, pending_title = pending_title, None
            rows = []
            continue
        if is_data:
            rows.append(fields)
            continue
        # caption / title line
        emit()
        header, rows, title = None, [], None
        pending_title = stripped.rstrip(", ").strip()

    emit()
    description = "\n".join(desc_lines).strip()
    return description, tables


def load_dataset(key: str, data_dir: str, base_url: str = BASE_URL,
                 allow_download: bool = True) -> FrenchDataset:
    stem, label = DATASETS[key]
    zb = fetch_zip_bytes(stem, data_dir, base_url, allow_download)
    text = csv_text_from_zip(zb)
    desc, tables = parse_french_csv(text)
    return FrenchDataset(key=key, stem=stem, label=label,
                         description=desc, tables=tables)


# --------------------------------------------------------------------------- #
# Quintile alignment (the headline deliverable)
# --------------------------------------------------------------------------- #
def _find_monthly_vw_returns(ds: FrenchDataset) -> str:
    """Pick the 'Average Value Weighted Returns -- Monthly' table by title,
    falling back to the first monthly table if titles are unusual."""
    for name in ds.tables:
        low = name.lower()
        if "value" in low and "weight" in low and "monthly" in low:
            return name
    # fallback: first table whose index is monthly
    for name, df in ds.tables.items():
        if isinstance(df.index, pd.PeriodIndex) and df.index.freqstr == "M":
            return name
    raise KeyError(f"No monthly value-weighted returns table found in {ds.stem}")


def _match_columns(columns, wanted):
    """Return the original column names matching `wanted` (Lo->Hi order), or None.
    Matching is case- and whitespace-insensitive so 'Qnt 2'/'Qnt2' both hit."""
    def norm(s):
        return re.sub(r"\s+", "", s).strip().lower()
    lookup = {norm(c): c for c in columns}
    picked = [lookup.get(norm(w)) for w in wanted]
    return picked if all(p is not None for p in picked) else None


def _bucket_meta(key: str, group: str):
    """Return (french_labels, bucket_codes, tags) for one factor and sort group."""
    labels = SORT_GROUPS[group]
    n = len(labels)
    prefix = _BUCKET_PREFIX[group]
    lo_tag, hi_tag = _EXTREME_TAGS.get(key, ("Lo", "Hi"))
    codes, tags = [], []
    for i in range(n):
        codes.append(f"{prefix}{i + 1}")
        if i == 0:
            tags.append(lo_tag)
        elif i == n - 1:
            tags.append(hi_tag)
        elif group == "tercile":
            tags.append(_MID_TAG.get(key, "Mid"))
        else:
            tags.append(codes[-1])
    return labels, codes, tags


def factor_portfolios(ds: FrenchDataset, group: str) -> pd.DataFrame:
    """Monthly value-weighted returns for one factor's tercile/quintile/decile
    portfolios. Columns: MultiIndex (bucket, tag, french_label) in Lo->Hi order."""
    tbl = _find_monthly_vw_returns(ds)
    df = ds.tables[tbl]
    labels, codes, tags = _bucket_meta(ds.key, group)
    cols = _match_columns(df.columns, labels)
    if cols is None:
        raise KeyError(
            f"Could not locate the {group} columns {labels} in {ds.stem} / "
            f"'{tbl}'. Columns present: {list(df.columns)}"
        )
    out = df[cols].copy()
    out.columns = pd.MultiIndex.from_tuples(
        [(codes[i], tags[i], cols[i]) for i in range(len(cols))],
        names=["bucket", "tag", "french_label"],
    )
    return out


def lined_up(datasets, group: str) -> pd.DataFrame:
    """Combine the three factors' returns for one sort group into a wide monthly
    frame. Columns: MultiIndex (factor, bucket, tag); rows aligned on month."""
    pieces = {}
    for ds in datasets:
        q = factor_portfolios(ds, group)
        q.columns = pd.MultiIndex.from_tuples(
            [(b, tag) for (b, tag, _lbl) in q.columns],
            names=["bucket", "tag"],
        )
        pieces[ds.label] = q
    wide = pd.concat(pieces, axis=1)
    wide.columns.names = ["factor", "bucket", "tag"]
    return wide.sort_index()


# Backwards-compatible convenience wrappers.
def factor_quintiles(ds: FrenchDataset) -> pd.DataFrame:
    return factor_portfolios(ds, "quintile")


def lined_up_quintiles(datasets) -> pd.DataFrame:
    return lined_up(datasets, "quintile")


# --------------------------------------------------------------------------- #
# Orchestration + retention
# --------------------------------------------------------------------------- #
def run(data_dir="data", out_dir="output", base_url=BASE_URL, allow_download=True,
        verbose=True):
    os.makedirs(out_dir, exist_ok=True)
    parsed = []
    for key in DATASETS:
        ds = load_dataset(key, data_dir, base_url, allow_download)
        parsed.append(ds)
        if verbose:
            print(f"[{ds.key}] {ds.label}: {len(ds.tables)} tables")
            for n, d in ds.tables.items():
                span = f"{d.index.min()}..{d.index.max()}" if len(d) else "empty"
                print(f"    - {n:52s} {d.shape[0]:>5}x{d.shape[1]:<3} {span}")

    # Retain EVERYTHING: every sub-table -> CSV + parquet, description -> txt.
    for ds in parsed:
        d = os.path.join(out_dir, ds.key)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "_description.txt"), "w") as fh:
            fh.write(ds.description)
        for i, (name, frame) in enumerate(ds.tables.items()):
            safe = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_").lower()
            stem = f"{i:02d}_{safe}"
            frame.to_csv(os.path.join(d, stem + ".csv"))
            try:
                frame.to_parquet(os.path.join(d, stem + ".parquet"))
            except Exception:
                pass

    # Headline deliverables: lined-up terciles, quintiles, and deciles
    # (monthly value-weighted returns, all three factors aligned on month).
    wides = {}
    for group in SORT_GROUPS:
        wide = lined_up(parsed, group)
        wides[group] = wide
        stem = f"{group}s_monthly_vw_returns"
        wide.to_csv(os.path.join(out_dir, stem + ".csv"))
        try:
            wide.to_parquet(os.path.join(out_dir, stem + ".parquet"))
        except Exception:
            pass
        if verbose:
            print(f"\nLined-up {group}s: {wide.shape[0]} months x {wide.shape[1]} "
                  f"series  ({wide.index.min()} .. {wide.index.max()})")

    return parsed, wides


if __name__ == "__main__":
    run()
