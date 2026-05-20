"""
pos_fisica.py — Posición Física consolidada por cultivo / destino / mes.

Compara lo vendido por Farmer Selling (suma del bucket de delivery del mes
elegido) con lo que va a embarcar Lineups (pipeline total = Sailed + At Roads
+ Lineup). El gap indica cuántas tn vendidas a entregar en ese tramo todavía
no aparecen en el lineup.

Render: llamar `render_pos_fisica(app_all_dir)` desde el wrapper.
"""

from __future__ import annotations

import sys
from calendar import monthrange
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st


@st.cache_data(show_spinner=False)
def _load_a_fijar_kt(_fs_dir_str: str, slug: str) -> float:
    """Lee el último valor de `a_fijar_acum_kt` del JSON de MINAGRI para el
    cultivo (cosecha actual = OC). Devuelve 0 si la key no existe o el archivo
    no tiene punto."""
    import json
    # Cosecha actual por cultivo (matchea con MAGYP)
    cos_by_slug = {
        "maiz":   "25_26",
        "sorgo":  "25_26",
        "trigo":  "25_26",
        "cebada": "25_26",
    }
    cos = cos_by_slug.get(slug)
    if not cos:
        return 0.0
    p = Path(_fs_dir_str) / "data" / f"minagri_{slug}_{cos}.json"
    if not p.exists():
        return 0.0
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return 0.0
    serie = data.get("serie", [])
    if not serie:
        return 0.0
    # Sort by date desc, take latest with a_fijar_acum_kt
    for pt in sorted(serie, key=lambda x: x.get("fecha", ""), reverse=True):
        v = pt.get("a_fijar_acum_kt")
        if v is not None:
            return float(v) * 1000.0  # JSON está en kt, devolvemos tn
    return 0.0


def _bucket_end_date(slug: str, bucket: str) -> date | None:
    """Último día del último mes del bucket. Ej. MAM maíz → 31-May-26."""
    months = BUCKET_MONTHS_BY_SLUG.get(slug, {}).get(bucket, [])
    if not months:
        return None
    yr, mn = months[-1]
    last_day = monthrange(yr, mn)[1]
    return date(yr, mn, last_day)


def _biz_days_to(target: date, today: date | None = None) -> int:
    """Días hábiles entre hoy y target inclusive. 0 si target ya pasó."""
    today = today or date.today()
    if target < today:
        return 0
    return len(pd.bdate_range(pd.Timestamp(today), pd.Timestamp(target)))


# ──────────────────────────────────────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────────────────────────────────────

CULTIVOS = {
    "maiz":   {"label": "🌽 Corn",        "lineups_cargo": "Maize",
               "buckets": ["MAM", "JJ", "AS", "OND", "JF"],
               "campaign_end": date(2027, 2, 28)},
    "trigo":  {"label": "🌾 Bread Wheat", "lineups_cargo": "Wheat",
               "buckets": ["NDJ", "FMA", "MJJ", "ASO"],
               "campaign_end": date(2026, 10, 31)},
    "sorgo":  {"label": "🌱 Sorghum",     "lineups_cargo": "Sorghum",
               "buckets": ["MAM", "JJ", "AS", "OND", "JF"],
               "campaign_end": date(2027, 2, 28)},
    "cebada": {"label": "🌿 Feed Barley", "lineups_cargo": "Barley",
               "buckets": ["NDJ", "FMA", "MJJ", "ASO"],
               "campaign_end": date(2026, 10, 31)},
}

# Label "humanos" de cada bucket (para subtítulos del heatmap)
BUCKET_LABELS = {
    "MAM": "Mar–May 26",
    "JJ":  "Jun–Jul 26",
    "AS":  "Aug–Sep 26",
    "OND": "Oct–Dec 26",
    "JF":  "Jan–Feb 27",
    "NDJ": "Nov 25 – Jan 26",
    "FMA": "Feb–Apr 26",
    "MJJ": "May–Jul 26",
    "ASO": "Aug–Oct 26",
}

DESTINOS = {
    "uprivers": {"label": "Up River",     "lineups_zone": "Up River"},
    "bahia":    {"label": "Bahía Blanca", "lineups_zone": "Bahía Blanca"},
    "necochea": {"label": "Necochea",     "lineups_zone": "Necochea"},
    # Interior tiene FS pero NO aparece en Lineups (consumo doméstico, no
    # exporta). Lineup = 0 siempre; Posición = FS.
    "interior": {"label": "Interior",     "lineups_zone": None},
}

# Meses calendario por cultivo (current crop year)
#   Maíz / Sorgo: Mar 26 → Feb 27
#   Trigo / Cebada: Nov 25 → Oct 26
_MONTHS_MAIZ_SORGO = [
    ("Mar 2026", 2026, 3),  ("Apr 2026", 2026, 4),  ("May 2026", 2026, 5),
    ("Jun 2026", 2026, 6),  ("Jul 2026", 2026, 7),  ("Aug 2026", 2026, 8),
    ("Sep 2026", 2026, 9),  ("Oct 2026", 2026, 10), ("Nov 2026", 2026, 11),
    ("Dec 2026", 2026, 12), ("Jan 2027", 2027, 1),  ("Feb 2027", 2027, 2),
]
_MONTHS_TRIGO_CEBADA = [
    ("Nov 2025", 2025, 11), ("Dec 2025", 2025, 12), ("Jan 2026", 2026, 1),
    ("Feb 2026", 2026, 2),  ("Mar 2026", 2026, 3),  ("Apr 2026", 2026, 4),
    ("May 2026", 2026, 5),  ("Jun 2026", 2026, 6),  ("Jul 2026", 2026, 7),
    ("Aug 2026", 2026, 8),  ("Sep 2026", 2026, 9),  ("Oct 2026", 2026, 10),
]

MONTHS_BY_SLUG = {
    "maiz":   _MONTHS_MAIZ_SORGO,
    "sorgo":  _MONTHS_MAIZ_SORGO,
    "trigo":  _MONTHS_TRIGO_CEBADA,
    "cebada": _MONTHS_TRIGO_CEBADA,
}

# Mapeo mes → bucket FS según cultivo
# (replica las "delivery_groups" de cultivos.py)
_BUCKETS_MAIZ_SORGO = {
    3: "MAM", 4: "MAM", 5: "MAM",      # Mar-Apr-May 26
    6: "JJ",  7: "JJ",                  # Jun-Jul 26
    8: "AS",  9: "AS",                  # Aug-Sep 26
    10: "OND", 11: "OND", 12: "OND",   # Oct-Nov-Dec 26
    1: "JF",  2: "JF",                  # Jan-Feb 27
}
_BUCKETS_TRIGO_CEBADA = {
    11: "NDJ", 12: "NDJ", 1: "NDJ",    # Nov 25 - Jan 26
    2: "FMA",  3: "FMA",  4: "FMA",     # Feb-Mar-Apr 26
    5: "MJJ",  6: "MJJ",  7: "MJJ",     # May-Jun-Jul 26
    8: "ASO",  9: "ASO",  10: "ASO",    # Aug-Sep-Oct 26
}

BUCKETS_BY_SLUG = {
    "maiz":   _BUCKETS_MAIZ_SORGO,
    "sorgo":  _BUCKETS_MAIZ_SORGO,
    "trigo":  _BUCKETS_TRIGO_CEBADA,
    "cebada": _BUCKETS_TRIGO_CEBADA,
}

# Bucket de cosecha (harvest) por cultivo — todo el A_Fijar de MAGYP
# se asigna a este bucket, distribuido entre los 3 puertos de exportación
# según el peso del FS PH+Fij dentro del bucket.
HARVEST_BUCKET_BY_SLUG = {
    "maiz":   "MAM",   # cosecha maíz Mar-May 26
    "sorgo":  "MAM",
    "trigo":  "NDJ",   # cosecha trigo Nov-Ene 25/26
    "cebada": "NDJ",
}


