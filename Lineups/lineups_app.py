"""
lineups_app.py — Lineups · Argentina Grain Shipments

Dashboard ejecutivo de volúmenes con:
  • Snapshot ejecutivo top
  • Overview: volumen por mes, acumulado mensual con forecast, acumulado anual con proyección
  • Tabs Puerto / Destino / Shipper con tabla + evolución mensual
  • Toggle Tons / % share, targets editables (Maíz)

Run:
    streamlit run lineups_app.py
"""

from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

# ═════════════════════════════════════════════════════════════════════════════
# Config
# ═════════════════════════════════════════════════════════════════════════════

st.set_page_config(
    page_title="Lineups · Argentina Grain",
    page_icon="🚢",
    layout="wide",
)

# Centramos el contenido principal con un ancho máximo
st.markdown(
    """
    <style>
        .main .block-container {
            max-width: 1280px;
            padding-top: 1.6rem;
            padding-bottom: 3rem;
            margin: 0 auto;
        }
        /* Centrar charts de Vega/Altair dentro de su contenedor */
        div[data-testid="stVegaLiteChart"],
        div[data-testid="stArrowVegaLiteChart"] {
            display: flex;
            justify-content: center;
        }
        /* Centrar TODO el contenido de los metrics: label, valor y delta */
        [data-testid="stMetric"] {
            text-align: center !important;
        }
        /* Label: el contenedor + todo lo de adentro (a veces hay un <p>
           o un <div> intermedio con su propio align). Usamos flex en el
           contenedor para asegurar centrado horizontal. */
        [data-testid="stMetric"] [data-testid="stMetricLabel"],
        [data-testid="stMetric"] label {
            display: flex !important;
            justify-content: center !important;
            align-items: center !important;
            width: 100% !important;
            text-align: center !important;
        }
        [data-testid="stMetric"] [data-testid="stMetricLabel"] *,
        [data-testid="stMetric"] label * {
            text-align: center !important;
            justify-content: center !important;
            width: auto !important;
        }
        /* Value */
        [data-testid="stMetric"] [data-testid="stMetricValue"],
        [data-testid="stMetric"] [data-testid="stMetricValue"] > div {
            text-align: center !important;
            justify-content: center !important;
            width: 100% !important;
        }
        /* Delta: flex container con ícono + texto, centrado */
        [data-testid="stMetric"] [data-testid="stMetricDelta"] {
            display: flex !important;
            justify-content: center !important;
            width: 100% !important;
        }
    </style>
    """,
    unsafe_allow_html=True,
)

DATA_DIR = Path(__file__).parent

# Carpeta MARS (Country Balance Sheets) — hermana de la carpeta de lineups.
# Se puede sobrescribir con el env var LINEUPS_MARS_DIR.
import os as _os
MARS_DIR = Path(_os.getenv("LINEUPS_MARS_DIR",
                           str(DATA_DIR.parent / "0. MARS")))

# Carpeta de fs_maiz para overlay de compras sobre los charts mensuales.
# Se puede sobrescribir con LINEUPS_FS_DIR.
FS_DIR = Path(_os.getenv("LINEUPS_FS_DIR",
                         str(DATA_DIR.parent / "fs_maiz")))

# Mapeo entre el label de cargo de Lineups y el slug de fs_maiz
LU_TO_FS_SLUG = {
    "Maize":   "maiz",
    "Wheat":   "trigo",
    "Sorghum": "sorgo",
    "Barley":  "cebada",
}

# Grupos OC por cultivo (idéntico a fs_maiz/cultivos.py — los excluyendo NC)
_FS_OC_GROUPS = {
    "maiz":   ["MAM", "JJ", "AS", "OND", "JF"],
    "trigo":  ["NDJ", "FMA", "MJJ", "ASO"],
    "sorgo":  ["MAM", "JJ", "AS", "OND", "JF"],
    "cebada": ["NDJ", "FMA", "MJJ", "ASO"],
}

# Mapping CARGO → archivo de MARS
MARS_FILES = {
    "Maize":   "Country Balance Sheet (32).xlsx",  # Corn (Mar/Feb)
    "Wheat":   "Country Balance Sheet (29).xlsx",  # Wheat (Dec/Nov)
    "Barley":  "Country Balance Sheet (30).xlsx",  # Barley (Dec/Nov)
    "Sorghum": "Country Balance Sheet (31).xlsx",  # Sorghum (Mar/Feb)
}

# Crop labels + emoji
CROP_NAMES = {
    "All Grains": ("All Grains (consolidated)", "🌾"),
    "Maize":      ("Maize",                     "🌽"),
    "Wheat":      ("Wheat",                     "🌾"),
    "Barley":     ("Barley",                    "🌿"),
    "Sorghum":    ("Sorghum",                   "🌱"),
}

# Crop year label (informative)
CROP_YEAR_LABEL = {
    "All Grains": "Combined crop year (Dec 25 → Feb 27)",
    "Maize":      "Crop year 26/27 (Mar/Feb)",
    "Sorghum":    "Crop year 26/27 (Mar/Feb)",
    "Wheat":      "Crop year 25/26 (Dec/Nov)",
    "Barley":     "Crop year 25/26 (Dec/Nov)",
}

# Crops that make up the "All Grains" aggregate
ALL_GRAINS_COMPONENTS = ["Maize", "Wheat", "Barley", "Sorghum"]

# Manual row exclusions: rows that match all the criteria in a dict get
# removed from the lineup. Useful when a record was mis-classified (eg.
# durum wheat reported as Wheat) and we don't want it polluting the totals.
EXCLUDED_ROWS = [
    {  # Durum wheat — the source xls labels it as Wheat but it is durum
        "MONTH":   "April 2026",
        "VESSEL":  "ISLAND",
        "DEST":    "Italy",
        "CARGO":   "Wheat",
    },
]

# Displayed month → (file, month_state)
#   "finalized" = only LOADED ;  "current" = LOADED + AT ROADS + LINEUP
MONTH_FILES: dict[str, tuple[str, str]] = {
    "November 2025": ("GRAIN-SBS-BARLEY-MALT SHIPMENTS NOV 2025.xls",   "finalized"),
    "December 2025": ("GRAIN-SBS-BARLEY-MALT SHIPMENTS DEC 2025.xls",   "finalized"),
    "January 2026":  ("GRAIN-SBS-BARLEY-MALT SHIPMENTS JAN 2026.xls",   "finalized"),
    "February 2026": ("GRAIN-SBS-BARLEY-MALT SHIPMENTS FEB 2026.xls",   "finalized"),
    "March 2026":    ("GRAIN-SBS-BARLEY-MALT SHIPMENTS March 2026.xls", "finalized"),
    "April 2026":    ("GRAIN-SBS-BARLEY-MALT SHIPMENTS April 2026.xls", "finalized"),
    "May 2026":      ("GRAIN-SBS-BARLEY-MALT SHIPMENTS May 2026.xls",   "current"),
}

# MARS month code ("05/2026") → label used in the app ("May 2026").
# Covers Dec 25 → Feb 27 so it works for both Maize/Sorghum (Mar/Feb) and
# Wheat/Barley (Dec/Nov).
MARS_MONTH_LABEL = {
    "12/2025": "December 2025", "01/2026": "January 2026",
    "02/2026": "February 2026",
    "03/2026": "March 2026",    "04/2026": "April 2026",
    "05/2026": "May 2026",      "06/2026": "June 2026",
    "07/2026": "July 2026",     "08/2026": "August 2026",
    "09/2026": "September 2026","10/2026": "October 2026",
    "11/2026": "November 2026", "12/2026": "December 2026",
    "01/2027": "January 2027",  "02/2027": "February 2027",
}

# Campaña por defecto: usada solo como fallback cuando MARS no está disponible.
# La campaña real se calcula dinámicamente por cultivo con get_campaign(crop).
_DEFAULT_CAMPAIGN_MONTHS = [
    ("November 2025",  pd.Timestamp(2025, 11, 1), pd.Timestamp(2025, 11, 30)),
    ("December 2025",  pd.Timestamp(2025, 12, 1), pd.Timestamp(2025, 12, 31)),
    ("January 2026",   pd.Timestamp(2026,  1, 1), pd.Timestamp(2026,  1, 31)),
    ("February 2026",  pd.Timestamp(2026,  2, 1), pd.Timestamp(2026,  2, 28)),
    ("March 2026",     pd.Timestamp(2026,  3, 1), pd.Timestamp(2026,  3, 31)),
    ("April 2026",     pd.Timestamp(2026,  4, 1), pd.Timestamp(2026,  4, 30)),
    ("May 2026",       pd.Timestamp(2026,  5, 1), pd.Timestamp(2026,  5, 31)),
    ("June 2026",      pd.Timestamp(2026,  6, 1), pd.Timestamp(2026,  6, 30)),
    ("July 2026",      pd.Timestamp(2026,  7, 1), pd.Timestamp(2026,  7, 31)),
    ("August 2026",    pd.Timestamp(2026,  8, 1), pd.Timestamp(2026,  8, 31)),
    ("September 2026", pd.Timestamp(2026,  9, 1), pd.Timestamp(2026,  9, 30)),
    ("October 2026",   pd.Timestamp(2026, 10, 1), pd.Timestamp(2026, 10, 31)),
    ("November 2026",  pd.Timestamp(2026, 11, 1), pd.Timestamp(2026, 11, 30)),
    ("December 2026",  pd.Timestamp(2026, 12, 1), pd.Timestamp(2026, 12, 31)),
    ("January 2027",   pd.Timestamp(2027,  1, 1), pd.Timestamp(2027,  1, 31)),
    ("February 2027",  pd.Timestamp(2027,  2, 1), pd.Timestamp(2027,  2, 28)),
]

# Estos globals se sobrescriben en el sidebar una vez que se conoce el crop.
# Las funciones definidas más abajo los resuelven en tiempo de llamada, así
# que cambiar las variables aquí afecta todos los charts y tablas.
CAMPAIGN_MONTHS = _DEFAULT_CAMPAIGN_MONTHS
CAMPAIGN_LABELS = [m[0] for m in CAMPAIGN_MONTHS]
CAMPAIGN_START  = CAMPAIGN_MONTHS[0][1]
CAMPAIGN_END    = CAMPAIGN_MONTHS[-1][2]

STATUS_ORDER  = ["Sailed", "At Roads", "Lineup"]

# Paleta (verde real, amarillo forecast, azul pipeline, gris target)
COL_SAILED   = "#2E7D32"
COL_ROADS    = "#F9A825"
COL_LINEUP   = "#1E88E5"
COL_FORECAST = "#FFC107"
COL_TARGET   = "#9E9E9E"
COL_PIPELINE = "#1565C0"

STATUS_COLORS = {"Sailed": COL_SAILED, "At Roads": COL_ROADS, "Lineup": COL_LINEUP}

