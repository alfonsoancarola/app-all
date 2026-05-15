"""
dashboard.py — Dashboard ejecutivo del App All

Combina datos de fs_maiz + Lineups en una sola vista:
  1. Compras FS de ayer por cultivo (OC / NC / total)
  2. Monthly Pace de cada cultivo (grilla 2×2) con compras + embarques
  3. Top 5 shippers de Lineups del mes en curso (por cultivo)
  4. Pizarra + Replacement por cultivo

Render: llamar `render_dashboard(app_all_dir)` desde el wrapper.
"""

from __future__ import annotations

import json
import os
import sys
from calendar import monthrange
from datetime import date, timedelta
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st


# ──────────────────────────────────────────────────────────────────────────────
# Config y helpers de cultivos
# ──────────────────────────────────────────────────────────────────────────────

CULTIVOS = [
    {"slug": "maiz",   "label": "Corn",        "emoji": "🌽",
     "oc": ["MAM", "JJ", "AS", "OND", "JF"], "has_nc": True},
    {"slug": "trigo",  "label": "Bread Wheat", "emoji": "🌾",
     "oc": ["NDJ", "FMA", "MJJ", "ASO"],     "has_nc": True},
    {"slug": "sorgo",  "label": "Sorghum",     "emoji": "🌱",
     "oc": ["MAM", "JJ", "AS", "OND", "JF"], "has_nc": False},
    {"slug": "cebada", "label": "Feed Barley", "emoji": "🌿",
     "oc": ["NDJ", "FMA", "MJJ", "ASO"],     "has_nc": False},
]

FS_TO_CARGO = {
    "maiz":   "Maize",
    "trigo":  "Wheat",
    "sorgo":  "Sorghum",
    "cebada": "Barley",
}

# Mapeo de slug → nombre de producto en el Recap Totalizado
SLUG_TO_RECAP_PROD = {
    "maiz":   "MAIZ",
    "trigo":  "TRIGO",
    "sorgo":  "SORGO",
    "cebada": "CEBADA FORRAJERA",
}

# Cosechas OC/NC por cultivo (formato Recap)
RECAP_OC_COSECHA = {p: "2025/2026" for p in SLUG_TO_RECAP_PROD.values()}
RECAP_NC_COSECHA = {p: "2026/2027" for p in SLUG_TO_RECAP_PROD.values()}

# Operaciones del Recap que cuentan como "compra física".
# Incluye ampliaciones (qtty +) y anulaciones (qtty −), que se compensan
# automáticamente al sumar. Cubrimos variantes de mayúsculas y con/sin tilde.
COMPRA_OPS = {
    # compras a precio
    "COMPRAS A PRECIO", "Compras a Precio", "Compra a Precio", "COMPRA A PRECIO",
    # fijaciones
    "FIJACIONES COMPRA", "Fijaciones Compra",
    "FIJACIONES COMPRA FAS EN PREMIO", "Fijaciones Compra Fas en Premio",
    "COMPRAS PAF", "Compras PAF",
    # ampliaciones / anulaciones (con signo embebido en QTTY)
    "AMPLIACION", "Ampliacion", "AMPLIACIÓN", "Ampliación",
    "ANULACION", "Anulacion", "ANULACIÓN", "Anulación",
}

# Carpeta del Recap Totalizado (overridable por env var)
RECAP_DIR = Path(os.environ.get(
    "RECAP_DIR",
    str(Path.home() / "5. Recap Totalizado"),
))


def _fmt_tn(v):
    """Formatea tn → kt rounded, con punto separador."""
    if v is None:
        return "—"
    try:
        kt = round(float(v) / 1000)
        if kt == 0 and v != 0:
            return f"{float(v)/1000:.1f}".replace(".", ",")
        return f"{kt:,}".replace(",", ".")
    except Exception:
        return "—"


def _fmt_usd(v, dec=2):
    if v is None:
        return "—"
    try:
        return f"${float(v):,.{dec}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return "—"


def _fmt_delta(curr, prev, suffix=""):
    if curr is None or prev is None or prev == 0:
        return ""
    pct = (curr - prev) / prev * 100
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct:.1f}%{suffix}"


# ──────────────────────────────────────────────────────────────────────────────
# Loaders
# ──────────────────────────────────────────────────────────────────────────────

def _matriz_path(fs_dir: Path, slug: str) -> Path:
    return fs_dir / "data" / f"matriz_{slug}.csv"


# Para trigo solo contamos compras con destino de exportación (Up River /
# Bahía / Necochea) — se excluye Interior.
_WHEAT_EXPORT_PORTS = ["uprivers", "bahia", "necochea"]


@st.cache_data(show_spinner=False)
def _load_matriz(_fs_dir_str: str, slug: str) -> pd.DataFrame:
    base = Path(_fs_dir_str) / "data"

    if slug == "trigo":
        # Sumamos las 3 sub-matrices de exportación
        sub_paths = [base / f"matriz_trigo_{p}.csv" for p in _WHEAT_EXPORT_PORTS]
        if all(p.exists() for p in sub_paths):
            try:
                dfs = [pd.read_csv(p) for p in sub_paths]
            except Exception:
                # Fallback al matriz total si algo falla al leer
                p_total = base / "matriz_trigo.csv"
                return pd.read_csv(p_total) if p_total.exists() else pd.DataFrame()

            num_cols = ["NDJ", "FMA", "MJJ", "ASO", "NC", "total", "min"]
            num_cols = [c for c in num_cols if c in dfs[0].columns]
            merged = dfs[0].copy()
            for other in dfs[1:]:
                merged = merged.merge(
                    other[["tipo", "label"] + num_cols],
                    on=["tipo", "label"], how="outer", suffixes=("", "_o"),
                )
                for c in num_cols:
                    co = f"{c}_o"
                    if co in merged.columns:
                        merged[c] = (merged[c].fillna(0) + merged[co].fillna(0)).astype(int)
                        merged.drop(columns=[co], inplace=True)
            return merged

    # Default: leer el matriz consolidado
    p = base / f"matriz_{slug}.csv"
    if not p.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(p)
    except Exception:
        return pd.DataFrame()


