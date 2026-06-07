# =============================================================================
# 01_data_pipeline.py
# QSS 20 Final Project — AI Labor Displacement & Corporate Tax Base
# Dartmouth College | Spring 2026
# =============================================================================
# PURPOSE:
#   Reads two source files, cleans and standardises them, and merges them into
#   a single analysis-ready CSV.
#
#   Source 1 : IRS Statistics of Income — Table 1 (Tax Year 2022)
#              data/Table_1.xlsx
#   Source 2 : Digital Planet AI-Jobs Data Booklet (March 2026)
#              data/Digital-Planet-AI-jobs-March-2026__2_.xlsx
#
#   Output   : data/02_merged_clean.csv
#
# ─────────────────────────────────────────────────────────────────────────────
# METHODOLOGY NOTE — IRS_Operational_Base proxy
# ─────────────────────────────────────────────────────────────────────────────
#   The uploaded Table_1.xlsx is an abbreviated 16-column extract of the full
#   IRS SOI Corporation Complete Report.  "Compensation of officers" and
#   "Salaries and wages" are absent from this extract, so a direct payroll-tax
#   base cannot be constructed.
#
#   Instead, the pipeline derives IRS_Operational_Base as:
#
#       IRS_Operational_Base = Total Receipts (All returns)
#                              − IRS_Net_Income_Less_Deficit
#
#   Algebraically this equals Total Deductions + Deficit, i.e. all revenue
#   consumed by operations — a reliable, fully-populated scale proxy for the
#   size of each sector's cost structure.  It can be cited in your presentation
#   as "IRS-reported total operational costs, Tax Year 2022 ($ thousands)".
#
#   RESEARCH CAVEAT : This proxy captures gross operating
#   cost scale rather than the labour-cost share specifically.  Sectors with
#   high capital intensity (e.g. Utilities, Manufacturing) will have a larger
#   Operational Base relative to payroll than labour-intensive sectors
#   (e.g. Professional Services, Health Care).  Flag this where relevant.
# =============================================================================

import os
import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# 0.  CONFIGURATION  — edit paths / column names here; never touch the logic
# ---------------------------------------------------------------------------
IRS_PATH   = "data/Table_1.xlsx"
IRS_SHEET  = "CRTAB01"

DP_PATH    = "data/Digital-Planet-AI-jobs-March-2026__2_.xlsx"
DP_SHEET   = "Effects of AI-Industry Level"

OUTPUT_PATH = "data/02_merged_clean.csv"

# IRS Table 1 header: "money amounts are in thousands of dollars".
# All raw IRS numeric cells must be multiplied by this factor so that the CSV
# output is in actual dollars.  Downstream code (e.g. the Monte Carlo notebook)
# divides by 1e12 to display trillions; without this scaling it would be
# dividing $-thousands by 1e12, producing values 1,000× too small.
IRS_UNIT_SCALE = 1_000


# ---------------------------------------------------------------------------
# 1.  HELPER FUNCTIONS
# ---------------------------------------------------------------------------