# Normalización de productos (CARGO)
CARGO_NORMALIZE = {
    "Maize":                  "Maize",
    "Maize flint":            "Maize",
    "Maize Cotufa (in bags)": "Maize (bags)",
    "Wheat":                  "Wheat",
    "Sorghum":                "Sorghum",
    "Barley":                 "Barley",
    "Malt":                   "Malt",
    "Sbs":                    "Soybean",
    "Black Beans (in bags)":  "Beans",
    "Red Beans - (in bags)":  "Beans",
    "Kidney Beans (in bags)": "Beans",
}
GRANEL = ["Maize", "Wheat", "Sorghum", "Barley"]

# Zonificación
PORT_TO_ZONE = {
    "San Lorenzo":        "Up River",
    "Rosario":            "Up River",
    "Ramallo":            "Up River",
    "San Pedro":          "Up River",
    "Lima":               "Up River",
    "Parana Guazu":       "Up River",
    "Villa Constitucion": "Up River",
    "Villa Constitución": "Up River",
    "Timbues":            "Up River",
    "Timbúes":            "Up River",
    "Puerto General San Martin": "Up River",
    "Bahia Blanca":  "Bahía Blanca",
    "Bahía Blanca":  "Bahía Blanca",
    "Necochea":      "Necochea",
    "Quequen":       "Necochea",
    "Quequén":       "Necochea",
}
ZONE_ORDER = ["Up River", "Bahía Blanca", "Necochea", "Otros"]

def port_to_zone(p):
    if not isinstance(p, str) or not p:
        return "Otros"
    return PORT_TO_ZONE.get(p.strip(), "Otros")


# ═════════════════════════════════════════════════════════════════════════════
# Formato
# ═════════════════════════════════════════════════════════════════════════════

def fmt_tn(v):
    if v is None or pd.isna(v) or v == 0:
        return "—"
    av = abs(v); sign = "-" if v < 0 else ""
    if av >= 1_000_000:
        return f"{sign}{av/1_000_000:.2f}M tn".replace(".", ",")
    if av >= 1_000:
        return f"{sign}{av/1000:,.0f}k tn".replace(",", ".")
    return f"{sign}{av:,.0f} tn".replace(",", ".")

def fmt_kt(v):
    if v is None or pd.isna(v):
        return "—"
    return f"{v/1000:,.0f} kt".replace(",", ".")

def fmt_int(v):
    if v is None or pd.isna(v):
        return "—"
    return f"{int(v):,}".replace(",", ".")

def fmt_pct(part, total):
    if not total:
        return "—"
    return f"{100*part/total:.1f}%".replace(".", ",")


# ═════════════════════════════════════════════════════════════════════════════
# Normalizadores
# ═════════════════════════════════════════════════════════════════════════════

def normalize_shipper(s):
    if not isinstance(s, str): return ""
    s = re.sub(r"\s+", " ", s).strip()
    low = s.lower()
    if low.startswith("cofco"):        return "Cofco Int. Arg."
    if low.startswith("molinos agro"): return "Molinos Agro"
    if low.startswith("adm"):          return "ADM Agro"
    return s

def normalize_port(p):
    if not isinstance(p, str): return ""
    p = re.sub(r"\s+", " ", p).strip()
    return re.sub(r"\s*-\s*Argentina\s*$", "", p, flags=re.IGNORECASE)

def normalize_dest(d):
    if not isinstance(d, str): return ""
    return re.sub(r"\s+", " ", d).strip()


# ═════════════════════════════════════════════════════════════════════════════
# Parser
# ═════════════════════════════════════════════════════════════════════════════

def _parse_one(path: Path) -> pd.DataFrame:
    raw = pd.read_excel(path, sheet_name=0, header=None)
    sections, end_row = [], len(raw)
    for i, row in raw.iterrows():
        cell = str(row[0]).strip() if pd.notna(row[0]) else ""
        if not cell: continue
        up = cell.upper()
        if "BEST REGARDS" in up:
            end_row = i; break
        if up.startswith("LOADED"):          sections.append((i, "Sailed"))
        elif up == "AT ROADS":               sections.append((i, "At Roads"))
        elif up in ("ANNOUNCED", "LINEUP"):  sections.append((i, "Lineup"))

    frames = []
    for idx, (start, status) in enumerate(sections):
        nxt = sections[idx+1][0] if idx+1 < len(sections) else end_row
        sub = raw.iloc[start+1:nxt].copy()
        sub.columns = ["CARGO","VESSEL","PORT","BERTH","ETA","TONS","SHIPPER","COORD","DEST"]
        sub["STATUS"] = status
        sub = sub[sub["CARGO"].notna() & sub["VESSEL"].notna()]
        frames.append(sub)

    if not frames: return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    df["TONS"] = pd.to_numeric(df["TONS"], errors="coerce").fillna(0)
    df = df[df["TONS"] > 0]

    df["CARGO_RAW"] = df["CARGO"].astype(str).str.strip()
    df["CARGO"]    = df["CARGO_RAW"].map(lambda x: CARGO_NORMALIZE.get(x, x))
    df["PORT"]     = df["PORT"].map(normalize_port)
    df["ZONE"]     = df["PORT"].map(port_to_zone)
    df["SHIPPER"]  = df["SHIPPER"].map(normalize_shipper)
    df["DEST"]     = df["DEST"].map(normalize_dest)
    df["VESSEL"]   = df["VESSEL"].astype(str).str.strip()
    df["BERTH"]    = df["BERTH"].astype(str).where(df["BERTH"].notna(), "")
    df["COORD"]    = df["COORD"].astype(str).where(df["COORD"].notna(), "")
    df["ETA"]      = pd.to_datetime(df["ETA"], errors="coerce", dayfirst=True)
    return df


@st.cache_data(show_spinner=False)
def load_all() -> pd.DataFrame:
    frames = []
    for label, (fname, kind) in MONTH_FILES.items():
        p = DATA_DIR / fname
        if not p.exists():
            continue
        try:
            df = _parse_one(p)
        except Exception as e:
            st.warning(f"No pude parsear {fname}: {e}")
            continue
        if df.empty: continue
        df["MONTH"] = label
        df["MONTH_STATE"] = kind
        frames.append(df)
    out = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    # Apply manual exclusions
    if not out.empty and EXCLUDED_ROWS:
        drop_mask = pd.Series(False, index=out.index)
        for crit in EXCLUDED_ROWS:
            row_mask = pd.Series(True, index=out.index)
            for col, val in crit.items():
                if col in out.columns:
                    if col == "VESSEL":
                        row_mask &= (out[col].astype(str).str.upper()
                                     == str(val).upper())
                    else:
                        row_mask &= (out[col] == val)
                else:
                    row_mask &= False
            drop_mask |= row_mask
        out = out[~drop_mask].reset_index(drop=True)
    return out


# ═════════════════════════════════════════════════════════════════════════════
# Parser de MARS (Country Balance Sheet)
# ═════════════════════════════════════════════════════════════════════════════

def _load_mars_combined() -> dict | None:
    """Combina los balance sheets de los 4 granos sumando mes por mes."""
    crops_data = {}
    for c in ALL_GRAINS_COMPONENTS:
        d = load_mars(c)  # esto usa la cache de st.cache_data
        if d is not None:
            crops_data[c] = d
    if not crops_data:
        return None

    # Unión de meses ordenados cronológicamente
    def _key(mk):
        mm, yy = mk.split("/")
        return (int(yy), int(mm))
    all_months = sorted(
        {mk for d in crops_data.values() for mk in d["months"]},
        key=_key
    )

    # Balance: sumar por concepto y mes
    combined_balance: dict[str, dict[str, float]] = {}
    for d in crops_data.values():
        for concept, vals in d["balance"].items():
            combined_balance.setdefault(concept, {})
            for mk, v in vals.items():
                combined_balance[concept][mk] = (
                    combined_balance[concept].get(mk, 0.0) + v
                )

    # Destinos: sumar tn por mes; si algún crop marca "Shipped" lo mantenemos
    combined_dests: dict[str, dict[str, dict]] = {}
    for d in crops_data.values():
        for dst, per_m in d["dests"].items():
            combined_dests.setdefault(dst, {})
            for mk, info in per_m.items():
                cell = combined_dests[dst].setdefault(
                    mk, {"status": "", "kt": 0.0}
                )
                cell["kt"] += float(info.get("kt", 0))
                if info.get("status") == "Shipped":
                    cell["status"] = "Shipped"
                elif not cell["status"]:
                    cell["status"] = info.get("status", "")

    return {
        "cargo":   "All Grains",
        "year":    "Combinado",
        "months":  all_months,
        "balance": combined_balance,
        "dests":   combined_dests,
    }


@st.cache_data(show_spinner=False)
def load_mars(cargo: str) -> dict | None:
    """Lee el balance sheet de MARS para un cargo (Maize / Wheat / Barley / Sorghum).

    También soporta "All Grains" → suma los 4 cultivos mes a mes.

    Devuelve dict:
      {
        "cargo":   nombre,
        "year":    "2026/2027",
        "months":  ["03/2026", "04/2026", ...],
        "balance": {concepto: {mes: tn_miles}},   # tn en kt
        "dests":   {destino: {mes: {"status":"Shipped"|"Expected", "kt": v}}},
      }
    Devuelve None si no encuentra el archivo.
    """
    if cargo == "All Grains":
        return _load_mars_combined()
    if cargo not in MARS_FILES:
        return None
    f = MARS_DIR / MARS_FILES[cargo]
    if not f.exists():
        return None

    title = pd.read_excel(f, sheet_name="Title", header=None)
    year = str(title.iloc[7, 1]).strip() if title.shape[0] > 7 else ""

    # ── Monthly Balance Sheet ─────────────────────────────────────────────
    bm = pd.read_excel(f, sheet_name="Monthly BalanceSheet", header=None)
    # Row 3 (idx) trae los meses, primera columna vacía, última columna "Total"
    months = []
    for c in range(1, bm.shape[1]):
        cell = bm.iloc[3, c]
        if pd.notna(cell) and str(cell).strip().lower() != "total":
            months.append(str(cell).strip())
    balance = {}
    for r in range(5, bm.shape[0]):
        label = bm.iloc[r, 0]
        if not isinstance(label, str):
            continue
        label = label.strip()
        if not label:
            continue
        per_month = {}
        for ci, mlabel in enumerate(months):
            v = bm.iloc[r, ci + 1]
            if pd.notna(v):
                try:
                    per_month[mlabel] = float(v)
                except Exception:
                    pass
        if per_month:
            balance[label] = per_month

    # ── Destinations table ────────────────────────────────────────────────
    bd = pd.read_excel(f, sheet_name="Destinations table", header=None)
    # Row 1 = Shipped/Expected ; Row 2 = mes
    status_row = [str(bd.iloc[1, c]).strip() if pd.notna(bd.iloc[1, c]) else ""
                  for c in range(1, bd.shape[1])]
    month_row  = [str(bd.iloc[2, c]).strip() if pd.notna(bd.iloc[2, c]) else ""
                  for c in range(1, bd.shape[1])]
    dests = {}
    for r in range(3, bd.shape[0]):
        label = bd.iloc[r, 0]
        if not isinstance(label, str):
            continue
        label = label.strip()
        if not label:
            continue
        per_month = {}
        for ci in range(len(month_row)):
            v = bd.iloc[r, ci + 1]
            if pd.notna(v):
                try:
                    per_month[month_row[ci]] = {
                        "status": status_row[ci],
                        "kt": float(v),
                    }
                except Exception:
                    pass
        if per_month:
            dests[label] = per_month

    return {
        "cargo":   cargo,
        "year":    year,
        "months":  months,
        "balance": balance,
        "dests":   dests,
    }