@st.cache_data(show_spinner=False)
def _load_prices(_fs_dir_str: str) -> dict:
    p = Path(_fs_dir_str) / "data" / "prices.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _parse_dia_label(s: str, year: int) -> pd.Timestamp | None:
    try:
        d, m = str(s).split("/")
        return pd.Timestamp(year, int(m), int(d))
    except Exception:
        return None


def _yesterday_row(df: pd.DataFrame, year: int) -> tuple[pd.Series | None, date | None]:
    """Devuelve la fila del último día hábil disponible (no hoy, no fin de semana).
    Y la fecha de ese día. None si no hay data."""
    if df.empty:
        return None, None
    daily = df[df["tipo"] == "diario"].copy()
    daily["fecha"] = daily["label"].apply(lambda s: _parse_dia_label(s, year))
    daily = daily.dropna(subset=["fecha"])
    today = pd.Timestamp(date.today())
    daily = daily[(daily["fecha"] < today) & (daily["fecha"].dt.weekday < 5)]
    if daily.empty:
        return None, None
    daily = daily.sort_values("fecha")
    last = daily.iloc[-1]
    return last, last["fecha"].date()


# ──────────────────────────────────────────────────────────────────────────────
# Recap Totalizado (compras propias)
# ──────────────────────────────────────────────────────────────────────────────

def _latest_recap_file(recap_dir: Path) -> Path | None:
    """Encuentra el último RecapTotalizado<...>.xlsx en la carpeta."""
    if not recap_dir.exists():
        return None
    candidates = sorted(
        recap_dir.glob("RecapTotalizado *.xlsx"),
        key=lambda p: p.stat().st_mtime, reverse=True,
    )
    return candidates[0] if candidates else None


@st.cache_data(show_spinner="Cargando compras propias (Recap)…")
def _load_recap_database(_recap_path_str: str, _mtime: float) -> pd.DataFrame:
    """Lee la hoja DATABASE del último RecapTotalizado. mtime se usa como
    invalidador de cache: cuando el archivo se actualiza, se recarga."""
    import openpyxl
    p = Path(_recap_path_str)
    if not p.exists():
        return pd.DataFrame()

    wb = openpyxl.load_workbook(p, data_only=True, read_only=True)
    if "DATABASE" not in wb.sheetnames:
        return pd.DataFrame()
    ws = wb["DATABASE"]
    rows = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        # row puede tener varios trailing Nones; padding defensivo
        padded = list(row) + [None] * max(0, 6 - len(row))
        mes, fec, prod, op, cos, qtty = padded[:6]
        rows.append({
            "fecha": fec, "producto": prod, "operacion": op,
            "cosecha": cos, "qtty": qtty,
        })
    df = pd.DataFrame(rows)
    df["fecha"] = pd.to_datetime(df["fecha"], errors="coerce")
    df = df.dropna(subset=["fecha", "producto", "qtty"])
    df["qtty"] = pd.to_numeric(df["qtty"], errors="coerce").fillna(0)
    df["producto"] = df["producto"].astype(str).str.upper().str.strip()
    df["operacion"] = df["operacion"].astype(str).str.strip()
    df["cosecha"] = df["cosecha"].astype(str).str.strip()
    # No filtramos por qtty>0: las ANULACION vienen con qtty negativa y queremos
    # que resten al sumar. Sólo descartamos filas con qtty=0 (ruido).
    return df[df["qtty"] != 0]


@st.cache_data(show_spinner=False)
def _load_recap_mat(_recap_path_str: str, _mtime: float) -> pd.DataFrame:
    """Lee la hoja DATABASE MAT del último RecapTotalizado."""
    import openpyxl
    p = Path(_recap_path_str)
    if not p.exists():
        return pd.DataFrame()
    wb = openpyxl.load_workbook(p, data_only=True, read_only=True)
    if "DATABASE MAT" not in wb.sheetnames:
        return pd.DataFrame()
    ws = wb["DATABASE MAT"]
    rows = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        if len(row) < 6:
            continue
        fec, op, prod, ent, qtty, px, *_ = row
        rows.append({
            "fecha": fec, "operacion": op, "producto": prod,
            "entrega": ent, "qtty": qtty, "px": px,
        })
    df = pd.DataFrame(rows)
    df["fecha"] = pd.to_datetime(df["fecha"], errors="coerce")
    df = df.dropna(subset=["fecha", "producto", "qtty"])
    df["qtty"] = pd.to_numeric(df["qtty"], errors="coerce").fillna(0)
    df["producto"] = df["producto"].astype(str).str.upper().str.strip()
    df["operacion"] = df["operacion"].astype(str).str.strip()
    return df[df["qtty"] > 0]


def _recap_compras_agg(df_recap: pd.DataFrame, slug: str,
                       day_from: date, day_to: date) -> dict:
    """Agrega compras propias para un cultivo en un rango de fechas.

    Returns dict {oc, nc, total_qtty}.
    """
    prod = SLUG_TO_RECAP_PROD.get(slug)
    if not prod or df_recap.empty:
        return {"oc": 0, "nc": 0, "total": 0}
    mask = (
        (df_recap["producto"] == prod) &
        (df_recap["operacion"].isin(COMPRA_OPS)) &
        (df_recap["fecha"].dt.date >= day_from) &
        (df_recap["fecha"].dt.date <= day_to)
    )
    sub = df_recap[mask]
    if sub.empty:
        return {"oc": 0, "nc": 0, "total": 0}
    oc_cos = RECAP_OC_COSECHA[prod]
    nc_cos = RECAP_NC_COSECHA[prod]
    oc = int(sub[sub["cosecha"] == oc_cos]["qtty"].sum())
    nc = int(sub[sub["cosecha"] == nc_cos]["qtty"].sum())
    return {"oc": oc, "nc": nc, "total": int(sub["qtty"].sum())}


