# Lineups · Argentina Grain Shipping Dashboard

A single-file Streamlit dashboard that reads the monthly Alpemar Shipping Agency
lineup xls files plus MARS Country Balance Sheets, and renders an executive
view of Argentina's grain exports (corn / wheat / barley / sorghum).

## Folders

This project depends on **two sibling folders** on the user's Mac:

- `~/3. Lineups/` (this folder) — the app and the monthly lineup xls files
- `~/0. MARS/` — Country Balance Sheets from MARS, used for targets and
  expected-volume comparisons

If you only have access to one of them, request the other with
`mcp__cowork__request_cowork_directory` before working on data flows.

The app discovers MARS via a relative path (`../0. MARS`). Override with
`LINEUPS_MARS_DIR` env var if needed.

## Files

```
3. Lineups/
├── lineups_app.py                                       # the entire app
├── requirements.txt
├── README.md
├── GRAIN-SBS-BARLEY-MALT SHIPMENTS March 2026.xls       # finalized month
├── GRAIN-SBS-BARLEY-MALT SHIPMENTS April 2026.xls       # finalized month
├── GRAIN-SBS-BARLEY-MALT SHIPMENTS May 2026.xls         # current month
└── Copia de app.py                                      # reference (Farmer
                                                        #  Selling app)

0. MARS/
├── Country Balance Sheet (29).xlsx  →  Wheat   (Dec/Nov crop year)
├── Country Balance Sheet (30).xlsx  →  Barley  (Dec/Nov crop year)
├── Country Balance Sheet (31).xlsx  →  Sorghum (Mar/Feb crop year)
└── Country Balance Sheet (32).xlsx  →  Corn / Maize (Mar/Feb crop year)
```

## Running

```bash
cd ~/"3. Lineups"
source .venv/bin/activate
streamlit run lineups_app.py
```

First time (creates venv):

```bash
cd ~/"3. Lineups"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run lineups_app.py
```

ngrok pattern (two terminals):

```bash
streamlit run lineups_app.py
# in another terminal:
ngrok http 8501          # or whichever port Streamlit picked
```

The fs_maiz app often runs at the same time and grabs 8501 → check Streamlit's
startup log for the actual port, and point ngrok at that one.

**Path gotcha**: `cd "~/3. Lineups"` does NOT expand `~` inside quotes. Use
`cd ~/"3. Lineups"` or `cd ~/3.\ Lineups`.

## Data model

### Lineup xls files (Alpemar)

Each monthly xls has one sheet with up to three sections separated by section
header rows:

- `LOADED <Month> YYYY` or just `LOADED` → maps to **Sailed**
- `AT ROADS` → maps to **At Roads**
- `ANNOUNCED` or `LINEUP` → maps to **Lineup**

Columns: CARGO · VESSEL · PORT · BERTH · ETA/ETF · TONS · SHIPPER · COORD · DEST.

Finalized months (March, April) only have `LOADED`. The current month (May)
carries all three sections.

### MARS Country Balance Sheets

Four xlsx files, one per crop. Used sheets:

- `Monthly BalanceSheet` — supply/demand by month including `Exports` row in kt
- `Destinations table` — kt per destination per month, marked `Shipped` for
  past months and `Expected` for future ones

Targets in the app come from MARS:

- Campaign target = sum of the `Exports` row
- Current-month target = `Exports[current month code]` (e.g. `05/2026`)

### Status conventions

- **Sailed** — vessel already departed (has an ETA/ETF date in the data)
- **At Roads** — at anchorage waiting (no ETA in the source xls)
- **Lineup** — announced, not yet at port (no ETA either)

So the cumulative *time series* can only use Sailed; At Roads / Lineup show up
as forecast or as part of the monthly aggregate.

### Zones

```python
PORT_TO_ZONE = {
    # Up River (Paraná river ports)
    "San Lorenzo", "Rosario", "Ramallo", "San Pedro", "Lima",
    "Parana Guazu", "Villa Constitucion", "Timbues",
    "Puerto General San Martin"  →  "Up River"
    # Atlantic south
    "Bahia Blanca"   →  "Bahía Blanca"
    "Necochea", "Quequen"  →  "Necochea"
}
```