def mars_exports_total(mars: dict | None) -> float:
    """Total de exports (kt) en la campaña según MARS. 0 si no se pudo cargar."""
    if not mars: return 0.0
    e = mars["balance"].get("Exports", {})
    return float(sum(e.values()))


def mars_exports_month(mars: dict | None, mars_month_key: str) -> float:
    """Exports kt para un mes (formato MARS 'MM/YYYY')."""
    if not mars: return 0.0
    return float(mars["balance"].get("Exports", {}).get(mars_month_key, 0.0))


def get_campaign(crop: str) -> dict:
    """Devuelve la campaña del cultivo basada en los meses de MARS.

    Returns:
      {
        "months":  [(label, start, end), ...] en orden cronológico,
        "labels":  [label, ...],
        "start":   primer día,
        "end":     último día,
        "year":    "26/27" o similar,
      }
    """
    mars = load_mars(crop)
    if not mars or not mars.get("months"):
        months = _DEFAULT_CAMPAIGN_MONTHS
        return {
            "months": months,
            "labels": [m[0] for m in months],
            "start":  months[0][1],
            "end":    months[-1][2],
            "year":   "—",
        }
    out = []
    for mk in mars["months"]:
        # mk = "MM/YYYY"
        try:
            mm, yy = mk.split("/")
            mm, yy = int(mm), int(yy)
        except Exception:
            continue
        label = MARS_MONTH_LABEL.get(mk, mk)
        start = pd.Timestamp(yy, mm, 1)
        end = (pd.Timestamp(yy + 1, 1, 1)
               if mm == 12 else pd.Timestamp(yy, mm + 1, 1)) - pd.Timedelta(days=1)
        out.append((label, start, end))
    return {
        "months": out,
        "labels": [m[0] for m in out],
        "start":  out[0][1] if out else _DEFAULT_CAMPAIGN_MONTHS[0][1],
        "end":    out[-1][2] if out else _DEFAULT_CAMPAIGN_MONTHS[-1][2],
        "year":   mars.get("year", "—"),
    }


def mars_balance_dataframe(mars: dict | None) -> pd.DataFrame:
    """Devuelve el balance sheet mensual como DataFrame para mostrar."""
    if not mars: return pd.DataFrame()
    rows = []
    for concept, vals in mars["balance"].items():
        row = {"Concepto": concept}
        total = 0.0
        for m in mars["months"]:
            v = vals.get(m, 0.0)
            row[m] = v
            total += v
        row["Total"] = total
        rows.append(row)
    return pd.DataFrame(rows)


# ═════════════════════════════════════════════════════════════════════════════
# Modelo: snapshot ejecutivo y forecast
# ═════════════════════════════════════════════════════════════════════════════

def current_month_label(df: pd.DataFrame) -> str:
    """Devuelve el label del mes en curso (estado=current)."""
    cur = df[df["MONTH_STATE"] == "current"]
    if cur.empty: return "—"
    return cur["MONTH"].iloc[0]


def as_of_date(df_maize_cur: pd.DataFrame, today: pd.Timestamp,
               month_start: pd.Timestamp, month_end: pd.Timestamp) -> pd.Timestamp:
    """Fecha 'as of' del análisis dentro del mes en curso."""
    last_eta = df_maize_cur.loc[df_maize_cur["STATUS"] == "Sailed", "ETA"].max()
    if pd.isna(last_eta):
        candidate = today
    else:
        candidate = max(today, last_eta.normalize())
    # clamp al rango del mes
    return min(max(candidate, month_start), month_end)


def snapshot(df_maize: pd.DataFrame,
             target_camp_tn: float,
             target_may_tn: float,
             current_month: str,
             today: pd.Timestamp) -> dict:
    """Calcula todos los números clave del snapshot."""
    # YTD = todo lo Sailed de la campaña (Mar→hoy)
    sailed_ytd = float(df_maize.loc[df_maize["STATUS"] == "Sailed", "TONS"].sum())
    pipeline   = float(df_maize.loc[df_maize["STATUS"].isin(["At Roads","Lineup"]),
                                    "TONS"].sum())

    # Mes en curso
    cur = df_maize[df_maize["MONTH"] == current_month]
    cur_sailed = float(cur.loc[cur["STATUS"] == "Sailed", "TONS"].sum())
    cur_roads  = float(cur.loc[cur["STATUS"] == "At Roads", "TONS"].sum())
    cur_lineup = float(cur.loc[cur["STATUS"] == "Lineup",   "TONS"].sum())
    cur_pipeline_total = cur_sailed + cur_roads + cur_lineup

    # Forecast cierre mes = Sailed + AtRoads + Lineup
    forecast_month = cur_pipeline_total

    # Forecast anual: Sailed YTD + Pipeline visible (sólo cubre mes en curso) +
    # proyección lineal del residual sobre los meses restantes.
    # current month aporta su pipeline; meses futuros (Jun→Feb) aportan el
    # promedio del residual restante.
    cur_idx = next((i for i,(lbl,_,_) in enumerate(CAMPAIGN_MONTHS)
                    if lbl == current_month), None)
    months_after_current = 0 if cur_idx is None else len(CAMPAIGN_MONTHS) - cur_idx - 1
    already_in_view = sailed_ytd + pipeline  # incluye Mar+Abr+May sailed+roads+lineup
    remaining_to_target = max(0.0, target_camp_tn - already_in_view)
    forecast_annual = already_in_view + remaining_to_target  # = target en escenario ideal
    # gap = target - forecast con datos actuales (sin proyectar el faltante)
    gap_camp = target_camp_tn - already_in_view

    # Pace ideal mensual al día de hoy
    month_start, month_end = next(
        ((s,e) for lbl,s,e in CAMPAIGN_MONTHS if lbl == current_month),
        (None, None)
    )
    if month_start is not None:
        days_in_month = (month_end - month_start).days + 1
        days_done = max(1, min(days_in_month, (today - month_start).days + 1))
        ideal_today_month = target_may_tn * days_done / days_in_month
    else:
        days_in_month, days_done, ideal_today_month = 31, 1, 0.0

    # Top puerto / destino / shipper en la campaña
    def _top(col):
        g = df_maize.groupby(col)["TONS"].sum().sort_values(ascending=False)
        return (g.index[0], float(g.iloc[0])) if len(g) else ("—", 0.0)
    top_port    = _top("PORT")
    top_dest    = _top("DEST")
    top_shipper = _top("SHIPPER")

    # Confidence del forecast del mes en curso
    if cur_pipeline_total > 0:
        share_sailed = cur_sailed / cur_pipeline_total
        share_lineup = cur_lineup / cur_pipeline_total
    else:
        share_sailed = share_lineup = 0.0
    pct_days = days_done / days_in_month if days_in_month else 0
    # heurística simple: si Sailed cubre buena parte y poca % de Lineup → alta
    if share_sailed >= 0.7 or (share_sailed >= 0.5 and pct_days >= 0.7):
        conf = ("Alta", "🟢")
    elif share_sailed >= 0.3 or share_lineup <= 0.5:
        conf = ("Media", "🟡")
    else:
        conf = ("Baja", "🔴")

    return dict(
        sailed_ytd=sailed_ytd, pipeline=pipeline,
        cur_sailed=cur_sailed, cur_roads=cur_roads, cur_lineup=cur_lineup,
        cur_pipeline_total=cur_pipeline_total,
        forecast_month=forecast_month,
        forecast_annual=forecast_annual,
        gap_camp=gap_camp,
        target_camp_tn=target_camp_tn,
        target_may_tn=target_may_tn,
        ideal_today_month=ideal_today_month,
        days_done=days_done, days_in_month=days_in_month,
        delta_vs_pace=cur_sailed - ideal_today_month,
        top_port=top_port, top_dest=top_dest, top_shipper=top_shipper,
        confidence=conf,
        months_after_current=months_after_current,
        current_month=current_month,
    )


# ═════════════════════════════════════════════════════════════════════════════
# Charts
# ═════════════════════════════════════════════════════════════════════════════

def _status_color_scale():
    return alt.Scale(domain=STATUS_ORDER,
                     range=[STATUS_COLORS[s] for s in STATUS_ORDER])


def monthly_volume_bar(df_maize: pd.DataFrame) -> alt.Chart:
    """Barra apilada por mes — Sailed / At Roads / Lineup."""
    g = (df_maize.groupby(["MONTH","STATUS"])["TONS"].sum()
                  .reset_index())
    months_present = [m for m in CAMPAIGN_LABELS if m in df_maize["MONTH"].unique()]
    base = alt.Chart(g).encode(
        x=alt.X("MONTH:N", sort=months_present, title="",
                axis=alt.Axis(labelAngle=0)),
        y=alt.Y("TONS:Q", title="Tonnes", axis=alt.Axis(format="~s")),
        color=alt.Color("STATUS:N", scale=_status_color_scale(),
                        sort=STATUS_ORDER,
                        legend=alt.Legend(title="Status", orient="top")),
        tooltip=[
            alt.Tooltip("MONTH:N", title="Month"),
            alt.Tooltip("STATUS:N", title="Status"),
            alt.Tooltip("TONS:Q", title="Tn", format=",.0f"),
        ],
    )
    return base.mark_bar(size=60).properties(height=320)


