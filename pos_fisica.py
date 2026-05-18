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
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st


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
    """Lee matriz_<slug>_<puerto>.csv. Devuelve DF vacío si no existe."""
    p = Path(_fs_dir_str) / "data" / f"matriz_{slug}_{puerto}.csv"
    if not p.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(p)
    except Exception:
        return pd.DataFrame()


def _fs_bucket_total(df: pd.DataFrame, bucket: str) -> int:
    """Suma total del bucket sobre todas las filas (mensuales + diarias)."""
    if df.empty or bucket not in df.columns:
        return 0
    sub = df[df["tipo"].isin(["mensual", "diario"])]
    return int(sub[bucket].sum())


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


def render_pos_fisica(app_all_dir: Path) -> None:
    fs_dir = app_all_dir / "fs_maiz"
    lineups_dir = app_all_dir / "Lineups"
    mars_dir = app_all_dir / "0. MARS"

    st.title("📦 Posición Física")
    st.caption(
        "Comparación **FS vendido** (verde) vs **Lineup estimado** (azul, "
        "Real + Proyectado) por cultivo, destino y bucket. Los valores con "
        "`*` incluyen proyección (MARS Exports × share histórico del puerto). "
        "Color de fondo indica cobertura aproximada: 🟢 ≈100% · 🟡 gap chico · "
        "🔴 gap grande · ⬜ sin data FS."
    )
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

        # ── Calcular totales del cultivo (suma sobre destinos × buckets) ──
        total_fs = 0
        total_lin_real = 0
        total_lin_proj = 0
        cell_cache: dict[tuple[str, str], dict] = {}
        for d_slug in destino_slugs:
            for b in buckets:
                data = _compute_cell_data(
                    slug, d_slug, b, fs_dir, lineups_dir, mars_dir,
                    lu_df_by_slug[slug], exports_by_slug[slug], shares_by_slug[slug],
                )
                cell_cache[(d_slug, b)] = data
                total_fs += data["fs_tn"]
                total_lin_real += data["pipeline_real_tn"]
                total_lin_proj += data["projected_tn"]
        total_lin_est = total_lin_real + total_lin_proj

        # ── Header del cultivo + resumen + shares ──
        st.markdown(
            f"<div style='font-weight:600;font-size:1.05rem;"
            f"margin:0.6rem 0 0.2rem 0;'>"
            f"{cult['label']}</div>",
            unsafe_allow_html=True,
        )

        # Posición REALIZADA = FS - Lineup Real (sin proyección, dónde estamos hoy)
        total_pos_real = total_fs - total_lin_real
        pos_real_color = "#1d6e51" if total_pos_real >= 0 else "#a32d2d"
        pos_real_bg = ("rgba(29,158,117,0.10)"
                       if total_pos_real >= 0 else "rgba(226,75,74,0.10)")
        pos_real_label = "LONG (FS > LIN)" if total_pos_real > 0 else (
            "SHORT (LIN > FS)" if total_pos_real < 0 else "FLAT")

        # Posición ESTIMADA = FS - Lineup Estimado (con proyección, forward-looking)
        total_pos = total_fs - total_lin_est
        pos_color = "#1d6e51" if total_pos >= 0 else "#a32d2d"
        pos_bg = ("rgba(29,158,117,0.10)"
                  if total_pos >= 0 else "rgba(226,75,74,0.10)")
        pos_label = "LONG (FS > LIN)" if total_pos > 0 else (
            "SHORT (LIN > FS)" if total_pos < 0 else "FLAT")

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

        # Línea de resumen (6 cards):
        # FS · LinReal · PosReal · LinEst · PosEst · Pace para flat
        sum_cols = st.columns(6)
        sum_cols[0].markdown(
            f"<div style='text-align:center;padding:0.4rem;"
            f"background:rgba(29,158,117,0.10);border-radius:6px;'>"
            f"<div style='font-size:0.62rem;color:#666;letter-spacing:1px;'>"
            f"FS REALIZADO</div>"
            f"<div style='font-size:1.1rem;font-weight:700;color:#1d6e51;'>"
            f"{_fmt_tn(total_fs)} kt</div></div>",
            unsafe_allow_html=True,
        )
        sum_cols[1].markdown(
            f"<div style='text-align:center;padding:0.4rem;"
            f"background:rgba(46,125,50,0.10);border-radius:6px;'>"
            f"<div style='font-size:0.62rem;color:#666;letter-spacing:1px;'>"
            f"LINEUP REALIZADO</div>"
            f"<div style='font-size:1.1rem;font-weight:700;color:#2E7D32;'>"
            f"{_fmt_tn(total_lin_real)} kt</div></div>",
            unsafe_allow_html=True,
        )
        pos_real_kt = total_pos_real / 1000
        pos_real_str = f"{pos_real_kt:+,.0f}".replace(",", ".") + " kt"
        sum_cols[2].markdown(
            f"<div style='text-align:center;padding:0.4rem;"
            f"background:{pos_real_bg};border-radius:6px;'>"
            f"<div style='font-size:0.62rem;color:#666;letter-spacing:1px;'>"
            f"POS. REALIZADA · {pos_real_label}</div>"
            f"<div style='font-size:1.1rem;font-weight:700;color:{pos_real_color};'>"
            f"{pos_real_str}</div></div>",
            unsafe_allow_html=True,
        )
        sum_cols[3].markdown(
            f"<div style='text-align:center;padding:0.4rem;"
            f"background:rgba(21,101,192,0.10);border-radius:6px;'>"
            f"<div style='font-size:0.62rem;color:#666;letter-spacing:1px;'>"
            f"LINEUP ESTIMADO *</div>"
            f"<div style='font-size:1.1rem;font-weight:700;color:#1565C0;'>"
            f"{_fmt_tn(total_lin_est)} kt</div></div>",
            unsafe_allow_html=True,
        )
        pos_kt = total_pos / 1000
        pos_str = f"{pos_kt:+,.0f}".replace(",", ".") + " kt"
        sum_cols[4].markdown(
            f"<div style='text-align:center;padding:0.4rem;"
            f"background:{pos_bg};border-radius:6px;'>"
            f"<div style='font-size:0.62rem;color:#666;letter-spacing:1px;'>"
            f"POS. ESTIMADA · {pos_label}</div>"
            f"<div style='font-size:1.1rem;font-weight:700;color:{pos_color};'>"
            f"{pos_str}</div></div>",
            unsafe_allow_html=True,
        )
        # 6ta card: Pace para llegar a flat
        if pace_to_flat is None:
            pace_str = "—"
        else:
            pace_kt = pace_to_flat / 1000
            pace_str = f"{pace_kt:,.0f}".replace(",", ".") + " kt/d"
        sum_cols[5].markdown(
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
            f"Pos. Realizada = FS − Lineup Real · Pos. Estimada = FS − Lineup Estimado "
            f"(con MARS×share). Long (+) = sobre-vendido vs pipeline · Short (−) = al revés. "
            f"Pace a flat = |Pos. Estimada| / días hábiles hasta {campaign_end.strftime('%d %b %Y')}. "
            f"Share del puerto: {share_str}"
        )

        # ── Construir tabla HTML con totales en kt + subtotales ──
        # Precomputar subtotales por destino (filas) y por bucket (columnas)
        row_totals = {}   # d_slug → {fs, real, proj}
        col_totals = {}   # bucket → {fs, real, proj}
        grand = {"fs": 0, "real": 0, "proj": 0}
        for d_slug in destino_slugs:
            row_totals[d_slug] = {"fs": 0, "real": 0, "proj": 0,
                                   "any_export": False}
            for b in buckets:
                data = cell_cache[(d_slug, b)]
                row_totals[d_slug]["fs"]   += data["fs_tn"]
                row_totals[d_slug]["real"] += data["pipeline_real_tn"]
                row_totals[d_slug]["proj"] += data["projected_tn"]
                row_totals[d_slug]["any_export"] |= data["is_export"]
                col_totals.setdefault(b, {"fs": 0, "real": 0, "proj": 0})
                col_totals[b]["fs"]   += data["fs_tn"]
                col_totals[b]["real"] += data["pipeline_real_tn"]
                col_totals[b]["proj"] += data["projected_tn"]
        for b in buckets:
            grand["fs"]   += col_totals[b]["fs"]
            grand["real"] += col_totals[b]["real"]
            grand["proj"] += col_totals[b]["proj"]

        def _subtotal_cell_html(fs_tn, lin_real_tn, proj_tn, is_export_total: bool,
                                biz_left: int = 0):
            """Celda de subtotal — grid 2×2 con FS·LINEUP arriba y POS·PACE abajo."""
            lin_total = lin_real_tn + proj_tn
            ast = "*" if proj_tn > 0 else ""
            pos = fs_tn - lin_total
            pos_c = "#1d6e51" if pos >= 0 else "#a32d2d"
            pace = (pos / biz_left) if biz_left > 0 else None

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
                        f"<div style='font-weight:700;font-size:0.82rem;color:{pos_c};'>"
                        f"{pace_str} <span style='font-size:0.58rem;color:#999;font-weight:500;'>kt/d</span></div>"
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
                f"<div style='font-size:0.55rem;color:#888;letter-spacing:0.5px;'>LINEUP{ast}</div>"
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

        html = [
            "<table style='width:100%;border-collapse:collapse;"
            "font-size:0.78rem;margin-bottom:0.5rem;'>"
        ]
        html.append(
            "<thead><tr>"
            "<th style='text-align:center;padding:6px 8px;color:#666;"
            "border-bottom:1px solid #ddd;'>Destino \\ Bucket</th>"
        )
        for b in buckets:
            html.append(
                f"<th style='text-align:center;padding:6px 8px;color:#444;"
                f"border-bottom:1px solid #ddd;'>"
                f"<div style='font-weight:600;'>{b}</div>"
                f"<div style='font-size:0.7rem;font-weight:400;color:#999;'>"
                f"{BUCKET_LABELS.get(b, '')}</div>"
                f"</th>"
            )
        # Header del subtotal por fila (columna Total a la derecha)
        html.append(
            "<th style='text-align:center;padding:6px 8px;color:#222;"
            "border-bottom:1px solid #ddd;background:rgba(0,0,0,0.04);'>"
            "<div style='font-weight:700;'>Total</div>"
            "<div style='font-size:0.7rem;font-weight:400;color:#999;'>"
            "todos los buckets</div></th>"
        )
        html.append("</tr></thead><tbody>")

        # Una fila por destino
        for d_slug in destino_slugs:
            d_lbl = DESTINOS[d_slug]["label"]
            html.append(
                f"<tr><td style='padding:6px 8px;font-weight:600;color:#333;"
                f"text-align:center;border-bottom:1px solid #eee;'>{d_lbl}</td>"
            )
            for b in buckets:
                data = cell_cache[(d_slug, b)]
                is_interior = not data["is_export"]
                if is_interior:
                    # Fondo gris neutro: no aplica el concepto de cobertura
                    bg = "rgba(0,0,0,0.025)"
                else:
                    bg, _fg = _coverage_color(data["coverage_pct"])
                asterisk = "*" if data["has_projection"] else ""

                pos = data["fs_tn"] - data["pipeline_total_tn"]
                pos_c = "#1d6e51" if pos >= 0 else "#a32d2d"
                pos_kt_cell = pos / 1000
                pos_cell_str = f"{pos_kt_cell:+,.0f}".replace(",", ".")

                # Pace = pos / biz_days_remaining (kt/d, signed con el mismo signo de POS)
                if biz_days_remaining > 0:
                    pace_cell = pos / biz_days_remaining  # tn/d
                    pace_kt_cell = pace_cell / 1000
                    pace_cell_str = f"{pace_kt_cell:+,.0f}".replace(",", ".")
                else:
                    pace_cell_str = "—"

                # Lineup / POS / Pace según sea Interior o export
                if is_interior:
                    lineup_value_html = (
                        "<div style='font-weight:700;font-size:0.82rem;color:#bbb;'>—</div>"
                    )
                    pos_value_html = (
                        f"<div style='font-weight:700;font-size:0.82rem;color:#1d6e51;'>"
                        f"{_fmt_tn(data['fs_tn'])} <span style='font-size:0.58rem;color:#999;font-weight:500;'>kt</span></div>"
                    )
                    pace_value_html = "<div style='font-weight:700;font-size:0.82rem;color:#bbb;'>—</div>"
                else:
                    lineup_value_html = (
                        f"<div style='font-weight:700;font-size:0.82rem;color:#1565C0;'>"
                        f"{_fmt_tn(data['pipeline_total_tn'])} <span style='font-size:0.58rem;color:#999;font-weight:500;'>kt</span></div>"
                    )
                    pos_value_html = (
                        f"<div style='font-weight:700;font-size:0.82rem;color:{pos_c};'>"
                        f"{pos_cell_str} <span style='font-size:0.58rem;color:#999;font-weight:500;'>kt</span></div>"
                    )
                    pace_value_html = (
                        f"<div style='font-weight:700;font-size:0.82rem;color:{pos_c};'>"
                        f"{pace_cell_str} <span style='font-size:0.58rem;color:#999;font-weight:500;'>kt/d</span></div>"
                    )

                # 2×2 grid: FS | LINEUP arriba ; POS | PACE abajo
                html.append(
                    f"<td style='padding:6px 4px;background:{bg};"
                    f"border-bottom:1px solid #eee;text-align:center;'>"
                    f"<div style='display:grid;grid-template-columns:1fr 1fr;"
                    f"gap:4px 6px;text-align:center;'>"
                    # Top-left: FS
                    f"<div>"
                    f"<div style='font-size:0.55rem;color:#888;letter-spacing:0.5px;'>FS</div>"
                    f"<div style='font-weight:700;font-size:0.82rem;color:#1d6e51;'>"
                    f"{_fmt_tn(data['fs_tn'])} <span style='font-size:0.58rem;color:#999;font-weight:500;'>kt</span></div>"
                    f"</div>"
                    # Top-right: LINEUP
                    f"<div>"
                    f"<div style='font-size:0.55rem;color:#888;letter-spacing:0.5px;'>LINEUP{asterisk}</div>"
                    f"{lineup_value_html}"
                    f"</div>"
                    # Bottom-left: POS
                    f"<div style='border-top:1px solid rgba(0,0,0,0.06);padding-top:3px;'>"
                    f"<div style='font-size:0.55rem;color:#888;letter-spacing:0.5px;'>POS</div>"
                    f"{pos_value_html}"
                    f"</div>"
                    # Bottom-right: PACE
                    f"<div style='border-top:1px solid rgba(0,0,0,0.06);padding-top:3px;'>"
                    f"<div style='font-size:0.55rem;color:#888;letter-spacing:0.5px;'>PACE</div>"
                    f"{pace_value_html}"
                    f"</div>"
                    f"</div></td>"
                )
            # Subtotal de fila (todos los buckets para este destino)
            rt = row_totals[d_slug]
            html.append(
                f"<td style='padding:6px 4px;background:rgba(0,0,0,0.04);"
                f"border-bottom:1px solid #eee;text-align:center;"
                f"border-left:2px solid rgba(0,0,0,0.08);'>"
                f"{_subtotal_cell_html(rt['fs'], rt['real'], rt['proj'], rt['any_export'], biz_days_remaining)}"
                f"</td>"
            )
            html.append("</tr>")

        # Fila de subtotales por bucket
        html.append(
            "<tr style='background:rgba(0,0,0,0.04);"
            "border-top:2px solid rgba(0,0,0,0.08);'>"
            "<td style='padding:6px 8px;font-weight:700;color:#222;"
            "text-align:center;'>Total</td>"
        )
        for b in buckets:
            ct = col_totals[b]
            html.append(
                f"<td style='padding:6px 4px;text-align:center;'>"
                f"{_subtotal_cell_html(ct['fs'], ct['real'], ct['proj'], True, biz_days_remaining)}"
                f"</td>"
            )
        # Grand total (esquina abajo-derecha)
        html.append(
            f"<td style='padding:6px 4px;text-align:center;"
            f"background:rgba(0,0,0,0.07);"
            f"border-left:2px solid rgba(0,0,0,0.08);'>"
            f"{_subtotal_cell_html(grand['fs'], grand['real'], grand['proj'], True, biz_days_remaining)}"
            f"</td>"
        )
        html.append("</tr>")
        html.append("</tbody></table>")

        st.markdown("".join(html), unsafe_allow_html=True)

    st.divider()
    st.caption(
        "**Cobertura = Pipeline / FS × 100**. Pipeline incluye Lineups reales "
        "(Mar/Apr/May 26 hoy) + proyección de meses faltantes (MARS Exports × "
        "share del puerto). Buckets de delivery: maíz/sorgo MAM=Mar-May, "
        "JJ=Jun-Jul, AS=Aug-Sep, OND=Oct-Dec, JF=Jan-Feb. "
        "Trigo/cebada NDJ=Nov-Jan, FMA=Feb-Apr, MJJ=May-Jul, ASO=Aug-Oct."
    )
