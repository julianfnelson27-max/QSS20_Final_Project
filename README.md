# QSS20 Final Project — AI Labor Displacement & Federal Revenue

**Research question:** If AI-driven labor displacement erodes the payroll tax base at a rate faster than corporate tax growth can offset, will the federal government enter a structural deficit trap where traditional revenue streams become insufficient to sustain national finances?

---

## Repository layout

```
data/       Raw source files
code/       Pipeline script and notebooks
output/     All generated CSVs and figures
```

---

## Code files

### [`code/01_data_pipeline.py`](code/01_data_pipeline.py)

**Inputs**
| File | Description |
|------|-------------|
| `data/Table_1.xlsx` | IRS Statistics of Income — Table 1 (Tax Year 2022), sheet `CRTAB01`. Money amounts in thousands of dollars. |
| `data/Digital-Planet-AI-jobs-March-2026.xlsx` | Digital Planet AI-Jobs Data Booklet (March 2026), sheet `Effects of AI-Industry Level`. |

**What it does**
1. Reads both source files, flattening two-level MultiIndex headers.
2. Filters the IRS data to 19 major NAICS sectors and derives two financial columns:
   - `IRS_Net_Income_Less_Deficit` — gross net income minus deficit
   - `IRS_Salaries_Wages` (alias for `IRS_Operational_Base`) — total receipts minus net income less deficit; a proxy for sector-wide operational cost scale
3. Scales all IRS dollar values from thousands → actual dollars.
4. Filters the Digital Planet data to Sector-level rows.
5. Standardises industry names on both sides and applies a small name-mapping table to align the three sectors where IRS and Digital Planet labels diverge.
6. Inner-joins the two datasets on the standardised industry name, printing pre- and post-merge diagnostics.

**Output**
| File | Description |
|------|-------------|
| `data/02_merged_clean.csv` | 19-row merged dataset with IRS financials and Digital Planet AI-exposure metrics, ready for simulation. |

---

### [`code/02_merged_clean.csv`](code/02_merged_clean.csv)

Intermediate analysis-ready file produced by `01_data_pipeline.py` and consumed by `03_montecarlo_simulation.ipynb`. Key columns:

| Column | Description |
|--------|-------------|
| `Industry_std` | Canonical industry name used for joining |
| `Industry_IRS` / `Industry_DP` | Original names from each source |
| `IRS_Net_Income_Less_Deficit` | Net corporate income after deficits ($) |
| `IRS_Salaries_Wages` | Operational cost proxy / wage-base proxy ($) |
| `Job and Income Loss: [Slow/Median/Fast] Time Progression - Percent Income Loss` | AI-driven income-loss rate by adoption timeline (0–1 scale) |

---

### [`code/03_montecarlo_simulation.ipynb`](code/03_montecarlo_simulation.ipynb)

**Input**
| File | Description |
|------|-------------|
| `data/02_merged_clean.csv` | Cleaned merged dataset from `01_data_pipeline.py` |

**What it does**
1. Computes baseline federal revenue per industry from three tax streams (payroll tax @ 15.3%, individual income tax on wages @ 22%, corporate income tax @ 21%).
2. Runs 100,000-iteration vectorised Monte Carlo simulations per industry across three AI adoption timelines (Slow / Median / Fast), applying lognormal noise to each industry's income-loss rate.
3. Calculates the net federal revenue shortfall (labor tax revenue lost minus a 3% annual corporate income growth offset) for each draw.
4. Flags **deficit-trap** industries where the median shortfall exceeds 5% of baseline total revenue.
5. Aggregates industry results to federal totals and prints a summary.
6. Produces three figures.

**Key simulation results**

| Timeline | Federal median shortfall | 90% CI | Shortfall as % of revenue | Deficit-trap industries |
|----------|--------------------------|--------|---------------------------|-------------------------|
| Slow | $0.32T | $0.29T – $0.35T | 2.0% | 1 of 19 |
| Median | $1.12T | $1.03T – $1.22T | 7.0% ⚠️ | 11 of 19 |
| Fast | $2.31T | $2.12T – $2.51T | 14.3% ⚠️ | 17 of 19 |

*(⚠️ = structural deficit-trap threshold of 5% exceeded)*

**Outputs**
| File | Description |
|------|-------------|
| `output/03_simulation_results.csv` | Industry-level simulation statistics (mean, std, p5/p25/p50/p75/p95 shortfall, deficit-trap flag) for all 3 timelines — 57 rows (19 industries × 3 timelines) |
| `output/03_deficit_trap_summary.csv` | Federal-aggregate summary: one row per timeline with total shortfall percentiles and deficit-trap industry counts |
| `output/03_fig1_federal_shortfall_by_timeline.png` | Bar chart of federal median shortfall with 90% CI by timeline |
| `output/03_fig2_industry_shortfall_fast.png` | Horizontal bar chart of industry-level median shortfalls under the Fast timeline; deficit-trap industries highlighted in red |
| `output/03_fig3_shortfall_kde_by_timeline.png` | KDE probability-density curves of the federal shortfall distribution for all three timelines |

---

## Data sources

| File | Source |
|------|--------|
| `data/Table_1.xlsx` | [IRS Statistics of Income — Corporation Complete Report, Table 1, Tax Year 2022](https://www.irs.gov/statistics/soi-tax-stats-corporation-complete-report) |
| `data/Digital-Planet-AI-jobs-March-2026.xlsx` | [Digital Planet AI-Jobs Data Booklet, March 2026 — Fletcher School, Tufts University](https://sites.tufts.edu/digitalplanet/) |