Up River dominates by far (~78% of granel volume).

### Crops

- **Maize** (English label throughout) — main focus, default selection
- **Wheat** / **Barley** — Dec/Nov campaign (different from corn!)
- **Sorghum** — Mar/Feb like corn
- **All Grains** — special aggregate that sums the 4 crops with a 15-month
  combined campaign (Dec 25 → Feb 27)

### CARGO normalization (CARGO_NORMALIZE)

- `Sbs` → `Soybean`
- `Maize Cotufa (in bags)` → `Maize (bags)` (popcorn maize, specialty)
- `Maize flint` → `Maize` (mergea)
- Beans variants → `Beans`

### Shipper normalization (normalize_shipper)

- Anything starting with `cofco` → `Cofco Int. Arg.`
- Anything starting with `molinos agro` → `Molinos Agro`
- Anything starting with `adm` → `ADM Agro`

### Manual exclusions (EXCLUDED_ROWS)

Currently filters out: April 2026, vessel `ISLAND` to Italy, which the source
xls labeled as Wheat but was actually durum wheat. Add similar dicts to
`EXCLUDED_ROWS` if more mis-classifications appear.

## App architecture

Single file `lineups_app.py`. Layout:

1. **Config & constants** — paths, MONTH_FILES, MARS_FILES, CROP_NAMES,
   CROP_YEAR_LABEL, MARS_MONTH_LABEL (Spanish→English month codes), colors
2. **Formatters** — `fmt_tn`, `fmt_kt`, `fmt_int`, `fmt_pct`
3. **Normalizers** — `normalize_shipper`, `normalize_port`, `normalize_dest`
4. **Parser** — `_parse_one`, `load_all` (lineup xls)
5. **MARS parser** — `_load_mars_combined`, `load_mars`, `get_campaign`,
   `mars_exports_total`, `mars_exports_month`, `mars_balance_dataframe`
6. **Model** — `snapshot()` computes all KPI numbers in one dict
7. **Chart helpers** — see "Reusable charts" below
8. **Sidebar** — filters + targets, sets the *global* `crop`, `df`,
   `df_crop_all`, `CAMPAIGN_MONTHS` (yes, the dynamic campaign is propagated
   via module globals reassigned in the sidebar block — the chart functions
   resolve them at call time)
9. **Header & KPIs** — 3 CEO summary cards
10. **Tabs** — Current Month / Overview / Port / Destination / Shipper / Data

### Reusable charts

- `monthly_volume_bar(df)` — stacked bar of monthly volume by status
- `cumulative_monthly_chart(df, snap, today)` — current-month daily cumulative
  with yellow forecast area, today line, target line
- `cumulative_annual_chart(df, snap, today, mars)` — full campaign trajectory:
  **solid green** for months with lineup data, **dashed yellow** for months
  fed from MARS Exports. No comparison overlays.
- `expected_plus_status_chart(df, dim, top_n)` — thick **Expected** bar +
  thin Sailed / At Roads / Lineup bars per group. Used in Current Month tab.
- `expected_plus_month_chart(df, dim, top_n)` — thick **Total** bar + one
  thin bar per loaded month so you can see which months drove the total.
  Used in Port / Destination / Shipper cumulative views.
- `pipeline_table(df, dim)` — pivot dim × (Sailed / At Roads / Lineup /
  Pipeline / Share %)
- `waterfall_chart(snap)` — Target → −Sailed → −AtRoads → −Lineup → Gap
  *(not currently used in any tab but kept for reuse)*

## Tab layout

- **📅 Current Month** *(first; default)*
  1. KPIs (Sailed / At Roads + Lineup / Current / Month target / vs Ideal Pace)
  2. Monthly cumulative line chart
  3. Top 10 shippers · Expected + status breakdown
  4. Ports (by zone) · Expected + status breakdown
  5. Top 10 destinations · Expected + status breakdown
  6. Volume {Month} aggregate + breakdown (4-bar summary)