@st.cache_data(show_spinner=False)
def fs_monthly_overlay(crop: str, month_start: pd.Timestamp,
                       month_end: pd.Timestamp,
                       today: pd.Timestamp) -> dict:
    """Devuelve realized + forecast de compras (FS) para superponer al chart
    mensual de Lineups.

    Realized: cumsum diario de OC hasta el cierre de ayer (igual lógica que la
    pestaña Monthly Pace de fs_maiz).
    Forecast: avg de los últimos 10 días hábiles × días hábiles restantes
    (incluyendo hoy).
    """
    empty = {
        "realized": pd.DataFrame(columns=["DATE", "FS_CUM"]),
        "forecast": pd.DataFrame(columns=["DATE", "FS_CUM"]),
        "avg": 0.0,
        "eom_expected": 0.0,
    }
    slug = LU_TO_FS_SLUG.get(crop)
    if slug is None:
        return empty
    p = FS_DIR / "data" / f"matriz_{slug}.csv"
    if not p.exists():
        return empty
    try:
        df = pd.read_csv(p)
    except Exception:
        return empty
    df = df[df["tipo"] == "diario"].copy()

    def _parse(s):
        try:
            d, m = str(s).split("/")
            return pd.Timestamp(month_start.year, int(m), int(d))
        except Exception:
            return None

    df["DATE"] = df["label"].apply(_parse)
    df = df.dropna(subset=["DATE"]).sort_values("DATE").reset_index(drop=True)

    oc_cols = [c for c in _FS_OC_GROUPS.get(slug, []) if c in df.columns]
    if not oc_cols:
        return empty
    df["OC"] = df[oc_cols].sum(axis=1).astype(float)

    today_n = pd.Timestamp(today).normalize()

    # Realized: días del mes en curso, < today, lunes-viernes
    cm = df[
        (df["DATE"].dt.month == month_start.month) &
        (df["DATE"].dt.year == month_start.year) &
        (df["DATE"] < today_n) &
        (df["DATE"].dt.weekday < 5)
    ].copy()
    if len(cm):
        cm["FS_CUM"] = cm["OC"].cumsum()
    realized = cm[["DATE", "FS_CUM"]].reset_index(drop=True) if len(cm) \
        else pd.DataFrame(columns=["DATE", "FS_CUM"])

    # Avg últimos 10 días hábiles previos a hoy (de toda la matriz, no solo
    # mes en curso, para tener señal estable a comienzo de mes)
    past = df[df["DATE"] < today_n].tail(10)
    avg = float(past["OC"].mean()) if len(past) else 0.0

    # Forecast: del último día realizado en adelante, avg por bdate
    biz_all = pd.bdate_range(month_start, month_end)
    biz_left = [d for d in biz_all if d.normalize() >= today_n]
    fc_rows = []
    last_cum = float(realized["FS_CUM"].iloc[-1]) if len(realized) else 0.0
    if len(realized):
        fc_rows.append({"DATE": realized["DATE"].iloc[-1], "FS_CUM": last_cum})
    running = last_cum
    for d in biz_left:
        running += avg
        fc_rows.append({"DATE": d, "FS_CUM": running})
    forecast = pd.DataFrame(fc_rows)

    return {
        "realized": realized,
        "forecast": forecast,
        "avg": avg,
        "eom_expected": last_cum + len(biz_left) * avg,
    }


def cumulative_monthly_chart(df_maize: pd.DataFrame, snap: dict,
                             today: pd.Timestamp,
                             fs_data: dict | None = None) -> alt.Chart:
    """Acumulado diario del mes en curso con forecast amarillo + ideal pace
    + overlay opcional de compras de Farmer Selling."""
    cur_month = snap["current_month"]
    month_start, month_end = next(
        ((s, e) for lbl, s, e in CAMPAIGN_MONTHS if lbl == cur_month),
        (None, None)
    )
    if month_start is None:
        return alt.Chart(pd.DataFrame({"x":[0],"y":[0]})).mark_point()

    cur = df_maize[df_maize["MONTH"] == cur_month].copy()
    sailed = cur[(cur["STATUS"] == "Sailed") & cur["ETA"].notna()].copy()
    sailed["DATE"] = sailed["ETA"].dt.normalize()
    daily = sailed.groupby("DATE")["TONS"].sum().sort_index()

    # El acumulado realizado se corta en la fecha en que Alpemar mandó el xls
    # (= file mtime). Esos archivos llegan una vez por semana, así que más allá
    # del último update todo es proyección, no "realizado".
    cap_date = pd.Timestamp(today).normalize()
    _cur_fname = MONTH_FILES.get(cur_month, (None, None))[0]
    if _cur_fname:
        _cur_path = DATA_DIR / _cur_fname
        if _cur_path.exists():
            _file_date = pd.Timestamp(_cur_path.stat().st_mtime, unit="s").normalize()
            cap_date = min(cap_date, _file_date)
    cap_date = max(cap_date, pd.Timestamp(month_start).normalize())

    # serie real diaria, en todos los días del mes hasta cap_date (no today)
    rng_real = pd.date_range(month_start, cap_date, freq="D")
    real_series = (daily.reindex(rng_real, fill_value=0).cumsum()
                        .reset_index())
    real_series.columns = ["DATE", "SAILED_CUM"]

    # ideal pace (gris)
    ideal = pd.DataFrame({
        "DATE": [month_start, month_end],
        "VALUE": [0.0, float(snap["target_may_tn"])],
    })

    # forecast amarillo: arranca en cap_date (último update del xls) y suma
    # (Roads + Lineup) distribuido linealmente sobre los días restantes hasta
    # fin de mes.
    sailed_today = float(real_series["SAILED_CUM"].iloc[-1]) if not real_series.empty else 0.0
    extra = float(snap["cur_roads"] + snap["cur_lineup"])
    rng_forecast = pd.date_range(cap_date, month_end, freq="D")
    if len(rng_forecast) > 1:
        slope = extra / (len(rng_forecast) - 1)
        fc_vals = [sailed_today + slope * i for i in range(len(rng_forecast))]
    else:
        fc_vals = [sailed_today + extra]
    forecast_series = pd.DataFrame({"DATE": rng_forecast, "VALUE": fc_vals})

    # ── Layers ──
    area_sailed = (alt.Chart(real_series)
                   .mark_area(opacity=0.30, color=COL_SAILED)
                   .encode(
                       x=alt.X("DATE:T", title="",
                               scale=alt.Scale(domain=[month_start, month_end])),
                       y=alt.Y("SAILED_CUM:Q", title="Cumulative tonnes",
                               axis=alt.Axis(format="~s")),
                       tooltip=[alt.Tooltip("DATE:T", title="Date"),
                                alt.Tooltip("SAILED_CUM:Q", title="Sailed cum.",
                                            format=",.0f")]))
    line_sailed = (alt.Chart(real_series)
                   .mark_line(color=COL_SAILED, strokeWidth=3)
                   .encode(x="DATE:T", y="SAILED_CUM:Q"))

    line_forecast = (alt.Chart(forecast_series)
                     .mark_line(color=COL_FORECAST, strokeWidth=3,
                                strokeDash=[2, 2])
                     .encode(x="DATE:T", y="VALUE:Q",
                             tooltip=[alt.Tooltip("DATE:T", title="Date"),
                                      alt.Tooltip("VALUE:Q", title="Forecast",
                                                  format=",.0f")]))
    area_forecast = (alt.Chart(forecast_series)
                     .mark_area(opacity=0.25, color=COL_FORECAST)
                     .encode(x="DATE:T", y="VALUE:Q"))

    line_ideal = (alt.Chart(ideal)
                  .mark_line(color=COL_TARGET, strokeWidth=2,
                             strokeDash=[6, 4])
                  .encode(x="DATE:T", y="VALUE:Q"))

    target_rule = (alt.Chart(pd.DataFrame({"y":[snap["target_may_tn"]]}))
                   .mark_rule(color="#C62828", strokeDash=[6, 4])
                   .encode(y="y:Q"))

    today_rule = (alt.Chart(pd.DataFrame({"x":[today]}))
                  .mark_rule(color="#424242", strokeDash=[3, 3])
                  .encode(x="x:T"))
    today_lbl = (alt.Chart(pd.DataFrame({"x":[today], "lbl":["Today"]}))
                 .mark_text(align="left", dx=4, dy=-2, color="#424242",
                            fontWeight="bold")
                 .encode(x="x:T", y=alt.value(8), text="lbl"))
    target_lbl = (alt.Chart(pd.DataFrame({
                    "y":[snap["target_may_tn"]],
                    "lbl":[f"Target {snap['target_may_tn']/1000:,.0f} kt"
                           .replace(",", ".")]}))
                  .mark_text(align="left", dx=5, dy=-4, color="#C62828")
                  .encode(x=alt.value(8), y="y:Q", text="lbl"))

    # ── Overlay de Farmer Selling (compras) — opcional ─────────────────
    fs_layers = []
    if fs_data is not None:
        fs_real = fs_data.get("realized", pd.DataFrame())
        fs_fc   = fs_data.get("forecast", pd.DataFrame())
        if len(fs_real) > 0:
            fs_layers.append(
                alt.Chart(fs_real)
                .mark_line(color="#5E35B1", strokeWidth=3)
                .encode(
                    x="DATE:T", y=alt.Y("FS_CUM:Q"),
                    tooltip=[alt.Tooltip("DATE:T", title="Date"),
                             alt.Tooltip("FS_CUM:Q",
                                         title="FS compras acum.",
                                         format=",.0f")],
                )
            )
        if len(fs_fc) > 0:
            fs_layers.append(
                alt.Chart(fs_fc)
                .mark_line(color="#B39DDB", strokeWidth=3,
                           strokeDash=[6, 4])
                .encode(
                    x="DATE:T", y=alt.Y("FS_CUM:Q"),
                    tooltip=[alt.Tooltip("DATE:T", title="Date"),
                             alt.Tooltip("FS_CUM:Q",
                                         title="FS forecast",
                                         format=",.0f")],
                )
            )

    layers = ([area_sailed, area_forecast, line_ideal,
               line_sailed, line_forecast, target_rule, target_lbl,
               today_rule, today_lbl] + fs_layers)
    return alt.layer(*layers).properties(height=380)