# Composición inversa de los buckets: cada bucket → lista de meses
# (year, month) que lo componen. Necesario para sumar Lineups across
# todos los meses del bucket.
_BUCKET_MONTHS_MAIZ_SORGO = {
    "MAM": [(2026, 3), (2026, 4), (2026, 5)],
    "JJ":  [(2026, 6), (2026, 7)],
    "AS":  [(2026, 8), (2026, 9)],
    "OND": [(2026, 10), (2026, 11), (2026, 12)],
    "JF":  [(2027, 1), (2027, 2)],
}
_BUCKET_MONTHS_TRIGO_CEBADA = {
    "NDJ": [(2025, 11), (2025, 12), (2026, 1)],
    "FMA": [(2026, 2), (2026, 3), (2026, 4)],
    "MJJ": [(2026, 5), (2026, 6), (2026, 7)],
    "ASO": [(2026, 8), (2026, 9), (2026, 10)],
}

BUCKET_MONTHS_BY_SLUG = {
    "maiz":   _BUCKET_MONTHS_MAIZ_SORGO,
    "sorgo":  _BUCKET_MONTHS_MAIZ_SORGO,
    "trigo":  _BUCKET_MONTHS_TRIGO_CEBADA,
    "cebada": _BUCKET_MONTHS_TRIGO_CEBADA,
}

# Para formatear "May 2026" en el label de Lineups
_MONTH_NAMES = {
    1: "January", 2: "February", 3: "March", 4: "April",
    5: "May", 6: "June", 7: "July", 8: "August",
    9: "September", 10: "October", 11: "November", 12: "December",
}


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _fmt_tn(v):
    if v is None:
        return "—"
    try:
        kt = round(float(v) / 1000)
        if kt == 0 and v != 0:
            return f"{float(v)/1000:.1f}".replace(".", ",")
        return f"{kt:,}".replace(",", ".")
    except Exception:
        return "—"


@st.cache_data(show_spinner=False)
def _load_matriz_puerto(_fs_dir_str: str, slug: str, puerto: str) -> pd.DataFrame:
    """Lee matriz_<slug>_<puerto>.csv. Si el CSV tiene cols mensuales
    (2026_03 ...), expande los buckets virtuales para compat. Devuelve DF
    vacío si no existe."""
    p = Path(_fs_dir_str) / "data" / f"matriz_{slug}_{puerto}.csv"
    if not p.exists():
        return pd.DataFrame()
    try:
        df = pd.read_csv(p)
    except Exception:
        return pd.DataFrame()
    # Expandir buckets virtuales si el schema es mensual
    import sys
    fs_path = str(Path(_fs_dir_str))
    if fs_path not in sys.path:
        sys.path.insert(0, fs_path)
    try:
        from cultivos import CULTIVOS, meses_cols, expand_buckets_from_months  # type: ignore
        cfg = CULTIVOS.get(slug)
        if cfg is not None:
            mcols = meses_cols(cfg)
            has_monthly = any(c in df.columns for c in mcols)
            if has_monthly:
                for c in mcols:
                    if c in df.columns:
                        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0).astype(int)
                expand_buckets_from_months(df, cfg)
    except Exception:
        pass
    return df


def _fs_bucket_total(df: pd.DataFrame, bucket: str) -> int:
    """Suma total del bucket sobre todas las filas (mensuales + diarias)."""
    if df.empty or bucket not in df.columns:
        return 0
    sub = df[df["tipo"].isin(["mensual", "diario"])]
    return int(sub[bucket].sum())


def _fs_month_total(df: pd.DataFrame, year: int, month: int) -> int:
    """Suma del mes calendario individual sobre filas mensuales+diarias.
    Asume schema mensual de la matriz: cols tipo '2026_03', '2026_04', ..."""
    if df.empty:
        return 0
    col = f"{year:04d}_{month:02d}"
    if col not in df.columns:
        return 0
    sub = df[df["tipo"].isin(["mensual", "diario"])]
    return int(sub[col].sum())


# ── MARS (Country Balance Sheet) ────────────────────────────────────────────

# Slug FS → archivo MARS
_MARS_FILES = {
    "maiz":   "Country Balance Sheet (32).xlsx",
    "trigo":  "Country Balance Sheet (29).xlsx",
    "cebada": "Country Balance Sheet (30).xlsx",
    "sorgo":  "Country Balance Sheet (31).xlsx",
}


@st.cache_data(show_spinner=False)
def _load_mars_exports(_mars_dir_str: str, slug: str) -> dict:
    """Devuelve {month_key: kt} de Exports para un cultivo.
    month_key tiene formato 'MM/YYYY' (ej. '05/2026'). Valor en kt.
    """
    fname = _MARS_FILES.get(slug)
    if not fname:
        return {}
    p = Path(_mars_dir_str) / fname
    if not p.exists():
        return {}
    try:
        import openpyxl
        wb = openpyxl.load_workbook(p, data_only=True, read_only=True)
        if "Monthly BalanceSheet" not in wb.sheetnames:
            return {}
        ws = wb["Monthly BalanceSheet"]
        # Row 4 (idx 3) tiene los meses; col[0] vacío, última col "Total"
        # Buscamos la fila "Exports" en col[0] desde la fila 6 en adelante
        rows = list(ws.iter_rows(values_only=True))
        if len(rows) < 6:
            return {}
        header_row = rows[3]
        months = []
        for ci, cell in enumerate(header_row[1:], start=1):
            if cell is None: continue
            s = str(cell).strip()
            if s and s.lower() != "total":
                months.append((ci, s))
        # Buscar la fila Exports
        out = {}
        for r in rows[5:]:
            if not r: continue
            label = r[0]
            if isinstance(label, str) and label.strip().lower() == "exports":
                for ci, mlabel in months:
                    v = r[ci]
                    if v is None: continue
                    try:
                        out[mlabel] = float(v)
                    except Exception:
                        pass
                break
        return out
    except Exception:
        return {}


def _month_to_mars_key(year: int, month: int) -> str:
    """(2026, 5) → '05/2026'."""
    return f"{month:02d}/{year}"


def _compute_port_share(df_lu: pd.DataFrame, zones: list[str]) -> dict:
    """Share del puerto sobre el total del cargo en los meses con xls.
    Devuelve {zone: share_fraction}, suma = 1.0.
    Usa TONS aggregate (todos los status) sobre todos los meses del DF.
    """
    if df_lu.empty:
        return {z: 0.0 for z in zones}
    grand = float(df_lu["TONS"].sum())
    if grand <= 0:
        return {z: 0.0 for z in zones}
    return {
        z: float(df_lu[df_lu["ZONE"] == z]["TONS"].sum()) / grand
        for z in zones
    }


# ──────────────────────────────────────────────────────────────────────────────
# Render
# ──────────────────────────────────────────────────────────────────────────────

def _coverage_color(coverage_pct: float | None) -> tuple[str, str]:
    """Devuelve (bg, fg) según el % de cobertura (Pipeline/FS)."""
    if coverage_pct is None:
        return "rgba(0,0,0,0.03)", "#aaa"  # gris — sin data
    if 95 <= coverage_pct <= 110:
        return "rgba(29,158,117,0.20)", "#1d6e51"  # verde — alineado
    if 80 <= coverage_pct <= 125:
        return "rgba(242,201,76,0.30)", "#7a5a00"  # amarillo — gap chico
    return "rgba(226,75,74,0.18)", "#a32d2d"        # rojo — gap grande