def flatten_multiindex_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Flatten a two-level MultiIndex header produced by pd.read_excel(header=[0,1]).

    Naming rules for each (top, bottom) pair:
      • Both named             → "<top> - <bottom>"
      • Top is 'Unnamed…'     → bottom label only
      • Bottom is 'Unnamed…'  → top label only
      • Both 'Unnamed…'       → "col_<position>"   (rare fallback)

    All labels are whitespace-normalised (internal newlines/spaces collapsed
    to a single space; leading/trailing whitespace stripped).
    """
    def _clean(s: str) -> str:
        return " ".join(str(s).strip().split())

    new_cols = []
    for pos, (top, bot) in enumerate(df.columns):
        t = _clean(top)
        b = _clean(bot)
        top_unnamed = t.lower().startswith("unnamed")
        bot_unnamed = b.lower().startswith("unnamed")

        if top_unnamed and bot_unnamed:
            new_cols.append(f"col_{pos}")
        elif top_unnamed:
            new_cols.append(b)
        elif bot_unnamed:
            new_cols.append(t)
        else:
            new_cols.append(f"{t} - {b}")

    df.columns = new_cols
    return df


def find_col(df: pd.DataFrame, keyword: str) -> str:
    """
    Return a column name from *df* that matches *keyword* (case-insensitive).

    Priority:
      1. Exact match                         (e.g. keyword="Industry")
      2. First column whose name contains keyword as a substring
    Raises KeyError if nothing matches.
    """
    keyword_lo = keyword.lower()
    exact = [c for c in df.columns if c.lower() == keyword_lo]
    if exact:
        return exact[0]
    partial = [c for c in df.columns if keyword_lo in c.lower()]
    if partial:
        return partial[0]
    raise KeyError(f"No column found matching '{keyword}'")


def standardise_industry_name(s) -> str:
    """
    Canonical industry name for cross-source matching:
      1. Strip leading/trailing whitespace
      2. Collapse internal whitespace (including newlines) to one space
      3. Apply title-case for uniform capitalisation
    """
    if not isinstance(s, str):
        return s
    return " ".join(s.strip().split()).title()


def coerce_numeric(series: pd.Series) -> pd.Series:
    """
    Convert an IRS dollar column to float64.
    The IRS uses sentinel 'd' where data were suppressed; those become NaN.
    """
    return pd.to_numeric(series.replace("d", np.nan), errors="coerce")


# ---------------------------------------------------------------------------
# Name-mapping applied AFTER title-casing both sides.
# Three IRS sector names diverge substantially from the Digital Planet labels.
# All other sectors align perfectly once whitespace/capitalisation is normalised.
# ---------------------------------------------------------------------------
IRS_TO_DP_CANONICAL: dict[str, str] = {
    # IRS shortens the sector; DP uses the full NAICS super-sector label.
    "Mining":
        "Mining, Quarrying, And Oil And Gas Extraction",

    # IRS uses legal-entity framing; DP uses the NAICS functional framing.
    "Management Of Companies (Holding Companies)":
        "Management Of Companies And Enterprises",

    # IRS omits the parenthetical present in DP.
    "Other Services":
        "Other Services (Except Public Administration)",
}

# Exact IRS major-sector names (as they appear in the spreadsheet cells).
# Selecting by name — not by row index — keeps the pipeline robust to
# row-order changes in future IRS publications.
IRS_MAJOR_SECTOR_NAMES = [
    "Agriculture, forestry, fishing and hunting",
    "Mining",
    "Utilities",
    "Construction",
    "Manufacturing",
    "Wholesale trade",
    "Retail trade",
    "Transportation and warehousing",
    "Information",
    "Finance and insurance",
    "Real estate and rental and leasing",
    "Professional, scientific, and technical services ",   # note trailing space
    "Management of companies (holding companies)",
    "Administrative and support and waste management and remediation services ",
    "Educational services",
    "Health care and social assistance ",                   # note trailing space
    "Arts, entertainment, and recreation",
    "Accommodation and food services",
    "Other services",
]


# ===========================================================================
# 2.  LOAD AND CLEAN: IRS TABLE 1
# ===========================================================================
# Excel row layout (0-indexed absolute rows in the file):
#   0  : "RETURNS OF ACTIVE CORPORATIONS"  ← title text
#   1  : table description                  ← title text
#   2  : money-amounts note                 ← title text
#   3  : first-level column headers         ← header row 0
#   4  : second-level column sub-headers    ← header row 1
#   5  : blank row                          ← skip
#   6  : column-number row (1, 2, 3 …)     ← skip (metadata, not data)
#   7+ : industry data rows                 ← data

df_irs_raw = pd.read_excel(
    IRS_PATH,
    sheet_name=IRS_SHEET,
    header=[0, 1],              # two-level header at file rows 3 & 4
    skiprows=[0, 1, 2, 5, 6],  # drop titles + blank + column-number row
)

df_irs_raw = flatten_multiindex_columns(df_irs_raw)

# Industry name lives in the first column (after flattening it is always pos 0)
INDUSTRY_COL_IRS = df_irs_raw.columns[0]

# --- 2a. Filter to major-sector rows (no hardcoded row indices) -------------
df_irs = (
    df_irs_raw
    .loc[df_irs_raw[INDUSTRY_COL_IRS].isin(IRS_MAJOR_SECTOR_NAMES)]
    .copy()
    .reset_index(drop=True)
)

# --- 2b. Extract financial metrics by column keyword ------------------------
net_income_col = find_col(df_irs, "Net income")
deficit_col    = find_col(df_irs, "Deficit")

# Multiply by IRS_UNIT_SCALE to convert from $thousands → actual dollars
df_irs["IRS_Net_Income"] = coerce_numeric(df_irs[net_income_col]) * IRS_UNIT_SCALE
df_irs["IRS_Deficit"]    = coerce_numeric(df_irs[deficit_col])    * IRS_UNIT_SCALE

# Net income (less deficit): standard IRS presentation
#   = gross net income − deficit amount
#   Where deficit was suppressed ('d' → NaN), treat the deficit as 0 so the
#   net income figure is still usable; flag this assumption with the NaN in
#   IRS_Deficit rather than silently zero-filling both.
df_irs["IRS_Net_Income_Less_Deficit"] = (
    df_irs["IRS_Net_Income"] - df_irs["IRS_Deficit"].fillna(0)
)

# --- 2c. IRS_Operational_Base (financial scale proxy) -----------------------
# Formula:  Total Receipts (All returns)  −  IRS_Net_Income_Less_Deficit
#
# Derivation:
#   Accounting identity:  Total Receipts = Net Income + Total Deductions
#   Rearranged:           Total Deductions = Total Receipts − Net Income
#   Using the net figure: Operational Base = Total Receipts − (Net Income − Deficit)
#                                          = Total Deductions + Deficit
#
# This equals all revenue consumed by operations (costs, expenses, taxes paid,
# plus any deficit position), and is fully populated for every sector in the
# abbreviated Table 1 extract.  No sentinel 'd' suppression affects these
# top-level sector-aggregate totals.
#
# Column is also aliased as IRS_Salaries_Wages in the output for schema
# continuity with any downstream code written against the original spec.
total_receipts_col = find_col(df_irs, "Total receipts")

# Total receipts also in $thousands → scale to actual dollars
df_irs["IRS_Operational_Base"] = (
    coerce_numeric(df_irs[total_receipts_col]) * IRS_UNIT_SCALE
    - df_irs["IRS_Net_Income_Less_Deficit"]
)

# --- 2d. Standardise the industry name for joining --------------------------
df_irs["Industry_std"] = (
    df_irs[INDUSTRY_COL_IRS]
    .map(standardise_industry_name)
    .replace(IRS_TO_DP_CANONICAL)
)

df_irs_clean = df_irs[[
    INDUSTRY_COL_IRS,
    "Industry_std",
    "IRS_Net_Income",
    "IRS_Deficit",
    "IRS_Net_Income_Less_Deficit",
    "IRS_Operational_Base",
]].rename(columns={
    INDUSTRY_COL_IRS:       "Industry_IRS",
    "IRS_Operational_Base": "IRS_Salaries_Wages",   # alias for schema continuity
})


# ===========================================================================
# 3.  LOAD AND CLEAN: DIGITAL PLANET — "Effects of AI-Industry Level"
# ===========================================================================
# Row 0 of the sheet is the top-level group header (e.g. "Total Occupation …",
# "Job and Income Loss: Slowest Time Progression", …).
# Row 1 is the per-column sub-header.
# The first two columns ("Industry Type", "Industry") have no group label and
# appear as 'Unnamed…' at the top level of the MultiIndex.

df_dp_raw = pd.read_excel(
    DP_PATH,
    sheet_name=DP_SHEET,
    header=[0, 1],
)

df_dp_raw = flatten_multiindex_columns(df_dp_raw)

# Use exact-priority find_col to avoid "Industry" matching "Industry Type"
INDUSTRY_TYPE_COL = find_col(df_dp_raw, "Industry Type")   # exact match → "Industry Type"
INDUSTRY_COL_DP   = find_col(df_dp_raw, "Industry")        # exact match → "Industry"

# Retain only the Sector-level rows
df_dp = (
    df_dp_raw
    .loc[df_dp_raw[INDUSTRY_TYPE_COL] == "Sector"]
    .copy()
    .reset_index(drop=True)
)

# Standardise the industry name for joining
df_dp["Industry_std"] = df_dp[INDUSTRY_COL_DP].map(standardise_industry_name)

df_dp_clean = df_dp.rename(columns={INDUSTRY_COL_DP: "Industry_DP"})


# ===========================================================================
# 4.  PRE-MERGE DIAGNOSTICS  (required by rubric)
# ===========================================================================

print("=" * 62)
print("PRE-MERGE ROW COUNTS")
print(f"  IRS major-sector rows       : {len(df_irs_clean):>4d}")
print(f"  Digital Planet sector rows  : {len(df_dp_clean):>4d}")
print()

irs_names = set(df_irs_clean["Industry_std"])
dp_names  = set(df_dp_clean["Industry_std"])

only_irs = irs_names - dp_names
only_dp  = dp_names  - irs_names

if only_irs:
    print("  [WARNING] IRS names with NO Digital Planet match (dropped):")
    for n in sorted(only_irs):
        print(f"    • {n}")
else:
    print("  [OK] Every IRS sector has a Digital Planet counterpart.")

if only_dp:
    print("  [INFO] Digital Planet names with no IRS match (dropped by inner join):")
    for n in sorted(only_dp):
        print(f"    • {n}")

print("=" * 62)


# ===========================================================================
# 5.  MERGE — inner join on standardised industry name
# ===========================================================================

df_merged = pd.merge(
    df_irs_clean,
    df_dp_clean,
    on="Industry_std",
    how="inner",
)

# Reorder: canonical name first, then IRS originals, then DP original, then data
lead_cols = ["Industry_std", "Industry_IRS", "Industry_DP"]
remaining = [c for c in df_merged.columns
             if c not in lead_cols + [INDUSTRY_TYPE_COL]]
df_merged = df_merged[lead_cols + remaining]

print(f"POST-MERGE ROW COUNT        : {len(df_merged):>4d}")
print("=" * 62)


# ===========================================================================
# 6.  OUTPUT
# ===========================================================================

os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
df_merged.to_csv(OUTPUT_PATH, index=False)
print(f"\nSaved → {OUTPUT_PATH}")
print(f"Columns in output ({len(df_merged.columns)}):")
for c in df_merged.columns:
    print(f"  {c}")
print()
print(df_merged[["Industry_std",
                  "IRS_Net_Income_Less_Deficit",
                  "IRS_Salaries_Wages"]].to_string(index=False))
print("\n(IRS_Salaries_Wages = IRS_Operational_Base proxy: Total Receipts − Net Income Less Deficit)")