def cumulative_annual_chart(df_maize: pd.DataFrame, snap: dict,
                            today: pd.Timestamp,
                            mars: dict | None) -> alt.Chart:
    """Acumulado anual en una sola trayectoria, sin comparaciones.

    Para los meses con lineup (Mar/Abr/May 2026) usa el pipeline total
    (Sailed + At Roads + Lineup). Para los meses siguientes (Jun→Feb) usa
    los Expected mensuales de la fila Exports de MARS. La línea pasa de
    sólida a punteada en la transición.
    """
    months_with_lineup = set(df_maize["MONTH"].unique())
    mars_exports = (mars["balance"].get("Exports", {})
                    if mars and "balance" in mars else {})
    label_to_mars = {v: k for k, v in MARS_MONTH_LABEL.items()}

    real_rows, fc_rows = [], []
    running = 0.0
    last_real = None  # (date, value, label)

    for label, m_start, m_end in CAMPAIGN_MONTHS:
        if label in months_with_lineup:
            tn = float(df_maize[df_maize["MONTH"] == label]["TONS"].sum())
            running += tn
            real_rows.append({"DATE": m_end, "VALUE": running,
                              "LABEL": label, "ADDED": tn,
                              "SRC": "Lineup"})
            last_real = (m_end, running, label)
        else:
            mars_key = label_to_mars.get(label)
            mars_kt = float(mars_exports.get(mars_key, 0)) if mars_key else 0
            if mars_kt <= 0 and not fc_rows and last_real is None:
                continue  # nada para empezar
            tn = mars_kt * 1000
            running += tn
            fc_rows.append({"DATE": m_end, "VALUE": running,
                            "LABEL": label, "ADDED": tn,
                            "SRC": "MARS"})

    # Para conectar visualmente las dos series, agregamos el último punto
    # real como primer punto de la forecast (no se ve repetido porque tienen
    # marcadores distintos)
    if last_real is not None and fc_rows:
        fc_rows = [{"DATE": last_real[0], "VALUE": last_real[1],
                    "LABEL": last_real[2], "ADDED": 0.0,
                    "SRC": "transition"}] + fc_rows

    # Agregar punto de origen para que la línea sólida arranque en 0
    if real_rows:
        real_rows = ([{"DATE": CAMPAIGN_START, "VALUE": 0.0,
                       "LABEL": "start", "ADDED": 0.0, "SRC": "start"}]
                     + real_rows)

    real_df = pd.DataFrame(real_rows)
    fc_df   = pd.DataFrame(fc_rows)

    # ── Capas ──
    x_scale = alt.Scale(domain=[CAMPAIGN_START, CAMPAIGN_END])
    y_axis  = alt.Y("VALUE:Q", title="Cumulative tonnes",
                    axis=alt.Axis(format="~s"))
    x_axis  = alt.X("DATE:T", title="", scale=x_scale)

    line_real = (alt.Chart(real_df)
                 .mark_line(color=COL_SAILED, strokeWidth=3.5,
                            interpolate="monotone")
                 .encode(x=x_axis, y=y_axis,
                         tooltip=[
                             alt.Tooltip("LABEL:N",  title="Month"),
                             alt.Tooltip("ADDED:Q",  title="Sumado tn",
                                         format=",.0f"),
                             alt.Tooltip("VALUE:Q",  title="Cumulative tn",
                                         format=",.0f"),
                             alt.Tooltip("SRC:N",    title="Source"),
                         ]))
    points_real = (alt.Chart(real_df[real_df["LABEL"] != "start"])
                   .mark_point(color=COL_SAILED, filled=True, size=90)
                   .encode(x=x_axis, y=y_axis,
                           tooltip=[
                               alt.Tooltip("LABEL:N", title="Month"),
                               alt.Tooltip("ADDED:Q", title="Lineup tn",
                                           format=",.0f"),
                               alt.Tooltip("VALUE:Q", title="Cumulative",
                                           format=",.0f"),
                           ]))

    layers = [line_real, points_real]

    if not fc_df.empty:
        line_fc = (alt.Chart(fc_df)
                   .mark_line(color=COL_FORECAST, strokeWidth=3.5,
                              strokeDash=[5, 4], interpolate="monotone")
                   .encode(x=x_axis, y=y_axis,
                           tooltip=[
                               alt.Tooltip("LABEL:N",  title="Month"),
                               alt.Tooltip("ADDED:Q",  title="MARS tn",
                                           format=",.0f"),
                               alt.Tooltip("VALUE:Q",  title="Acumulado tn",
                                           format=",.0f"),
                               alt.Tooltip("SRC:N",    title="Source"),
                           ]))
        points_fc = (alt.Chart(fc_df[fc_df["SRC"] != "transition"])
                     .mark_point(color=COL_FORECAST, filled=True, size=70,
                                 shape="diamond")
                     .encode(x=x_axis, y=y_axis,
                             tooltip=[
                                 alt.Tooltip("LABEL:N",  title="Month"),
                                 alt.Tooltip("ADDED:Q",  title="MARS tn",
                                             format=",.0f"),
                                 alt.Tooltip("VALUE:Q",  title="Acumulado",
                                             format=",.0f"),
                             ]))
        layers += [line_fc, points_fc]

    # Línea vertical de "Today" como referencia posicional, no comparativa
    today_rule = (alt.Chart(pd.DataFrame({"x": [today]}))
                  .mark_rule(color="#9E9E9E", strokeDash=[2, 3])
                  .encode(x="x:T"))
    today_lbl  = (alt.Chart(pd.DataFrame({"x": [today], "lbl": ["Today"]}))
                  .mark_text(align="left", dx=4, dy=-4, color="#666",
                             fontWeight="bold", fontSize=11)
                  .encode(x="x:T", y=alt.value(10), text="lbl"))
    layers += [today_rule, today_lbl]

    return alt.layer(*layers).properties(height=400)


def waterfall_chart(snap: dict) -> alt.Chart:
    """Waterfall: Target → -Sailed → -AtRoads → -Lineup → Gap."""
    steps = [
        ("Target",   snap["target_camp_tn"],     "total"),
        ("Sailed",   -snap["sailed_ytd"],        "minus"),
        ("At Roads", -snap["cur_roads"],         "minus"),
        ("Lineup",   -snap["cur_lineup"],        "minus"),
        ("Gap",       snap["target_camp_tn"]
                      - snap["sailed_ytd"]
                      - snap["cur_roads"]
                      - snap["cur_lineup"],     "remaining"),
    ]
    rows, running = [], 0.0
    for label, val, kind in steps:
        if kind in ("total", "remaining"):
            rows.append({"step": label, "start": 0.0, "end": val,
                         "delta": val, "kind": kind})
        else:
            new_run = running + val  # val es negativo
            rows.append({"step": label, "start": new_run, "end": running,
                         "delta": val, "kind": kind})
            running = new_run
    if running == 0.0:
        # caso edge: si no se acumuló nada, mantenemos
        pass
    # ajustar running cuando es total (no acumulamos)
    # recomputamos running para que sea consistente: parte del Target hacia abajo
    rows = []
    running = float(snap["target_camp_tn"])
    rows.append({"step": "Target",   "start": 0,        "end": running,
                 "delta": running,   "kind": "total"})
    for lbl, val in [("Sailed",   snap["sailed_ytd"]),
                     ("At Roads", snap["cur_roads"]),
                     ("Lineup",   snap["cur_lineup"])]:
        new_run = running - val
        rows.append({"step": lbl, "start": new_run, "end": running,
                     "delta": -val, "kind": "minus"})
        running = new_run
    rows.append({"step": "Gap restante", "start": 0, "end": running,
                 "delta": running, "kind": "remaining"})

    wf = pd.DataFrame(rows)
    color_scale = alt.Scale(
        domain=["total","minus","remaining"],
        range=["#1565C0", COL_SAILED, "#C62828"]
    )
    chart = (alt.Chart(wf)
             .mark_bar(size=50)
             .encode(
                 x=alt.X("step:N",
                         sort=["Target","Sailed","At Roads","Lineup","Gap restante"],
                         title=""),
                 y=alt.Y("start:Q", title="Tonnes",
                         axis=alt.Axis(format="~s")),
                 y2="end:Q",
                 color=alt.Color("kind:N", scale=color_scale,
                                 legend=None),
                 tooltip=[
                     alt.Tooltip("step:N", title="Paso"),
                     alt.Tooltip("delta:Q", title="Δ", format=",.0f"),
                     alt.Tooltip("end:Q", title="Nivel", format=",.0f"),
                 ],
             )
             .properties(height=320))
    return chart


def pipeline_table(df: pd.DataFrame, dim: str, share_mode: bool = False,
                   top_n: int | None = None) -> pd.DataFrame:
    """Tabla dim × (Sailed / At Roads / Lineup / Pipeline / Share)."""
    pv = df.pivot_table(index=dim, columns="STATUS", values="TONS",
                        aggfunc="sum", fill_value=0)
    for c in STATUS_ORDER:
        if c not in pv.columns: pv[c] = 0
    pv = pv[STATUS_ORDER]
    pv["Pipeline"] = pv.sum(axis=1)
    pv = pv.sort_values("Pipeline", ascending=False)
    if top_n: pv = pv.head(top_n)
    grand = float(pv["Pipeline"].sum())
    pv["Share %"] = pv["Pipeline"] / grand * 100 if grand else 0.0

    out = pv.copy()
    if share_mode:
        for c in STATUS_ORDER + ["Pipeline"]:
            out[c] = pv[c].map(lambda v: fmt_pct(v, grand))
    else:
        for c in STATUS_ORDER + ["Pipeline"]:
            out[c] = pv[c].map(fmt_int)
    out["Share %"] = pv["Share %"].map(lambda v: f"{v:.1f}%".replace(".",","))
    return out


def monthly_evolution_stacked(df: pd.DataFrame, dim: str, top_n: int = 8,
                              height: int = 320) -> alt.Chart:
    """Stacked bar mes × dim. Mantiene escala granel filtrada."""
    top_groups = (df.groupby(dim)["TONS"].sum()
                    .sort_values(ascending=False).head(top_n).index.tolist())
    work = df.copy()
    work[dim] = work[dim].where(work[dim].isin(top_groups), other="Otros")
    g = (work.groupby(["MONTH", dim])["TONS"].sum().reset_index())

    months_present = [m for m in CAMPAIGN_LABELS if m in g["MONTH"].unique()]
    order = top_groups + (["Otros"] if "Otros" in g[dim].unique() else [])

    chart = (alt.Chart(g)
             .mark_bar(size=60)
             .encode(
                 x=alt.X("MONTH:N", sort=months_present, title="",
                         axis=alt.Axis(labelAngle=0)),
                 y=alt.Y("TONS:Q", title="Tonnes",
                         axis=alt.Axis(format="~s")),
                 color=alt.Color(f"{dim}:N", sort=order,
                                 scale=alt.Scale(scheme="tableau10"),
                                 legend=alt.Legend(title=dim.title(),
                                                   orient="right")),
                 tooltip=[
                     alt.Tooltip("MONTH:N", title="Month"),
                     alt.Tooltip(f"{dim}:N", title=dim.title()),
                     alt.Tooltip("TONS:Q", title="Tn", format=",.0f"),
                 ],
             )
             .properties(height=height))
    return chart


def donut_chart(df: pd.DataFrame, dim: str, top_n: int = 10) -> alt.Chart:
    g = (df.groupby(dim)["TONS"].sum()
           .sort_values(ascending=False).reset_index())
    if len(g) > top_n:
        top = g.head(top_n).copy()
        others_tn = float(g["TONS"].iloc[top_n:].sum())
        top = pd.concat([top, pd.DataFrame({dim:["Otros"], "TONS":[others_tn]})])
        g = top
    chart = (alt.Chart(g)
             .mark_arc(innerRadius=70)
             .encode(
                 theta=alt.Theta("TONS:Q"),
                 color=alt.Color(f"{dim}:N",
                                 scale=alt.Scale(scheme="tableau10"),
                                 legend=alt.Legend(title="", orient="right")),
                 tooltip=[
                     alt.Tooltip(f"{dim}:N", title=dim.title()),
                     alt.Tooltip("TONS:Q", title="Tn", format=",.0f"),
                 ],
             )
             .properties(height=340))
    return chart