def _compute_cell_data(
    slug: str, destino_slug: str, bucket: str,
    fs_dir: Path, lineups_dir: Path, mars_dir: Path,
    df_lu_cargo: pd.DataFrame, exports_kt: dict, port_shares: dict,
) -> dict:
    """Computa todos los datos para una celda (cultivo × destino × bucket).

    Returns dict con: fs_tn, pipeline_real_tn, projected_tn, pipeline_total_tn,
    coverage_pct, has_projection, months_missing (lista).
    """
    df_matriz = _load_matriz_puerto(str(fs_dir), slug, destino_slug)
    fs_total = _fs_bucket_total(df_matriz, bucket)

    bucket_months = BUCKET_MONTHS_BY_SLUG[slug].get(bucket, [])
    bucket_month_labels = [f"{_MONTH_NAMES[m]} {y}" for (y, m) in bucket_months]
    lu_zone = DESTINOS[destino_slug]["lineups_zone"]

    sailed_roads_lineup = 0
    projected_tn = 0
    months_missing: list[str] = []

    # Interior NO aparece en Lineups → todo lo de Lineup queda en 0
    is_export = lu_zone is not None

    if is_export and not df_lu_cargo.empty:
        available = set(df_lu_cargo["MONTH"].unique())
        months_with_data = [m for m in bucket_month_labels if m in available]
        for (yr, mn), lbl in zip(bucket_months, bucket_month_labels):
            if lbl not in available:
                months_missing.append(lbl)
        # Actuals
        mask_real = (
            df_lu_cargo["MONTH"].isin(months_with_data) &
            (df_lu_cargo["ZONE"] == lu_zone)
        )
        sailed_roads_lineup = int(df_lu_cargo[mask_real]["TONS"].sum())

        # Proyección
        share = port_shares.get(lu_zone, 0.0)
        for (yr, mn), lbl in zip(bucket_months, bucket_month_labels):
            if lbl in months_with_data:
                continue
            mkey = _month_to_mars_key(yr, mn)
            exp_kt = exports_kt.get(mkey)
            if exp_kt is not None:
                projected_tn += int(round(exp_kt * 1000 * share))

    pipeline_total = sailed_roads_lineup + projected_tn
    if not is_export:
        # Interior: no aplica cobertura, la marcamos como neutral
        coverage = None
    elif fs_total > 0:
        coverage = pipeline_total / fs_total * 100
    else:
        coverage = None

    return {
        "fs_tn": fs_total,
        "pipeline_real_tn": sailed_roads_lineup,
        "projected_tn": projected_tn,
        "pipeline_total_tn": pipeline_total,
        "coverage_pct": coverage,
        "has_projection": projected_tn > 0,
        "months_missing": months_missing,
        "is_export": is_export,
    }


def _compute_cell_data_monthly(
    slug: str, destino_slug: str, year: int, month: int,
    fs_dir: Path,
    df_lu_cargo: pd.DataFrame, exports_kt: dict, port_shares: dict,
) -> dict:
    """Idéntico a _compute_cell_data pero para UN mes calendario individual.

    FS:      suma de la col '{year}_{month:02d}' en matriz_<slug>_<puerto>.csv.
    Exports: si el mes tiene xls (en df_lu_cargo.MONTH) → suma de TONS por zona.
             Si no → MARS_kt × share del puerto × 1000 (proyectado).
    """
    df_matriz = _load_matriz_puerto(str(fs_dir), slug, destino_slug)
    fs_total = _fs_month_total(df_matriz, year, month)

    lu_zone = DESTINOS[destino_slug]["lineups_zone"]
    is_export = lu_zone is not None

    full_month_lbl = f"{_MONTH_NAMES[month]} {year}"

    sailed_roads_lineup = 0
    projected_tn = 0
    has_projection = False

    if is_export and not df_lu_cargo.empty:
        available = set(df_lu_cargo["MONTH"].unique())
        if full_month_lbl in available:
            mask_real = (
                (df_lu_cargo["MONTH"] == full_month_lbl)
                & (df_lu_cargo["ZONE"] == lu_zone)
            )
            sailed_roads_lineup = int(df_lu_cargo[mask_real]["TONS"].sum())
        else:
            mkey = _month_to_mars_key(year, month)
            exp_kt = exports_kt.get(mkey)
            share = port_shares.get(lu_zone, 0.0)
            if exp_kt is not None:
                projected_tn = int(round(exp_kt * 1000 * share))
                has_projection = projected_tn > 0

    pipeline_total = sailed_roads_lineup + projected_tn
    if not is_export:
        coverage = None
    elif fs_total > 0:
        coverage = pipeline_total / fs_total * 100
    else:
        coverage = None

    return {
        "fs_tn": fs_total,
        "pipeline_real_tn": sailed_roads_lineup,
        "projected_tn": projected_tn,
        "pipeline_total_tn": pipeline_total,
        "coverage_pct": coverage,
        "has_projection": has_projection,
        "is_export": is_export,
    }