- **📊 Overview** — only the Annual Cumulative chart + 4 KPIs (cumulative to
  date, rest of year MARS, estimated close, MARS total).

- **🏭 Port** — radio toggle "By zone" / "Port detail" + cumulative
  *Total + per-month* chart + pivot table.

- **🌍 Destination** — Top N slider + cumulative *Total + per-month* chart +
  pivot table.

- **🚛 Shipper** — KPIs (Top 3 concentration, Equivalent shippers / HHI, top
  gainer, top decliner) + share evolution lines + cumulative *Total + per-month*
  chart + leaderboard.

- **📋 Data** — raw filtered table + CSV download.

## UI conventions (the user cares about these)

- **Language**: everything in English (sidebar, tabs, captions, axis titles,
  tooltips, column names, month labels). Crops in English (Maize, not Maíz).
- **Months**: "March 2026", "April 2026", ... "February 2027".
- **Numbers**: kt with `.` as thousand separator (e.g. `1.234 kt`).
- **Colors**: Sailed = green `#2E7D32`, At Roads = amber `#F9A825`,
  Lineup = blue `#1E88E5`, Target/ideal = gray `#9E9E9E`,
  Forecast = yellow `#FFC107`.
- **"Current" vs "Pipeline"**: in current-month metrics use **"Current"**.
  "Pipeline" is reserved for full-campaign accumulated totals.
- **Layout**: main container is capped at 1280px and centered (CSS injected
  after `st.set_page_config`).
- **Tabs**: always prefix with relevant emoji (📅 📊 🏭 🌍 🚛 📋).

## Important: campaign window is *per crop*

`CAMPAIGN_MONTHS` / `CAMPAIGN_LABELS` / `CAMPAIGN_START` / `CAMPAIGN_END` are
module-level globals that get **reassigned in the sidebar block** based on the
selected crop:

- Maize / Sorghum → March 2026 → February 2027 (12 months)
- Wheat / Barley → December 2025 → November 2026 (12 months)
- All Grains → December 2025 → February 2027 (15 months, union)

Chart functions resolve these names at call time, so when you switch crops in
the sidebar everything downstream picks up the new campaign.

## Validation cheatsheet

To sanity-check without running Streamlit, mock the streamlit module and
execute the file up to `# Sidebar`:

```python
class _A:
    def __call__(self,*a,**k): return _A()
    def __getattr__(self,n): return _A()
    def __enter__(self): return self
    def __exit__(self,*a): return False
class _St:
    column_config=_A(); sidebar=_A()
    @staticmethod
    def cache_data(*a,**k):
        def d(f): return f
        return d
    def __getattr__(self,n): return _A()
sys.modules["streamlit"] = _St()
src = Path("lineups_app.py").read_text().split("# Sidebar")[0]
ns = {"__file__": "lineups_app.py"}
exec(src, ns)
df = ns["load_all"]()
# Now you can call ns["snapshot"], ns["expected_plus_status_chart"], etc.
```

Expected sanity numbers (validated against the raw xls):

- March 2026: 6.985 kt (all Sailed)
- April 2026: 6.625 kt (all Sailed; 6.624 if ISLAND→Italy still in)
- May 2026: 6.938 kt (1.704 Sailed + 1.057 At Roads + 2.266 Lineup)
- Maize total in lineup: 13.746 kt across Mar/Apr/May
- Maize MARS total campaign exports: 40.942 kt
- Maize current-month MARS target: 4.292 kt

## When working on this app

- **Always provide the terminal command** to restart Streamlit after a change.
  The user prefers reminders for `cd ~/"3. Lineups" && source .venv/bin/activate
  && streamlit run lineups_app.py`.
- **Validate visually after big changes** by mocking Streamlit and running the
  parser/snapshot.
- **Use the Skill / helper conventions**: `expected_plus_month_chart` for
  cumulative views, `expected_plus_status_chart` for current-month views.
  Don't duplicate inline.
- **Translate every user-facing string**. Don't mix Spanish/English in the UI.
- The user prefers small iterative changes over big rewrites; ask before
  restructuring more than one tab.