def _recap_mat_agg(df_mat: pd.DataFrame, slug: str,
                   day_from: date, day_to: date) -> int:
    """Total tn de MAT (operaciones del mes en curso) para un cultivo."""
    prod = SLUG_TO_RECAP_PROD.get(slug)
    if not prod or df_mat.empty:
        return 0
    mask = (
        (df_mat["producto"] == prod) &
        (df_mat["fecha"].dt.date >= day_from) &
        (df_mat["fecha"].dt.date <= day_to)
    )
    return int(df_mat[mask]["qtty"].sum())


def _week_to_yesterday_df(df: pd.DataFrame, year: int) -> pd.DataFrame:
    """Devuelve las filas diarias desde el lunes de esta semana hasta ayer
    (incluyendo ambos, excluyendo hoy y fines de semana)."""
    if df.empty:
        return df
    daily = df[df["tipo"] == "diario"].copy()
    daily["fecha"] = daily["label"].apply(lambda s: _parse_dia_label(s, year))
    daily = daily.dropna(subset=["fecha"])
    today = pd.Timestamp(date.today())
    week_monday = today - pd.Timedelta(days=today.weekday())  # lunes 00:00
    daily = daily[
        (daily["fecha"] >= week_monday) &
        (daily["fecha"] < today) &
        (daily["fecha"].dt.weekday < 5)
    ]
    return daily


# ──────────────────────────────────────────────────────────────────────────────
# Monthly Pace por cultivo (mini chart para grilla 2×2)
# ──────────────────────────────────────────────────────────────────────────────

def _build_monthly_pace_chart(
    df: pd.DataFrame, cultivo: dict, today: date,
    lineups_dir: Path,
) -> alt.Chart | None:
    """Replica condensada del chart de Monthly Pace de fs_maiz, con overlay de
    embarques de Lineups."""
    if df.empty:
        return None
    daily = df[df["tipo"] == "diario"].copy()
    daily["fecha"] = daily["label"].apply(lambda s: _parse_dia_label(s, today.year))
    daily = daily.dropna(subset=["fecha"]).sort_values("fecha").reset_index(drop=True)

    oc_cols = [c for c in cultivo["oc"] if c in daily.columns]
    if not oc_cols:
        return None
    daily["oc"] = daily[oc_cols].sum(axis=1).astype(float)

    today_ts = pd.Timestamp(today)
    # Mes en curso, < hoy, lun-vie
    cm = daily[
        (daily["fecha"].dt.month == today.month) &
        (daily["fecha"].dt.year == today.year) &
        (daily["fecha"] < today_ts) &
        (daily["fecha"].dt.weekday < 5)
    ].copy()
    cm = cm.sort_values("fecha").reset_index(drop=True)
    cm["cum"] = cm["oc"].cumsum()

    # Avg últimos 10 hábiles
    past = daily[daily["fecha"] < today_ts].tail(10)
    avg = float(past["oc"].mean()) if len(past) else 0.0

    # Forecast
    last_day = monthrange(today.year, today.month)[1]
    month_start = pd.Timestamp(today.year, today.month, 1)
    month_end = pd.Timestamp(today.year, today.month, last_day)
    biz_all = pd.bdate_range(month_start, month_end)
    biz_left = [d for d in biz_all if d.normalize() >= today_ts.normalize()]
    fc_rows = []
    last_cum = float(cm["cum"].iloc[-1]) if len(cm) else 0.0
    if len(cm):
        fc_rows.append({"fecha": cm["fecha"].iloc[-1], "cum": last_cum, "serie": "Forecast"})
    running = last_cum
    for d in biz_left:
        running += avg
        fc_rows.append({"fecha": d, "cum": running, "serie": "Forecast"})

    real = cm[["fecha", "cum"]].copy()
    real["serie"] = "Compras"
    fc = pd.DataFrame(fc_rows)

    # Overlay embarques de Lineups
    lu_real = pd.DataFrame()
    lu_fc = pd.DataFrame()
    try:
        if str(lineups_dir) not in sys.path:
            sys.path.insert(0, str(lineups_dir))
        import _lineups_loader as lu  # type: ignore

        lu_df = lu.load_for_crop(cultivo["slug"], lineups_dir)
        if not lu_df.empty:
            month_lbl_lu = f"{today_ts.strftime('%B')} {today.year}"
            file_date = lu.file_last_date_for_month(month_lbl_lu, lineups_dir)
            lu_data = lu.monthly_cumulative(
                lu_df, month_lbl=month_lbl_lu,
                month_start=month_start, month_end=month_end,
                today=today_ts, last_data_date=file_date,
            )
            lu_real = lu_data["sailed_daily_cum"].rename(
                columns={"DATE": "fecha", "sailed_cum": "cum"}
            )
            lu_real["serie"] = "Loaded (Sailed)"
            # Forecast embarques: pipeline distribuido en biz days desde cap
            cap = lu_data["cap_date"]
            extra = float(lu_data["roads_total"] + lu_data["lineup_total"])
            biz_fut = [d for d in biz_all if d.normalize() > cap.normalize()]
            if biz_fut and extra > 0:
                slope = extra / len(biz_fut)
                last_lu = float(lu_real["cum"].iloc[-1]) if len(lu_real) else 0.0
                rows = [{"fecha": cap, "cum": last_lu, "serie": "Loaded + At Roads + Lineup"}]
                r = last_lu
                for d in biz_fut:
                    r += slope
                    rows.append({"fecha": d, "cum": r, "serie": "Loaded + At Roads + Lineup"})
                lu_fc = pd.DataFrame(rows)
    except Exception:
        pass

    # Construir layers
    all_data = pd.concat(
        [real, fc, lu_real, lu_fc], ignore_index=True
    ) if not real.empty else pd.concat([fc, lu_real, lu_fc], ignore_index=True)
    if all_data.empty:
        return None
    all_data["dia"] = pd.to_datetime(all_data["fecha"]).dt.strftime("%d/%m")
    dia_order = (
        all_data.sort_values("fecha")["dia"].drop_duplicates().tolist()
    )

    color = alt.Color(
        "serie:N",
        scale=alt.Scale(
            domain=["Compras", "Forecast", "Loaded (Sailed)", "Loaded + At Roads + Lineup"],
            range=["#1D9E75", "#F2C94C", "#185FA5", "#A0C4E8"],
        ),
        legend=alt.Legend(orient="bottom", title=None,
                          labelFontSize=9, symbolSize=80),
    )
    x = alt.X("dia:O", sort=dia_order,
              axis=alt.Axis(title=None, labelAngle=-45, grid=False,
                            labelFontSize=8))
    y = alt.Y("cum:Q", title=None, axis=alt.Axis(format="~s", labelFontSize=8))

    layers = []
    if not real.empty:
        layers.append(
            alt.Chart(real.assign(dia=real["fecha"].dt.strftime("%d/%m")))
            .mark_line(point=True, strokeWidth=2.5)
            .encode(x=x, y=y, color=color)
        )
    if not fc.empty:
        layers.append(
            alt.Chart(fc.assign(dia=fc["fecha"].dt.strftime("%d/%m")))
            .mark_line(point=True, strokeWidth=2.5, strokeDash=[5, 3])
            .encode(x=x, y=y, color=color)
        )
    if not lu_real.empty:
        layers.append(
            alt.Chart(lu_real.assign(dia=pd.to_datetime(lu_real["fecha"]).dt.strftime("%d/%m")))
            .mark_line(point=True, strokeWidth=2.5)
            .encode(x=x, y=y, color=color)
        )
    if not lu_fc.empty:
        layers.append(
            alt.Chart(lu_fc.assign(dia=pd.to_datetime(lu_fc["fecha"]).dt.strftime("%d/%m")))
            .mark_line(point=True, strokeWidth=2.5, strokeDash=[5, 3])
            .encode(x=x, y=y, color=color)
        )

    if not layers:
        return None
    return alt.layer(*layers).properties(
        height=240,
        title=alt.TitleParams(f"{cultivo['emoji']} {cultivo['label']}",
                              fontSize=14, anchor="start"),
    )