def expected_plus_status_chart(df_cur: pd.DataFrame, dim: str,
                               top_n: int = 10,
                               height: int = 420,
                               dim_label: str | None = None) -> alt.Chart:
    """For each value of `dim`, draw one thick **Expected** bar (total)
    + three thinner bars for Sailed / At Roads / Lineup.
    Top-N groups, X axis horizontal, Y axis = kt.
    """
    by_dim_st = (df_cur.groupby([dim, "STATUS"])["TONS"].sum()
                       .unstack(fill_value=0))
    for s in STATUS_ORDER:
        if s not in by_dim_st.columns:
            by_dim_st[s] = 0.0
    by_dim_st["Expected"] = by_dim_st[STATUS_ORDER].sum(axis=1)
    by_dim_st = by_dim_st.sort_values("Expected", ascending=False).head(top_n)
    order = by_dim_st.index.tolist()

    rows = []
    for k, r in by_dim_st.iterrows():
        rows.append({"K": k, "TYPE": "Expected", "kt": r["Expected"] / 1000})
        for s in STATUS_ORDER:
            rows.append({"K": k, "TYPE": s, "kt": r[s] / 1000})
    long_df = pd.DataFrame(rows)
    if long_df.empty:
        return alt.Chart(pd.DataFrame({"x": [0], "y": [0]})).mark_point()

    TYPE_ORDER  = ["Expected", "Sailed", "At Roads", "Lineup"]
    TYPE_COLORS = {
        "Expected": "#616161",
        "Sailed":   COL_SAILED,
        "At Roads": COL_ROADS,
        "Lineup":   COL_LINEUP,
    }
    color_scale = alt.Scale(
        domain=TYPE_ORDER,
        range=[TYPE_COLORS[t] for t in TYPE_ORDER],
    )

    base_enc = dict(
        x=alt.X("K:N", sort=order, title="",
                axis=alt.Axis(labelAngle=-30, labelFontSize=11)),
        xOffset=alt.XOffset("TYPE:N", sort=TYPE_ORDER),
        y=alt.Y("kt:Q", title="kt", axis=alt.Axis(format=",.0f")),
        color=alt.Color("TYPE:N", scale=color_scale, sort=TYPE_ORDER,
                        legend=alt.Legend(title="", orient="top")),
        tooltip=[
            alt.Tooltip("K:N",    title=dim_label or dim.title()),
            alt.Tooltip("TYPE:N", title="Type"),
            alt.Tooltip("kt:Q",   title="kt", format=",.1f"),
        ],
    )
    big = (alt.Chart(long_df[long_df["TYPE"] == "Expected"])
           .mark_bar(size=22).encode(**base_enc))
    small = (alt.Chart(long_df[long_df["TYPE"] != "Expected"])
             .mark_bar(size=11).encode(**base_enc))
    return (big + small).properties(height=height)


def expected_plus_month_chart(df: pd.DataFrame, dim: str,
                              top_n: int = 10,
                              height: int = 420,
                              dim_label: str | None = None) -> alt.Chart:
    """For each value of `dim`, draw one thick **Total** bar (sum across
    all loaded months) + one thinner bar per month so you can see which
    month drove the total.
    """
    by_dim_m = (df.groupby([dim, "MONTH"])["TONS"].sum()
                  .unstack(fill_value=0))
    months_present = [m for m in CAMPAIGN_LABELS if m in by_dim_m.columns]
    if not months_present:
        return alt.Chart(pd.DataFrame({"x":[0],"y":[0]})).mark_point()
    by_dim_m = by_dim_m[months_present]
    by_dim_m["Total"] = by_dim_m.sum(axis=1)
    by_dim_m = by_dim_m.sort_values("Total", ascending=False).head(top_n)
    order = by_dim_m.index.tolist()

    rows = []
    for k, r in by_dim_m.iterrows():
        rows.append({"K": k, "TYPE": "Total", "kt": r["Total"] / 1000})
        for m in months_present:
            rows.append({"K": k, "TYPE": m, "kt": r[m] / 1000})
    long_df = pd.DataFrame(rows)

    TYPE_ORDER  = ["Total"] + months_present
    month_palette = ["#1565C0", "#26A69A", "#FFC107", "#EF6C00", "#7B1FA2",
                     "#2E7D32", "#C62828", "#00838F", "#5D4037", "#6A1B9A",
                     "#283593", "#558B2F"]
    range_colors = ["#616161"] + month_palette[:len(months_present)]
    color_scale  = alt.Scale(domain=TYPE_ORDER, range=range_colors)

    base_enc = dict(
        x=alt.X("K:N", sort=order, title="",
                axis=alt.Axis(labelAngle=-30, labelFontSize=11)),
        xOffset=alt.XOffset("TYPE:N", sort=TYPE_ORDER),
        y=alt.Y("kt:Q", title="kt", axis=alt.Axis(format=",.0f")),
        color=alt.Color("TYPE:N", scale=color_scale, sort=TYPE_ORDER,
                        legend=alt.Legend(title="", orient="top")),
        tooltip=[
            alt.Tooltip("K:N",    title=dim_label or dim.title()),
            alt.Tooltip("TYPE:N", title="Month"),
            alt.Tooltip("kt:Q",   title="kt", format=",.1f"),
        ],
    )
    big = (alt.Chart(long_df[long_df["TYPE"] == "Total"])
           .mark_bar(size=22).encode(**base_enc))
    small = (alt.Chart(long_df[long_df["TYPE"] != "Total"])
             .mark_bar(size=11).encode(**base_enc))
    return (big + small).properties(height=height)


# ═════════════════════════════════════════════════════════════════════════════
# Sidebar
# ═════════════════════════════════════════════════════════════════════════════

df_all = load_all()

if df_all.empty:
    st.error("No encontré ningún archivo de lineups en la carpeta.")
    st.stop()

with st.sidebar:
    st.title("🚢 Lineups")
    st.caption("Argentina · Grain Shipments")
    st.divider()

    # ── Crop selector ──────────────────────────────────────────────────
    crop_options = ["All Grains", "Maize", "Wheat", "Barley", "Sorghum"]
    crop = st.selectbox(
        "Crop",
        crop_options,
        index=1,  # default Maize (All Grains stays first but not default)
        format_func=lambda c: f"{CROP_NAMES[c][1]} {CROP_NAMES[c][0]}",
        key="crop_sel",
    )
    crop_label, crop_emoji = CROP_NAMES[crop]
    st.caption(f"📅 {CROP_YEAR_LABEL.get(crop, '')}")
    st.divider()

    # Compute the crop's campaign and propagate to globals
    _campaign = get_campaign(crop)
    CAMPAIGN_MONTHS = _campaign["months"]
    CAMPAIGN_LABELS = _campaign["labels"]
    CAMPAIGN_START  = _campaign["start"]
    CAMPAIGN_END    = _campaign["end"]

    months = list(MONTH_FILES.keys())
    months_present = [m for m in months if m in df_all["MONTH"].unique()]
    month_sel = st.multiselect("Month", months_present, default=months_present)

    # Crop universe (one or many if "All Grains")
    if crop == "All Grains":
        crop_mask = df_all["CARGO"].isin(ALL_GRAINS_COMPONENTS)
    else:
        crop_mask = df_all["CARGO"] == crop

    df_step = df_all[crop_mask & df_all["MONTH"].isin(month_sel)] \
              if month_sel else df_all[crop_mask]

    status_sel = st.multiselect("Status", STATUS_ORDER, default=STATUS_ORDER)

    zones_present = [z for z in ZONE_ORDER if z in df_step["ZONE"].unique()]
    zone_sel = st.multiselect("Zone", zones_present, default=zones_present)

    ports = sorted(
        df_step[df_step["ZONE"].isin(zone_sel)]["PORT"].dropna().unique()
    ) if zone_sel else sorted(df_step["PORT"].dropna().unique())
    port_sel = st.multiselect("Port (detail)", ports, default=[])

    dests = sorted(df_step["DEST"].dropna().unique())
    dest_sel = st.multiselect("Destination", dests, default=[])

    shippers = sorted(df_step["SHIPPER"].dropna().unique())
    shipper_sel = st.multiselect("Shipper", shippers, default=[])

    st.divider()
    share_mode = st.toggle("📊 Show as % share", value=False,
                           help="Pivot tables as % of total.")

    st.divider()
    st.subheader(f"{crop_label} targets (kt)")
    # Load MARS for the selected crop
    mars_crop = load_mars(crop)
    if mars_crop is not None:
        default_camp = int(round(mars_exports_total(mars_crop)))
        # current month = "05/2026"
        default_may  = int(round(mars_exports_month(mars_crop, "05/2026")))
        st.caption(f"🟢 MARS · {mars_crop['year']} · defaults auto-loaded")
    else:
        default_camp, default_may = 0, 0
        st.caption("⚪ MARS not available for this crop")

    target_camp = st.number_input(f"Crop year target ({crop_label})",
                                  min_value=0, value=default_camp, step=100)
    target_may  = st.number_input("Current month target",
                                  min_value=0, value=default_may, step=10)

    st.divider()
    st.caption(f"📁 {len(df_all)} total records · "
               f"{df_all['MONTH'].nunique()} months")
    if mars_crop is not None:
        st.caption(f"📑 MARS {crop}: {len(mars_crop['dests'])} destinations · "
                   f"{len(mars_crop['months'])} months")


# Aplicar filtros: el universo SIEMPRE arranca filtrado por cultivo
if crop == "All Grains":
    _crop_mask = df_all["CARGO"].isin(ALL_GRAINS_COMPONENTS)
else:
    _crop_mask = df_all["CARGO"] == crop

df = df_all[_crop_mask].copy()
if month_sel:   df = df[df["MONTH"].isin(month_sel)]
if status_sel:  df = df[df["STATUS"].isin(status_sel)]
if zone_sel:    df = df[df["ZONE"].isin(zone_sel)]
if port_sel:    df = df[df["PORT"].isin(port_sel)]
if dest_sel:    df = df[df["DEST"].isin(dest_sel)]
if shipper_sel: df = df[df["SHIPPER"].isin(shipper_sel)]

# DataFrame del cultivo para snapshot/charts (ignora estado, mantiene resto)
df_crop_all = df_all[_crop_mask].copy()
if dest_sel:    df_crop_all = df_crop_all[df_crop_all["DEST"].isin(dest_sel)]
if shipper_sel: df_crop_all = df_crop_all[df_crop_all["SHIPPER"].isin(shipper_sel)]


# ═════════════════════════════════════════════════════════════════════════════
# Snapshot ejecutivo
# ═════════════════════════════════════════════════════════════════════════════

st.title("🚢 Lineups · Argentina Grain Shipments")
today = pd.Timestamp(date.today())
# Si la fecha real del sistema está fuera de la campaña, usamos un día sensato
# dentro del mes en curso para que los gráficos no se rompan.
cur_month_lbl = current_month_label(df_all)
cur_bounds = next(((s,e) for lbl,s,e in CAMPAIGN_MONTHS if lbl == cur_month_lbl),
                  (None, None))
if cur_bounds[0] is not None:
    today = max(min(today, cur_bounds[1]), cur_bounds[0])

snap = snapshot(
    df_maize=df_crop_all,
    target_camp_tn=target_camp * 1000,
    target_may_tn=target_may  * 1000,
    current_month=cur_month_lbl,
    today=today,
)

