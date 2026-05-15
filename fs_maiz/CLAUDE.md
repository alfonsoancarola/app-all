# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Streamlit dashboard + daily Python pipeline that tracks Argentine grain "Farmer Selling" — the cadence at which farmers sell each new crop to exporters/industry. Multi-crop: corn, sorghum, wheat, barley. Two public data sources are scraped daily:

- **SIO Granos** (`siogranos.com.ar`) — every reported sale operation (date, tonnes, delivery month, location, etc.). Scraped with Playwright headless because the page is ASP.NET with no public API. SIO caps queries at 180 days per request → backfill scripts chunk into ≤180-day windows.
- **MAGYP / MINAGRI** ("Compras del Sector Exportador") — weekly XLSX with PH (Precio Hecho) + Fijado totals per crop and crop-year. Scraped from the MAGYP website; the script keys on URL hash and only appends a point when a new file is published.

The cron (`launchd` on macOS) runs `correr_diario.py`, which: (1) downloads SIO last 180d, (2) merges into `data/sio_historico.csv` with row-exact dedup, (3) for each crop, checks MINAGRI and regenerates `data/matriz_<cultivo>.csv`. The Streamlit app reads only those generated CSVs + a few JSONs — it never hits the network at request time.

Source comments and historical commit messages are in Spanish; UI strings and newer code are in English. When editing existing files, match the language already in that file.

## Common commands

```bash
make setup                  # one-time: .venv, deps, Playwright Chromium
make daily                  # full pipeline (what cron runs): SIO → merge → MINAGRI → matrices for all crops
make run                    # launch Streamlit app (defaults to private mode)
FS_MODO=public make run     # public mode hides internal LDC data + targets

make sio                    # only download SIO (last 180d) → ~/Downloads/sio.csv
make minagri                # only check MAGYP for new XLSX (corn-only legacy form)
make update SIO=path.csv    # rebuild matrix from existing CSV (skips network)

# Backfills (run once)
make backfill-minagri-historico   # 10 cosechas × 4 crops of MAGYP history
make backfill-sio-historico       # SIO from 2017 (~30-60min, ~2GB)
make historical-metrics           # recompute data/historical_metrics_<slug>.json from above
make geojson-ar                   # download Argentine provinces GeoJSON (for the origin map)

# Debug modes when SIO/MAGYP change their pages
make discover-sio                 # dump form selectors found on SIO page
make debug-sio                    # run with browser visible
make discover-minagri             # dump links found on MAGYP page

# Scheduling (macOS launchd)
make schedule HORAS=10:00,17:00   # default schedule
make unschedule
```

Single-crop runs of the orchestrator: `python correr_diario.py --cultivos maiz,trigo`. Force MINAGRI reparse: `.venv/bin/python actualizar_minagri.py --force`.

There is no test suite, no linter config, and no CI. "Verifying" a change means running `make daily` (or the relevant sub-step) and inspecting the regenerated CSV / loading the app.

## Architecture

### Crop config is the single source of truth

[cultivos.py](cultivos.py) defines `CULTIVOS`, a dict keyed by slug (`maiz`, `trigo`, `cebada`, `sorgo`). Every other module — pipeline, app, historical metrics — looks up its per-crop knobs here:

- `sio_producto`, `sio_ddl_value` — how to filter SIO
- `magyp_tab`, `cosecha`, `magyp_seccion` — which MAGYP tab/section to parse (default section is "Compras Sector Exportador")
- `delivery_groups` — list of `(bucket_name, date_from, date_to)` tuples that map a SIO operation's delivery date to a column (e.g. `MAM` = Mar–May 2026 for corn). **These are absolute dates** for the current crop year — `compute_historical_metrics.py` shifts them by N years to compute the same buckets for prior cosechas.
- `cosecha` vs `cosecha_label` — `cosecha` is the MAGYP/SIO key (e.g. `25/26`); `cosecha_label` is the LDC-internal display year (often offset by +1 for autumn-harvested crops). Always use the right one for the right consumer.
- `balance_hist` — historical supply/demand balance table (M tn). Source is the LDC Country Balance Sheet (internal); the user can override values from the sidebar.

Helper functions: `get_cultivo(slug)`, `grupo_de_entrega(date, cfg)`, `slug_de(cfg)`, `minagri_json_path(cfg)` (returns `data/minagri_<slug>_<cosecha>.json`).

### Data flow and on-disk layout

```
SIO (Playwright)  ──→  ~/Downloads/sio.csv  ─merge dedup─→  data/sio_historico.csv  (UTF-16, semicolon)
MAGYP (httpx)     ──→  data/minagri_<slug>_<cosecha>.json   (one per crop, append-only)
                                                   │
                                                   ▼
                              actualizar_fs.py  per crop  ──→  data/matriz_<cultivo>.csv
                                                                              │
                                                                              ▼
                                                                        app.py reads
```

`data/sio_historico.csv` is **UTF-16 with `;` delimiter** (SIO's native format) — preserved on merge. Don't rewrite as UTF-8.

### The matrix CSV format

Columns: `tipo, label, <bucket1>, <bucket2>, ..., total, low, prior, min`. The bucket columns vary by crop (corn/sorghum: `MAM,JJ,AS,OND,JF`; wheat/barley: `NDJ,FMA,MJJ,ASO`).

Row types (`tipo`):
- `mensual` — one row per month from `primer_mes_mensual` up to the month before current.
- `diario` — one business day in the current "tracked month" (May 2026 for autumn crops). Used for the rolling 10-day average.
- `mayo_target` — three sentinel rows (Objetivo / Ritmo nec./día / Falta) shown only in private mode; hidden when `FS_MODO=public`.

The core formula in [actualizar_fs.py](actualizar_fs.py):
```
cell[month][bucket] = MINAGRI_volume[month] × (SIO_split_for_bucket / SIO_total_for_month)
```
i.e. MAGYP gives the **monthly total** (PH + Fijado), SIO gives the **bucket distribution within the month**. When MINAGRI hasn't published a number for a month, falls back to raw SIO. The `min` column stores the MINAGRI delta in tonnes (kt × 1000) by linear interpolation between weekly cuts.

### Display units

Internal data is in **tonnes**. The UI formats as **kilotonnes** via `fmt_tn()` in `app.py`. Don't change the on-disk units; only change the formatter if the display rule changes.

### Geography helpers

- [destinos.py](destinos.py) categorizes the SIO `LUGAR ENTREGA` free-text field into 4 buckets: Up River (Rosario), Bahía Blanca, Necochea, Interior. The `/En destino` vs `/En origen` suffix is about who pays freight — ignore it for placement.
- [provincias.py](provincias.py) maps SIO province strings to ISO 3166-2:AR codes for the choropleth map.
- [logistica.py](logistica.py) is a small ship-loading scheduler (Gral Lagos terminal) used by a separate tab; 18h fixed load time, no overlap permitted globally.

### Streamlit app structure

[app.py](app.py) is one large file (~80KB). Sidebar selects the crop and a reference cosecha; main area is tabbed (Matrix, Origins/Destinations, Logistics, etc.). The "Matrix" tab owns the page header — other tabs render their own content only. Public mode (`FS_MODO=public`) hides targets, internal LDC balance overrides, and the daily target rows. When adding a new tab, do **not** put global headers in it.