# ──────────────────────────────────────────────────────────────────────────────
# Replacement helpers
# ──────────────────────────────────────────────────────────────────────────────

# Ciclo CBOT corn (también usado para sorgo): H/K/N/U/Z (Mar/May/Jul/Sep/Dic)
_CBOT_CYCLE_NUM = [3, 5, 7, 9, 12]
_CBOT_MONTH_ES = {3: "Mar", 5: "May", 7: "Jul", 9: "Sep", 12: "Dic"}

# Qué "view" de cbot_usd_tn usar por cultivo
_CBOT_VIEW = {
    "maiz":   "corn",
    "sorgo":  "corn",
    "trigo":  "wheat_chicago",
    "cebada": "wheat_chicago",
}


def _next_cycle_cbot_label(ref_date: date) -> str | None:
    """Primer contrato del ciclo cuyo día 1 es > ref_date. Formato 'Jul-26'."""
    for yo in range(0, 6):
        for mn in _CBOT_CYCLE_NUM:
            yr = ref_date.year + yo
            if date(yr, mn, 1) > ref_date:
                return f"{_CBOT_MONTH_ES[mn]}-{yr % 100:02d}"
    return None


def _front_cbot_label(prices: dict, cbot_view: str, ref_date: date) -> str | None:
    """Primer contrato disponible en cbot_usd_tn[view] cuyo día 1 es >= ref_date.
    Si no encuentra ninguno >= ref_date, devuelve el primero disponible."""
    view = (prices.get("cbot_usd_tn", {}).get(cbot_view) or {})
    if not view:
        return None
    # Parse labels "Mes-YY" → date
    _MES = {"Ene":1,"Feb":2,"Mar":3,"Abr":4,"May":5,"Jun":6,
            "Jul":7,"Ago":8,"Sep":9,"Oct":10,"Nov":11,"Dic":12}
    rows = []
    for lbl in view.keys():
        try:
            mes, yy = lbl.split("-")
            rows.append((date(2000 + int(yy), _MES[mes], 1), lbl))
        except Exception:
            continue
    if not rows:
        return None
    rows.sort()
    # Devolvemos el primer contrato cuyo mes-1 sea >= ref (mes en curso o futuro)
    for d, lbl in rows:
        # Front-month = mes actual o siguiente (no pivoteamos al próximo aún si
        # estamos en el mes de entrega del current).
        if d.year > ref_date.year or (d.year == ref_date.year and d.month >= ref_date.month):
            return lbl
    return rows[-1][1]


def _compute_replacement(slug: str, prices: dict, today: date) -> dict:
    """Calcula replacement.

    - Maíz: replacement vs CBOT (next cycle del ciclo H/K/N/U/Z).
      Devuelve `repl_cents_bu` (cents/bushel diff vs CBOT).
    - Trigo / Sorgo / Cebada: no tienen Chicago asociado.
      Devuelve `repl_usd_tn` = pizarra + MINAGRI × retención + elevación.

    Returns dict con todas las keys (None donde no aplica).
    """
    out = {
        "piz": None, "minagri": None,
        "cbot_usd_tn": None, "cbot_cents_bu": None, "cbot_contract": None,
        "repl_cents_bu": None,
        "repl_usd_tn": None,
    }
    if not prices:
        return out

    cfg = prices.get("config") or {}
    piz = (prices.get("pizarra_usd_tn", {}).get(slug, {}) or {}).get("today")
    # MINAGRI cercano (FOB del shipment próximo) — para replacement de spot.
    minagri = (prices.get("minagri_fob_usd_tn", {}).get(slug, {}) or {}).get("cercano")
    out["piz"] = piz
    out["minagri"] = minagri

    if piz is None or minagri is None:
        return out

    retention = (cfg.get("retention") or {}).get(slug, 0)
    elev = cfg.get("elevation_cost_usd_tn", 12)
    usd_tn_eq = piz + minagri * retention + elev  # USD/tn

    # SOLO maíz tiene Chicago. Para los demás devolvemos repl_usd_tn (cost-add)
    if slug == "maiz":
        bushels = (cfg.get("bushels_per_tn") or {}).get(slug, 39.368)
        cents_bu_eq = usd_tn_eq * 100 / bushels

        contract = _next_cycle_cbot_label(today)
        out["cbot_contract"] = contract
        if contract:
            cbot_usd_tn = (prices.get("cbot_usd_tn", {}).get("corn") or {}).get(contract)
            out["cbot_usd_tn"] = cbot_usd_tn
            if cbot_usd_tn is not None:
                out["cbot_cents_bu"] = cbot_usd_tn * 100 / bushels
                out["repl_cents_bu"] = cents_bu_eq - out["cbot_cents_bu"]
    else:
        # Trigo / sorgo / cebada → solo el "FOB equivalente" en USD/tn
        out["repl_usd_tn"] = usd_tn_eq

    return out