st.caption(
    f"📅 Today: **{today.strftime('%d-%b-%Y')}**  ·  "
    f"Current month: **{cur_month_lbl}** (day {snap['days_done']}/{snap['days_in_month']})  ·  "
    f"Crop: {crop_emoji} **{crop_label}**"
)

# CEO summary cards
s1, s2, s3 = st.columns(3)
s1.metric(
    f"Forecast {cur_month_lbl.split()[0]}",
    fmt_tn(snap["forecast_month"]),
    f"{fmt_pct(snap['forecast_month'], snap['target_may_tn'])} of target",
)
s2.metric(
    f"Total cumulative end of {cur_month_lbl.split()[0]} expected",
    fmt_tn(snap["sailed_ytd"] + snap["pipeline"]),
    f"{fmt_pct(snap['sailed_ytd']+snap['pipeline'], snap['target_camp_tn'])} of target",
)
s3.metric(
    "Gap vs Target",
    fmt_tn(snap["gap_camp"]),
    "To be committed" if snap["gap_camp"] > 0 else "Over-committed",
    delta_color="inverse",
)

st.divider()


# ═════════════════════════════════════════════════════════════════════════════
# Tabs
# ═════════════════════════════════════════════════════════════════════════════

(tab_current, tab_overview, tab_port, tab_dest,
 tab_ship, tab_data) = st.tabs(
    ["📅 Current Month", "📊 Overview", "🏭 Port", "🌍 Destination",
     "🚛 Shipper", "📋 Data"]
)


# ────────────────────────── CURRENT MONTH ────────────────────────────────────
with tab_current:
    st.subheader(f"📅 {cur_month_lbl} · {crop_emoji} {crop_label}")

    # KPIs del mes en curso
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric(f"Sailed {cur_month_lbl.split()[0]}",
              fmt_tn(snap["cur_sailed"]),
              fmt_pct(snap["cur_sailed"], snap["target_may_tn"]))
    k2.metric("At Roads + Lineup",
              fmt_tn(snap["cur_roads"] + snap["cur_lineup"]),
              f"{fmt_tn(snap['cur_roads'])} + {fmt_tn(snap['cur_lineup'])}")
    k3.metric("Current",
              fmt_tn(snap["cur_pipeline_total"]),
              fmt_pct(snap["cur_pipeline_total"], snap["target_may_tn"]))
    k4.metric("Month target",
              fmt_tn(snap["target_may_tn"]),
              f"{target_may:,} kt".replace(",", "."))
    k5.metric("vs Ideal Pace",
              fmt_tn(abs(snap["delta_vs_pace"])),
              "↑ ahead" if snap["delta_vs_pace"] >= 0 else "↓ behind")

    st.divider()

    # 1) Cumulative monthly (con forecast amarillo + overlay FS)
    st.subheader("📈 Monthly cumulative")

    # FS overlay (compras): solo cuando el cargo tiene equivalente en FS
    _cur_bounds_fs = next(((s, e) for lbl, s, e in CAMPAIGN_MONTHS
                           if lbl == cur_month_lbl), (None, None))
    _fs_overlay = None
    if crop in LU_TO_FS_SLUG and _cur_bounds_fs[0] is not None:
        _fs_overlay = fs_monthly_overlay(
            crop=crop,
            month_start=_cur_bounds_fs[0],
            month_end=_cur_bounds_fs[1],
            today=today,
        )

    st.altair_chart(
        cumulative_monthly_chart(df_crop_all, snap, today, _fs_overlay),
        use_container_width=True,
    )
    _fs_caption_extra = ""
    if _fs_overlay and len(_fs_overlay["realized"]) > 0:
        _fs_caption_extra = (
            " · 🟪 **FS compras** (sólido = realizado hasta ayer, "
            "punteado = proyección con avg de últimos 10 días "
            f"≈ **{_fs_overlay['avg']/1000:,.1f} kt/día**)"
        ).replace(",", ".")
    st.caption(
        "🟢 Sailed actual · 🟡 Forecast (Sailed + At Roads + Lineup distributed "
        "over remaining days) · ⬜ Grey dashed: linear Ideal Pace · "
        "🔴 Red line: month target" + _fs_caption_extra
    )

    st.divider()

    # Universo del mes en curso
    df_cur_month = df[df["MONTH"] == cur_month_lbl]

    if df_cur_month.empty:
        st.info("No records for the current month with the active filters.")
    else:
        # 2) Top 10 shippers
        st.subheader(f"🚛 Top 10 shippers · {cur_month_lbl}")
        st.altair_chart(
            expected_plus_status_chart(df_cur_month, "SHIPPER", top_n=10,
                                       dim_label="Shipper"),
            use_container_width=True,
        )

        st.divider()

        # 3) Ports by zone (Up River / Bahía Blanca / Necochea)
        st.subheader(f"🏭 Ports · {cur_month_lbl}")

        # 3 donuts: one per zone showing Sailed / At Roads / Lineup internal mix
        zones_ordered = (df_cur_month.groupby("ZONE")["TONS"].sum()
                                      .sort_values(ascending=False)
                                      .index.tolist())
        if zones_ordered:
            dcols = st.columns(len(zones_ordered))
            for i, z in enumerate(zones_ordered):
                zone_df = df_cur_month[df_cur_month["ZONE"] == z]
                by_st = zone_df.groupby("STATUS")["TONS"].sum()
                total_kt = float(by_st.sum()) / 1000
                donut_df = pd.DataFrame({
                    "Status": STATUS_ORDER,
                    "Tn":     [float(by_st.get(s, 0)) for s in STATUS_ORDER],
                })
                donut_df = donut_df[donut_df["Tn"] > 0]
                with dcols[i]:
                    st.metric(z, f"{total_kt:,.0f} kt".replace(",", "."))
                    if donut_df.empty:
                        st.caption("No data")
                        continue
                    donut = (alt.Chart(donut_df)
                             .mark_arc(innerRadius=55, outerRadius=95)
                             .encode(
                                 theta=alt.Theta("Tn:Q"),
                                 color=alt.Color(
                                     "Status:N",
                                     scale=_status_color_scale(),
                                     sort=STATUS_ORDER,
                                     legend=alt.Legend(orient="bottom",
                                                       title=None)),
                                 tooltip=[
                                     alt.Tooltip("Status:N"),
                                     alt.Tooltip("Tn:Q", format=",.0f"),
                                 ],
                             )
                             .properties(height=260))
                    st.altair_chart(donut, use_container_width=True)

        st.divider()

        # 4) Top 10 destinations
        st.subheader(f"🌍 Top 10 destinations · {cur_month_lbl}")
        st.altair_chart(
            expected_plus_status_chart(df_cur_month, "DEST", top_n=10,
                                       dim_label="Destination"),
            use_container_width=True,
        )
        st.caption("Per group: one thick **Expected** bar (Sailed + At Roads + "
                   "Lineup) plus three thinner bars with the status breakdown.")

        st.divider()

        # 5) Current month volume — aggregate + status breakdown side by side
        st.subheader(f"📊 Volume {cur_month_lbl.split()[0]} · aggregate + breakdown")

        volume_label = f"Volume {cur_month_lbl.split()[0]}"
        vol_total = snap["cur_sailed"] + snap["cur_roads"] + snap["cur_lineup"]
        vol_df = pd.DataFrame([
            {"TYPE": volume_label,  "kt": vol_total/1000},
            {"TYPE": "Loaded",      "kt": snap["cur_sailed"]/1000},
            {"TYPE": "At Roads",    "kt": snap["cur_roads"]/1000},
            {"TYPE": "Lineup",      "kt": snap["cur_lineup"]/1000},
        ])
        vol_order = [volume_label, "Loaded", "At Roads", "Lineup"]
        vol_color = alt.Scale(
            domain=vol_order,
            range=["#616161", COL_SAILED, COL_ROADS, COL_LINEUP],
        )
        vol_chart = (alt.Chart(vol_df)
                     .mark_bar(size=80)
                     .encode(
                         x=alt.X("TYPE:N", sort=vol_order, title="",
                                 axis=alt.Axis(labelAngle=0,
                                               labelFontSize=12)),
                         y=alt.Y("kt:Q", title="kt",
                                 axis=alt.Axis(format=",.0f")),
                         color=alt.Color("TYPE:N", scale=vol_color,
                                         sort=vol_order, legend=None),
                         tooltip=[
                             alt.Tooltip("TYPE:N", title=""),
                             alt.Tooltip("kt:Q", title="kt", format=",.1f"),
                         ],
                     )
                     .properties(height=320))
        # Etiqueta de valor encima de cada barra
        vol_text = (alt.Chart(vol_df)
                    .mark_text(dy=-8, fontSize=12, fontWeight="bold",
                               color="#424242")
                    .encode(
                        x=alt.X("TYPE:N", sort=vol_order),
                        y="kt:Q",
                        text=alt.Text("kt:Q", format=",.0f"),
                    ))
        st.altair_chart((vol_chart + vol_text), use_container_width=True)

# ────────────────────────── OVERVIEW ─────────────────────────────────────────
with tab_overview:

    # Annual cumulative — lineup up to today + MARS from next month onward
    st.subheader(f"📊 Annual Cumulative · "
                 f"{CROP_YEAR_LABEL.get(crop, 'Crop year')}")

    # Lineup cumulative (Mar+Apr+May full pipeline)
    lineup_accum = float(df_crop_all["TONS"].sum())
    # Sum of MARS Expected for the months without lineup
    months_with_lineup = set(df_crop_all["MONTH"].unique())
    mars_exp = (mars_crop["balance"].get("Exports", {})
                if mars_crop else {})
    label_to_mars = {v: k for k, v in MARS_MONTH_LABEL.items()}
    mars_future_kt = sum(
        v for k, v in mars_exp.items()
        if MARS_MONTH_LABEL.get(k) not in months_with_lineup
    )
    eoy_total = lineup_accum + mars_future_kt * 1000

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Cumulative to date (Lineup)",
              fmt_tn(lineup_accum))
    k2.metric("Rest of year (MARS)",
              fmt_tn(mars_future_kt * 1000),
              f"{mars_future_kt:,.0f} kt".replace(",", "."))
    k3.metric("Estimated crop year close",
              fmt_tn(eoy_total))
    k4.metric("MARS crop year exports",
              fmt_tn(sum(mars_exp.values()) * 1000) if mars_exp else "—")

    st.altair_chart(
        cumulative_annual_chart(df_crop_all, snap, today, mars_crop),
        use_container_width=True,
    )
    st.caption(
        "🟢 **Solid** = actual lineup (Sailed + At Roads + Lineup) for the "
        "months with data · 🟡 **Dashed** = MARS Exports Expected for the "
        "rest of the crop year. Single trajectory, no comparisons."
    )



