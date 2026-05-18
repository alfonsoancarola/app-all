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
    "maiz":   {"label": "🌽 Corn",        "lineups_cargo": "Maize"},
    "trigo":  {"label": "🌾 Bread Wheat", "lineups_cargo": "Wheat"},
    "sorgo":  {"label": "🌱 Sorghum",     "lineups_cargo": "Sorghum"},
    "cebada": {"label": "🌿 Feed Barley", "lineups_cargo": "Barley"},
}

DESTINOS = {
    "uprivers": {"label": "Up River",     "lineups_zone": "Up River"},
    "bahia":    {"label": "Bahía Blanca", "lineups_zone": "Bahía Blanca"},
    "necochea": {"label": "Necochea",     "lineups_zone": "Necochea"},
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

def render_pos_fisica(app_all_dir: Path) -> None:
    fs_dir = app_all_dir / "fs_maiz"
    lineups_dir = app_all_dir / "Lineups"

    st.title("📦 Posición Física")
    st.caption(
        "Farmer Selling **vendido** (suma del bucket de delivery) vs Lineups "
        "**pipeline** (Sailed + At Roads + Lineup del mes) por cultivo, destino y mes."
    )

    # ── Selectores ──────────────────────────────────────────────────────────
    sel_cols = st.columns(3)
    cultivo_slug = sel_cols[0].selectbox(
        "Cultivo",
        options=list(CULTIVOS.keys()),
        format_func=lambda s: CULTIVOS[s]["label"],
        key="pf_cultivo",
    )
    destino_slug = sel_cols[1].selectbox(
        "Destino",
        options=list(DESTINOS.keys()),
        format_func=lambda d: DESTINOS[d]["label"],
        key="pf_destino",
    )
    month_options = MONTHS_BY_SLUG[cultivo_slug]
    month_labels = [m[0] for m in month_options]
    # Default al mes actual si está en la lista
    today = date.today()
    today_label = today.strftime("%b %Y").replace("Jan", "Jan").replace(".", "")
    try:
        default_idx = next(
            i for i, m in enumerate(month_options) if m[1] == today.year and m[2] == today.month
        )
    except StopIteration:
        default_idx = 0
    month_sel_label = sel_cols[2].selectbox(
        "Mes", options=month_labels, index=default_idx, key="pf_mes",
    )
    # Buscar el (label, year, month) del mes elegido
    month_tuple = next(m for m in month_options if m[0] == month_sel_label)
    month_year, month_num = month_tuple[1], month_tuple[2]

    # ── Determinar bucket FS y zona Lineups ─────────────────────────────────
    bucket = BUCKETS_BY_SLUG[cultivo_slug].get(month_num)
    if bucket is None:
        st.warning(
            f"No hay bucket FS definido para {month_sel_label} en "
            f"{CULTIVOS[cultivo_slug]['label']}."
        )
        return
    lu_zone = DESTINOS[destino_slug]["lineups_zone"]
    cargo = CULTIVOS[cultivo_slug]["lineups_cargo"]

    st.divider()

    # ── FS Acumulado ────────────────────────────────────────────────────────
    df_matriz = _load_matriz_puerto(str(fs_dir), cultivo_slug, destino_slug)
    fs_total = _fs_bucket_total(df_matriz, bucket)

    # ── Lineups Pipeline (sumando TODOS los meses del bucket) ──────────────
    sailed = roads = lineup = 0
    projected_tn = 0  # proyección para los meses sin xls
    bucket_months = BUCKET_MONTHS_BY_SLUG[cultivo_slug].get(bucket, [])
    # Convertir (year, month) → labels tipo "May 2026"
    bucket_month_labels = [
        f"{_MONTH_NAMES[m]} {y}" for (y, m) in bucket_months
    ]
    months_with_data: list[str] = []
    months_missing: list[tuple[int, int, str]] = []  # (year, month, label)
    port_share = 0.0
    proj_breakdown: list[tuple[str, float]] = []  # (month_label, projected_tn)

    try:
        if str(lineups_dir) not in sys.path:
            sys.path.insert(0, str(lineups_dir))
        import _lineups_loader as lu  # type: ignore

        df_lu = lu.load_for_crop(cultivo_slug, lineups_dir)
        if not df_lu.empty:
            available_months = set(df_lu["MONTH"].unique())
            for (yr, mn), lbl in zip(bucket_months, bucket_month_labels):
                if lbl in available_months:
                    months_with_data.append(lbl)
                else:
                    months_missing.append((yr, mn, lbl))
            # Actuals — meses cargados
            mask_real = (
                df_lu["MONTH"].isin(months_with_data) &
                (df_lu["ZONE"] == lu_zone)
            )
            sub = df_lu[mask_real]
            sailed = int(sub[sub["STATUS"] == "Sailed"]["TONS"].sum())
            roads  = int(sub[sub["STATUS"] == "At Roads"]["TONS"].sum())
            lineup = int(sub[sub["STATUS"] == "Lineup"]["TONS"].sum())

            # ── Proyección para meses faltantes ──
            if months_missing:
                # Share del puerto sobre los xls cargados (todos los meses, todos los status)
                shares = _compute_port_share(df_lu, list(DESTINOS[d]["lineups_zone"] for d in DESTINOS))
                port_share = shares.get(lu_zone, 0.0)
                # MARS Exports
                mars_dir = app_all_dir / "0. MARS"
                exports_kt = _load_mars_exports(str(mars_dir), cultivo_slug)
                for yr, mn, lbl in months_missing:
                    mkey = _month_to_mars_key(yr, mn)
                    exp_kt = exports_kt.get(mkey)
                    if exp_kt is None:
                        proj_breakdown.append((lbl, 0))
                        continue
                    # exp_kt está en kt; share es fracción → resultado en tn
                    proj_tn = int(round(exp_kt * 1000 * port_share))
                    projected_tn += proj_tn
                    proj_breakdown.append((lbl, proj_tn))
    except Exception as e:
        st.warning(f"No pude cargar Lineups: {e}")

    pipeline_real = sailed + roads + lineup
    pipeline_total = pipeline_real + projected_tn
    gap = fs_total - pipeline_total
    has_projection = projected_tn > 0

    # ── Header del bloque ───────────────────────────────────────────────────
    cult_lbl = CULTIVOS[cultivo_slug]["label"]
    dest_lbl = DESTINOS[destino_slug]["label"]
    st.subheader(
        f"{cult_lbl} · {dest_lbl} · {month_sel_label}  ·  bucket **{bucket}**"
    )

    # ── 2 columnas: FS | Lineups ───────────────────────────────────────────
    c_fs, c_lu = st.columns(2)

    with c_fs:
        st.markdown(
            f"""
            <div style='text-align:center;padding:1rem 0.5rem;
                        background:rgba(29,158,117,0.08);border-radius:10px;'>
                <div style='font-size:0.75rem;color:#888;letter-spacing:1px;'>
                    FARMER SELLING · acumulado bucket {bucket}
                </div>
                <div style='font-size:2.2rem;font-weight:700;color:#1d6e51;
                            line-height:1.1;margin:0.4rem 0;'>
                    {_fmt_tn(fs_total)} kt
                </div>
                <div style='font-size:0.7rem;color:#666;'>
                    Suma de mensuales cerrados + mes en curso, destino
                    <b>{dest_lbl}</b>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    # Texto chiquito describiendo qué meses son reales vs proyectados
    real_str = ", ".join(m.split()[0][:3] for m in months_with_data) if months_with_data else "ninguno"
    miss_str = ", ".join(m.split()[0][:3] for _, _, m in months_missing) if months_missing else None
    lu_subtitle_parts = [f"Real: {real_str}"]
    if miss_str:
        lu_subtitle_parts.append(
            f"Proyectado: {miss_str} (MARS×{port_share*100:.1f}% share)"
        )
    lu_subtitle = " · ".join(lu_subtitle_parts) + f"<br/>{dest_lbl}"

    asterisk = " *" if has_projection else ""

    with c_lu:
        st.markdown(
            f"""
            <div style='text-align:center;padding:1rem 0.5rem;
                        background:rgba(21,101,192,0.08);border-radius:10px;'>
                <div style='font-size:0.75rem;color:#888;letter-spacing:1px;'>
                    LINEUPS · pipeline bucket {bucket}{asterisk}
                </div>
                <div style='font-size:2.2rem;font-weight:700;color:#1565C0;
                            line-height:1.1;margin:0.4rem 0;'>
                    {_fmt_tn(pipeline_total)} kt{asterisk}
                </div>
                <div style='font-size:0.7rem;color:#666;line-height:1.3;'>
                    {lu_subtitle}
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    # ── Breakdown Lineups (Sailed / Roads / Lineup / Proyectado) ───────────
    st.markdown("<div style='height:0.8rem;'></div>", unsafe_allow_html=True)
    cols_b = st.columns(4 if has_projection else 3)
    cols_b[0].metric("🟢 Sailed (loaded)", f"{_fmt_tn(sailed)} kt")
    cols_b[1].metric("🟠 At Roads",        f"{_fmt_tn(roads)} kt")
    cols_b[2].metric("🔵 Lineup",          f"{_fmt_tn(lineup)} kt")
    if has_projection:
        cols_b[3].metric("🟣 Proyectado*",  f"{_fmt_tn(projected_tn)} kt",
                         help="MARS Exports × share del puerto (calculado "
                              "sobre los xls cargados).")

    st.divider()

    # ── Gap ─────────────────────────────────────────────────────────────────
    gap_color = "#1d6e51" if gap > 0 else ("#a32d2d" if gap < 0 else "#888")
    gap_lbl = (
        f"FS está {abs(gap)/1000:,.0f} kt"
        if gap != 0
        else "—"
    ).replace(",", ".")
    if gap > 0:
        gap_explain = f"por **encima** del pipeline (falta aparecer en lineup)"
    elif gap < 0:
        gap_explain = f"por **debajo** del pipeline (más pipeline que vendido)"
    else:
        gap_explain = "alineado con el pipeline"

    st.markdown(
        f"""
        <div style='text-align:center;padding:1rem;border:1px dashed {gap_color};
                    border-radius:10px;'>
            <div style='font-size:0.8rem;color:#888;letter-spacing:1px;'>
                GAP · FS − Pipeline
            </div>
            <div style='font-size:1.8rem;font-weight:700;color:{gap_color};
                        line-height:1.2;margin:0.3rem 0;'>
                {gap:+,.0f} tn
            </div>
            <div style='font-size:0.85rem;color:#444;'>
                {gap_lbl} {gap_explain}
            </div>
        </div>
        """.replace(",", "."),
        unsafe_allow_html=True,
    )

    # ── Caption con detalle del cálculo ────────────────────────────────────
    bucket_months_full = ", ".join(bucket_month_labels)
    caption_parts = [
        f"FS leído de `matriz_{cultivo_slug}_{destino_slug}.csv` (suma del "
        f"bucket **{bucket}**)",
        f"Lineups: CARGO=**{cargo}** + ZONE=**{lu_zone}** + MONTH ∈ "
        f"{{{bucket_months_full}}}",
    ]
    if has_projection:
        proj_detail = ", ".join(
            f"{lbl.split()[0][:3]} {_fmt_tn(tn)} kt" for lbl, tn in proj_breakdown
        )
        caption_parts.append(
            f"**Proyección\\***: share del puerto **{port_share*100:.1f}%** "
            f"(total {lu_zone}/total cargo en xls) × MARS Exports. "
            f"Breakdown proy: {proj_detail}"
        )
    st.caption(" · ".join(caption_parts))