def render_pos_fisica(app_all_dir: Path) -> None:
    fs_dir = app_all_dir / "fs_maiz"
    lineups_dir = app_all_dir / "Lineups"
    mars_dir = app_all_dir / "0. MARS"

    st.title("📦 Posición Física")
    st.caption(
        "Comparación **FS vendido** (verde) vs **Exports estimados** (azul, "
        "Real + Proyectado) por cultivo, destino y bucket. Los valores con "
        "`*` incluyen proyección (MARS Exports × share histórico del puerto). "
        "Color de fondo indica cobertura aproximada: 🟢 ≈100% · 🟡 gap chico · "
        "🔴 gap grande · ⬜ sin data FS."
    )

    # Toggle: Por mes (flujo mensual) vs Acumulada (running total por puerto)
    modo = st.radio(
        "Vista",
        options=["Por mes", "Acumulada"],
        index=0,
        horizontal=True,
        help=(
            "‘Por mes’ muestra el flujo de cada mes calendario por separado. "
            "‘Acumulada’ muestra el running total por puerto: cada celda "
            "acumula FS / Exports / Pos desde el primer mes del cultivo hasta "
            "el mes de esa fila — útil para ver cómo se va abriendo el gap a "
            "lo largo de la campaña."
        ),
        key="pos_fisica_modo",
    )
    is_acumulada = (modo == "Acumulada")
    st.markdown("<div style='height:0.5rem;'></div>", unsafe_allow_html=True)

    # ── Pre-cargar Lineups + MARS + shares por cultivo ─────────────────────
    if str(lineups_dir) not in sys.path:
        sys.path.insert(0, str(lineups_dir))
    try:
        import _lineups_loader as lu  # type: ignore
    except Exception as e:
        st.error(f"No pude cargar el módulo de Lineups: {e}")
        return

    lu_df_by_slug: dict = {}
    exports_by_slug: dict = {}
    shares_by_slug: dict = {}
    zones = [DESTINOS[d]["lineups_zone"] for d in DESTINOS]
    for slug in CULTIVOS:
        df_lu = lu.load_for_crop(slug, lineups_dir)
        lu_df_by_slug[slug] = df_lu
        exports_by_slug[slug] = _load_mars_exports(str(mars_dir), slug)
        shares_by_slug[slug] = _compute_port_share(df_lu, zones)

    # ── Iterar cultivos y armar heatmap por cada uno ───────────────────────
    destino_slugs = list(DESTINOS.keys())
    destino_labels = [DESTINOS[d]["label"] for d in destino_slugs]

    for slug, cult in CULTIVOS.items():
        buckets = cult["buckets"]
        share_str = " · ".join(
            f"{DESTINOS[d]['label']} {shares_by_slug[slug].get(DESTINOS[d]['lineups_zone'], 0)*100:.1f}%"
            for d in destino_slugs
        )

        # ── Calcular totales del cultivo (cell_cache por (destino × mes)) ──
        # La lista de meses calendario del cultivo (Mar 26 → Feb 27 maíz/sorgo,
        # Nov 25 → Oct 26 trigo/cebada).
        months_calendar = MONTHS_BY_SLUG[slug]  # [(label, year, month), ...]
        total_fs = 0
        total_lin_real = 0
        total_lin_proj = 0
        cell_cache: dict[tuple[str, int, int], dict] = {}
        for d_slug in destino_slugs:
            for (_lbl, yr, mn) in months_calendar:
                data = _compute_cell_data_monthly(
                    slug, d_slug, yr, mn, fs_dir,
                    lu_df_by_slug[slug], exports_by_slug[slug], shares_by_slug[slug],
                )
                cell_cache[(d_slug, yr, mn)] = data
                total_fs += data["fs_tn"]
                total_lin_real += data["pipeline_real_tn"]
                total_lin_proj += data["projected_tn"]
        total_lin_est = total_lin_real + total_lin_proj

        # ── A Fijar (MAGYP): TODO va al bucket de cosecha, ahora distribuido
        # a nivel (mes × puerto) usando el peso del FS PH+Fij dentro del
        # bucket de cosecha, solo en puertos de exportación.
        total_a_fijar = _load_a_fijar_kt(str(fs_dir), slug)  # tn
        harvest_bucket = HARVEST_BUCKET_BY_SLUG.get(slug, "MAM")
        harvest_months = BUCKET_MONTHS_BY_SLUG[slug].get(harvest_bucket, [])
        total_fs_harvest_export = sum(
            cell_cache[(d, y, m)]["fs_tn"]
            for d in destino_slugs
            for (y, m) in harvest_months
            if (d, y, m) in cell_cache and cell_cache[(d, y, m)]["is_export"]
        )
        for data in cell_cache.values():
            data["a_fijar_tn"] = 0.0
        if total_fs_harvest_export > 0:
            for d in destino_slugs:
                for (y, m) in harvest_months:
                    cell = cell_cache.get((d, y, m))
                    if cell is None or not cell["is_export"]:
                        continue
                    weight = cell["fs_tn"] / total_fs_harvest_export
                    cell["a_fijar_tn"] = total_a_fijar * weight
        for data in cell_cache.values():
            data["fs_total_tn"] = data["fs_tn"] + data["a_fijar_tn"]

        # ── Header del cultivo + resumen + shares ──
        st.markdown(
            f"<div style='font-weight:600;font-size:1.05rem;"
            f"margin:0.6rem 0 0.2rem 0;'>"
            f"{cult['label']}</div>",
            unsafe_allow_html=True,
        )

        # FS físico TOTAL = PH + Fijado + A_Fijar. El A_Fijar es commitment
        # físico — tonelada vendida con precio abierto — así que SIEMPRE entra
        # en la posición física, tanto realizada como total.
        total_fs_total = total_fs + total_a_fijar

        # Posición REALIZADA = (FS PH+Fij + A_Fijar) − Exports Real
        # (sin proyección de Lineups; "dónde estamos hoy" pero contemplando
        # todo el commitment físico).
        total_pos_real = total_fs_total - total_lin_real
        pos_real_color = "#1d6e51" if total_pos_real >= 0 else "#a32d2d"
        pos_real_bg = ("rgba(29,158,117,0.10)"
                       if total_pos_real >= 0 else "rgba(226,75,74,0.10)")
        pos_real_label = "LONG ((FS+AF) > EXP)" if total_pos_real > 0 else (
            "SHORT (EXP > (FS+AF))" if total_pos_real < 0 else "FLAT")

        # Posición TOTAL = (FS PH+Fij + A_Fijar) − Exports Estimados
        # (con proyección MARS para meses sin xls). Esta es la posición física
        # "forward looking" — todo lo comprometido físicamente vs todo lo que
        # vamos a embarcar.
        total_pos = total_fs_total - total_lin_est
        pos_color = "#1d6e51" if total_pos >= 0 else "#a32d2d"
        pos_bg = ("rgba(29,158,117,0.10)"
                  if total_pos >= 0 else "rgba(226,75,74,0.10)")
        pos_label = "LONG ((FS+AF) > EXP)" if total_pos > 0 else (
            "SHORT (EXP > (FS+AF))" if total_pos < 0 else "FLAT")

        # Pace para flat: |Pos Estimada| / días hábiles restantes hasta fin de campaña
        campaign_end = cult["campaign_end"]
        today_d = date.today()
        if today_d <= campaign_end:
            biz_left = pd.bdate_range(pd.Timestamp(today_d),
                                       pd.Timestamp(campaign_end))
            biz_days_remaining = len(biz_left)
        else:
            biz_days_remaining = 0
        if biz_days_remaining > 0:
            pace_to_flat = abs(total_pos) / biz_days_remaining  # tn/día
        else:
            pace_to_flat = None
        # Hint sobre qué hace falta (si pos<0 hay que sumar lineup; si >0 al revés)
        if total_pos < 0:
            pace_hint = "↑ vender/embarcar más"
        elif total_pos > 0:
            pace_hint = "↓ comprar/cubrir más"
        else:
            pace_hint = "ya estás flat"

        # Stock-to-Usage en MESES, consumiendo el LONG contra los exports
        # MARS MES A MES desde el mes SIGUIENTE al actual (ignorando meses
        # pasados y el mes en curso, que ya están casi embarcados). Esto
        # respeta la estacionalidad real de MARS (cosecha vs. valles) y mide
        # "cuántos meses adelante me cubre el LONG físico".
        exports_kt_slug = exports_by_slug[slug]
        today_ym = (today_d.year, today_d.month)
        ordered_months_exp = []
        for (_lbl, yr, mn) in MONTHS_BY_SLUG[slug]:
            # Saltar meses ya transcurridos y el mes en curso
            if (yr, mn) <= today_ym:
                continue
            mars_key = f"{mn:02d}/{yr}"
            exp_kt_v = exports_kt_slug.get(mars_key, 0)
            exp_tn = float(exp_kt_v) * 1000
            ordered_months_exp.append((yr, mn, exp_tn))

        remaining_long = abs(total_pos_real)
        months_covered = 0.0
        total_exp_available = sum(e for _, _, e in ordered_months_exp)
        for (_yr, _mn, exp_tn) in ordered_months_exp:
            if remaining_long <= 0:
                break
            if exp_tn <= 0:
                continue
            if remaining_long >= exp_tn:
                months_covered += 1.0
                remaining_long -= exp_tn
            else:
                months_covered += remaining_long / exp_tn
                remaining_long = 0
        # Si todavía queda LONG después de TODOS los meses, marcamos overflow
        overflow = remaining_long > 0
        # SHORT: se invierte el signo (faltan meses para cerrar al ritmo prox)
        if total_exp_available <= 0:
            stu_months = None
        else:
            stu_months = months_covered if total_pos_real >= 0 else -months_covered

        if stu_months is None:
            stu_color = "#888"
            stu_bg = "rgba(120,120,120,0.10)"
            stu_label = "—"
        elif stu_months > 0:
            stu_color = "#1d6e51"
            stu_bg = "rgba(29,158,117,0.10)"
            stu_label = "LONG · stock cubre" + (" (campaña+)" if overflow else "")
        elif stu_months < 0:
            stu_color = "#a32d2d"
            stu_bg = "rgba(226,75,74,0.10)"
            stu_label = "SHORT · faltan"
        else:
            stu_color = "#444"
            stu_bg = "rgba(120,120,120,0.10)"
            stu_label = "FLAT"

        # Línea de resumen (8 cards):
        # FS PH+Fij · A Fijar · Exports Real · Pos Real · S/U · Exports Est · Pos Total · Pace
        sum_cols = st.columns(8)
        sum_cols[0].markdown(
            f"<div style='text-align:center;padding:0.4rem;"
            f"background:rgba(29,158,117,0.10);border-radius:6px;'>"
            f"<div style='font-size:0.62rem;color:#666;letter-spacing:1px;'>"
            f"FS PH + FIJADO</div>"
            f"<div style='font-size:1.1rem;font-weight:700;color:#1d6e51;'>"
            f"{_fmt_tn(total_fs)} kt</div></div>",
            unsafe_allow_html=True,
        )
        sum_cols[1].markdown(
            f"<div style='text-align:center;padding:0.4rem;"
            f"background:rgba(245,124,0,0.10);border-radius:6px;'>"
            f"<div style='font-size:0.62rem;color:#666;letter-spacing:1px;'>"
            f"A FIJAR (MAGYP)</div>"
            f"<div style='font-size:1.1rem;font-weight:700;color:#F57C00;'>"
            f"{_fmt_tn(total_a_fijar)} kt</div></div>",
            unsafe_allow_html=True,
        )
        sum_cols[2].markdown(
            f"<div style='text-align:center;padding:0.4rem;"
            f"background:rgba(46,125,50,0.10);border-radius:6px;'>"
            f"<div style='font-size:0.62rem;color:#666;letter-spacing:1px;'>"
            f"EXPORTS REALIZADOS</div>"
            f"<div style='font-size:1.1rem;font-weight:700;color:#2E7D32;'>"
            f"{_fmt_tn(total_lin_real)} kt</div></div>",
            unsafe_allow_html=True,
        )
        pos_real_kt = total_pos_real / 1000
        pos_real_str = f"{pos_real_kt:+,.0f}".replace(",", ".") + " kt"
        sum_cols[3].markdown(
            f"<div style='text-align:center;padding:0.4rem;"
            f"background:{pos_real_bg};border-radius:6px;'>"
            f"<div style='font-size:0.62rem;color:#666;letter-spacing:1px;'>"
            f"POS. REAL FÍSICA · {pos_real_label}</div>"
            f"<div style='font-size:1.1rem;font-weight:700;color:{pos_real_color};'>"
            f"{pos_real_str}</div></div>",
            unsafe_allow_html=True,
        )
        # Card de Stock to Usage (entre Pos. Real Física y Exports Estimados)
        # Mostramos meses de stock con signo y 1 decimal usando coma decimal.
        if stu_months is None:
            stu_str = "—"
        else:
            stu_str = f"{abs(stu_months):.1f}".replace(".", ",") + " meses"
            # Prefijo de signo explícito (más legible que "+1,2 meses")
            # Solo agregamos "+" para LONG; SHORT lo decimos con el label.
        sum_cols[4].markdown(
            f"<div style='text-align:center;padding:0.4rem;"
            f"background:{stu_bg};border-radius:6px;'>"
            f"<div style='font-size:0.62rem;color:#666;letter-spacing:1px;'>"
            f"STOCK TO USAGE · {stu_label}</div>"
            f"<div style='font-size:1.1rem;font-weight:700;color:{stu_color};'>"
            f"{stu_str}</div></div>",
            unsafe_allow_html=True,
        )
        sum_cols[5].markdown(
            f"<div style='text-align:center;padding:0.4rem;"
            f"background:rgba(21,101,192,0.10);border-radius:6px;'>"
            f"<div style='font-size:0.62rem;color:#666;letter-spacing:1px;'>"
            f"EXPORTS ESTIMADOS *</div>"
            f"<div style='font-size:1.1rem;font-weight:700;color:#1565C0;'>"
            f"{_fmt_tn(total_lin_est)} kt</div></div>",
            unsafe_allow_html=True,
        )
        pos_kt = total_pos / 1000
        pos_str = f"{pos_kt:+,.0f}".replace(",", ".") + " kt"
        sum_cols[6].markdown(
            f"<div style='text-align:center;padding:0.4rem;"
            f"background:{pos_bg};border-radius:6px;'>"
            f"<div style='font-size:0.62rem;color:#666;letter-spacing:1px;'>"
            f"POS. TOTAL · {pos_label}</div>"
            f"<div style='font-size:1.1rem;font-weight:700;color:{pos_color};'>"
            f"{pos_str}</div></div>",
            unsafe_allow_html=True,
        )
        # 8va card: Pace para llegar a flat
        if pace_to_flat is None:
            pace_str = "—"
        else:
            pace_kt = pace_to_flat / 1000
            pace_str = f"{pace_kt:,.0f}".replace(",", ".") + " kt/d"
        sum_cols[7].markdown(
            f"<div style='text-align:center;padding:0.4rem;"
            f"background:rgba(120,120,120,0.10);border-radius:6px;'>"
            f"<div style='font-size:0.62rem;color:#666;letter-spacing:1px;'>"
            f"PACE A FLAT · {biz_days_remaining}d</div>"
            f"<div style='font-size:1.1rem;font-weight:700;color:#444;'>"
            f"{pace_str}</div>"
            f"<div style='font-size:0.6rem;color:#888;'>{pace_hint}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )
        st.caption(
            f"**Pos. Real Física = (FS PH+Fij + A_Fijar) − Exports Real** — "
            f"todo lo comprometido físicamente hoy vs lo ya embarcado. "
            f"**Stock/Usage = meses de stock al ritmo MARS mensual** — "
            f"se consume el LONG físico mes a mes con los exports MARS "
            f"proyectados, arrancando desde el mes SIGUIENTE al actual "
            f"(meses pasados ya están embarcados). Respeta la estacionalidad "
            f"de MARS (cosecha vs. valles). LONG = el stock dura X meses · "
            f"SHORT = faltan X meses para cerrar el gap. "
            f"**Pos. Total = (FS PH+Fij + A_Fijar) − Exports Estimados** — "
            f"misma posición pero con la proyección MARS de embarques futuros. "
            f"Long (+) = sobre-vendido · Short (−) = al revés. "
            f"Pace a flat = |Pos. Total| / días hábiles hasta {campaign_end.strftime('%d %b %Y')}. "
            f"A_Fijar se asigna 100% al bucket de cosecha, distribuido entre "
            f"puertos por el peso del FS PH+Fij. "
            f"Share del puerto: {share_str}"
        )

        # ── Construir tabla HTML con totales en kt + subtotales ──
        # Schema nuevo: rows = meses calendario, cols = 4 puertos + Total.
        # Precomputar subtotales por MES (filas) y por PUERTO (cols).
        # Usamos fs_total_tn (FS PH+Fij + a_fijar pro-rata) para que cierren
        # con las cards de arriba.
        row_totals_m = {}   # (yr, mn) → {fs, real, proj}
        col_totals_d = {}   # d_slug → {fs, real, proj, any_export}
        grand = {"fs": 0.0, "real": 0, "proj": 0}
        for d_slug in destino_slugs:
            col_totals_d[d_slug] = {"fs": 0.0, "real": 0, "proj": 0,
                                     "any_export": False}
        for (_lbl, yr, mn) in months_calendar:
            row_totals_m[(yr, mn)] = {"fs": 0.0, "real": 0, "proj": 0,
                                       "any_export": False}
            for d_slug in destino_slugs:
                data = cell_cache[(d_slug, yr, mn)]
                fs_eff = data.get("fs_total_tn", data["fs_tn"])
                row_totals_m[(yr, mn)]["fs"]   += fs_eff
                row_totals_m[(yr, mn)]["real"] += data["pipeline_real_tn"]
                row_totals_m[(yr, mn)]["proj"] += data["projected_tn"]
                row_totals_m[(yr, mn)]["any_export"] |= data["is_export"]
                col_totals_d[d_slug]["fs"]   += fs_eff
                col_totals_d[d_slug]["real"] += data["pipeline_real_tn"]
                col_totals_d[d_slug]["proj"] += data["projected_tn"]
                col_totals_d[d_slug]["any_export"] |= data["is_export"]
                grand["fs"]   += fs_eff
                grand["real"] += data["pipeline_real_tn"]
                grand["proj"] += data["projected_tn"]

        def _subtotal_cell_html(fs_tn, lin_real_tn, proj_tn, is_export_total: bool,
                                biz_left: int = 0):
            """Celda de subtotal — grid 2×2 con FS·LINEUP arriba y POS·PACE abajo.

            Pace = -pos / biz_left (mismo convenio que las celdas regulares:
            positivo = falta sumar, negativo = sobra).
            """
            lin_total = lin_real_tn + proj_tn
            ast = "*" if proj_tn > 0 else ""
            pos = fs_tn - lin_total
            pos_c = "#1d6e51" if pos >= 0 else "#a32d2d"
            pace_c = "#a32d2d" if pos < 0 else ("#1d6e51" if pos > 0 else "#888")
            pace = (-pos / biz_left) if biz_left > 0 else None
            days_chip_sub = (
                f"<div style='font-size:0.5rem;color:#bbb;line-height:1;'>"
                f"{biz_left}d</div>" if biz_left > 0 else ""
            )

            if not is_export_total:
                lin_value = "<div style='font-weight:700;font-size:0.82rem;color:#bbb;'>—</div>"
                pos_value = (
                    f"<div style='font-weight:700;font-size:0.82rem;color:#1d6e51;'>"
                    f"{_fmt_tn(fs_tn)} <span style='font-size:0.58rem;color:#999;font-weight:500;'>kt</span></div>"
                )
                pace_value = "<div style='font-weight:700;font-size:0.82rem;color:#bbb;'>—</div>"
            else:
                lin_value = (
                    f"<div style='font-weight:700;font-size:0.82rem;color:#1565C0;'>"
                    f"{_fmt_tn(lin_total)} <span style='font-size:0.58rem;color:#999;font-weight:500;'>kt</span></div>"
                )
                pos_kt_total = pos / 1000
                pos_str = f"{pos_kt_total:+,.0f}".replace(",", ".")
                pos_value = (
                    f"<div style='font-weight:700;font-size:0.82rem;color:{pos_c};'>"
                    f"{pos_str} <span style='font-size:0.58rem;color:#999;font-weight:500;'>kt</span></div>"
                )
                if pace is None:
                    pace_value = "<div style='font-weight:700;font-size:0.82rem;color:#bbb;'>—</div>"
                else:
                    pace_kt_total = pace / 1000
                    pace_str = f"{pace_kt_total:+,.0f}".replace(",", ".")
                    pace_value = (
                        f"<div style='font-weight:700;font-size:0.82rem;color:{pace_c};'>"
                        f"{pace_str} <span style='font-size:0.58rem;color:#999;font-weight:500;'>kt/d</span></div>"
                        f"{days_chip_sub}"
                    )

            return (
                "<div style='display:grid;grid-template-columns:1fr 1fr;"
                "gap:4px 6px;text-align:center;'>"
                # Top-left FS
                f"<div>"
                f"<div style='font-size:0.55rem;color:#888;letter-spacing:0.5px;'>FS</div>"
                f"<div style='font-weight:700;font-size:0.82rem;color:#1d6e51;'>"
                f"{_fmt_tn(fs_tn)} <span style='font-size:0.58rem;color:#999;font-weight:500;'>kt</span></div>"
                f"</div>"
                # Top-right LINEUP
                f"<div>"
                f"<div style='font-size:0.55rem;color:#888;letter-spacing:0.5px;'>EXPORTS{ast}</div>"
                f"{lin_value}"
                f"</div>"
                # Bottom-left POS
                f"<div style='border-top:1px solid rgba(0,0,0,0.06);padding-top:3px;'>"
                f"<div style='font-size:0.55rem;color:#888;letter-spacing:0.5px;'>POS</div>"
                f"{pos_value}"
                f"</div>"
                # Bottom-right PACE
                f"<div style='border-top:1px solid rgba(0,0,0,0.06);padding-top:3px;'>"
                f"<div style='font-size:0.55rem;color:#888;letter-spacing:0.5px;'>PACE</div>"
                f"{pace_value}"
                f"</div>"
                "</div>"
            )

        # ── HTML del heatmap: rows = meses, cols = 4 puertos + Total ─────
        # Cada celda: 2x2 grid con FS | EXPORTS | POS | PACE.
        # PACE de cada celda usa los días hábiles desde HOY hasta el FIN del
        # mes calendario (vencimiento del delivery).
        html = [
            "<table style='width:100%;border-collapse:collapse;"
            "font-size:0.78rem;margin-bottom:0.5rem;'>"
        ]
        html.append(
            "<thead><tr>"
            "<th style='text-align:center;padding:6px 8px;color:#666;"
            "border-bottom:1px solid #ddd;'>Mes \\ Puerto</th>"
        )
        # Total como primera columna (antes de los puertos)
        html.append(
            "<th style='text-align:center;padding:6px 8px;color:#222;"
            "border-bottom:1px solid #ddd;background:rgba(0,0,0,0.04);"
            "border-right:2px solid rgba(0,0,0,0.08);'>"
            "<div style='font-weight:700;'>Total</div>"
            "<div style='font-size:0.7rem;font-weight:400;color:#999;'>"
            "todos los puertos</div></th>"
        )
        for d_slug in destino_slugs:
            html.append(
                f"<th style='text-align:center;padding:6px 8px;color:#444;"
                f"border-bottom:1px solid #ddd;'>"
                f"<div style='font-weight:600;'>{DESTINOS[d_slug]['label']}</div>"
                f"</th>"
            )
        html.append("</tr></thead><tbody>")

        # Para mostrar el bucket en el label del mes (info de delivery)
        month_to_bucket = BUCKETS_BY_SLUG.get(slug, {})

        # Una fila por mes calendario
        # En modo "Acumulada" llevamos un running total acumulando meses
        # hacia adelante, tanto por puerto como para el Total del mes.
        cum_by_port: dict[str, dict] = {
            d: {"fs": 0.0, "lin": 0.0, "has_proj": False}
            for d in destino_slugs
        }
        cum_row_total = {"fs": 0.0, "real": 0, "proj": 0, "any_export": False}
        for (mlbl, yr, mn) in months_calendar:
            bucket_of_month = month_to_bucket.get(mn, "")
            # Label de la fila: "Mar 26 · MAM"
            month_short = f"{_MONTH_NAMES[mn][:3]} {str(yr)[-2:]}"
            row_label_html = (
                f"<div style='font-weight:600;color:#333;'>{month_short}</div>"
                f"<div style='font-size:0.65rem;color:#999;font-weight:500;'>"
                f"{bucket_of_month}</div>"
            )
            html.append(
                f"<tr><td style='padding:6px 8px;text-align:center;"
                f"border-bottom:1px solid #eee;'>{row_label_html}</td>"
            )

            # Días hábiles desde hoy al fin de este mes (para PACE)
            last_day = monthrange(yr, mn)[1]
            end_of_month = date(yr, mn, last_day)
            biz_left_mn = _biz_days_to(end_of_month)
            days_chip = (
                f"<div style='font-size:0.5rem;color:#bbb;line-height:1;'>"
                f"{biz_left_mn}d</div>" if biz_left_mn > 0 else ""
            )

            # ── Subtotal del mes (PRIMERA columna después del label) ──
            rt = row_totals_m[(yr, mn)]
            cum_row_total["fs"]   += rt["fs"]
            cum_row_total["real"] += rt["real"]
            cum_row_total["proj"] += rt["proj"]
            cum_row_total["any_export"] |= rt["any_export"]
            if is_acumulada:
                tot_fs = cum_row_total["fs"]
                tot_real = cum_row_total["real"]
                tot_proj = cum_row_total["proj"]
                tot_any_export = cum_row_total["any_export"]
            else:
                tot_fs = rt["fs"]
                tot_real = rt["real"]
                tot_proj = rt["proj"]
                tot_any_export = rt["any_export"]
            html.append(
                f"<td style='padding:6px 4px;background:rgba(0,0,0,0.04);"
                f"border-bottom:1px solid #eee;text-align:center;"
                f"border-right:2px solid rgba(0,0,0,0.08);'>"
                f"{_subtotal_cell_html(tot_fs, tot_real, tot_proj, tot_any_export, biz_left_mn)}"
                f"</td>"
            )

            for d_slug in destino_slugs:
                data = cell_cache[(d_slug, yr, mn)]
                is_interior = not data["is_export"]
                if is_interior:
                    bg = "rgba(0,0,0,0.025)"
                else:
                    bg, _fg = _coverage_color(data["coverage_pct"])

                # FS con a_fijar pro-rata + Exports del mes
                fs_mes = data.get("fs_total_tn", data["fs_tn"])
                lin_mes = data["pipeline_total_tn"]
                mes_has_proj = data["has_projection"]

                # Update running totals por puerto
                cum_by_port[d_slug]["fs"] += fs_mes
                cum_by_port[d_slug]["lin"] += lin_mes
                cum_by_port[d_slug]["has_proj"] = (
                    cum_by_port[d_slug]["has_proj"] or mes_has_proj
                )

                if is_acumulada:
                    fs_show = cum_by_port[d_slug]["fs"]
                    lin_show = cum_by_port[d_slug]["lin"]
                    pos = fs_show - lin_show
                    cell_has_proj = cum_by_port[d_slug]["has_proj"]
                else:
                    fs_show = fs_mes
                    lin_show = lin_mes
                    pos = fs_mes - lin_mes
                    cell_has_proj = mes_has_proj

                asterisk = "*" if cell_has_proj else ""
                pos_c = "#1d6e51" if pos >= 0 else "#a32d2d"
                pos_kt_cell = pos / 1000
                pos_cell_str = f"{pos_kt_cell:+,.0f}".replace(",", ".")

                if biz_left_mn > 0:
                    pace_cell = -pos / biz_left_mn
                    pace_kt_cell = pace_cell / 1000
                    pace_cell_str = f"{pace_kt_cell:+,.0f}".replace(",", ".")
                else:
                    pace_cell_str = "—"
                pace_c = "#a32d2d" if pos < 0 else ("#1d6e51" if pos > 0 else "#888")

                if is_interior:
                    lineup_value_html = (
                        "<div style='font-weight:700;font-size:0.82rem;color:#bbb;'>—</div>"
                    )
                    pos_value_html = (
                        f"<div style='font-weight:700;font-size:0.82rem;color:#1d6e51;'>"
                        f"{_fmt_tn(fs_show)} <span style='font-size:0.58rem;color:#999;font-weight:500;'>kt</span></div>"
                    )
                    pace_value_html = "<div style='font-weight:700;font-size:0.82rem;color:#bbb;'>—</div>"
                else:
                    lineup_value_html = (
                        f"<div style='font-weight:700;font-size:0.82rem;color:#1565C0;'>"
                        f"{_fmt_tn(lin_show)} <span style='font-size:0.58rem;color:#999;font-weight:500;'>kt</span></div>"
                    )
                    pos_value_html = (
                        f"<div style='font-weight:700;font-size:0.82rem;color:{pos_c};'>"
                        f"{pos_cell_str} <span style='font-size:0.58rem;color:#999;font-weight:500;'>kt</span></div>"
                    )
                    pace_value_html = (
                        f"<div style='font-weight:700;font-size:0.82rem;color:{pace_c};'>"
                        f"{pace_cell_str} <span style='font-size:0.58rem;color:#999;font-weight:500;'>kt/d</span></div>"
                        f"{days_chip}"
                    )

                html.append(
                    f"<td style='padding:6px 4px;background:{bg};"
                    f"border-bottom:1px solid #eee;text-align:center;'>"
                    f"<div style='display:grid;grid-template-columns:1fr 1fr;"
                    f"gap:4px 6px;text-align:center;'>"
                    f"<div>"
                    f"<div style='font-size:0.55rem;color:#888;letter-spacing:0.5px;'>FS</div>"
                    f"<div style='font-weight:700;font-size:0.82rem;color:#1d6e51;'>"
                    f"{_fmt_tn(fs_show)} <span style='font-size:0.58rem;color:#999;font-weight:500;'>kt</span></div>"
                    f"</div>"
                    f"<div>"
                    f"<div style='font-size:0.55rem;color:#888;letter-spacing:0.5px;'>EXPORTS{asterisk}</div>"
                    f"{lineup_value_html}"
                    f"</div>"
                    f"<div style='border-top:1px solid rgba(0,0,0,0.06);padding-top:3px;'>"
                    f"<div style='font-size:0.55rem;color:#888;letter-spacing:0.5px;'>POS</div>"
                    f"{pos_value_html}"
                    f"</div>"
                    f"<div style='border-top:1px solid rgba(0,0,0,0.06);padding-top:3px;'>"
                    f"<div style='font-size:0.55rem;color:#888;letter-spacing:0.5px;'>PACE</div>"
                    f"{pace_value_html}"
                    f"</div>"
                    f"</div></td>"
                )
            html.append("</tr>")

        # Fila de subtotales por puerto (suma de todos los meses).
        # El primer TD después del label es el GRAND TOTAL (esquina), después
        # vienen los 4 puertos en el mismo orden que el header.
        html.append(
            "<tr style='background:rgba(0,0,0,0.04);"
            "border-top:2px solid rgba(0,0,0,0.08);'>"
            "<td style='padding:6px 8px;font-weight:700;color:#222;"
            "text-align:center;'>Total</td>"
        )
        # Grand total como primera columna después del label (alineado con el
        # header de la columna Total que también está acá).
        html.append(
            f"<td style='padding:6px 4px;text-align:center;"
            f"background:rgba(0,0,0,0.07);"
            f"border-right:2px solid rgba(0,0,0,0.08);'>"
            f"{_subtotal_cell_html(grand['fs'], grand['real'], grand['proj'], True, biz_days_remaining)}"
            f"</td>"
        )
        for d_slug in destino_slugs:
            ct = col_totals_d[d_slug]
            html.append(
                f"<td style='padding:6px 4px;text-align:center;'>"
                f"{_subtotal_cell_html(ct['fs'], ct['real'], ct['proj'], ct['any_export'], biz_days_remaining)}"
                f"</td>"
            )
        html.append("</tr>")
        html.append("</tbody></table>")

        st.markdown("".join(html), unsafe_allow_html=True)

    st.divider()
    st.caption(
        "**Cobertura = Pipeline / FS × 100**. Pipeline incluye Lineups reales "
        "(meses con xls cargado) + proyección de meses faltantes (MARS Exports "
        "× share del puerto). Filas = meses calendario de delivery; columnas "
        "= 4 puertos (Up River, Bahía, Necochea, Interior). "
        "PACE por celda = días hábiles desde hoy hasta el fin del mes."
    )

    # ──────────────────────────────────────────────────────────────────────
    # 🏛 Pos. Física LDC · data interna manual
    # Layout consolidado: 6 items son COLUMNAS globales agrupadas por
    # puerto. Cada fila es (mes × cultivo). Item label se muestra UNA vez
    # en el header, cultivo se escribe en la primera col de cada fila.
    # ──────────────────────────────────────────────────────────────────────
    st.divider()
    st.markdown("## 🏛 Pos. Física LDC")
    st.caption(
        "Datos internos de LDC (manual). Items (BP, FV, Stk, OV, OM, FC) en "
        "columnas; meses + cultivos en filas. Cada bloque de 6 columnas "
        "representa un puerto. Editá los valores en `pos_fisica_ldc_data.py`."
    )
    try:
        import sys as _sys_ldc
        if str(app_all_dir) not in _sys_ldc.path:
            _sys_ldc.path.insert(0, str(app_all_dir))
        from pos_fisica_ldc_data import (
            LDC_FIELDS as _LDC_FIELDS,
            get_ldc_cell as _get_ldc_cell,
            get_ldc_total_month as _get_ldc_total,
        )
    except Exception as e:
        st.error(f"No pude cargar pos_fisica_ldc_data.py: {e}")
        return

    # Abreviaciones cortas para los 6 items (cols del mini-bloque)
    _LDC_ITEM_ABBR = {
        "business_plan":  "BP",
        "faltan_vender":  "FV",
        "stocks":         "Stk",
        "open_vencido":   "OV",
        "open_mes":       "OM",
        "falta_comprar":  "FC",
    }
    _LDC_ITEM_FULL_LABELS = [
        ("BP",  "Business Plan",  "#1d6e51"),
        ("FV",  "Faltan vender",  "#F57C00"),
        ("Stk", "Stocks",         "#1565C0"),
        ("OV",  "Open vencido",   "#a32d2d"),
        ("OM",  "Open del mes",   "#7B3FB8"),
        ("FC",  "Falta comprar",  "#444444"),
    ]
    _LDC_ITEM_KEYS = [k for k, _, _ in _LDC_FIELDS]
    _LDC_ITEM_COLORS = {k: c for k, _, c in _LDC_FIELDS}

    _LDC_PORTS = [
        (None,       "Total",        "rgba(0,0,0,0.04)"),
        ("uprivers", "Up River",     "transparent"),
        ("bahia",    "Bahía Blanca", "transparent"),
        ("necochea", "Necochea",     "transparent"),
    ]
    _LDC_CROPS = [
        ("maiz",   "🌽 Maíz"),
        ("trigo",  "🌾 Trigo"),
        ("sorgo",  "🌱 Sorgo"),
        ("cebada", "🌿 Cebada"),
    ]

    def _fmt_ldc(v):
        if v is None or v == 0:
            return "—"
        try:
            return f"{int(round(float(v))):,}".replace(",", ".")
        except Exception:
            return str(v)

    # Leyenda de abreviaciones
    _legend_html = " · ".join(
        f"<span style='color:{c};font-weight:600'>{abbr}</span> "
        f"<span style='color:#666'>{full}</span>"
        for abbr, full, c in _LDC_ITEM_FULL_LABELS
    )
    st.markdown(
        f"<div style='font-size:0.72rem;color:#888;margin-bottom:0.4rem'>"
        f"<b>Items:</b> {_legend_html}</div>",
        unsafe_allow_html=True,
    )

    months_calendar = MONTHS_BY_SLUG["maiz"]

    # Construir tabla HTML
    html = ["<table style='width:100%;border-collapse:collapse;"
            "font-size:0.7rem;margin-bottom:0.5rem;table-layout:auto;'>"]

    # ── Header de 2 niveles ──
    # Nivel 1: puerto (Mes | Cultivo | Total: 6 cols | UpRiver: 6 cols | Bahía: 6 cols | Necochea: 6 cols)
    html.append("<thead>")
    html.append("<tr>")
    html.append("<th rowspan=2 style='text-align:center;padding:6px 4px;"
                "color:#666;border-bottom:1px solid #ddd;"
                "vertical-align:middle;'>Mes</th>")
    html.append("<th rowspan=2 style='text-align:center;padding:6px 4px;"
                "color:#666;border-bottom:1px solid #ddd;"
                "vertical-align:middle;'>Cultivo</th>")
    for p_slug, p_lbl, p_bg in _LDC_PORTS:
        html.append(
            f"<th colspan=6 style='text-align:center;padding:4px 4px;"
            f"color:#222;border-bottom:1px solid #ccc;background:{p_bg};"
            f"font-weight:700;border-left:2px solid rgba(0,0,0,0.08);'>"
            f"{p_lbl}</th>"
        )
    html.append("</tr>")
    # Nivel 2: items (BP | FV | Stk | OV | OM | FC) × 4 puertos
    html.append("<tr>")
    for p_slug, _, p_bg in _LDC_PORTS:
        for i, (abbr, _, color) in enumerate(_LDC_ITEM_FULL_LABELS):
            border_left = ("border-left:2px solid rgba(0,0,0,0.08);"
                            if i == 0 else "")
            html.append(
                f"<th style='text-align:center;padding:3px 3px;"
                f"font-size:0.6rem;color:{color};background:{p_bg};"
                f"border-bottom:1px solid #ddd;{border_left}'>"
                f"{abbr}</th>"
            )
    html.append("</tr>")
    html.append("</thead><tbody>")

    # ── Body: una fila por (mes, cultivo) ──
    for (mlbl, yr, mn) in months_calendar:
        month_short = f"{_MONTH_NAMES[mn][:3]} {str(yr)[-2:]}"
        for crop_idx, (crop_slug, crop_lbl) in enumerate(_LDC_CROPS):
            # Mes: solo en la primera fila del bloque (rowspan = N cultivos)
            mes_cell = ""
            if crop_idx == 0:
                mes_cell = (
                    f"<td rowspan={len(_LDC_CROPS)} "
                    f"style='padding:4px 4px;text-align:center;"
                    f"border-bottom:1px solid #ddd;font-weight:700;"
                    f"color:#333;vertical-align:middle;"
                    f"background:rgba(0,0,0,0.02);font-size:0.78rem;'>"
                    f"{month_short}</td>"
                )
            html.append(f"<tr>{mes_cell}")
            # Cultivo
            border_bottom = ("1px solid #ddd" if crop_idx == len(_LDC_CROPS) - 1
                              else "1px solid #f0f0f0")
            html.append(
                f"<td style='padding:3px 6px;text-align:left;"
                f"border-bottom:{border_bottom};font-size:0.7rem;"
                f"font-weight:600;color:#333;white-space:nowrap;'>"
                f"{crop_lbl}</td>"
            )
            # Por puerto: 6 valores
            for p_slug, _, p_bg in _LDC_PORTS:
                if p_slug is None:
                    cell = _get_ldc_total(crop_slug, yr, mn)
                else:
                    cell = _get_ldc_cell(crop_slug, yr, mn, p_slug)
                for i, key in enumerate(_LDC_ITEM_KEYS):
                    v = cell.get(key, 0)
                    color = _LDC_ITEM_COLORS[key]
                    val_str = _fmt_ldc(v)
                    border_left = ("border-left:2px solid rgba(0,0,0,0.08);"
                                    if i == 0 else "")
                    style = (
                        f"text-align:right;padding:2px 4px;"
                        f"border-bottom:{border_bottom};background:{p_bg};"
                        f"font-size:0.65rem;color:{color};"
                        f"font-weight:600;white-space:nowrap;{border_left}"
                    )
                    if val_str == "—":
                        style = style.replace(f"color:{color}", "color:#ccc"
                                              ).replace("font-weight:600",
                                                          "font-weight:400")
                    html.append(f"<td style='{style}'>{val_str}</td>")
            html.append("</tr>")
    html.append("</tbody></table>")
    st.markdown("".join(html), unsafe_allow_html=True)

    st.caption(
        "Para llenar la tabla, editá `pos_fisica_ldc_data.py` agregando "
        "entradas tipo `LDC_DATA['maiz']['2026_05']['uprivers'] = "
        "{'business_plan': 200_000, 'faltan_vender': 35_000, ...}`. "
        "Las celdas vacías muestran —. La columna Total es la suma de los "
        "3 puertos export."
    )