# ────────────────────────── PORT ─────────────────────────────────────────────
with tab_port:
    view = st.radio("View", ["By zone", "Port detail"],
                    horizontal=True, key="port_view")
    dim = "ZONE" if view == "By zone" else "PORT"

    months_loaded = sorted(df["MONTH"].unique().tolist())
    months_label = " + ".join(m.split()[0] for m in months_loaded) \
                   if months_loaded else "—"

    st.subheader(f"🏭 {dim.title()} · cumulative · {months_label}")
    if df.empty:
        st.info("No records with the active filters.")
    else:
        st.altair_chart(
            expected_plus_month_chart(df, dim, top_n=15,
                                      dim_label=dim.title()),
            use_container_width=True,
        )
        st.caption("Per group: one thick **Total** bar (cumulative across all "
                   "loaded months) plus one thinner bar per month so you can "
                   "see which months drove the total.")

    st.subheader(f"Summary table · {dim.title()}")
    st.dataframe(pipeline_table(df, dim, share_mode=share_mode),
                 use_container_width=True)


# ────────────────────────── DESTINATION ──────────────────────────────────────
with tab_dest:
    top_n = st.slider("Top N destinations", 5, 30, 12, key="dest_topn")

    months_loaded = sorted(df["MONTH"].unique().tolist())
    months_label = " + ".join(m.split()[0] for m in months_loaded) \
                   if months_loaded else "—"

    st.subheader(f"🌍 Top {top_n} destinations · cumulative · {months_label}")
    if df.empty:
        st.info("No records with the active filters.")
    else:
        st.altair_chart(
            expected_plus_month_chart(df, "DEST", top_n=top_n,
                                      dim_label="Destination"),
            use_container_width=True,
        )
        st.caption("Per destination: one thick **Total** bar (cumulative across "
                   "all loaded months) plus one thinner bar per month showing "
                   "how each month contributed.")

    st.subheader("Summary table")
    st.dataframe(pipeline_table(df, "DEST", share_mode=share_mode, top_n=top_n),
                 use_container_width=True)


# ────────────────────────── SHIPPER ──────────────────────────────────────────
with tab_ship:
    top_n = st.slider("Top N shippers", 5, 20, 8, key="ship_topn",
                      help="How many shippers to show in lines and bars")

    months_present = [m for m in CAMPAIGN_LABELS if m in df["MONTH"].unique()]
    cur_lbl  = cur_month_lbl
    cur_idx_c = next((i for i,(lbl,_,_) in enumerate(CAMPAIGN_MONTHS)
                     if lbl == cur_lbl), None)
    prev_lbl = (CAMPAIGN_MONTHS[cur_idx_c-1][0]
                if cur_idx_c and cur_idx_c > 0 else None)

    # Totales por mes y por shipper
    total_by_month = df.groupby("MONTH")["TONS"].sum()
    sh_by_month    = df.groupby(["MONTH","SHIPPER"])["TONS"].sum().reset_index()
    overall        = (df.groupby("SHIPPER")["TONS"].sum()
                        .sort_values(ascending=False))
    top_shippers   = overall.head(top_n).index.tolist()

    cur_total      = float(total_by_month.get(cur_lbl, 0))
    cur_sh         = (df[df["MONTH"] == cur_lbl].groupby("SHIPPER")["TONS"]
                        .sum().sort_values(ascending=False))
    prev_total     = float(total_by_month.get(prev_lbl, 0)) if prev_lbl else 0
    prev_sh        = (df[df["MONTH"] == prev_lbl].groupby("SHIPPER")["TONS"].sum()
                      if prev_lbl else pd.Series(dtype=float))

    # KPIs
    top3_share = (100 * cur_sh.head(3).sum() / cur_total) if cur_total else 0
    top5_share = (100 * cur_sh.head(5).sum() / cur_total) if cur_total else 0

    if prev_lbl and prev_total:
        all_shippers = set(cur_sh.index) | set(prev_sh.index)
        delta_pp = {
            sh: (100 * cur_sh.get(sh, 0) / cur_total
                 - 100 * prev_sh.get(sh, 0) / prev_total)
            for sh in all_shippers
        }
        gainer = max(delta_pp.items(), key=lambda x: x[1])
        loser  = min(delta_pp.items(), key=lambda x: x[1])
    else:
        gainer = ("—", 0); loser = ("—", 0)

    # HHI (Herfindahl) sobre el mes en curso, como proxy de concentración
    if cur_total:
        shares = (cur_sh / cur_total)
        hhi = float((shares ** 2).sum()) * 10_000  # convención: 0–10.000
        equivalent_n = (1 / (shares ** 2).sum()) if (shares ** 2).sum() else 0
    else:
        hhi, equivalent_n = 0, 0

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Top 3 concentration",
              f"{top3_share:.1f}%",
              f"Top 5: {top5_share:.1f}%")
    k2.metric("Equivalent shippers",
              f"{equivalent_n:.1f}",
              f"HHI {int(hhi):,}".replace(",", "."))
    k3.metric(f"Top gainer {cur_lbl.split()[0]}",
              gainer[0] if gainer[1] > 0 else "—",
              f"{gainer[1]:+.1f} pp" if gainer[1] != 0 else "—")
    k4.metric(f"Top decliner {cur_lbl.split()[0]}",
              loser[0] if loser[1] < 0 else "—",
              f"{loser[1]:+.1f} pp" if loser[1] != 0 else "—",
              delta_color="inverse")

    st.divider()

    # ── Chart 1: Monthly share % (lines with labels at the end) ────────────
    st.subheader(f"📈 Share evolution · Top {top_n} shippers")

    sm = sh_by_month[sh_by_month["SHIPPER"].isin(top_shippers)].copy()
    sm["MONTH_TOTAL"] = sm["MONTH"].map(total_by_month)
    sm["SHARE"] = 100 * sm["TONS"] / sm["MONTH_TOTAL"]

    line_order = sorted(top_shippers,
                        key=lambda s: -cur_sh.get(s, 0))

    base = alt.Chart(sm).encode(
        x=alt.X("MONTH:N", sort=months_present, title="",
                axis=alt.Axis(labelAngle=0, labelFontSize=12)),
        y=alt.Y("SHARE:Q", title="Monthly share (%)",
                axis=alt.Axis(format=".0f")),
        color=alt.Color("SHIPPER:N", sort=line_order,
                        scale=alt.Scale(scheme="tableau10"),
                        legend=None),
        tooltip=[
            alt.Tooltip("SHIPPER:N", title="Shipper"),
            alt.Tooltip("MONTH:N",   title="Month"),
            alt.Tooltip("SHARE:Q",   title="Share %", format=".2f"),
            alt.Tooltip("TONS:Q",    title="Tn",      format=",.0f"),
        ],
    )
    lines  = base.mark_line(strokeWidth=2.8)
    points = base.mark_point(filled=True, size=70)

    # Etiquetas al final de cada línea
    last_m = months_present[-1] if months_present else None
    labels_df = sm[sm["MONTH"] == last_m].copy() if last_m else sm.iloc[:0]
    end_labels = (alt.Chart(labels_df)
                  .mark_text(align="left", baseline="middle", dx=6,
                             fontSize=11, fontWeight="bold")
                  .encode(
                      x=alt.X("MONTH:N", sort=months_present),
                      y="SHARE:Q",
                      text="SHIPPER:N",
                      color=alt.Color("SHIPPER:N", sort=line_order,
                                      scale=alt.Scale(scheme="tableau10"),
                                      legend=None),
                  ))

    st.altair_chart((lines + points + end_labels)
                    .properties(height=440),
                    use_container_width=True)
    st.caption("Each line shows the shipper's share of the **monthly** total. "
               "Labels on the right are the current position.")

    st.divider()

    # ── Chart 2: Cumulative — Total + per-month breakdown ──────────────────
    months_loaded = sorted(df["MONTH"].unique().tolist())
    months_label = " + ".join(m.split()[0] for m in months_loaded) \
                   if months_loaded else "—"
    st.subheader(f"📊 Cumulative · {months_label} · total + per-month")

    df_cum = df[df["SHIPPER"].isin(top_shippers)]
    st.altair_chart(
        expected_plus_month_chart(df_cum, "SHIPPER", top_n=top_n,
                                  dim_label="Shipper"),
        use_container_width=True,
    )
    st.caption("For each shipper: a thick **Total** bar (cumulative across all "
               "loaded months) plus one thinner bar per month so you can see "
               "which months drove the total.")

    st.divider()

    # ── Leaderboard table ──────────────────────────────────────────────────
    st.subheader("🏆 Leaderboard")
    overall_total = float(df["TONS"].sum())
    rows = []
    for sh in overall.index[:top_n]:
        total_tn  = float(overall[sh])
        c_tn      = float(cur_sh.get(sh, 0))
        p_tn      = float(prev_sh.get(sh, 0)) if prev_lbl else 0
        c_share   = (100 * c_tn / cur_total) if cur_total else 0
        p_share   = (100 * p_tn / prev_total) if prev_total else 0
        rows.append({
            "Shipper":              sh,
            "Pipeline (kt)":        total_tn / 1000,
            f"{cur_lbl.split()[0]} (kt)": c_tn / 1000,
            "Crop year share":      100 * total_tn / overall_total
                                    if overall_total else 0,
            f"Share {cur_lbl.split()[0]}": c_share,
            "Δ pp":                 c_share - p_share,
            "Δ kt":                 (c_tn - p_tn) / 1000,
        })
    lb = pd.DataFrame(rows).reset_index(drop=True)
    lb.insert(0, "Rank", range(1, len(lb) + 1))

    lb_show = lb.copy()
    for c in ["Pipeline (kt)", f"{cur_lbl.split()[0]} (kt)"]:
        lb_show[c] = lb_show[c].map(lambda v: f"{v:,.0f}".replace(",", "."))
    lb_show["Δ kt"] = lb_show["Δ kt"].map(
        lambda v: f"{v:+,.0f}".replace(",", "."))
    for c in ["Crop year share", f"Share {cur_lbl.split()[0]}"]:
        lb_show[c] = lb_show[c].map(lambda v: f"{v:.1f}%")
    lb_show["Δ pp"] = lb_show["Δ pp"].map(lambda v: f"{v:+.1f} pp")
    st.dataframe(lb_show, use_container_width=True, hide_index=True)


# ────────────────────────── DATA ─────────────────────────────────────────────
with tab_data:
    st.subheader(f"Records ({len(df):,})".replace(",", "."))
    cols = ["MONTH","STATUS","CARGO","VESSEL","ZONE","PORT","BERTH",
            "ETA","TONS","SHIPPER","COORD","DEST"]
    show = (df[cols]
              .sort_values(["MONTH","STATUS","ETA"])
              .reset_index(drop=True))
    st.dataframe(show, use_container_width=True, hide_index=True,
                 column_config={
                     "TONS": st.column_config.NumberColumn("Tons",
                                                            format="%.0f"),
                     "ETA": st.column_config.DatetimeColumn("ETA/ETF",
                                                            format="DD/MM/YYYY HH:mm"),
                 })
    csv = show.to_csv(index=False).encode("utf-8")
    st.download_button("⬇️ Download filtered CSV", csv,
                       "lineups_filtered.csv", "text/csv")