# ──────────────────────────────────────────────────────────────────────────────
# Render principal
# ──────────────────────────────────────────────────────────────────────────────

def render_dashboard(app_all_dir: Path) -> None:
    fs_dir = app_all_dir / "fs_maiz"
    lineups_dir = app_all_dir / "Lineups"
    os.environ.setdefault("LINEUPS_MARS_DIR", str(app_all_dir / "0. MARS"))

    today = date.today()

    st.title("📊 Dashboard")
    st.caption(f"Last update view: {today.strftime('%A %d %B %Y')}")

    # ════════════════════════════════════════════════════════════════════════
    # 0. PIZARRA · Replacement (arriba del todo, una sola fila)
    # ════════════════════════════════════════════════════════════════════════
    prices_top = _load_prices(str(fs_dir))
    cbot_as_of = (prices_top.get("cbot_usd_tn") or {}).get("as_of")
    cbot_as_of_short = ""
    if cbot_as_of:
        try:
            _d = pd.Timestamp(cbot_as_of)
            cbot_as_of_short = _d.strftime("%d/%m")
        except Exception:
            cbot_as_of_short = str(cbot_as_of)

    piz_cols = st.columns(len(CULTIVOS))
    for i, cult in enumerate(CULTIVOS):
        piz_obj = (prices_top.get("pizarra_usd_tn", {}).get(cult["slug"]) or {})
        piz_today = piz_obj.get("today")
        piz_yest = piz_obj.get("yesterday")
        rep = _compute_replacement(cult["slug"], prices_top, today)

        delta_dod = ""
        if piz_today is not None and piz_yest is not None and piz_yest != 0:
            dod_pct = (piz_today - piz_yest) / piz_yest * 100
            color = "#1d6e51" if dod_pct >= 0 else "#a32d2d"
            delta_dod = (f"<span style='font-size:0.72rem;color:{color};'>"
                         f"{dod_pct:+.1f}% DoD</span>")

        # Maíz: replacement vs CBOT en ¢/bu (pos = above CBOT)
        # Resto: replacement = FOB equivalente en USD/tn (sin CBOT)
        if cult["slug"] == "maiz":
            repl = rep["repl_cents_bu"]
            if repl is None:
                repl_str = "—"
                repl_color = "#888"
                repl_unit = " /bu"
            else:
                repl_str = f"{repl:+.1f}¢"
                repl_color = "#1d6e51" if repl >= 0 else "#a32d2d"
                repl_unit = " /bu"
            _cbot_date_suffix = f" · close {cbot_as_of_short}" if cbot_as_of_short else ""
            repl_sub = f"vs CBOT {rep['cbot_contract'] or '—'}{_cbot_date_suffix}"
        else:
            repl_usd = rep["repl_usd_tn"]
            if repl_usd is None:
                repl_str = "—"
                repl_color = "#888"
                repl_unit = ""
            else:
                repl_str = _fmt_usd(repl_usd)
                repl_color = "#222"
                repl_unit = " /tn"
            repl_sub = "pizarra + MINAGRI×ret + elev"

        with piz_cols[i]:
            st.markdown(
                f"""
                <div style='text-align:center;padding:0.5rem 0.3rem;'>
                    <div style='font-weight:600;font-size:0.95rem;margin-bottom:0.3rem;'>
                        {cult['emoji']} {cult['label']}
                    </div>
                    <div style='font-size:0.7rem;color:#888;letter-spacing:1px;'>PIZARRA</div>
                    <div style='font-size:1.5rem;font-weight:700;color:#222;line-height:1.1;'>
                        {_fmt_usd(piz_today) if piz_today is not None else '—'}<span style='font-size:0.7rem;color:#888;'> /tn</span>
                    </div>
                    <div>{delta_dod}</div>
                    <div style='margin-top:0.45rem;font-size:0.7rem;color:#888;letter-spacing:1px;'>
                        REPLACEMENT
                    </div>
                    <div style='font-size:1.2rem;font-weight:600;color:{repl_color};line-height:1.1;'>
                        {repl_str}<span style='font-size:0.7rem;color:#888;'>{repl_unit}</span>
                    </div>
                    <div style='font-size:0.7rem;color:#888;'>
                        {repl_sub}
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    st.divider()

    # ════════════════════════════════════════════════════════════════════════
    # 1. Farmer Selling · Ayer · Semana · Pace OC (semanal + 10d)
    # ════════════════════════════════════════════════════════════════════════
    st.subheader("📅 Farmer Selling · ayer, semana y pace OC")

    cols = st.columns(len(CULTIVOS))
    yesterday_date_overall = None
    for i, cult in enumerate(CULTIVOS):
        df = _load_matriz(str(fs_dir), cult["slug"])
        last_row, last_date = _yesterday_row(df, today.year)
        yesterday_date_overall = yesterday_date_overall or last_date
        if last_row is None:
            cols[i].metric(f"{cult['emoji']} {cult['label']}", "—")
            continue

        oc_cols_present = [c for c in cult["oc"] if c in df.columns]

        # AYER (OC / NC)
        oc_y = sum(int(last_row[c]) for c in oc_cols_present)
        nc_y = int(last_row["NC"]) if cult["has_nc"] and "NC" in df.columns else 0

        # SEMANA hasta ayer (lun→ayer, sin fin de semana)
        week_df = _week_to_yesterday_df(df, today.year)
        if not week_df.empty and oc_cols_present:
            oc_w = int(week_df[oc_cols_present].sum().sum())
            nc_w = int(week_df["NC"].sum()) if cult["has_nc"] and "NC" in week_df.columns else 0
            week_n = len(week_df)
        else:
            oc_w = nc_w = week_n = 0

        # PACE OC · semana = sum_OC / N días hábiles transcurridos
        pace_w = int(round(oc_w / week_n)) if week_n > 0 else 0

        # PACE OC · 10d = avg de los últimos 10 días hábiles
        # (calculado sobre toda la matriz, no solo mes en curso)
        daily_all = df[df["tipo"] == "diario"].copy()
        daily_all["fecha"] = daily_all["label"].apply(
            lambda s: _parse_dia_label(s, today.year)
        )
        daily_all = daily_all.dropna(subset=["fecha"]).sort_values("fecha")
        today_ts = pd.Timestamp(today)
        past = daily_all[daily_all["fecha"] < today_ts].tail(10)
        if len(past) > 0 and oc_cols_present:
            pace_10d = int(round(past[oc_cols_present].sum(axis=1).mean()))
            pace_10d_n = len(past)
        else:
            pace_10d = 0
            pace_10d_n = 0

        with cols[i]:
            st.markdown(
                f"<div style='font-weight:600;font-size:1rem;text-align:center;"
                f"margin-bottom:0.3rem;'>{cult['emoji']} {cult['label']}</div>",
                unsafe_allow_html=True,
            )

            # AYER (OC / NC)
            st.markdown(
                f"<div style='text-align:center;font-size:0.75rem;"
                f"color:#888;letter-spacing:1px;margin-top:0.3rem;'>AYER</div>",
                unsafe_allow_html=True,
            )
            sub_l, sub_r = st.columns(2)
            sub_l.markdown(
                f"<div style='font-size:0.78rem;color:#666;text-align:center;'>"
                f"OC<br><span style='font-size:1.05rem;font-weight:700;color:#222;'>"
                f"{_fmt_tn(oc_y)} kt</span></div>",
                unsafe_allow_html=True,
            )
            sub_r.markdown(
                f"<div style='font-size:0.78rem;color:#666;text-align:center;'>"
                f"NC<br><span style='font-size:1.05rem;font-weight:700;color:#222;'>"
                f"{_fmt_tn(nc_y) + ' kt' if cult['has_nc'] else '—'}</span></div>",
                unsafe_allow_html=True,
            )

            # Separador
            st.markdown(
                "<hr style='margin:0.6rem 0 0.4rem 0;border:none;"
                "border-top:1px solid rgba(0,0,0,0.08);'/>",
                unsafe_allow_html=True,
            )

            # SEMANA (OC / NC)
            st.markdown(
                f"<div style='text-align:center;font-size:0.75rem;"
                f"color:#888;letter-spacing:1px;'>"
                f"SEMANA ({week_n}d)</div>",
                unsafe_allow_html=True,
            )
            sub_l, sub_r = st.columns(2)
            sub_l.markdown(
                f"<div style='font-size:0.78rem;color:#666;text-align:center;'>"
                f"OC<br><span style='font-size:1.05rem;font-weight:700;color:#222;'>"
                f"{_fmt_tn(oc_w)} kt</span></div>",
                unsafe_allow_html=True,
            )
            sub_r.markdown(
                f"<div style='font-size:0.78rem;color:#666;text-align:center;'>"
                f"NC<br><span style='font-size:1.05rem;font-weight:700;color:#222;'>"
                f"{_fmt_tn(nc_w) + ' kt' if cult['has_nc'] else '—'}</span></div>",
                unsafe_allow_html=True,
            )

            # Separador
            st.markdown(
                "<hr style='margin:0.6rem 0 0.4rem 0;border:none;"
                "border-top:1px solid rgba(0,0,0,0.08);'/>",
                unsafe_allow_html=True,
            )

            # PACE OC (semana / 10d) — solo OC
            st.markdown(
                f"<div style='text-align:center;font-size:0.75rem;"
                f"color:#888;letter-spacing:1px;'>PACE · OC</div>",
                unsafe_allow_html=True,
            )
            sub_l, sub_r = st.columns(2)
            sub_l.markdown(
                f"<div style='font-size:0.72rem;color:#666;text-align:center;'>"
                f"Semana<br><span style='font-size:1rem;font-weight:600;color:#1D9E75;'>"
                f"{_fmt_tn(pace_w)}<span style='font-size:0.7rem;color:#888;'> kt/d</span>"
                f"</span></div>",
                unsafe_allow_html=True,
            )
            sub_r.markdown(
                f"<div style='font-size:0.72rem;color:#666;text-align:center;'>"
                f"10d<br><span style='font-size:1rem;font-weight:600;color:#1D9E75;'>"
                f"{_fmt_tn(pace_10d)}<span style='font-size:0.7rem;color:#888;'> kt/d</span>"
                f"</span></div>",
                unsafe_allow_html=True,
            )

    if yesterday_date_overall:
        st.caption(
            f"Datos al cierre de **{yesterday_date_overall.strftime('%d %b %Y')}**. "
            f"Semana = lunes→ayer (sin fin de semana). "
            f"Pace OC · Semana = ΣOC / días transcurridos; "
            f"Pace OC · 10d = avg OC de los últimos 10 días hábiles."
        )

    # FS por cultivo para computar share — capturamos los valores aquí
    fs_oc_week_by_slug = {}
    fs_nc_week_by_slug = {}
    fs_oc_yest_by_slug = {}
    fs_nc_yest_by_slug = {}
    for cult in CULTIVOS:
        df_cult = _load_matriz(str(fs_dir), cult["slug"])
        if df_cult.empty:
            fs_oc_week_by_slug[cult["slug"]] = 0
            fs_nc_week_by_slug[cult["slug"]] = 0
            fs_oc_yest_by_slug[cult["slug"]] = 0
            fs_nc_yest_by_slug[cult["slug"]] = 0
            continue
        last_row_c, _ = _yesterday_row(df_cult, today.year)
        week_df_c = _week_to_yesterday_df(df_cult, today.year)
        oc_cols_c = [c for c in cult["oc"] if c in df_cult.columns]
        if last_row_c is not None and oc_cols_c:
            fs_oc_yest_by_slug[cult["slug"]] = sum(int(last_row_c[c]) for c in oc_cols_c)
            fs_nc_yest_by_slug[cult["slug"]] = (
                int(last_row_c["NC"]) if cult["has_nc"] and "NC" in df_cult.columns else 0
            )
        else:
            fs_oc_yest_by_slug[cult["slug"]] = 0
            fs_nc_yest_by_slug[cult["slug"]] = 0
        if not week_df_c.empty and oc_cols_c:
            fs_oc_week_by_slug[cult["slug"]] = int(week_df_c[oc_cols_c].sum().sum())
            fs_nc_week_by_slug[cult["slug"]] = (
                int(week_df_c["NC"].sum())
                if cult["has_nc"] and "NC" in week_df_c.columns else 0
            )
        else:
            fs_oc_week_by_slug[cult["slug"]] = 0
            fs_nc_week_by_slug[cult["slug"]] = 0

    st.divider()

    # ════════════════════════════════════════════════════════════════════════
    # 1B. Nuestras compras (Recap Totalizado) + share vs FS
    # ════════════════════════════════════════════════════════════════════════
    st.subheader("🏢 Nuestras compras · ayer y semana (share vs FS)")

    recap_file = _latest_recap_file(RECAP_DIR)
    if recap_file is None:
        st.info(
            f"No encontré ningún `RecapTotalizado *.xlsx` en `{RECAP_DIR}`. "
            "Si lo moviste, exportá `RECAP_DIR=/ruta/...` antes de lanzar la app."
        )
    else:
        df_recap = _load_recap_database(str(recap_file), recap_file.stat().st_mtime)
        df_mat = _load_recap_mat(str(recap_file), recap_file.stat().st_mtime)

        # Rango: semana corriente (lun→ayer)
        week_mon = today - timedelta(days=today.weekday())
        yesterday_d = today - timedelta(days=1)
        # Si hoy es lunes, "ayer" = viernes pasado; recortamos a sólo lun-vie
        while yesterday_d.weekday() >= 5:
            yesterday_d -= timedelta(days=1)

        rc_cols = st.columns(len(CULTIVOS))
        for i, cult in enumerate(CULTIVOS):
            slug = cult["slug"]
            # Compras propias del cultivo
            ag_yest = _recap_compras_agg(df_recap, slug, yesterday_d, yesterday_d)
            ag_week = _recap_compras_agg(df_recap, slug, week_mon, yesterday_d)
            mat_week = _recap_mat_agg(df_mat, slug, week_mon, yesterday_d)

            # Share = nuestras / FS × 100. FS está en tn también.
            def _share(part, whole):
                if whole and whole > 0:
                    return f"{part/whole*100:.1f}%"
                return "—"

            share_oc_y = _share(ag_yest["oc"], fs_oc_yest_by_slug.get(slug, 0))
            share_oc_w = _share(ag_week["oc"], fs_oc_week_by_slug.get(slug, 0))
            share_nc_w = _share(ag_week["nc"], fs_nc_week_by_slug.get(slug, 0))

            with rc_cols[i]:
                st.markdown(
                    f"<div style='font-weight:600;font-size:1rem;text-align:center;"
                    f"margin-bottom:0.3rem;'>{cult['emoji']} {cult['label']}</div>",
                    unsafe_allow_html=True,
                )

                # AYER
                st.markdown(
                    f"<div style='text-align:center;font-size:0.75rem;color:#888;"
                    f"letter-spacing:1px;'>AYER</div>",
                    unsafe_allow_html=True,
                )
                sl, sr = st.columns(2)
                sl.markdown(
                    f"<div style='font-size:0.78rem;color:#666;text-align:center;'>"
                    f"OC<br><span style='font-size:1.05rem;font-weight:700;color:#222;'>"
                    f"{_fmt_tn(ag_yest['oc'])} kt</span>"
                    f"<br><span style='font-size:0.7rem;color:#1565C0;'>share {share_oc_y}</span>"
                    f"</div>",
                    unsafe_allow_html=True,
                )
                sr.markdown(
                    f"<div style='font-size:0.78rem;color:#666;text-align:center;'>"
                    f"NC<br><span style='font-size:1.05rem;font-weight:700;color:#222;'>"
                    f"{_fmt_tn(ag_yest['nc'])} kt</span>"
                    f"</div>",
                    unsafe_allow_html=True,
                )

                # Separador
                st.markdown(
                    "<hr style='margin:0.6rem 0 0.4rem 0;border:none;"
                    "border-top:1px solid rgba(0,0,0,0.08);'/>",
                    unsafe_allow_html=True,
                )

                # SEMANA
                st.markdown(
                    f"<div style='text-align:center;font-size:0.75rem;color:#888;"
                    f"letter-spacing:1px;'>SEMANA</div>",
                    unsafe_allow_html=True,
                )
                sl, sr = st.columns(2)
                sl.markdown(
                    f"<div style='font-size:0.78rem;color:#666;text-align:center;'>"
                    f"OC<br><span style='font-size:1.05rem;font-weight:700;color:#222;'>"
                    f"{_fmt_tn(ag_week['oc'])} kt</span>"
                    f"<br><span style='font-size:0.7rem;color:#1565C0;'>share {share_oc_w}</span>"
                    f"</div>",
                    unsafe_allow_html=True,
                )
                sr.markdown(
                    f"<div style='font-size:0.78rem;color:#666;text-align:center;'>"
                    f"NC<br><span style='font-size:1.05rem;font-weight:700;color:#222;'>"
                    f"{_fmt_tn(ag_week['nc'])} kt</span>"
                    f"<br><span style='font-size:0.7rem;color:#1565C0;'>share {share_nc_w}</span>"
                    f"</div>",
                    unsafe_allow_html=True,
                )

                # MAT
                st.markdown(
                    "<hr style='margin:0.6rem 0 0.4rem 0;border:none;"
                    "border-top:1px solid rgba(0,0,0,0.08);'/>",
                    unsafe_allow_html=True,
                )
                st.markdown(
                    f"<div style='text-align:center;font-size:0.75rem;color:#888;"
                    f"letter-spacing:1px;'>MAT · SEMANA</div>",
                    unsafe_allow_html=True,
                )
                st.markdown(
                    f"<div style='text-align:center;font-size:1rem;font-weight:600;"
                    f"color:#7B1FA2;'>{_fmt_tn(mat_week)} kt</div>",
                    unsafe_allow_html=True,
                )

        st.caption(
            f"Recap: **{recap_file.name}** "
            f"(actualizado {pd.Timestamp(recap_file.stat().st_mtime, unit='s').strftime('%d/%m %H:%M')}). "
            f"Compras = COMPRAS A PRECIO + FIJACIONES COMPRA + FAS EN PREMIO + COMPRAS PAF "
            f"+ AMPLIACION (+) + ANULACION (−, con signo del Recap). "
            f"Share = nuestras / Farmer Selling del mismo período."
        )

    st.divider()

    # ════════════════════════════════════════════════════════════════════════
    # 2. Monthly Pace por cultivo (grilla 2×2)
    # ════════════════════════════════════════════════════════════════════════
    st.subheader("📈 Monthly Pace · compras + embarques")

    grid_rows = [CULTIVOS[:2], CULTIVOS[2:]]
    for row in grid_rows:
        cs = st.columns(2)
        for c, cult in zip(cs, row):
            df = _load_matriz(str(fs_dir), cult["slug"])
            chart = _build_monthly_pace_chart(df, cult, today, lineups_dir)
            with c:
                if chart is None:
                    st.info(f"Sin datos para {cult['label']}.")
                else:
                    st.altair_chart(chart, use_container_width=True)

    st.caption(
        "🟢 Compras realizadas (FS) · 🟡 Forecast compras · "
        "🔵 Loaded (Sailed) · 🟦 Loaded + At Roads + Lineup."
    )

    st.divider()

    # ════════════════════════════════════════════════════════════════════════
    # 3. Top 5 shippers de Lineups por cultivo (grilla 2×2, stacked bars)
    # ════════════════════════════════════════════════════════════════════════
    st.subheader("🚛 Top 5 shippers · mes en curso")

    SHIPPER_BAR_COLORS = {
        "Total":    "#424242",  # gris oscuro
        "Sailed":   "#2E7D32",  # verde — ya embarcado
        "At Roads": "#F9A825",  # naranja — en rada
        "Lineup":   "#1565C0",  # azul — anunciado
    }
    BAR_ORDER = ["Total", "Sailed", "At Roads", "Lineup"]

    try:
        if str(lineups_dir) not in sys.path:
            sys.path.insert(0, str(lineups_dir))
        import _lineups_loader as lu  # type: ignore
        all_lu = lu.load_all(lineups_dir)
        month_lbl_lu = f"{pd.Timestamp(today).strftime('%B')} {today.year}"
        cur_month = all_lu[all_lu["MONTH"] == month_lbl_lu].copy()

        if cur_month.empty or "SHIPPER" not in cur_month.columns:
            st.info("No hay data de shippers para el mes en curso.")
        else:
            def _shipper_chart_for(cargo: str, emoji: str, label: str):
                sub = cur_month[cur_month["CARGO"] == cargo]
                if sub.empty:
                    return None
                # Top 5 shippers por total
                top5 = (sub.groupby("SHIPPER")["TONS"].sum()
                            .sort_values(ascending=False).head(5).index.tolist())
                if not top5:
                    return None
                sub_top = sub[sub["SHIPPER"].isin(top5)]

                # 4 valores por shipper: Total / Sailed / At Roads / Lineup
                rows = []
                for shipper in top5:
                    sh_df = sub_top[sub_top["SHIPPER"] == shipper]
                    rows.append({
                        "Shipper": shipper, "Métrica": "Total",
                        "Tons": float(sh_df["TONS"].sum()),
                    })
                    for status in ["Sailed", "At Roads", "Lineup"]:
                        v = sh_df[sh_df["STATUS"] == status]["TONS"].sum()
                        rows.append({
                            "Shipper": shipper, "Métrica": status,
                            "Tons": float(v),
                        })
                gdf = pd.DataFrame(rows)

                # Barras agrupadas: xOffset por Métrica dentro de cada Shipper
                chart = (alt.Chart(gdf)
                    .mark_bar()
                    .encode(
                        x=alt.X("Shipper:N", sort=top5,
                                axis=alt.Axis(title=None, labelAngle=-25,
                                              labelFontSize=10)),
                        xOffset=alt.XOffset("Métrica:N", sort=BAR_ORDER),
                        y=alt.Y("Tons:Q",
                                axis=alt.Axis(format="~s", title=None,
                                              labelFontSize=9)),
                        color=alt.Color(
                            "Métrica:N",
                            scale=alt.Scale(
                                domain=BAR_ORDER,
                                range=[SHIPPER_BAR_COLORS[s] for s in BAR_ORDER],
                            ),
                            sort=BAR_ORDER,
                            legend=alt.Legend(orient="bottom", title=None,
                                              labelFontSize=10),
                        ),
                        tooltip=[
                            alt.Tooltip("Shipper:N"),
                            alt.Tooltip("Métrica:N"),
                            alt.Tooltip("Tons:Q", title="Tons", format=",.0f"),
                        ],
                    ))

                return chart.properties(
                    height=280,
                    title=alt.TitleParams(f"{emoji} {label}",
                                          fontSize=14, anchor="start"),
                )

            grid_rows = [CULTIVOS[:2], CULTIVOS[2:]]
            for row in grid_rows:
                cs = st.columns(2)
                for c, cult in zip(cs, row):
                    cargo = FS_TO_CARGO[cult["slug"]]
                    ch = _shipper_chart_for(cargo, cult["emoji"], cult["label"])
                    with c:
                        if ch is None:
                            st.info(f"Sin shippers de {cult['label']} este mes.")
                        else:
                            st.altair_chart(ch, use_container_width=True)

            st.caption(
                "4 barras por shipper: ⬛ Total · 🟢 Sailed · 🟠 At Roads · 🔵 Lineup."
            )
    except Exception as e:
        st.warning(f"No pude cargar shippers de Lineups: {e}")

