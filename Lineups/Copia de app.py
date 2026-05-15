"""
app.py — Farmer Selling 25/26 multi-crop (Corn / Wheat / Barley / Sorghum)
Run:
    make run                            # private mode (default)
    FS_MODO=public make run             # public mode (hides internal LDC data)

Each crop has its own matrix and its own delivery buckets (config in
cultivos.py). Selected from the sidebar.
"""

import os
import streamlit as st
import pandas as pd
import altair as alt
from pathlib import Path

from cultivos import CULTIVOS, get_cultivo

MODO_PUBLICO = os.getenv("FS_MODO", "private").lower() == "public"

st.set_page_config(
    page_title="Farmer Selling · 25/26",
    page_icon="🌾",
    layout="wide",
)

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)


# ── Helpers ───────────────────────────────────────────────────────────────────

def fmt_tn(v):
    """Format a value given in tonnes as kilotons (rounded). The internal
    data stays in tn — this only affects display."""
    if v == 0:
        return "—"
    kt = round(v / 1000)
    if kt == 0:
        # Tiny non-zero — show 1 decimal so it doesn't disappear
        return f"{v/1000:.1f}".replace(".", ",")
    return f"{kt:,}".replace(",", ".")

def fmt_pct(v):
    return f"{v:.1f}%"

def load_matriz(cfg: dict):
    """Loads the matrix for the selected crop."""
    path = DATA_DIR / cfg["matriz_csv"]
    if not path.exists():
        return None
    df = pd.read_csv(path)
    for col in cfg["grupos"] + ["total"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)
    df["low"]   = df["low"].astype(str).str.lower() == "true"
    df["prior"] = df["prior"].astype(str).str.lower() == "true"
    return df


def load_prices():
    """Loads data/prices.json (returns None if missing/corrupt)."""
    p = DATA_DIR / "prices.json"
    if not p.exists():
        return None
    try:
        import json as _json
        return _json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


@st.cache_data(show_spinner=False)
def load_prices_history() -> list[dict]:
    """Lee data/prices_history.jsonl (un snapshot por boletín).
    Devuelve lista ordenada por fecha asc. Cada record:
        {boletin, date, tc, pizarra, mat, cbot, minagri}
    """
    p = DATA_DIR / "prices_history.jsonl"
    if not p.exists():
        return []
    import json as _json
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(_json.loads(line))
        except Exception:
            continue
    # Ordenar por fecha asc (más viejos primero, más nuevos al final)
    out.sort(key=lambda r: r.get("date") or "")
    return out


def _lookup_history(history: list[dict], target_iso: str, *path_keys):
    """Encuentra el snapshot con fecha <= target_iso (nearest-prior) y extrae
    el valor siguiendo path_keys. Devuelve None si no hay match o falta el
    valor.

    Ejemplo: _lookup_history(hist, "2026-05-06", "pizarra", "maiz")
             _lookup_history(hist, "2026-05-06", "mat", "maiz", "MAY26")
    """
    if not history or not target_iso:
        return None
    # binary search-ish: como la lista está ordenada asc, recorremos al revés
    rec = None
    for r in reversed(history):
        d = r.get("date") or ""
        if d and d <= target_iso:
            rec = r
            break
    if rec is None:
        return None
    cur = rec
    for k in path_keys:
        if isinstance(cur, dict):
            cur = cur.get(k)
        else:
            return None
    return cur


def compute_replacement(slug: str, prices: dict):
    """Mat Replacement (cents/bushel spread vs CBOT).

    Formula: (pizarra + minagri*retención + elevación) × (100 / bushels_per_tn) − CBOT
    Returns None if any required price is missing.
    """
    if not prices:
        return None
    cfg = prices.get("config") or {}
    piz = (prices.get("pizarra_usd_tn", {}).get(slug, {}) or {}).get("today")
    minagri = (prices.get("minagri_fob_usd_tn", {}).get(slug, {}) or {}).get("today")
    cbot_key = (cfg.get("cbot_mapping") or {}).get(slug)
    cbot = ((prices.get("cbot_cents_bushel", {}).get(cbot_key, {}) or {}).get("today")
            if cbot_key else None)
    if piz is None or minagri is None or cbot is None:
        return None
    retention = (cfg.get("retention") or {}).get(slug, 0)
    elev      = cfg.get("elevation_cost_usd_tn", 12)
    bushels   = (cfg.get("bushels_per_tn") or {}).get(slug, 39.368)
    usd_tn_eq = piz + minagri * retention + elev
    cents_bu_eq = usd_tn_eq * 100 / bushels
    return cents_bu_eq - cbot


def apply_destination_filter(df, cfg, destinos_sel, grupos, all_destinos):
    """Scale a main matrix DataFrame by SIO destination split.

    For each non-target row, multiplies the per-destination raw SIO of the
    selected destinations by (main.total / total_raw_SIO) to bring the
    selected subset onto the MINAGRI scale.

    Returns a scaled copy of df. `mayo_target` rows are untouched.
    If destinos_sel is empty or per-destination matrices are missing,
    returns df.copy() unchanged.
    """
    if not destinos_sel:
        return df.copy()

    per_dest = {}
    for d in all_destinos:
        p = DATA_DIR / cfg["matriz_csv"].replace(".csv", f"_{d}.csv")
        if p.exists():
            try:
                dfd = pd.read_csv(p)
                for col in grupos + ["total"]:
                    dfd[col] = pd.to_numeric(dfd[col], errors="coerce").fillna(0)
                per_dest[d] = dfd
            except Exception:
                pass

    if any(d not in per_dest for d in destinos_sel) or not per_dest:
        return df.copy()

    # Denominator: sum of ALL destinations.
    df_all = per_dest[all_destinos[0]].copy()
    for d in all_destinos[1:]:
        if d in per_dest:
            for col in grupos + ["total"]:
                df_all[col] = df_all[col] + per_dest[d][col]

    # Numerator: sum of SELECTED destinations.
    df_sel = per_dest[destinos_sel[0]].copy()
    for d in destinos_sel[1:]:
        for col in grupos + ["total"]:
            df_sel[col] = df_sel[col] + per_dest[d][col]

    df_scaled = df.copy()
    for idx in df_scaled.index:
        row_main = df.loc[idx]
        if row_main["tipo"] == "mayo_target":
            continue
        mask = ((df_all["tipo"] == row_main["tipo"]) &
                (df_all["label"] == row_main["label"]))
        if not mask.any():
            continue
        row_all = df_all[mask].iloc[0]
        row_sel = df_sel[mask].iloc[0]
        sio_total  = float(row_all["total"])
        main_total = float(row_main["total"])
        scale = (main_total / sio_total) if sio_total > 0 else 0.0
        for col in grupos + ["total"]:
            df_scaled.at[idx, col] = int(round(row_sel[col] * scale))
    return df_scaled


# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    # ── Crop selector ────────────────────────────────────────────────────
    _CROP_OPTIONS = ["all_crops", *CULTIVOS.keys()]
    cultivo_slug = st.selectbox(
        "Crop",
        options=_CROP_OPTIONS,
        format_func=lambda s: (
            "🌾 All Crops" if s == "all_crops"
            else f"{CULTIVOS[s]['emoji']} {CULTIVOS[s]['label']}"
        ),
        index=0,  # "all_crops" is first → app opens directly on the dashboard
        key="cultivo_slug",
    )
    IS_ALL_CROPS = (cultivo_slug == "all_crops")

    if not IS_ALL_CROPS:
        cfg = get_cultivo(cultivo_slug)
        GRUPOS           = cfg["grupos"]
        GRUPO_SUBTITULOS = cfg["subtitulos"]
        GRUPO_COLORES    = cfg["colores"]
        daily_cfg        = cfg.get("daily_mes")
        # DIAS_HABILES_MAYO: only May days (the raw list includes April+May to feed
        # the rolling average of the last 10 business days).
        _todos_dias_habiles = daily_cfg["dias_habiles"] if daily_cfg else []
        DIAS_HABILES_MAYO = [d for d in _todos_dias_habiles if d.endswith("/05")]
        OBJETIVO_MAYO    = 2_826_000 if cultivo_slug == "maiz" else 0
        RITMO_NECESARIO  = round(OBJETIVO_MAYO / len(DIAS_HABILES_MAYO)) if DIAS_HABILES_MAYO else 0

        st.title(f"{cfg['emoji']} Farmer Selling")
        st.caption(f"{cfg['label']} · crop year {cfg.get('cosecha_label', cfg['cosecha'])}")
        st.divider()

        BALANCE_HIST = cfg["balance_hist"]
        _DEFAULT_CAMP = cfg.get("balance_default", "25/26")

        CAMPANAS = list(BALANCE_HIST.keys())
        _idx = CAMPANAS.index(_DEFAULT_CAMP) if _DEFAULT_CAMP in CAMPANAS else 0
        camp_sel = st.selectbox("Reference crop year", CAMPANAS,
                                index=_idx, key=f"campana_ref_{cultivo_slug}")
        ref = BALANCE_HIST[camp_sel]

        st.markdown("**Supply / demand balance (M tn)**")
        # Wide ranges so it works for corn (~60M tn) and barley (~1M tn) alike
        carry_in  = st.number_input("Est. Carry In",    min_value=0.0, max_value=200.0, value=float(ref["ci"]),   step=0.05, format="%.3f")
        prod_mn   = st.number_input("Est. Production",  min_value=0.0, max_value=200.0, value=float(ref["prod"]), step=0.1,  format="%.3f")
        imp_mn    = st.number_input("Est. Imports",     min_value=0.0, max_value=50.0,  value=float(ref["imp"]),  step=0.05, format="%.3f")
        domestic  = st.number_input("Est. Domestic",    min_value=0.0, max_value=200.0, value=float(ref["dom"]),  step=0.1,  format="%.3f")
        carry_out = st.number_input("Est. Carry Out",   min_value=0.0, max_value=200.0, value=float(ref["co"]),   step=0.05, format="%.3f")

        exp_calc = carry_in + prod_mn + imp_mn - domestic - carry_out
        color_bg = "rgba(29,158,117,0.12)" if exp_calc >= 0 else "rgba(226,75,74,0.12)"
        st.markdown(
            f"<div style='background:{color_bg};border-radius:6px;padding:6px 10px;margin-top:4px'>"
            f"📦 <b>Exports: {exp_calc:.3f} M tn</b></div>",
            unsafe_allow_html=True
        )

        total_dem = domestic + exp_calc
        stu = (carry_out / total_dem * 100) if total_dem > 0 else 0
        st.caption(f"Stock/use ratio: **{stu:.2f}%**")

        exp  = exp_calc * 1_000_000
        prod = prod_mn  * 1_000_000

        st.divider()
        mayo_mode = st.radio("May 2026", ["Daily", "Cumulative"], horizontal=True)
        view_mode = st.radio(
            "Matrix display",
            ["Kilotonnes", "% of month", "% of group", "% of total"],
        )
    else:
        # All Crops mode — placeholders so the rest of the file doesn't crash
        # (most of these are unused since the All Crops branch st.stop()s before
        # the per-crop data loading and tabs).
        cfg = None
        GRUPOS = []
        GRUPO_SUBTITULOS = {}
        GRUPO_COLORES = {}
        DIAS_HABILES_MAYO = []
        OBJETIVO_MAYO = 0
        RITMO_NECESARIO = 0
        BALANCE_HIST = {}
        camp_sel = None
        carry_in = prod_mn = imp_mn = domestic = carry_out = 0
        exp_calc = 0
        exp = 0
        prod = 0
        mayo_mode = "Daily"
        view_mode = "Kilotonnes"

        st.title("🌾 Farmer Selling")
        st.caption("All Crops · comparative dashboard")
        st.divider()
        st.caption(
            "Each crop uses its **default** balance assumption. "
            "Pick a specific crop above to override the balance."
        )

    # ── Global destination filter (applies to every tab & every crop) ───
    from destinos import DESTINOS as _DESTINOS, DESTINOS_LABEL as _DESTINOS_LABEL
    st.divider()
    destinos_sel = st.multiselect(
        "🎯 Filter by destination",
        options=_DESTINOS,
        default=[],
        format_func=lambda d: _DESTINOS_LABEL[d],
        key="destinos_sel_global",
        help=("Apply SIO destination split to MINAGRI volumes. "
              "Affects every metric across all crops and tabs. "
              "Historical comparison panels stay unfiltered (no destination "
              "dimension in precomputed metrics)."),
    )



# ── If "All Crops" is selected in the sidebar, render the comparative
#    dashboard and skip the rest of the app (single-crop tabs).
if IS_ALL_CROPS:
    from cultivos import CULTIVOS as _ALL_CULTIVOS
    from datetime import date as _ac_date, timedelta as _ac_td

    # ── Compact CSS (scoped: only renders when in All Crops mode because
    #    of the st.stop() at the end of this branch) ──────────────────────
    st.markdown("""
        <style>
        /* All-Crops ultra-compact + centered mode */
        [data-testid="stMetric"] {
            padding: 0.2rem 0.25rem;
            margin: 0;
            background: rgba(0,0,0,0.025);
            border-radius: 3px;
            text-align: center;
            /* Uniform box height across all metrics (visual consistency) */
            min-height: 4.4rem;
            height: 100%;
            display: flex !important;
            flex-direction: column !important;
            justify-content: center !important;
            box-sizing: border-box;
        }
        /* Make column children stretch so each metric fills the row height */
        [data-testid="stHorizontalBlock"] {
            align-items: stretch !important;
        }
        [data-testid="stHorizontalBlock"] > div[data-testid="column"] {
            display: flex !important;
            flex-direction: column !important;
        }
        [data-testid="stHorizontalBlock"] > div[data-testid="column"] > div,
        [data-testid="stHorizontalBlock"] > div[data-testid="column"] [data-testid="stVerticalBlock"],
        [data-testid="stHorizontalBlock"] > div[data-testid="column"] [data-testid="stVerticalBlock"] > div {
            height: 100%;
        }
        [data-testid="stHorizontalBlock"] > div[data-testid="column"] [data-testid="stMarkdownContainer"] {
            height: 100%;
        }
        [data-testid="stMetric"] > div,
        [data-testid="stMetric"] label {
            display: flex !important;
            flex-direction: column !important;
            justify-content: center !important;
            align-items: center !important;
            text-align: center !important;
            width: 100% !important;
            gap: 0 !important;
        }
        /* Label (small text on top): MAM, JJ, Total cumulative, etc. */
        [data-testid="stMetricLabel"] {
            display: flex !important;
            justify-content: center !important;
            width: 100% !important;
            margin: 0 !important;
        }
        [data-testid="stMetricLabel"] > div,
        [data-testid="stMetricLabel"] p {
            font-size: 0.6rem !important;
            line-height: 1 !important;
            text-align: center !important;
            width: 100% !important;
            margin: 0 auto !important;
            display: block !important;
        }
        [data-testid="stMetricValue"],
        [data-testid="stMetricValue"] > div {
            font-size: 0.9rem !important;
            line-height: 1.1 !important;
            justify-content: center;
            text-align: center;
            width: 100%;
            font-weight: 600;
            margin: 0 !important;
        }
        [data-testid="stMetricDelta"] {
            font-size: 0.55rem !important;
            padding-top: 0 !important;
            justify-content: center;
            text-align: center;
            width: 100%;
            line-height: 1 !important;
        }
        /* Ocultar el ícono de flecha (cuadradito ↑/↓) — solo texto coloreado */
        [data-testid="stMetricDelta"] svg {
            display: none !important;
        }
        /* Quitar cualquier fondo que Streamlit pueda agregar al delta */
        [data-testid="stMetricDelta"],
        [data-testid="stMetricDelta"] > div,
        [data-testid="stMetricDelta"] span {
            background: transparent !important;
        }
        /* Coloreo del delta: verde para positivo / rojo para negativo. */
        [data-testid="stMetricDelta"][data-direction="up"],
        [data-testid="stMetricDelta"][data-direction="up"] * {
            color: #1d9e6f !important;
        }
        [data-testid="stMetricDelta"][data-direction="down"],
        [data-testid="stMetricDelta"][data-direction="down"] * {
            color: #d44545 !important;
        }
        /* Fallback por si Streamlit no expone data-direction. */
        [data-testid="stMetricDelta"]:has(svg[data-testid="stMetricDeltaIcon-Up"]),
        [data-testid="stMetricDelta"]:has(svg[data-testid="stMetricDeltaIcon-Up"]) * {
            color: #1d9e6f !important;
        }
        [data-testid="stMetricDelta"]:has(svg[data-testid="stMetricDeltaIcon-Down"]),
        [data-testid="stMetricDelta"]:has(svg[data-testid="stMetricDeltaIcon-Down"]) * {
            color: #d44545 !important;
        }
        /* Crop-level title (### emoji + name) */
        .stMarkdown h3 {
            margin: 0.25rem 0 0.1rem 0;
            font-size: 0.92rem;
            text-align: center;
            color: #1d9e75;
            border-bottom: 1px solid rgba(29,158,117,0.25);
            padding-bottom: 0.1rem;
        }
        /* Section subheaders (##### emoji + name) */
        .stMarkdown h5 {
            margin: 0.25rem 0 0.05rem 0;
            font-size: 0.72rem;
            font-weight: 600;
            text-align: center;
            text-transform: uppercase;
            letter-spacing: 0.03em;
            color: #666;
        }
        .stMarkdown h5 span {
            text-transform: none !important;
            letter-spacing: normal !important;
        }
        [data-testid="stHorizontalBlock"] {
            gap: 0.2rem;
        }
        /* Reduce padding around horizontal blocks */
        [data-testid="stHorizontalBlock"] > div {
            padding: 0 !important;
        }
        /* Tighter vertical spacing between blocks */
        [data-testid="stVerticalBlock"] > div {
            gap: 0.15rem !important;
        }
        hr {
            margin: 0.2rem 0 !important;
            border-color: rgba(0,0,0,0.08) !important;
        }
        [data-testid="stCaptionContainer"] {
            margin-top: 0 !important;
            margin-bottom: 0.15rem !important;
        }
        </style>
    """, unsafe_allow_html=True)

    st.subheader("🌾 All Crops · Key Metrics")
    if destinos_sel:
        st.info(
            f"🎯 Filtered by destination: **{', '.join(_DESTINOS_LABEL[d] for d in destinos_sel)}**"
            f" — values scaled by SIO destination split (MINAGRI × dest share)."
        )
    st.caption(
        "Side-by-side macro KPIs, May tracking, Last business week, "
        "This week cumulative & Last business day for every crop. "
        "Uses each crop's **default** balance assumption."
    )

    # ── Status bar: última actualización por fuente ─────────────────────────
    def _render_status_bar():
        """Compact row showing last-update timestamp per data source."""
        import json as _json_sb
        from datetime import date as _d_sb, datetime as _dt_sb

        def _age_days(d):
            try:
                if isinstance(d, str):
                    d = _d_sb.fromisoformat(d)
                return (_d_sb.today() - d).days
            except Exception:
                return None

        def _color(days):
            if days is None:
                return "#888"
            if days <= 1:   return "#1d9e6f"  # fresh
            if days <= 3:   return "#c8a838"  # warning
            return "#d44545"                  # stale

        def _file_mtime(*candidates):
            """Returns 'DD/MM HH:MM' of mtime for the first existing file, or ''."""
            for c in candidates:
                p = Path(c)
                if p.exists():
                    return _dt_sb.fromtimestamp(p.stat().st_mtime).strftime("%d/%m %H:%M")
            return ""

        chips = []

        # SIO: max date across daily rows of all crops
        sio_max = None
        try:
            for _slug, _cfg in _ALL_CULTIVOS.items():
                _df = load_matriz(_cfg)
                if _df is None:
                    continue
                _dias = _df[_df["tipo"] == "diario"]["label"].tolist()
                for lbl in _dias:
                    try:
                        dd, mm = lbl.split("/")
                        d = _d_sb(_d_sb.today().year, int(mm), int(dd))
                        if sio_max is None or d > sio_max:
                            sio_max = d
                    except Exception:
                        continue
        except Exception:
            pass
        sio_age = _age_days(sio_max)
        sio_mt  = _file_mtime("data/sio_historico.csv", "data/matriz_maiz.csv")
        chips.append(("📥", "SIO Granos",
                      sio_max.strftime("%d/%m/%Y") if sio_max else "—",
                      _color(sio_age),
                      f"{sio_age}d ago" if sio_age is not None else "",
                      sio_mt))

        # MINAGRI: por cultivo (mostramos el más reciente + min de los demás)
        mn_dates = {}
        mn_mtime = ""
        for _slug, _cfg in _ALL_CULTIVOS.items():
            d = _last_minagri_date(_cfg)
            if d:
                mn_dates[_slug] = d
            try:
                from cultivos import minagri_json_path
                mt = _file_mtime(minagri_json_path(_cfg))
                if mt and mt > mn_mtime:
                    mn_mtime = mt
            except Exception:
                pass
        if mn_dates:
            mn_max = max(mn_dates.values())
            mn_min = min(mn_dates.values())
            mn_age = _age_days(mn_max)
            if mn_max == mn_min:
                mn_txt = mn_max.strftime("%d/%m/%Y")
            else:
                mn_txt = f"{mn_min:%d/%m}–{mn_max:%d/%m}"
            chips.append(("📡", "MINAGRI", mn_txt, _color(mn_age),
                          f"{mn_age}d ago" if mn_age is not None else "",
                          mn_mtime))

        # BCR boletín / MAT / CBOT (todos del mismo PDF)
        bn = (_prices_data or {}).get("boletin") or {}
        bn_date = bn.get("date_iso")
        bn_num  = bn.get("number")
        bn_age  = _age_days(bn_date)
        bn_mt   = _file_mtime("data/prices.json")
        chips.append(("📰", f"BCR Boletín N°{bn_num}" if bn_num else "BCR Boletín",
                      _d_sb.fromisoformat(bn_date).strftime("%d/%m/%Y") if bn_date else "—",
                      _color(bn_age),
                      f"{bn_age}d ago" if bn_age is not None else "",
                      bn_mt))

        # CAC pizarra (intra-día, más fresca)
        cac_date = None
        try:
            cac_date = (((_prices_data or {}).get("pizarra_usd_tn") or {})
                        .get("maiz") or {}).get("as_of")
        except Exception:
            pass
        cac_age = _age_days(cac_date)
        cac_mt  = _file_mtime("data/prices.json")
        chips.append(("🏛", "CAC Pizarra",
                      _d_sb.fromisoformat(cac_date).strftime("%d/%m/%Y") if cac_date else "—",
                      _color(cac_age),
                      f"{cac_age}d ago" if cac_age is not None else "",
                      cac_mt))

        # Render como chips horizontales
        html = ["<div style='display:flex;flex-wrap:wrap;gap:0.4rem;margin:0.4rem 0;"
                "font-size:0.75rem;font-family:-apple-system,BlinkMacSystemFont,sans-serif'>"]
        for emoji, name, dt, col, age, refresh in chips:
            refresh_html = (f"<span style='color:#aaa;font-size:0.7em;margin-left:4px'>"
                            f"· ref {refresh}</span>") if refresh else ""
            html.append(
                f"<div style='display:flex;align-items:center;gap:0.35rem;"
                f"padding:0.25rem 0.55rem;background:rgba(0,0,0,0.03);"
                f"border-left:3px solid {col};border-radius:3px'>"
                f"<span>{emoji}</span>"
                f"<span style='color:#555;font-weight:600'>{name}</span>"
                f"<span style='color:{col};font-weight:600'>{dt}</span>"
                f"<span style='color:#999;font-size:0.7em'>{age}</span>"
                f"{refresh_html}"
                f"</div>"
            )
        html.append("</div>")
        st.markdown("".join(html), unsafe_allow_html=True)

    def _ac_parse_lbl(s):
        try:
            d, m = s.split("/")
            return _ac_date(2026, int(m), int(d))
        except Exception:
            return None

    # Load prices once for the whole All Crops dashboard
    _prices_data = load_prices()
    _prices_age_note = ""
    if _prices_data and _prices_data.get("updated_at"):
        _prices_age_note = f" · last update: {_prices_data['updated_at']}"

    # Histórico de precios para DoD/WoW/MoM en la tabla Replacement curve.
    _prices_history = load_prices_history()
    _bn_date_str = ((_prices_data or {}).get("boletin") or {}).get("date_iso")
    _wow_iso = _mom_iso = None
    if _bn_date_str:
        try:
            _bn_d = _ac_date.fromisoformat(_bn_date_str)
            _wow_iso = (_bn_d - _ac_td(days=7)).isoformat()
            _mom_iso = (_bn_d - _ac_td(days=30)).isoformat()
        except Exception:
            pass

    def _hist_at(target_iso, *path):
        """Wrapper que devuelve el valor histórico en target_iso (nearest-prior)
        siguiendo path keys. None si no hay match."""
        if not target_iso:
            return None
        return _lookup_history(_prices_history, target_iso, *path)

    def _last_minagri_date(cfg):
        """Lee data/minagri_<slug>_<cosecha>.json y devuelve la fecha del último
        corte publicado (= último día cubierto). None si no hay archivo o vacío.
        """
        try:
            from cultivos import minagri_json_path
            import json as _json_mn
            p = Path(minagri_json_path(cfg))
            if not p.exists():
                return None
            data = _json_mn.loads(p.read_text(encoding="utf-8"))
            series = data.get("serie") or []
            if not series:
                return None
            return max(_ac_date.fromisoformat(pt["fecha"]) for pt in series
                       if pt.get("fecha"))
        except Exception:
            return None

    # Renderear la barra de estado ahora que todos los helpers están definidos.
    _render_status_bar()

    for _ac_slug, _ac_cfg in _ALL_CULTIVOS.items():
        st.divider()
        _ac_gru   = _ac_cfg["grupos"]
        _ac_sub   = _ac_cfg["subtitulos"]
        _ac_label = _ac_cfg["label"]
        _ac_emoji = _ac_cfg["emoji"]
        _ac_cy    = _ac_cfg.get("cosecha_label", _ac_cfg["cosecha"])

        # Helper: section label as a card to the LEFT of metrics (saves the
        # vertical row that a normal markdown header would occupy).
        def _section_card(emoji_label, sub_text=""):
            inner = (f"<div style='font-size:0.7rem;font-weight:600;color:#1d6e51;"
                     f"text-transform:uppercase;letter-spacing:0.03em;line-height:1.1'>"
                     f"{emoji_label}</div>")
            if sub_text:
                inner += (f"<div style='font-size:0.55rem;color:#888;margin-top:2px;"
                          f"line-height:1'>{sub_text}</div>")
            return (f"<div style='display:flex;flex-direction:column;justify-content:center;"
                    f"align-items:center;height:100%;min-height:4.4rem;"
                    f"padding:0.25rem 0.4rem;box-sizing:border-box;"
                    f"background:rgba(29,158,117,0.08);border-radius:3px;text-align:center'>"
                    f"{inner}</div>")

        st.markdown(f"### {_ac_emoji} {_ac_label} · {_ac_cy}")

        # Load matrix for this crop (apply global destination filter if active)
        _ac_df = load_matriz(_ac_cfg)
        if _ac_df is None:
            st.warning(f"📂 No matrix CSV for {_ac_label}. Run `make daily`.")
            continue
        if destinos_sel:
            _ac_df = apply_destination_filter(_ac_df, _ac_cfg, destinos_sel, _ac_gru, _DESTINOS)

        _ac_df_mens = _ac_df[_ac_df["tipo"] == "mensual"].copy()
        _ac_df_dias = _ac_df[_ac_df["tipo"] == "diario"].copy()
        _ac_df_dias_mayo = _ac_df_dias[_ac_df_dias["label"].str.contains("/05")]

        # OC groups = todas las delivery groups MENOS NC. El "Total" en TODAS
        # las secciones suma solo OC (cosecha vigente 25/26); NC sigue
        # mostrándose como columna independiente.
        _ac_gru_oc = [g for g in _ac_gru if g != "NC"]

        def _sum_oc_row(row):
            """Suma de buckets OC para una fila (Series)."""
            return sum(int(row[g]) for g in _ac_gru_oc)

        def _sum_oc_df(df):
            """Suma de buckets OC para todo un DataFrame (columna-suma)."""
            if len(df) == 0 or not _ac_gru_oc:
                return 0
            return int(df[_ac_gru_oc].sum().sum())

        _ac_total = _sum_oc_df(_ac_df_mens) + _sum_oc_df(_ac_df_dias_mayo)
        _ac_tot_g = {g: int(_ac_df_mens[g].sum() + _ac_df_dias_mayo[g].sum()) for g in _ac_gru}

        # Default balance → exp_calc per crop
        _ac_bh   = _ac_cfg["balance_hist"]
        _ac_bdef = _ac_cfg.get("balance_default", list(_ac_bh.keys())[0])
        _ac_b    = _ac_bh[_ac_bdef]
        _ac_exp_calc = _ac_b["ci"] + _ac_b["prod"] + _ac_b["imp"] - _ac_b["dom"] - _ac_b["co"]
        _ac_exp = _ac_exp_calc * 1_000_000

        # ── Pre-compute Current Month + Current Month Expected + Current Crop
        #    totals so that the BS section can reference the projected total.
        # Filtramos strict < today: la acumulada toma hasta AYER, y today queda
        # contado como "biz day faltante" (× promedio) — así la proyección no
        # depende de si SIO ya publicó datos de hoy o no.
        _today_ac = _ac_date.today()
        def _label_is_past(lbl):
            dt = _ac_parse_lbl(lbl)
            return (dt is not None) and (dt < _today_ac)

        # Freeze line: último día cubierto por MINAGRI para este cultivo.
        # Días del mes <= cutoff son "frozen" (MINAGRI×split SIO), días > cutoff
        # son "running" (SIO crudo). El avg/proyección usa SOLO días running
        # para capturar el ritmo vigente (no el corregido por MINAGRI).
        _cutoff_minagri = _last_minagri_date(_ac_cfg)

        _cm_dias_may  = _ac_df_dias[_ac_df_dias["label"].str.contains("/05")]
        _cm_dias      = _cm_dias_may[_cm_dias_may["label"].apply(_label_is_past)]
        _cm_tot  = _sum_oc_df(_cm_dias)                                # OC only (frozen + running)
        _cm_g    = {g: int(_cm_dias[g].sum()) for g in _ac_gru}

        # 10-day rolling avg: solo días RUNNING (post-cutoff) y < today.
        # Esto refleja el ritmo SIO vigente, no la escalada por MINAGRI.
        def _label_is_running(lbl):
            dt = _ac_parse_lbl(lbl)
            if dt is None:
                return False
            if dt >= _today_ac:
                return False
            if _cutoff_minagri is not None and dt <= _cutoff_minagri:
                return False
            return True

        _ac_df_dias_run = _ac_df_dias[_ac_df_dias["label"].apply(_label_is_running)]
        _cm_n    = min(10, len(_ac_df_dias_run))
        _cm_recent  = _ac_df_dias_run.tail(_cm_n)
        _cm_avg_tot = ((_sum_oc_df(_cm_recent) / _cm_n) if _cm_n > 0 else 0)  # OC only
        _cm_avg_g   = {g: ((_cm_recent[g].sum() / _cm_n) if _cm_n > 0 else 0) for g in _ac_gru}

        _cm_dh = [d for d in (_ac_cfg["daily_mes"]["dias_habiles"]
                              if _ac_cfg.get("daily_mes") else [])
                  if d.endswith("/05")]
        _cm_n_total = len(_cm_dh)
        _cm_n_disp  = len(_cm_dias)                     # biz days WITH data (≤ ayer)
        _cm_bdl     = max(0, _cm_n_total - _cm_n_disp)  # incluye hoy + futuros
        _cm_tot_exp = _cm_tot + _cm_bdl * _cm_avg_tot   # OC only
        _cm_g_exp   = {g: _cm_g[g] + _cm_bdl * _cm_avg_g[g] for g in _ac_gru}

        # Current Crop total = closed months actuals + current month projection (OC only)
        _cc_closed_tot = _sum_oc_df(_ac_df_mens)
        _cc_closed_g   = {g: int(_ac_df_mens[g].sum()) for g in _ac_gru}
        _cc_total      = _cc_closed_tot + int(round(_cm_tot_exp))
        _cc_split      = {g: _cc_closed_g[g] + int(round(_cm_g_exp[g])) for g in _ac_gru}

        # Last closed month label (most recent row of df_mens, e.g. "Abr-26")
        _last_closed_label = (_ac_df_mens.iloc[-1]["label"]
                              if len(_ac_df_mens) > 0 else "—")
        _projection_month_label = "May-26"  # all crops currently track May 2026

        # (Balance Sheet section moved to AFTER Current Crop — ahora aparece
        # como último item de cada crop, en el mismo formato inline-label que
        # los demás. Ver bloque al final de la iteración.)

        # 2. Prices ──────────────────────────────────────────────────
        # Source: data/prices.json (populado por `scrapers/bcr_boletin.py`).

        # Per-crop simple lookups (pizarra + minagri front)
        _p_piz = ((_prices_data or {}).get("pizarra_usd_tn", {}).get(_ac_slug) or {})
        _p_min = ((_prices_data or {}).get("minagri_fob_usd_tn", {}).get(_ac_slug) or {})

        def _dod_pct(today, yesterday):
            if today is None or yesterday is None or yesterday == 0:
                return None
            return f"{(today - yesterday) / yesterday * 100:+.2f}% DoD"

        _piz_today, _piz_yest = _p_piz.get("today"), _p_piz.get("yesterday")
        _min_cerc = _p_min.get("cercano") if isinstance(_p_min, dict) else None
        _min_cos  = _p_min.get("cosecha_nva") if isinstance(_p_min, dict) else None
        _tc       = (_prices_data or {}).get("tc_bna_compra")

        # Yesterday's minagri snapshot (used by the sorgo/cebada fallback mini-table)
        _min_prev_top = ((_prices_data or {}).get("minagri_fob_usd_tn_prev")
                         or {}).get(_ac_slug) or {}
        _min_cerc_prev_top = (_min_prev_top.get("cercano")
                              if isinstance(_min_prev_top, dict) else None)
        _min_cos_prev_top  = (_min_prev_top.get("cosecha_nva")
                              if isinstance(_min_prev_top, dict) else None)

        # 2b. Replacement curve table — solo para maíz y trigo (que tienen MAT) ─
        if _ac_slug in ("maiz", "trigo"):
            _cfg_p = (_prices_data or {}).get("config") or {}
            _ret = (_cfg_p.get("retention") or {}).get(_ac_slug, 0)
            _bu  = (_cfg_p.get("bushels_per_tn") or {}).get(_ac_slug, 39.368)
            _elev = _cfg_p.get("elevation_cost_usd_tn", 12)
            # MAT futures por mes (USD/tn)
            _mat_map = (((_prices_data or {}).get("mat_usd_tn") or {})
                        .get(_ac_slug) or {})
            # CBOT views:
            #   - Maíz: 1 vista (corn)
            #   - Trigo: 2 vistas (HRW Kansas + SRW Chicago) — Argentino trigo pan
            #     es más cercano a HRW pero SRW es el contrato más líquido del CBOT.
            if _ac_slug == "maiz":
                _cbot_views_def = [("corn", "")]
            else:
                _cbot_views_def = [
                    ("wheat_kansas",  "HRW"),
                    ("wheat_chicago", "SRW"),
                ]
            # Build per-view metadata: (col_key, label, today_map, prev_map)
            _cbot_views = []
            for _ck, _vl in _cbot_views_def:
                _now  = (((_prices_data or {}).get("cbot_usd_tn") or {})
                         .get(_ck) or {})
                _prev = (((_prices_data or {}).get("cbot_usd_tn_prev") or {})
                         .get(_ck) or {})
                _cbot_views.append({"key": _ck, "label": _vl, "now": _now, "prev": _prev})
            # First view used for "match month" lookup
            _cbot_col      = _cbot_views[0]["key"]
            _cbot_map      = _cbot_views[0]["now"]

            # Map MAT contract → CBOT contract month (next-listed convention)
            _MAT_TO_CBOT_CORN = {
                "MAY26": "May-26", "JUN26": "Jul-26", "JUL26": "Jul-26",
                "SEP26": "Sep-26", "DIC26": "Dic-26", "ABR27": "May-27",
                "JUL27": "Jul-27",
            }
            _MAT_TO_CBOT_WHEAT = {
                "MAY26": "May-26", "JUL26": "Jul-26", "DIC26": "Dic-26",
                "ENE27": "Mar-27",
            }
            _mat_to_cbot = _MAT_TO_CBOT_CORN if _ac_slug == "maiz" else _MAT_TO_CBOT_WHEAT

            # Yesterday snapshots for DoD (populated by scraper on boletín date change)
            _mat_prev_map  = (((_prices_data or {}).get("mat_usd_tn_prev") or {})
                              .get(_ac_slug) or {})
            _cbot_prev_map = (((_prices_data or {}).get("cbot_usd_tn_prev") or {})
                              .get(_cbot_col) or {})
            _min_prev_map  = (((_prices_data or {}).get("minagri_fob_usd_tn_prev") or {})
                              .get(_ac_slug) or {})
            if _mat_map and isinstance(_p_min, dict) and _p_min.get("cercano"):
                # Boundary entre cosecha vigente y cosecha nueva (post-harvest):
                #   maíz  → ABR27 (cosecha 26/27 sale Mar-May 2027)
                #   trigo → DIC26 (cosecha 26/27 sale Nov-Dic 2026)
                _NEW_CROP_BOUNDARY = {"maiz": ("ABR", 27), "trigo": ("DIC", 26)}
                _SP_MONTH_NUM = {
                    "ENE": 1, "FEB": 2, "MAR": 3, "ABR": 4, "MAY": 5, "JUN": 6,
                    "JUL": 7, "AGO": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DIC": 12,
                }

                def _is_new_crop(mat_key):
                    bound = _NEW_CROP_BOUNDARY.get(_ac_slug)
                    if not bound:
                        return False
                    bmon, byr = bound
                    bound_idx = byr * 12 + _SP_MONTH_NUM[bmon]
                    import re as _re
                    m = _re.match(r"^([A-Z]{3})(\d{2})$", mat_key)
                    if not m:
                        return False
                    mon, yr = m.group(1), int(m.group(2))
                    return yr * 12 + _SP_MONTH_NUM.get(mon, 0) >= bound_idx

                def _min_for_contract(mat_key):
                    """Returns (minagri_value, label) according to old/new crop boundary."""
                    if _is_new_crop(mat_key) and _min_cos is not None:
                        return _min_cos, "cos.nva"
                    return _min_cerc, "cerc."

                # Compute rows
                _rows_data = []

                # Helper: compute replacement from inputs (USD/tn → cents/bushel)
                def _calc_repl(_mat_val, _min_val, _cbot_val):
                    if _mat_val is None or _min_val is None or _cbot_val is None:
                        return None, None
                    _eq  = _mat_val + _min_val * _ret + _elev
                    _usd = _eq - _cbot_val
                    _cts = _usd * 100 / _bu
                    return _usd, _cts

                # Look up yesterday's minagri_cerc/cos for DoD calc on repl
                _min_prev = ((_prices_data or {}).get("minagri_fob_usd_tn_prev")
                             or {}).get(_ac_slug) or {}
                _min_cerc_prev = (_min_prev.get("cercano")
                                  if isinstance(_min_prev, dict) else None)
                _min_cos_prev  = (_min_prev.get("cosecha_nva")
                                  if isinstance(_min_prev, dict) else None)

                def _min_yest_for_contract(mat_key):
                    if _is_new_crop(mat_key) and _min_cos_prev is not None:
                        return _min_cos_prev
                    return _min_cerc_prev

                # Helper: build the per-view dict (cbot + repl, today + prev + wow + mom)
                def _build_views(mat_today, mat_prev, mat_wow, mat_mom,
                                 min_today, min_prev, min_wow, min_mom,
                                 min_key,  # "cercano" o "cosecha_nva" para lookup hist
                                 cbot_key):
                    out = []
                    for _v in _cbot_views:
                        _c_now  = _v["now"].get(cbot_key) if cbot_key else None
                        _c_prev = _v["prev"].get(cbot_key) if cbot_key else None
                        _c_wow  = _hist_at(_wow_iso, "cbot", _v["key"], cbot_key) if cbot_key else None
                        _c_mom  = _hist_at(_mom_iso, "cbot", _v["key"], cbot_key) if cbot_key else None
                        _ru, _rc           = _calc_repl(mat_today, min_today, _c_now)
                        _ru_prev, _rc_prev = _calc_repl(mat_prev,  min_prev,  _c_prev)
                        _ru_wow,  _rc_wow  = _calc_repl(mat_wow,   min_wow,   _c_wow)
                        _ru_mom,  _rc_mom  = _calc_repl(mat_mom,   min_mom,   _c_mom)
                        out.append({
                            "label":         _v["label"],
                            "cbot":          _c_now,
                            "cbot_prev":     _c_prev,
                            "cbot_wow":      _c_wow,
                            "cbot_mom":      _c_mom,
                            "repl_usd":      _ru,
                            "repl_cts":      _rc,
                            "repl_cts_prev": _rc_prev,
                            "repl_cts_wow":  _rc_wow,
                            "repl_cts_mom":  _rc_mom,
                        })
                    return out

                # ── SPOT row (Pizarra hoy) at the top ─────────────────────────
                if _piz_today is not None:
                    _spot_cbot_key = (_mat_to_cbot.get(next(iter(_mat_map.keys())))
                                      if _mat_map else None)
                    _piz_wow = _hist_at(_wow_iso, "pizarra", _ac_slug)
                    _piz_mom = _hist_at(_mom_iso, "pizarra", _ac_slug)
                    _mcer_wow = _hist_at(_wow_iso, "minagri", _ac_slug, "cercano")
                    _mcer_mom = _hist_at(_mom_iso, "minagri", _ac_slug, "cercano")
                    _rows_data.append({
                        "is_spot":  True,
                        "mat_key":  "PIZARRA",
                        "mat":      _piz_today,
                        "mat_prev": _piz_yest,
                        "mat_wow":  _piz_wow,
                        "mat_mom":  _piz_mom,
                        "min":      _min_cerc,
                        "min_prev": _min_cerc_prev,
                        "min_wow":  _mcer_wow,
                        "min_mom":  _mcer_mom,
                        "min_lbl":  "cerc.",
                        "cbot_key": _spot_cbot_key,
                        "views":    _build_views(_piz_today, _piz_yest, _piz_wow, _piz_mom,
                                                  _min_cerc, _min_cerc_prev, _mcer_wow, _mcer_mom,
                                                  "cercano",
                                                  _spot_cbot_key),
                    })

                # ── MAT contract rows ─────────────────────────────────────────
                for _mat_key in _mat_map.keys():
                    _mat = _mat_map[_mat_key]
                    _mat_prev = _mat_prev_map.get(_mat_key)
                    _mat_wow  = _hist_at(_wow_iso, "mat", _ac_slug, _mat_key)
                    _mat_mom  = _hist_at(_mom_iso, "mat", _ac_slug, _mat_key)
                    _cbot_key_match = _mat_to_cbot.get(_mat_key)
                    _min_val, _min_lbl = _min_for_contract(_mat_key)
                    _min_yest = _min_yest_for_contract(_mat_key)
                    _min_hist_key = "cosecha_nva" if _is_new_crop(_mat_key) else "cercano"
                    _min_wow  = _hist_at(_wow_iso, "minagri", _ac_slug, _min_hist_key)
                    _min_mom  = _hist_at(_mom_iso, "minagri", _ac_slug, _min_hist_key)
                    _rows_data.append({
                        "is_spot":  False,
                        "mat_key":  _mat_key,
                        "mat":      _mat,
                        "mat_prev": _mat_prev,
                        "mat_wow":  _mat_wow,
                        "mat_mom":  _mat_mom,
                        "min":      _min_val,
                        "min_prev": _min_yest,
                        "min_wow":  _min_wow,
                        "min_mom":  _min_mom,
                        "min_lbl":  _min_lbl,
                        "cbot_key": _cbot_key_match,
                        "views":    _build_views(_mat, _mat_prev, _mat_wow, _mat_mom,
                                                  _min_val, _min_yest, _min_wow, _min_mom,
                                                  _min_hist_key,
                                                  _cbot_key_match),
                    })

                # Build a styled HTML table — color-coded Repl cells, right-aligned
                # numbers, compact padding, monospace numbers for alignment.
                def _cell_color(repl):
                    if repl is None:
                        return "rgba(0,0,0,0.04)", "#888"
                    if repl >= 0:
                        return "rgba(29,158,117,0.15)", "#1d6e51"   # green
                    return "rgba(226,75,74,0.15)", "#a32d2d"          # red

                def _one_delta(today, ref, decimals, kind):
                    """Renderiza una sola línea de delta (DoD/WoW/MoM)."""
                    if today is None or ref is None:
                        return f"<span class='delta-line muted'>{kind} —</span>"
                    d = today - ref
                    if d == 0:
                        cls = "zero"
                    else:
                        cls = "up" if d > 0 else "dn"
                    return (f"<span class='delta-line {cls}'>"
                            f"<span class='dl-k'>{kind}</span> {d:+.{decimals}f}</span>")

                def _deltas_html(today, prev, wow, mom, decimals=2):
                    """3 deltas horizontales en una nueva línea bajo el precio."""
                    inner = (_one_delta(today, prev, decimals, "D")
                             + _one_delta(today, wow, decimals, "W")
                             + _one_delta(today, mom, decimals, "M"))
                    return f"<div class='deltas-row'>{inner}</div>"

                # Alias por compatibilidad — algunos call sites todavía usan _dod_html
                def _dod_html(today, yest, decimals=2):
                    return _one_delta(today, yest, decimals, "D")

                # ── Helper: build a styled HTML table for a subset of rows ────
                # show_header=True renders <thead>. include_style=True embeds the
                # <style> block (only needed on the first render per page).
                def _build_repl_html(rows, show_header=True, include_style=True):
                    h = []
                    if include_style:
                        h.append("""
                        <style>
                          .repl-tbl { width: 100%; border-collapse: collapse;
                                      table-layout: fixed;
                                      font-size: 0.78rem; font-family: -apple-system, BlinkMacSystemFont, sans-serif; }
                          .repl-tbl th { background: rgba(0,0,0,0.04); color: #555;
                                         text-transform: uppercase; letter-spacing: 0.04em;
                                         font-size: 0.65rem; font-weight: 600;
                                         padding: 6px 8px; text-align: center;
                                         border-bottom: 1px solid rgba(0,0,0,0.08); }
                          .repl-tbl td { padding: 5px 8px; text-align: center;
                                         border-bottom: 1px solid rgba(0,0,0,0.04);
                                         font-variant-numeric: tabular-nums;
                                         line-height: 1.15; }
                          .repl-tbl tr.spot { background: rgba(29,158,117,0.05); }
                          .repl-tbl tr.spot td.month { color: #185FA5; }
                          .repl-tbl td.month { font-weight: 600; color: #1d9e75; }
                          .repl-tbl td.muted { color: #999; font-size: 0.7rem; }
                          .repl-tbl td.min-tag { font-size: 0.65rem; color: #777; }
                          .repl-tbl td.repl { font-weight: 600; }
                          .repl-tbl .dod { display: block; font-size: 0.6rem; margin-top: 1px;
                                           font-weight: 500; }
                          .repl-tbl .dod.up   { color: #1d6e51; }
                          .repl-tbl .dod.dn   { color: #a32d2d; }
                          .repl-tbl .dod.zero { color: #999; }
                          /* Bloque debajo del precio con D / W / M en horizontal */
                          .repl-tbl .deltas-row { display: block; margin-top: 2px;
                                                  white-space: nowrap; }
                          .repl-tbl .delta-line { display: inline; font-size: 0.58rem;
                                                  line-height: 1.05; font-weight: 500;
                                                  margin-right: 5px; }
                          .repl-tbl .delta-line.up    { color: #1d6e51; }
                          .repl-tbl .delta-line.dn    { color: #a32d2d; }
                          .repl-tbl .delta-line.zero  { color: #999; }
                          .repl-tbl .delta-line.muted { color: #bbb; }
                          .repl-tbl .delta-line .dl-k { color: #888; font-weight: 600;
                                                        font-size: 0.55rem; margin-right: 2px; }
                        </style>
                        """)
                    h.append("<table class='repl-tbl'>")
                    if show_header:
                        h.append("""
                          <thead><tr>
                            <th>Contrato</th>
                            <th>MAT / Pizarra<br/><span style='font-weight:400;text-transform:none;letter-spacing:0;color:#999'>USD/tn</span></th>
                            <th>Min FOB<br/><span style='font-weight:400;text-transform:none;letter-spacing:0;color:#999'>USD/tn</span></th>
                            <th>CBOT match</th>
                        """)
                        for _v in _cbot_views:
                            _vlbl = f" {_v['label']}" if _v['label'] else ""
                            h.append(
                                f"<th>CBOT{_vlbl}<br/><span style='font-weight:400;"
                                f"text-transform:none;letter-spacing:0;color:#999'>¢/bu</span></th>"
                                f"<th>Repl{_vlbl}<br/><span style='font-weight:400;"
                                f"text-transform:none;letter-spacing:0;color:#999'>¢/bu</span></th>"
                            )
                        h.append("</tr></thead>")
                    h.append("<tbody>")
                    for r in rows:
                        tr_cls = "spot" if r.get("is_spot") else ""
                        h.append(f"<tr class='{tr_cls}'>")
                        h.append(f"<td class='month'>{r['mat_key']}</td>")
                        # MAT / Pizarra (USD/tn) + DoD/WoW/MoM
                        _mat_d = _deltas_html(r['mat'], r.get('mat_prev'),
                                              r.get('mat_wow'), r.get('mat_mom'), 2)
                        h.append(f"<td>{r['mat']:.2f}{_mat_d}</td>")
                        # Min FOB (USD/tn) + DoD/WoW/MoM
                        if r.get("min") is not None:
                            _min_d = _deltas_html(r['min'], r.get('min_prev'),
                                                  r.get('min_wow'), r.get('min_mom'), 0)
                            h.append(
                                f"<td>{r['min']:.0f}"
                                f" <span class='min-tag'>({r['min_lbl']})</span>"
                                f"{_min_d}</td>"
                            )
                        else:
                            h.append("<td class='muted'>—</td>")
                        # CBOT month label (no DoD)
                        h.append(f"<td class='muted'>{r['cbot_key'] or '—'}</td>")
                        # For each CBOT view: CBOT (¢/bu) + Repl (¢/bu)
                        for v in r.get("views", []):
                            _c_cts      = (v['cbot']      * 100 / _bu) if v['cbot']      is not None else None
                            _c_cts_prev = (v['cbot_prev'] * 100 / _bu) if v.get('cbot_prev') is not None else None
                            _c_cts_wow  = (v['cbot_wow']  * 100 / _bu) if v.get('cbot_wow')  is not None else None
                            _c_cts_mom  = (v['cbot_mom']  * 100 / _bu) if v.get('cbot_mom')  is not None else None
                            if _c_cts is not None:
                                _cb_d = _deltas_html(_c_cts, _c_cts_prev,
                                                     _c_cts_wow, _c_cts_mom, 1)
                                h.append(f"<td>{_c_cts:.1f}{_cb_d}</td>")
                            else:
                                h.append("<td class='muted'>—</td>")
                            bg, fg = _cell_color(v["repl_usd"])
                            if v['repl_cts'] is not None:
                                _rp_d = _deltas_html(v['repl_cts'], v.get('repl_cts_prev'),
                                                     v.get('repl_cts_wow'), v.get('repl_cts_mom'), 1)
                                h.append(
                                    f"<td class='repl' style='background:{bg};color:{fg}'>"
                                    f"{v['repl_cts']:+.1f}{_rp_d}</td>"
                                )
                            else:
                                h.append("<td class='muted'>—</td>")
                        h.append("</tr>")
                    h.append("</tbody></table>")
                    return "".join(h)

                # ── Split rows into Pizarra (visible always) + MAT (in expander)
                _pizarra_rows = [r for r in _rows_data if r.get("is_spot")]
                _mat_rows     = [r for r in _rows_data if not r.get("is_spot")]

                # Mini-table outside expander: header + PIZARRA row
                st.markdown(
                    _build_repl_html(_pizarra_rows, show_header=True, include_style=True),
                    unsafe_allow_html=True,
                )

                # Full curve inside expander: just the MAT contract rows, no
                # header (the visible table above already shows column names).
                with st.expander(
                    f"📊 Replacement curve · MAT vs CBOT "
                    f"(ret. {_ret*100:.1f}% · elev. {_elev} USD/tn)",
                    expanded=False,
                ):
                    st.markdown(
                        _build_repl_html(_mat_rows, show_header=True, include_style=False),
                        unsafe_allow_html=True,
                    )
        else:
            # 2c. Sorgo / Cebada: no MAT futures → render a simplified mini-table
            # con Pizarra · FOB equiv · MINAGRI · MARGEN. Misma estética que la
            # fila spot de la tabla grande.
            #   FOB equiv. = Pizarra + Elevación + MinFOB × retención
            #   MARGEN     = MINAGRI − FOB equiv. (positivo = exportador con
            #                margen; negativo = sin paridad)
            _cfg_p2 = (_prices_data or {}).get("config") or {}
            _ret2  = (_cfg_p2.get("retention") or {}).get(_ac_slug, 0)
            _elev2 = _cfg_p2.get("elevation_cost_usd_tn", 12)

            def _one_delta_sc(today, ref, decimals, kind):
                if today is None or ref is None:
                    return f"<span class='delta-line muted'>{kind} —</span>"
                d = today - ref
                if d == 0:
                    cls = "zero"
                else:
                    cls = "up" if d > 0 else "dn"
                return (f"<span class='delta-line {cls}'>"
                        f"<span class='dl-k'>{kind}</span> {d:+.{decimals}f}</span>")

            def _deltas_sc(today, prev, wow, mom, decimals=2):
                inner = (_one_delta_sc(today, prev, decimals, "D")
                         + _one_delta_sc(today, wow,  decimals, "W")
                         + _one_delta_sc(today, mom,  decimals, "M"))
                return f"<div class='deltas-row'>{inner}</div>"

            def _fob_eq(piz, minfob):
                if piz is None or minfob is None:
                    return None
                return piz + _elev2 + minfob * _ret2

            # Lookups históricos para Pizarra y Minagri
            _piz_wow_sc = _hist_at(_wow_iso, "pizarra", _ac_slug)
            _piz_mom_sc = _hist_at(_mom_iso, "pizarra", _ac_slug)
            _mcer_wow_sc = _hist_at(_wow_iso, "minagri", _ac_slug, "cercano")
            _mcer_mom_sc = _hist_at(_mom_iso, "minagri", _ac_slug, "cercano")

            _fob_now  = _fob_eq(_piz_today, _min_cerc)
            _fob_prev = _fob_eq(_piz_yest,  _min_cerc_prev_top)
            _fob_wow  = _fob_eq(_piz_wow_sc, _mcer_wow_sc)
            _fob_mom  = _fob_eq(_piz_mom_sc, _mcer_mom_sc)
            _marg_now  = (_min_cerc - _fob_now)  if (_min_cerc is not None and _fob_now  is not None) else None
            _marg_prev = (_min_cerc_prev_top - _fob_prev) if (_min_cerc_prev_top is not None and _fob_prev is not None) else None
            _marg_wow  = (_mcer_wow_sc - _fob_wow) if (_mcer_wow_sc is not None and _fob_wow is not None) else None
            _marg_mom  = (_mcer_mom_sc - _fob_mom) if (_mcer_mom_sc is not None and _fob_mom is not None) else None

            _piz_cell = (f"{_piz_today:.2f}"
                          f"{_deltas_sc(_piz_today, _piz_yest, _piz_wow_sc, _piz_mom_sc, 2)}"
                          if _piz_today is not None else "<span class='muted'>—</span>")
            _fob_cell = (f"{_fob_now:.1f}"
                          f"{_deltas_sc(_fob_now, _fob_prev, _fob_wow, _fob_mom, 1)}"
                          if _fob_now is not None else "<span class='muted'>—</span>")
            _min_cell = (f"{_min_cerc:.0f}"
                          f"{_deltas_sc(_min_cerc, _min_cerc_prev_top, _mcer_wow_sc, _mcer_mom_sc, 0)}"
                          if _min_cerc is not None else "<span class='muted'>—</span>")
            if _marg_now is not None:
                if _marg_now >= 0:
                    _marg_bg, _marg_fg = "rgba(29,158,117,0.15)", "#1d6e51"
                else:
                    _marg_bg, _marg_fg = "rgba(226,75,74,0.15)", "#a32d2d"
                _marg_cell = (f"<td class='repl' style='background:{_marg_bg};color:{_marg_fg}'>"
                              f"{_marg_now:+.1f}"
                              f"{_deltas_sc(_marg_now, _marg_prev, _marg_wow, _marg_mom, 1)}</td>")
            else:
                _marg_cell = "<td class='muted'>—</td>"

            st.markdown(
                """
                <style>
                  .repl-tbl { width: 100%; border-collapse: collapse;
                              table-layout: fixed;
                              font-size: 0.78rem; font-family: -apple-system, BlinkMacSystemFont, sans-serif; }
                  .repl-tbl th { background: rgba(0,0,0,0.04); color: #555;
                                 text-transform: uppercase; letter-spacing: 0.04em;
                                 font-size: 0.65rem; font-weight: 600;
                                 padding: 6px 8px; text-align: center;
                                 border-bottom: 1px solid rgba(0,0,0,0.08); }
                  .repl-tbl td { padding: 5px 8px; text-align: center;
                                 border-bottom: 1px solid rgba(0,0,0,0.04);
                                 font-variant-numeric: tabular-nums;
                                 line-height: 1.15; }
                  .repl-tbl tr.spot { background: rgba(29,158,117,0.05); }
                  .repl-tbl tr.spot td.month { color: #185FA5; }
                  .repl-tbl td.month { font-weight: 600; }
                  .repl-tbl td.muted { color: #999; font-size: 0.7rem; }
                  .repl-tbl td.repl { font-weight: 600; }
                  .repl-tbl .dod { display: block; font-size: 0.6rem; margin-top: 1px;
                                   font-weight: 500; }
                  .repl-tbl .dod.up   { color: #1d6e51; }
                  .repl-tbl .dod.dn   { color: #a32d2d; }
                  .repl-tbl .dod.zero { color: #999; }
                  .repl-tbl .deltas-row { display: block; margin-top: 2px;
                                          white-space: nowrap; }
                  .repl-tbl .delta-line { display: inline; font-size: 0.58rem;
                                          line-height: 1.05; font-weight: 500;
                                          margin-right: 5px; }
                  .repl-tbl .delta-line.up    { color: #1d6e51; }
                  .repl-tbl .delta-line.dn    { color: #a32d2d; }
                  .repl-tbl .delta-line.zero  { color: #999; }
                  .repl-tbl .delta-line.muted { color: #bbb; }
                  .repl-tbl .delta-line .dl-k { color: #888; font-weight: 600;
                                                font-size: 0.55rem; margin-right: 2px; }
                </style>
                <table class='repl-tbl'>
                  <thead><tr>
                    <th>Contrato</th>
                    <th>Pizarra<br/><span style='font-weight:400;text-transform:none;letter-spacing:0;color:#999'>USD/tn</span></th>
                """
                f"<th>FOB equiv.<br/><span style='font-weight:400;text-transform:none;letter-spacing:0;color:#999'>"
                f"Piz + {_elev2:.0f} + Min×{_ret2*100:.1f}%</span></th>"
                """
                    <th>MINAGRI<br/><span style='font-weight:400;text-transform:none;letter-spacing:0;color:#999'>USD/tn FOB cerc.</span></th>
                    <th>MARGEN<br/><span style='font-weight:400;text-transform:none;letter-spacing:0;color:#999'>MINAGRI − FOB eq.</span></th>
                  </tr></thead>
                """
                f"<tbody><tr class='spot'>"
                f"<td class='month'>PIZARRA</td>"
                f"<td>{_piz_cell}</td>"
                f"<td>{_fob_cell}</td>"
                f"<td>{_min_cell}</td>"
                f"{_marg_cell}"
                f"</tr></tbody></table>",
                unsafe_allow_html=True,
            )

        # Shared: parse fechas of daily rows, find last business day < today
        _ac_lw = _ac_df_dias.copy()
        _ac_lw["fecha"] = _ac_lw["label"].apply(_ac_parse_lbl)
        _ac_lw = _ac_lw.dropna(subset=["fecha"]).sort_values("fecha").reset_index(drop=True)
        _ac_today = _ac_date.today()
        _ac_lw_past = _ac_lw[_ac_lw["fecha"] < _ac_today].reset_index(drop=True)

        # 3. Last Business Day (ayer) ─────────────────────────────────
        if len(_ac_lw_past) >= 1:
            _last = _ac_lw_past.iloc[-1]
            _prev = _ac_lw_past.iloc[-2] if len(_ac_lw_past) >= 2 else None

            _hdr_extra = f" vs {_prev['fecha']:%d/%m}" if _prev is not None else ""
            _sub_lbd = f"{_last['fecha']:%d/%m}{_hdr_extra}"

            def _maiz_dod(v, v_p):
                if v_p is None or v_p <= 0:
                    return None
                return f"{(v - v_p) / v_p * 100:+.1f}% DoD"

            _lbd = st.columns([1.4] + [1] * (1 + len(_ac_gru) + 1))
            _lbd[0].markdown(_section_card("📅 Last B-day · OC", _sub_lbd),
                             unsafe_allow_html=True)
            _tot_lbd  = _sum_oc_row(_last)
            _tot_prev = _sum_oc_row(_prev) if _prev is not None else None
            _lbd[1].metric("Total", fmt_tn(_tot_lbd) + " kt",
                           delta=_maiz_dod(_tot_lbd, _tot_prev))
            for _c, _g in zip(_lbd[2:2 + len(_ac_gru)], _ac_gru):
                _v   = int(_last[_g])
                _v_p = int(_prev[_g]) if _prev is not None else None
                _c.metric(f"{_g} ({_ac_sub[_g]})", fmt_tn(_v) + " kt",
                          delta=_maiz_dod(_v, _v_p))
            # DoD Variation (last column = total % change)
            _dod_str = _maiz_dod(_tot_lbd, _tot_prev)
            _lbd[-1].metric("DoD Var.",
                            _dod_str.replace(" DoD", "") if _dod_str else "—")

        # ── Collapsible: rest of "compras" (week / month / cosecha / BS) ────
        # Por defecto el usuario ve Pizarra + Last B-day; al tocar el expander
        # aparecen This Week / Last Week / Current Month / Month Expected /
        # Current Crop / Balance Sheet.
        with st.expander("📋 Semana · Mes · Cosecha · Balance Sheet", expanded=False):
            # ── Pre-compute Last Business Week boundaries + totals (lo usamos
            #    como denominador en This Week, y después rendereamos su propia
            #    sección abajo).
            _lw_pre = None
            if len(_ac_lw) > 0:
                _ultimo = _ac_lw["fecha"].max()
                _diff_fri = (_ultimo.weekday() - 4) % 7
                _fri_lw    = _ultimo - _ac_td(days=_diff_fri)
                _mon_lw    = _fri_lw - _ac_td(days=4)
                _fri_2sem  = _fri_lw - _ac_td(days=14)
                _mon_2sem  = _fri_2sem - _ac_td(days=4)
                _w_lw   = _ac_lw[(_ac_lw["fecha"] >= _mon_lw)  & (_ac_lw["fecha"] <= _fri_lw)]
                _w_2sem = _ac_lw[(_ac_lw["fecha"] >= _mon_2sem) & (_ac_lw["fecha"] <= _fri_2sem)]
                if len(_w_lw) > 0:
                    _lw_tot_pre = _sum_oc_df(_w_lw)
                    _lw_pre = {
                        "mon": _mon_lw, "fri": _fri_lw,
                        "total":   _lw_tot_pre,
                        "per_g":   {g: int(_w_lw[g].sum()) for g in _ac_gru},
                        "label":   f"{_mon_lw:%d/%m}–{_fri_lw:%d/%m}",
                        "n_days":  len(_w_lw),
                        "avg":     int(round(_lw_tot_pre / len(_w_lw))),
                    }

            # 4. This Week Cumulative (counting up to last business day) ──
            if len(_ac_lw_past) >= 1:
                _tw_ult = _ac_lw_past["fecha"].max()
                _tw_mon = _tw_ult - _ac_td(days=_tw_ult.weekday())
                _tw_df  = _ac_lw_past[(_ac_lw_past["fecha"] >= _tw_mon) &
                                       (_ac_lw_past["fecha"] <= _tw_ult)]
                if len(_tw_df) > 0:
                    _sub_tw = (f"{_tw_mon:%d/%m}–{_tw_ult:%d/%m} "
                               f"({len(_tw_df)}d)")
                    _tw = st.columns([1.4] + [1] * (1 + len(_ac_gru) + 1))
                    _tw[0].markdown(_section_card("📊 This Week · OC", _sub_tw),
                                     unsafe_allow_html=True)

                    # Helper: "+X.X% vs last wk (Y kt)" — color verde/rojo según signo
                    _lw_lbl_tw = (_lw_pre["label"] if _lw_pre else "last wk")
                    def _vs_lw(curr, prev):
                        if prev is None or prev <= 0:
                            return None
                        return (f"{(curr - prev) / prev * 100:+.1f}% vs "
                                f"{_lw_lbl_tw} ({fmt_tn(prev)})")

                    _tot_tw = _sum_oc_df(_tw_df)
                    _tw[1].metric("Total", fmt_tn(_tot_tw) + " kt",
                                  delta=_vs_lw(_tot_tw,
                                               _lw_pre["total"] if _lw_pre else None))
                    for _c, _g in zip(_tw[2:2 + len(_ac_gru)], _ac_gru):
                        _v   = int(_tw_df[_g].sum())
                        _v_p = (_lw_pre["per_g"].get(_g) if _lw_pre else None)
                        _c.metric(f"{_g} ({_ac_sub[_g]})",
                                  fmt_tn(_v) + " kt",
                                  delta=_vs_lw(_v, _v_p))
                    _avg_tw = int(round(_tot_tw / len(_tw_df))) if len(_tw_df) else 0
                    _avg_lw_pre = (_lw_pre["avg"] if _lw_pre else None)
                    _avg_delta = None
                    if _avg_lw_pre is not None and _avg_lw_pre > 0:
                        _avg_delta = (
                            f"{(_avg_tw - _avg_lw_pre) / _avg_lw_pre * 100:+.1f}% "
                            f"vs last wk avg ({fmt_tn(_avg_lw_pre)})"
                        )
                    _tw[-1].metric("Avg/Day", fmt_tn(_avg_tw) + " kt",
                                   delta=_avg_delta)

            # 5. Last Business Week ───────────────────────────────────────
            # (_w_lw / _w_2sem ya computados arriba para el delta de This Week)
            if len(_ac_lw) > 0:
                if len(_w_lw) > 0:
                    _sub_lw = f"{_mon_lw:%d/%m}–{_fri_lw:%d/%m} ({len(_w_lw)}d)"

                    def _maiz_wow(v, v_p):
                        if v_p <= 0:
                            return None
                        return f"{(v - v_p) / v_p * 100:+.1f}% vs 2 wks"

                    _lwc = st.columns([1.4] + [1] * (1 + len(_ac_gru) + 1))
                    _lwc[0].markdown(_section_card("📊 Last Week · OC", _sub_lw),
                                      unsafe_allow_html=True)
                    _tot_lw   = _sum_oc_df(_w_lw)
                    _tot_2sem = _sum_oc_df(_w_2sem) if len(_w_2sem) > 0 else 0
                    _lwc[1].metric("Total", fmt_tn(_tot_lw) + " kt",
                                   delta=_maiz_wow(_tot_lw, _tot_2sem))
                    for _c, _g in zip(_lwc[2:2 + len(_ac_gru)], _ac_gru):
                        _v   = int(_w_lw[_g].sum())
                        _v_2 = int(_w_2sem[_g].sum()) if len(_w_2sem) > 0 else 0
                        _c.metric(f"{_g} ({_ac_sub[_g]})", fmt_tn(_v) + " kt",
                                  delta=_maiz_wow(_v, _v_2))
                    _avg_lw   = int(round(_tot_lw / len(_w_lw))) if len(_w_lw) else 0
                    _avg_2sem = int(round(_tot_2sem / len(_w_2sem))) if len(_w_2sem) else 0
                    _lwc[-1].metric("Avg/Day", fmt_tn(_avg_lw) + " kt",
                                    delta=_maiz_wow(_avg_lw, _avg_2sem))

            # 6. Current Month ────────────────────────────────────────────
            # 3-month avg benchmark (mean of last 3 closed mensual rows like
            # Feb-26 / Mar-26 / Abr-26) — used by Current Month Expected below.
            # OC only (suma OC por fila, después promedio sobre filas).
            _3mo_df = _ac_df_mens.tail(3)
            _3mo_n  = len(_3mo_df)
            _3mo_avg_total = ((_3mo_df[_ac_gru_oc].sum(axis=1).mean())
                              if _3mo_n >= 1 and _ac_gru_oc else 0)
            _3mo_avg_g     = ({g: float(_3mo_df[g].mean()) for g in _ac_gru}
                              if _3mo_n >= 1 else {g: 0 for g in _ac_gru})
            _3mo_label     = " / ".join(_3mo_df["label"].tolist()) if _3mo_n >= 1 else "—"

            # Compute the actual date range covered by /05 data
            if len(_cm_dias) > 0:
                _cm_first = _cm_dias.iloc[0]["label"]
                _cm_last  = _cm_dias.iloc[-1]["label"]
                _cm_n_d   = len(_cm_dias)
                _cm_range = (f"{_cm_first} – {_cm_last}, "
                             f"{_cm_n_d} day{'s' if _cm_n_d != 1 else ''}")
            else:
                _cm_range = "no data yet for May"

            # Prev month totals (OC only) para usar como delta dentro de cada
            # metric box.
            if len(_ac_df_mens) > 0:
                _prev_row    = _ac_df_mens.iloc[-1]
                _prev_label  = _prev_row["label"]
                _prev_total  = _sum_oc_row(_prev_row)
                _prev_g      = {g: int(_prev_row[g]) for g in _ac_gru}
            else:
                _prev_label, _prev_total = "—", 0
                _prev_g = {g: 0 for g in _ac_gru}

            def _vs_prev(curr, prev):
                """Returns '+X.X% vs {prev_label} (Y kt)' — verde/rojo según signo."""
                if prev is None or prev <= 0:
                    return None
                return (f"{(curr - prev) / prev * 100:+.1f}% vs "
                        f"{_prev_label} ({fmt_tn(prev)})")

            _cmc = st.columns([1.4] + [1] * (1 + len(_ac_gru) + 1))
            _cmc[0].markdown(_section_card("📆 Current Month · OC", _cm_range),
                              unsafe_allow_html=True)
            _cmc[1].metric("Total cumulative", fmt_tn(_cm_tot) + " kt",
                           delta=_vs_prev(_cm_tot, _prev_total))
            for _c, _g in zip(_cmc[2:2 + len(_ac_gru)], _ac_gru):
                _c.metric(f"{_g} ({_ac_sub[_g]})", fmt_tn(_cm_g[_g]) + " kt",
                          delta=_vs_prev(_cm_g[_g], _prev_g.get(_g, 0)))
            _cmc[-1].metric(f"Avg last {_cm_n} days",
                            fmt_tn(round(_cm_avg_tot)) + " kt/day")

            # 7. Current Month Expected ───────────────────────────────────
            # Compare projected full-month total against 3-mo avg of last
            # closed mensual months (e.g., Feb-26 / Mar-26 / Abr-26).
            # End-of-month label = last business day in dh_mayo (e.g. "29/05")
            _cm_last_dh = _cm_dh[-1] if _cm_dh else "31/05"
            _cm_disp_to = _cm_dias.iloc[-1]["label"] if len(_cm_dias) > 0 else "—"

            def _3mo_delta(value, avg):
                """value & avg both in tn. Returns (delta_str, color).
                Color siempre 'normal' — el CSS de All Crops fuerza verde/rojo."""
                if avg is None or avg <= 0:
                    return (None, "off")
                pct = (value - avg) / avg * 100
                return (f"{pct:+.1f}% vs 3-mo avg", "normal")

            _sub_cme = (f"{_cm_disp_to} + {_cm_bdl}d × 10d avg · "
                        f"vs 3-mo: {_3mo_label}")
            _cme = st.columns([1.4] + [1] * (1 + len(_ac_gru) + 1))
            _cme[0].markdown(_section_card("🎯 Month Expected · OC", _sub_cme),
                              unsafe_allow_html=True)
            _d_exp_tot, _dc_exp_tot = _3mo_delta(_cm_tot_exp, _3mo_avg_total)
            _cme[1].metric("Total Expected", fmt_tn(round(_cm_tot_exp)) + " kt",
                           delta=_d_exp_tot, delta_color=_dc_exp_tot,
                           help=f"3-mo avg total ≈ {fmt_tn(round(_3mo_avg_total))} kt")
            for _c, _g in zip(_cme[2:2 + len(_ac_gru)], _ac_gru):
                _d_g, _dc_g = _3mo_delta(_cm_g_exp[_g], _3mo_avg_g.get(_g, 0))
                _c.metric(f"{_g} ({_ac_sub[_g]})",
                          fmt_tn(round(_cm_g_exp[_g])) + " kt",
                          delta=_d_g, delta_color=_dc_g)
            _cme[-1].metric("Biz Days Left", f"{_cm_bdl}/{_cm_n_total}")

            # 8. Current Crop (closed months actuals + current month projection) ──
            # Historical pace benchmark: for each past cosecha, the equivalent
            # end-of-current-month total = ph_pricing_kt(same calendar date) +
            # month_actual_kt (full current month). Same for per-group.
            _hm_path_cc = DATA_DIR / f"historical_metrics_{_ac_slug}.json"
            _cc_avg_total_kt = None
            _cc_avg_g_kt     = {g: None for g in _ac_gru}
            _cc_n_yrs        = 0
            if _hm_path_cc.exists():
                try:
                    import json as _json_cc
                    _hm_cc = _json_cc.loads(_hm_path_cc.read_text(encoding="utf-8"))
                    _hist_cc = [r for r in _hm_cc.get("rows", [])
                                if not r.get("is_current")]
                    if _hist_cc:
                        _cc_n_yrs = len(_hist_cc)
                        _cc_avg_total_kt = sum(
                            r.get("ph_pricing_kt", 0) + r.get("month_actual_kt", 0)
                            for r in _hist_cc
                        ) / _cc_n_yrs
                        for _g in _ac_gru:
                            _cc_avg_g_kt[_g] = sum(
                                r.get("groups_kt", {}).get(_g, 0)
                                + r.get("month_groups_kt", {}).get(_g, 0)
                                for r in _hist_cc
                            ) / _cc_n_yrs
                except Exception:
                    pass

            def _pace_delta(value_tn, avg_kt):
                """value is in tn, avg is in kt. Returns (delta_str, color).
                Color siempre 'normal' — el CSS de All Crops fuerza verde/rojo."""
                if avg_kt is None or avg_kt <= 0:
                    return (None, "off")
                avg_tn = avg_kt * 1000
                pct = (value_tn - avg_tn) / avg_tn * 100
                return (f"{pct:+.1f}% vs {_cc_n_yrs}-yr avg", "normal")

            _sub_cc = (f"closed→{_last_closed_label} + proj {_projection_month_label}")
            _ccc = st.columns([1.4] + [1] * (1 + len(_ac_gru) + 1))
            _ccc[0].markdown(_section_card("🌾 Current Crop · OC", _sub_cc),
                              unsafe_allow_html=True)
            _cc_d_total, _cc_dc_total = _pace_delta(_cc_total, _cc_avg_total_kt)
            _ccc[1].metric(
                "PH+Pricing (closed + est.)",
                fmt_tn(_cc_total) + " kt",
                delta=_cc_d_total,
                delta_color=_cc_dc_total,
                help=f"= sum of closed months ({_cc_closed_tot:,} kt up to {_last_closed_label}) "
                     f"+ {_projection_month_label} projection ({int(round(_cm_tot_exp)):,} kt). "
                     f"Matches Est FS in Balance Sheet. Delta compares against the "
                     f"avg of past cosechas' total at same point (ph_pricing + full month).",
            )
            for _c, _g in zip(_ccc[2:2 + len(_ac_gru)], _ac_gru):
                _d, _dc = _pace_delta(_cc_split[_g], _cc_avg_g_kt[_g])
                _c.metric(
                    f"{_g} ({_ac_sub[_g]})",
                    fmt_tn(_cc_split[_g]) + " kt",
                    delta=_d,
                    delta_color=_dc,
                    help=f"Closed: {_cc_closed_g[_g]:,} kt + {_projection_month_label} est: "
                         f"{int(round(_cm_g_exp[_g])):,} kt",
                )
            _cc_last3_avg = (int(round(_ac_df_mens.tail(3)[_ac_gru_oc].sum(axis=1).mean()))
                             if len(_ac_df_mens) > 0 and _ac_gru_oc else 0)
            _ccc[-1].metric("L3mo Avg", fmt_tn(_cc_last3_avg) + " kt")

            # 9. Balance Sheet ────────────────────────────────────────────
            # Última sección — usa el mismo formato inline-label que el resto.
            # Promedios históricos de cada campo del BS: forzamos el MISMO N
            # que Current Crop (_cc_n_yrs) tomando las N cosechas más recientes
            # del balance_hist excluyendo la vigente — así el "N-yr avg" es
            # consistente entre ambas secciones.
            _bs = _ac_b
            def _key_year(k):
                try:
                    return int(str(k).split("/")[0])
                except Exception:
                    return -1
            _bal_keys_past = sorted(
                [k for k in _ac_bh.keys() if k != _ac_bdef],
                key=_key_year, reverse=True,
            )
            _target_n = _cc_n_yrs if _cc_n_yrs > 0 else len(_bal_keys_past)
            _bal_keys_used = _bal_keys_past[:_target_n]
            _bal_other = {k: _ac_bh[k] for k in _bal_keys_used}
            _bal_n_yrs = len(_bal_other)

            def _avg_field(field):
                vals = [v.get(field) for v in _bal_other.values()
                        if isinstance(v, dict) and v.get(field) is not None]
                return (sum(vals) / len(vals)) if vals else None

            _bal_avg_ci   = _avg_field("ci")
            _bal_avg_prod = _avg_field("prod")
            _bal_avg_imp  = _avg_field("imp")
            _bal_avg_dom  = _avg_field("dom")
            _bal_avg_co   = _avg_field("co")
            # Exports derivado: ci + prod + imp - dom - co por cosecha → promedio
            _exp_vals = [(v["ci"] + v["prod"] + v["imp"] - v["dom"] - v["co"])
                         for v in _bal_other.values()
                         if all(k in v for k in ("ci","prod","imp","dom","co"))]
            _bal_avg_exp = (sum(_exp_vals) / len(_exp_vals)) if _exp_vals else None

            # FS/Exports avg: viene de historical_metrics (fs_pct = ph_pricing / est_exp × 100)
            _fs_pct_vals = []
            if _hm_path_cc.exists():
                try:
                    _fs_pct_vals = [r.get("fs_pct") for r in _hist_cc
                                    if r.get("fs_pct") is not None]
                except Exception:
                    pass
            _fs_pct_avg = ((sum(_fs_pct_vals) / len(_fs_pct_vals))
                           if _fs_pct_vals else None)

            def _bs_delta(curr, avg, suffix=None):
                """Delta vs avg. curr/avg en la misma unidad. Color neutral."""
                if avg is None or avg <= 0:
                    return None
                pct = (curr - avg) / avg * 100
                lbl = suffix or f"vs {_bal_n_yrs}-yr avg"
                return f"{pct:+.1f}% {lbl}"

            _bsc = st.columns([1.4] + [1] * 8)
            _bsc[0].markdown(_section_card("📋 Balance Sheet", "M tn / kt"),
                              unsafe_allow_html=True)
            _bsc[1].metric("Carry In",    f"{_bs['ci']:.2f} M tn",
                           delta=_bs_delta(_bs["ci"], _bal_avg_ci))
            _bsc[2].metric("Production",  f"{_bs['prod']:.2f} M tn",
                           delta=_bs_delta(_bs["prod"], _bal_avg_prod))
            _bsc[3].metric("Imports",     f"{_bs['imp']:.2f} M tn",
                           delta=_bs_delta(_bs["imp"], _bal_avg_imp))
            _bsc[4].metric("Domestic",    f"{_bs['dom']:.2f} M tn",
                           delta=_bs_delta(_bs["dom"], _bal_avg_dom))
            _bsc[5].metric("Carry Out",   f"{_bs['co']:.2f} M tn",
                           delta=_bs_delta(_bs["co"], _bal_avg_co))
            _bsc[6].metric("Exports",     f"{_ac_exp_calc:.2f} M tn",
                           delta=_bs_delta(_ac_exp_calc, _bal_avg_exp))
            # Est FS · delta vs N-yr historical avg (mismo cálculo que Current Crop)
            _bs_d_total, _bs_dc_total = _pace_delta(_cc_total, _cc_avg_total_kt)
            _bsc[7].metric("Est FS", fmt_tn(_cc_total) + " kt",
                            delta=_bs_d_total,
                            delta_color=_bs_dc_total,
                            help="Sum of closed months + current month projection. "
                                 "Matches PH+Pricing (closed + est.) en Current Crop.")
            # FS/Exports · current ratio vs historical avg fs_pct
            _fs_now = (_cc_total / _ac_exp * 100) if _ac_exp > 0 else None
            _fs_delta = None
            if _fs_now is not None and _fs_pct_avg is not None and _fs_pct_avg > 0:
                _pp = _fs_now - _fs_pct_avg
                _fs_delta = f"{_pp:+.1f}pp vs {len(_fs_pct_vals)}-yr avg"
            _bsc[8].metric("FS / Exports",
                            fmt_pct(_fs_now) if _fs_now is not None else "—",
                            delta=_fs_delta)

    st.stop()


# ── Carga de datos ────────────────────────────────────────────────────────────

df = load_matriz(cfg)

if df is None:
    st.title(f"{cfg['emoji']} Farmer Selling · {cfg['label']} {cfg.get('cosecha_label', cfg['cosecha'])}")
    st.warning(
        f"📂 Can't find `data/{cfg['matriz_csv']}`. "
        "Run:\n\n```bash\nmake daily\n```\n"
        "to regenerate them from the pipeline (SIO + MINAGRI)."
    )
    st.stop()

df_mens    = df[df["tipo"] == "mensual"].copy()
df_dias    = df[df["tipo"] == "diario"].copy()
df_targets = df[df["tipo"] == "mayo_target"].copy() if "mayo_target" in df["tipo"].values else df.iloc[0:0]

if MODO_PUBLICO:
    df_targets = df_targets.iloc[0:0]

if mayo_mode == "Cumulative" and len(df_dias) > 0:
    df_dias_show = df_dias.copy()
    for g in GRUPOS + ["total"]:
        df_dias_show[g] = df_dias[g].cumsum()
    df_dias_show["label"] = df_dias_show["label"] + " cum"
else:
    df_dias_show = df_dias.copy()

# For the matrix table: only May days (April is already aggregated into the
# Abr-26 monthly row). The rolling average still uses the full df_dias.
df_dias_show = df_dias_show[df_dias_show["label"].str.contains("/05")]

df_normal   = pd.concat([df_mens, df_dias_show], ignore_index=True)
# For totals: only May days are counted separately (April is already in the
# Abr-26 monthly row — avoiding double-count).
_df_dias_mayo = df_dias[df_dias["label"].str.contains("/05")]
total_all   = int(df_mens["total"].sum() + _df_dias_mayo["total"].sum())
totales_col = {g: int(df_mens[g].sum() + _df_dias_mayo[g].sum()) for g in GRUPOS}


# ── Title and macro metrics ───────────────────────────────────────────────────

st.title(f"{cfg['emoji']} Farmer Selling · {cfg['label']} {cfg.get('cosecha_label', cfg['cosecha'])}")

tab1, tab2, tab3, tab4 = st.tabs(["📊 Matrix", "📈 Charts", "🚢 Destinations", "🗺️ Origin map"])

# ── TAB 1: MATRIX (macro header + historical comparison + matrix table) ─────

with tab1:

    # ── Save originals so we can restore at end of tab1 (other tabs see
    #    the unfiltered crop view). destinos_sel comes from the sidebar.
    _orig_df            = df
    _orig_df_mens       = df_mens
    _orig_df_dias       = df_dias
    _orig_df_dias_show  = df_dias_show
    _orig_df_targets    = df_targets
    _orig_df_dias_mayo  = _df_dias_mayo
    _orig_total_all     = total_all
    _orig_totales_col   = totales_col

    if destinos_sel:
        # Load per-destination matrices (raw SIO filtered by destination).
        _per_dest = {}
        _missing  = []
        for _d in _DESTINOS:
            _p = DATA_DIR / cfg["matriz_csv"].replace(".csv", f"_{_d}.csv")
            if _p.exists():
                try:
                    _dfd = pd.read_csv(_p)
                    for _col in GRUPOS + ["total"]:
                        _dfd[_col] = pd.to_numeric(_dfd[_col], errors="coerce").fillna(0)
                    _per_dest[_d] = _dfd
                except Exception:
                    _missing.append(_d)
            else:
                _missing.append(_d)

        if any(_d in _missing for _d in destinos_sel) or not _per_dest:
            st.warning(
                f"⚠️ Missing per-destination matrices for "
                f"{[d for d in destinos_sel if d in _missing]}. "
                f"Run `make daily`. Filter ignored."
            )
            destinos_sel = []
        else:
            # Denominator: sum of ALL destinations (= total raw SIO per row).
            _df_all_sio = _per_dest[_DESTINOS[0]].copy()
            for _d in _DESTINOS[1:]:
                if _d in _per_dest:
                    for _col in GRUPOS + ["total"]:
                        _df_all_sio[_col] = _df_all_sio[_col] + _per_dest[_d][_col]
            # Numerator: sum of SELECTED destinations.
            _df_sel = _per_dest[destinos_sel[0]].copy()
            for _d in destinos_sel[1:]:
                for _col in GRUPOS + ["total"]:
                    _df_sel[_col] = _df_sel[_col] + _per_dest[_d][_col]

            # Scale per row: cell_filt = sel.cell × (main.total / all_sio.total)
            # mayo_target rows (projections) are left untouched.
            _df_scaled = df.copy()
            for _idx in _df_scaled.index:
                _row_main = df.loc[_idx]
                if _row_main["tipo"] == "mayo_target":
                    continue
                _mask = ((_df_all_sio["tipo"] == _row_main["tipo"]) &
                         (_df_all_sio["label"] == _row_main["label"]))
                if not _mask.any():
                    continue
                _row_all = _df_all_sio[_mask].iloc[0]
                _row_sel = _df_sel[_mask].iloc[0]
                _sio_total  = float(_row_all["total"])
                _main_total = float(_row_main["total"])
                _scale = (_main_total / _sio_total) if _sio_total > 0 else 0.0
                for _col in GRUPOS + ["total"]:
                    _df_scaled.at[_idx, _col] = int(round(_row_sel[_col] * _scale))

            # Re-derive all downstream working frames from the scaled df.
            df = _df_scaled
            df_mens = df[df["tipo"] == "mensual"].copy()
            df_dias = df[df["tipo"] == "diario"].copy()
            df_targets = (df[df["tipo"] == "mayo_target"].copy()
                          if "mayo_target" in df["tipo"].values else df.iloc[0:0])
            if MODO_PUBLICO:
                df_targets = df_targets.iloc[0:0]
            if mayo_mode == "Cumulative" and len(df_dias) > 0:
                df_dias_show = df_dias.copy()
                for _g in GRUPOS + ["total"]:
                    df_dias_show[_g] = df_dias[_g].cumsum()
                df_dias_show["label"] = df_dias_show["label"] + " cum"
            else:
                df_dias_show = df_dias.copy()
            df_dias_show = df_dias_show[df_dias_show["label"].str.contains("/05")]
            _df_dias_mayo = df_dias[df_dias["label"].str.contains("/05")]
            total_all   = int(df_mens["total"].sum() + _df_dias_mayo["total"].sum())
            totales_col = {g: int(df_mens[g].sum() + _df_dias_mayo[g].sum()) for g in GRUPOS}

    # ── Macro KPIs row 1: ALWAYS full crop (unaffected by destination filter) ─
    _n_cols_macro = 3 + len(GRUPOS)
    _macro_cols = st.columns(_n_cols_macro)
    _macro_cols[0].metric("Est. Exports",        f"{exp_calc * 1000:,.0f} kt".replace(",", "."))
    _macro_cols[1].metric("PH + Pricing acum.",  fmt_tn(_orig_total_all) + " kt")
    _macro_cols[2].metric("FS / Exports",        fmt_pct(_orig_total_all/exp*100) if exp > 0 else "—")
    for _col_g, _g in zip(_macro_cols[3:], GRUPOS):
        _pct_g = (_orig_totales_col[_g] / _orig_total_all * 100) if _orig_total_all > 0 else 0
        _col_g.metric(
            f"{_g} ({GRUPO_SUBTITULOS[_g]})",
            fmt_tn(_orig_totales_col[_g]) + " kt",
            delta=f"{_pct_g:.1f}% of priced",
            delta_color="off",
        )

    # ── Macro KPIs row 2: filtered subset (only rendered when filter active) ──
    if destinos_sel:
        st.markdown(
            f"<div style='color:#1d9e75;font-size:0.85em;margin:0.5em 0 -0.5em 0;font-weight:600'>"
            f"🎯 Filtered: {', '.join(_DESTINOS_LABEL[d] for d in destinos_sel)}"
            f"</div>",
            unsafe_allow_html=True,
        )
        _f_cols = st.columns(_n_cols_macro)
        # Est. Exports: same forecast (not filterable) — leave blank for alignment
        _f_cols[0].metric(" ", "—", label_visibility="hidden")
        # PH + Pricing acum (filtered) + % of full crop
        _pct_ph = (total_all / _orig_total_all * 100) if _orig_total_all > 0 else 0
        _f_cols[1].metric(
            "PH + Pricing acum.",
            fmt_tn(total_all) + " kt",
            delta=f"{_pct_ph:.1f}% of total",
            delta_color="off",
        )
        # FS / Exports (filtered)
        _f_cols[2].metric(
            "FS / Exports",
            fmt_pct(total_all/exp*100) if exp > 0 else "—",
        )
        for _col_g, _g in zip(_f_cols[3:], GRUPOS):
            _full_v = _orig_totales_col[_g]
            _f_pct  = (totales_col[_g] / _full_v * 100) if _full_v > 0 else 0
            _col_g.metric(
                f"{_g} ({GRUPO_SUBTITULOS[_g]})",
                fmt_tn(totales_col[_g]) + " kt",
                delta=f"{_f_pct:.1f}% of total",
                delta_color="off",
            )

    # ── May tracking: avg last 10 business days + month-end projection ────────
    # Lives here (top-level) so it's always visible — not tied to a specific tab.
    if len(df_dias) > 0 and DIAS_HABILES_MAYO:
        df_dias_mayo  = df_dias[df_dias["label"].str.endswith("/05")]
        n_recent      = min(10, len(df_dias))
        df_recent     = df_dias.tail(n_recent)
        avg_recent    = df_recent["total"].sum() / n_recent if n_recent else 0
        # Total May business days from config (filter the "/05")
        dias_mayo_cfg = [d for d in DIAS_HABILES_MAYO if d.endswith("/05")]
        n_mes_total   = len(dias_mayo_cfg)
        n_mayo_disp   = len(df_dias_mayo)
        real_mayo     = df_dias_mayo["total"].sum() if n_mayo_disp else 0
        dias_restantes = max(0, n_mes_total - n_mayo_disp)
        proyeccion    = real_mayo + dias_restantes * avg_recent
        primer_dia = df_recent["label"].iloc[0]
        ultimo_dia = df_recent["label"].iloc[-1]

        st.markdown(f"##### 📅 May tracking · {cfg['label']}")
        sm1, sm2, sm3, sm4 = st.columns(4)
        sm1.metric("May actual cumulative", fmt_tn(round(real_mayo)) + " kt",
                   help=f"{n_mayo_disp} May business days published.")
        sm2.metric(f"Avg last {n_recent} business days", fmt_tn(round(avg_recent)) + " kt/day",
                   help=f"Average between {primer_dia} and {ultimo_dia} (includes April if May has fewer than 10 days).")
        sm3.metric("Business days left in May", f"{dias_restantes}/{n_mes_total}")
        # Calculamos el 7-yr avg del mes corriente desde historical_metrics (si existe)
        _proj_delta_str = None
        _proj_delta_color = "off"
        try:
            import json as _sm_json
            from cultivos import slug_de as _sm_slug
            _sm_path = DATA_DIR / f"historical_metrics_{_sm_slug(cfg)}.json"
            if _sm_path.exists():
                _sm = _sm_json.loads(_sm_path.read_text(encoding="utf-8"))
                _hist_rows_sm = [r for r in _sm.get("rows", []) if not r.get("is_current")]
                if _hist_rows_sm:
                    _avg7_kt = sum(r.get("month_actual_kt", 0) for r in _hist_rows_sm) / len(_hist_rows_sm)
                    _avg7_tn = _avg7_kt * 1000  # back to tn for delta math
                    if _avg7_tn > 0:
                        _delta_pct = (proyeccion - _avg7_tn) / _avg7_tn * 100
                        _proj_delta_str = f"{_delta_pct:+.1f}% vs {len(_hist_rows_sm)}-yr avg"
                        _proj_delta_color = "normal" if _delta_pct >= 0 else "inverse"
        except Exception:
            pass
        if _proj_delta_str is None:
            _proj_delta_str = (f"+{fmt_tn(round(dias_restantes * avg_recent))} kt pending"
                               if dias_restantes else "Month closed")
            _proj_delta_color = "off"
        sm4.metric("May-end projection", fmt_tn(round(proyeccion)) + " kt",
                   delta=_proj_delta_str, delta_color=_proj_delta_color)

    # ── Last business week: total + per-group breakdown + WoW vs 2 weeks ago ──
    if len(df_dias) > 0:
        from datetime import date as _lw_date, timedelta as _lw_td

        def _parse_lbl(s):
            # Labels come as "DD/MM" (year implicit 2026 — the app works on the current month)
            try:
                d, m = s.split("/")
                return _lw_date(2026, int(m), int(d))
            except Exception:
                return None

        _df_lw = df_dias.copy()
        _df_lw["fecha"] = _df_lw["label"].apply(_parse_lbl)
        _df_lw = _df_lw.dropna(subset=["fecha"])

        if len(_df_lw) > 0:
            ultimo = _df_lw["fecha"].max()
            # Last full business week = Mon-Fri ending on the Friday <= last day with data
            diff_to_fri = (ultimo.weekday() - 4) % 7
            viernes_ult = ultimo - _lw_td(days=diff_to_fri)
            lunes_ult   = viernes_ult - _lw_td(days=4)
            # Two weeks ago
            viernes_2sem = viernes_ult - _lw_td(days=14)
            lunes_2sem   = viernes_2sem - _lw_td(days=4)

            df_w_lw  = _df_lw[(_df_lw["fecha"] >= lunes_ult)  & (_df_lw["fecha"] <= viernes_ult)]
            df_w_2sem = _df_lw[(_df_lw["fecha"] >= lunes_2sem) & (_df_lw["fecha"] <= viernes_2sem)]

            if len(df_w_lw) > 0:
                st.markdown(
                    f"##### 📊 Last business week · {cfg['label']}"
                    f" <span style='color:#888;font-size:0.8em;font-weight:normal'>"
                    f"({lunes_ult:%d/%m} – {viernes_ult:%d/%m}, "
                    f"{len(df_w_lw)} day{'s' if len(df_w_lw)!=1 else ''} with data)"
                    f"</span>",
                    unsafe_allow_html=True,
                )

                def _wow_delta(v_lw, v_2sem):
                    if v_2sem <= 0:
                        return None
                    pct = (v_lw - v_2sem) / v_2sem * 100
                    return f"{pct:+.1f}% vs 2 wks ago"

                cols_lw = st.columns(1 + len(GRUPOS) + 1)  # +1 for Avg/day
                tot_lw   = int(df_w_lw["total"].sum())
                tot_2sem = int(df_w_2sem["total"].sum()) if len(df_w_2sem) > 0 else 0
                cols_lw[0].metric(
                    "Total", fmt_tn(tot_lw) + " kt",
                    delta=_wow_delta(tot_lw, tot_2sem),
                )
                for col, g in zip(cols_lw[1:1 + len(GRUPOS)], GRUPOS):
                    v_lw   = int(df_w_lw[g].sum())
                    v_2sem = int(df_w_2sem[g].sum()) if len(df_w_2sem) > 0 else 0
                    col.metric(
                        f"{g} ({GRUPO_SUBTITULOS[g]})",
                        fmt_tn(v_lw) + " kt",
                        delta=_wow_delta(v_lw, v_2sem),
                    )
                # Avg/day across the week (Total / days_with_data)
                avg_lw   = int(round(tot_lw / len(df_w_lw))) if len(df_w_lw) > 0 else 0
                avg_2sem = int(round(tot_2sem / len(df_w_2sem))) if len(df_w_2sem) > 0 else 0
                cols_lw[-1].metric(
                    "Avg/day", fmt_tn(avg_lw) + " kt",
                    delta=_wow_delta(avg_lw, avg_2sem),
                )

    # ── This week cumulative: Monday → last day with data + per-group + Avg ──
    if len(df_dias) > 0:
        from datetime import date as _tw_date, timedelta as _tw_td

        def _parse_lbl_tw(s):
            try:
                d, m = s.split("/")
                return _tw_date(2026, int(m), int(d))
            except Exception:
                return None

        _df_tw = df_dias.copy()
        _df_tw["fecha"] = _df_tw["label"].apply(_parse_lbl_tw)
        _df_tw = _df_tw.dropna(subset=["fecha"]).sort_values("fecha").reset_index(drop=True)

        if len(_df_tw) > 0:
            _ult_tw = _df_tw["fecha"].max()
            _mon_tw = _ult_tw - _tw_td(days=_ult_tw.weekday())  # Monday of this week
            df_tw   = _df_tw[(_df_tw["fecha"] >= _mon_tw) & (_df_tw["fecha"] <= _ult_tw)]

            if len(df_tw) > 0:
                st.markdown(
                    f"##### 📊 This week cumulative · {cfg['label']}"
                    f" <span style='color:#888;font-size:0.8em;font-weight:normal'>"
                    f"({_mon_tw:%d/%m} – {_ult_tw:%d/%m}, "
                    f"{len(df_tw)} day{'s' if len(df_tw)!=1 else ''} so far)"
                    f"</span>",
                    unsafe_allow_html=True,
                )

                cols_tw = st.columns(1 + len(GRUPOS) + 1)  # +1 for Avg/day
                tot_tw  = int(df_tw["total"].sum())
                cols_tw[0].metric("Total", fmt_tn(tot_tw) + " kt")
                for col, g in zip(cols_tw[1:1 + len(GRUPOS)], GRUPOS):
                    v = int(df_tw[g].sum())
                    col.metric(f"{g} ({GRUPO_SUBTITULOS[g]})", fmt_tn(v) + " kt")
                avg_tw = int(round(tot_tw / len(df_tw))) if len(df_tw) > 0 else 0
                cols_tw[-1].metric("Avg/day", fmt_tn(avg_tw) + " kt")

    # ── Last business day: total + per-group breakdown + DoD vs previous day ──
    if len(df_dias) > 0:
        from datetime import date as _lbd_date

        def _parse_lbl_lbd(s):
            try:
                d, m = s.split("/")
                return _lbd_date(2026, int(m), int(d))
            except Exception:
                return None

        _df_lbd = df_dias.copy()
        _df_lbd["fecha"] = _df_lbd["label"].apply(_parse_lbl_lbd)
        _df_lbd = _df_lbd.dropna(subset=["fecha"]).sort_values("fecha").reset_index(drop=True)

        # Exclude TODAY from the picker — we want the last full business day
        # before today (handles post-weekend / post-holiday automatically).
        _today_lbd = _lbd_date.today()
        _df_lbd_past = _df_lbd[_df_lbd["fecha"] < _today_lbd].reset_index(drop=True)

        if len(_df_lbd_past) >= 1:
            _last_row = _df_lbd_past.iloc[-1]
            _prev_row = _df_lbd_past.iloc[-2] if len(_df_lbd_past) >= 2 else None

            _hdr_extra = (f" vs {_prev_row['fecha']:%d/%m}" if _prev_row is not None else "")
            st.markdown(
                f"##### 📅 Last business day · {cfg['label']}"
                f" <span style='color:#888;font-size:0.8em;font-weight:normal'>"
                f"({_last_row['fecha']:%d/%m}{_hdr_extra})"
                f"</span>",
                unsafe_allow_html=True,
            )

            def _dod_delta(v, v_prev):
                if v_prev is None or v_prev <= 0:
                    return None
                pct = (v - v_prev) / v_prev * 100
                return f"{pct:+.1f}% DoD"

            cols_lbd = st.columns(1 + len(GRUPOS))
            tot_lbd  = int(_last_row["total"])
            tot_prev = int(_prev_row["total"]) if _prev_row is not None else None
            cols_lbd[0].metric(
                "Total", fmt_tn(tot_lbd) + " kt",
                delta=_dod_delta(tot_lbd, tot_prev),
            )
            for col, g in zip(cols_lbd[1:], GRUPOS):
                v      = int(_last_row[g])
                v_prev = int(_prev_row[g]) if _prev_row is not None else None
                col.metric(
                    f"{g} ({GRUPO_SUBTITULOS[g]})",
                    fmt_tn(v) + " kt",
                    delta=_dod_delta(v, v_prev),
                )

    # ── 📈 Historical comparison: full metrics row per cosecha ────────────────
    # Lee data/historical_metrics_<crop>.json (precomputed por compute_historical_metrics.py).
    import json as _hm_json
    from datetime import date as _hm_date
    from cultivos import slug_de as _hm_slug

    _hm_path = DATA_DIR / f"historical_metrics_{_hm_slug(cfg)}.json"
    if _hm_path.exists():
        try:
            _hm = _hm_json.loads(_hm_path.read_text(encoding="utf-8"))
        except Exception:
            _hm = None
    else:
        _hm = None

    if _hm is None or not _hm.get("rows"):
        st.info("ℹ Run `make historical-metrics` to populate the historical comparison panel "
                "(requires `make backfill-sio-historico` first if you don't have it).")
    else:
        _hm_rows   = _hm["rows"]
        _hm_grupos = _hm["grupos"]
        _hm_sub    = _hm["subtitulos"]
        _hm_curr_d = _hm_date.fromisoformat(_hm["current_date"])

        _hm_unfiltered_note = (
            " · <em style='color:#a35a00'>(unfiltered — full crop)</em>"
            if destinos_sel else ""
        )
        st.markdown(
            f"##### 📈 Historical comparison · {cfg['label']}{_hm_unfiltered_note}"
            f" <span style='color:#888;font-size:0.8em;font-weight:normal'>"
            f"(each row at the same calendar date as the current MAGYP cut · {_hm_curr_d:%d/%m/%Y})</span>",
            unsafe_allow_html=True,
        )

        # ── Construcción de la tabla compacta ────────────────────────────────
        def _fmt_kt_int(v):
            if v is None or v == 0:
                return "—"
            return f"{int(v):,}".replace(",", ".") + " kt"

        def _fmt_pct1(v):
            if v is None or v == 0:
                return "—"
            return f"{v:.1f}%"

        def _row_to_dict(label, prod, est_exp, ph, fs, groups):
            d = {
                "Crop year":    label,
                "Production":   _fmt_kt_int(prod),
                "Est. Exports": _fmt_kt_int(est_exp),
                "PH + Pricing": _fmt_kt_int(ph),
                "FS / Exports": _fmt_pct1(fs),
            }
            for g in _hm_grupos:
                d[f"{g} ({_hm_sub[g]})"] = _fmt_kt_int(groups.get(g, 0))
            return d

        _table_rows = []

        # 1) Current + N históricas
        for _row in _hm_rows:
            _label_show = _row.get("cosecha_label") or _row["cosecha"]
            if _row["is_current"]:
                _label_show = f"⭐ Current · {_label_show}"
            _table_rows.append(_row_to_dict(
                _label_show,
                _row.get("production_kt", 0),
                _row["est_exports_kt"],
                _row["ph_pricing_kt"],
                _row["fs_pct"],
                _row["groups_kt"],
            ))

        # 2) N-yr avg + Pace vs avg
        _hist_only = [r for r in _hm_rows if not r["is_current"]]
        _cur_row   = next((r for r in _hm_rows if r["is_current"]), None)
        if _hist_only and _cur_row:
            _n_h     = len(_hist_only)
            _avg_prod = sum(r.get("production_kt", 0) for r in _hist_only) / _n_h
            _avg_exp  = sum(r["est_exports_kt"] for r in _hist_only) / _n_h
            _avg_ph   = sum(r["ph_pricing_kt"]  for r in _hist_only) / _n_h
            _avg_fs   = sum(r["fs_pct"]         for r in _hist_only) / _n_h
            _avg_g    = {g: sum(r["groups_kt"].get(g, 0) for r in _hist_only) / _n_h
                         for g in _hm_grupos}
            _table_rows.append(_row_to_dict(
                f"{_n_h}-yr avg", _avg_prod, _avg_exp, _avg_ph, _avg_fs, _avg_g))

            # Fila Pace vs avg en %
            def _dpct(c, a):
                return (c - a) / a * 100 if a else 0
            _pace_row = {
                "Crop year":    "Pace vs avg",
                "Production":   f"{_dpct(_cur_row.get('production_kt', 0), _avg_prod):+.1f}%",
                "Est. Exports": f"{_dpct(_cur_row['est_exports_kt'], _avg_exp):+.1f}%",
                "PH + Pricing": f"{_dpct(_cur_row['ph_pricing_kt'],  _avg_ph):+.1f}%",
                "FS / Exports": f"{_cur_row['fs_pct'] - _avg_fs:+.1f} pp",
            }
            for g in _hm_grupos:
                _pace_row[f"{g} ({_hm_sub[g]})"] = f"{_dpct(_cur_row['groups_kt'].get(g, 0), _avg_g[g]):+.1f}%"
            _table_rows.append(_pace_row)

        _df_hm = pd.DataFrame(_table_rows)

        # ── Render con highlighting de filas especiales ──────────────────────
        def _highlight(row):
            if "Current" in str(row["Crop year"]):
                return ["background-color: rgba(29,158,117,0.12); font-weight: 600"] * len(row)
            if "yr avg" in str(row["Crop year"]):
                return ["background-color: rgba(0,0,0,0.06); font-style: italic"] * len(row)
            if "Pace vs avg" in str(row["Crop year"]):
                return ["background-color: rgba(55,138,221,0.10); font-weight: 600"] * len(row)
            return [""] * len(row)

        st.dataframe(
            _df_hm.style.apply(_highlight, axis=1),
            use_container_width=True, hide_index=True,
            height=55 + 35 * len(_df_hm),
        )

    # ── Comparación histórica del mes corriente (lee historical_metrics) ───
    import json as _hmm_json
    from cultivos import slug_de as _hmm_slug
    _hmm_path = DATA_DIR / f"historical_metrics_{_hmm_slug(cfg)}.json"
    if _hmm_path.exists():
        try:
            _hmm = _hmm_json.loads(_hmm_path.read_text(encoding="utf-8"))
        except Exception:
            _hmm = None
        if _hmm and _hmm.get("rows"):
            _hmm_rows   = _hmm["rows"]
            _hmm_grupos = _hmm["grupos"]
            _hmm_sub    = _hmm["subtitulos"]
            _hmm_mon    = _hmm.get("current_month_name", "Current month")

            _hmm_unfiltered_note = (
                " · <em style='color:#a35a00'>(unfiltered — full crop)</em>"
                if destinos_sel else ""
            )
            st.markdown(
                f"###### 🗓️ {_hmm_mon} historical · {cfg['label']}{_hmm_unfiltered_note}"
                f" <span style='color:#888;font-size:0.8em;font-weight:normal'>"
                f"(current row = actual-to-date · past years = full-month actuals)"
                f"</span>",
                unsafe_allow_html=True,
            )

            def _fmt_kt_int_m(v):
                if v is None or v == 0:
                    return "—"
                return f"{int(v):,}".replace(",", ".") + " kt"

            # Todas las filas: current (actual to-date) + históricas (full)
            _mt_rows = []
            for _r in _hmm_rows:
                _label = _r.get("cosecha_label") or _r["cosecha"]
                if _r["is_current"]:
                    _label = f"⭐ Current · {_label}"
                _row_data = {
                    "Crop year":          _label,
                    f"{_hmm_mon} total":  _fmt_kt_int_m(_r.get("month_actual_kt", 0)),
                }
                for _g in _hmm_grupos:
                    _row_data[f"{_g} ({_hmm_sub[_g]})"] = _fmt_kt_int_m(
                        _r.get("month_groups_kt", {}).get(_g, 0))
                _mt_rows.append(_row_data)

            # 7-yr avg (solo de las históricas, no current)
            _hist_only_m = [r for r in _hmm_rows if not r["is_current"]]
            if _hist_only_m:
                _n_hm = len(_hist_only_m)
                _avg_act = sum(r.get("month_actual_kt", 0) for r in _hist_only_m) / _n_hm
                _avg_g_m = {g: sum(r.get("month_groups_kt", {}).get(g, 0) for r in _hist_only_m) / _n_hm
                            for g in _hmm_grupos}
                _avg_row = {
                    "Crop year":          f"{_n_hm}-yr avg",
                    f"{_hmm_mon} total":  _fmt_kt_int_m(round(_avg_act)),
                }
                for _g in _hmm_grupos:
                    _avg_row[f"{_g} ({_hmm_sub[_g]})"] = _fmt_kt_int_m(round(_avg_g_m[_g]))
                _mt_rows.append(_avg_row)

            _df_mt = pd.DataFrame(_mt_rows)

            def _highlight_m(row):
                v = str(row["Crop year"])
                if "Current" in v:
                    return ["background-color: rgba(29,158,117,0.12); font-weight: 600"] * len(row)
                if "yr avg" in v:
                    return ["background-color: rgba(0,0,0,0.06); font-style: italic; font-weight: 600"] * len(row)
                return [""] * len(row)

            st.dataframe(
                _df_mt.style.apply(_highlight_m, axis=1),
                use_container_width=True, hide_index=True,
                height=55 + 35 * len(_df_mt),
            )

    # ── 🩺 Data Health: freshness + cross-validation ──────────────────────────────
    with st.expander("🩺 Data Health · freshness & cross-checks", expanded=False):
        from datetime import date as _dh_date
        import json as _dh_json
        from cultivos import minagri_json_path as _dh_mp

        dh1, dh2, dh3 = st.columns(3)

        # ── Col 1: SIO freshness ──────────────────────────────────────────────
        with dh1:
            st.markdown("**📥 SIO Granos**")
            if len(df_dias) > 0:
                ultimo_label = df_dias.iloc[-1]["label"]
                ultimo_total = int(df_dias.iloc[-1]["total"])
                n_mayo_disp_dh  = len(df_dias[df_dias["label"].str.endswith("/05")])
                n_mayo_total_dh = len(DIAS_HABILES_MAYO) if DIAS_HABILES_MAYO else 0
                st.metric("Last business day", ultimo_label)
                st.metric("Last day · total kt", fmt_tn(ultimo_total))
                st.metric("May business days", f"{n_mayo_disp_dh}/{n_mayo_total_dh}")
                try:
                    d, m = ultimo_label.split("/")
                    last_date_sio = _dh_date(2026, int(m), int(d))
                    days_old_sio = (_dh_date.today() - last_date_sio).days
                    if days_old_sio <= 1:
                        st.success("✓ Fresh (≤1 day)")
                    elif days_old_sio <= 3:
                        st.warning(f"⚠ {days_old_sio} days old")
                    else:
                        st.error(f"🔴 {days_old_sio} days old — pipeline stuck?")
                except Exception:
                    pass
            else:
                st.info("No daily SIO data loaded.")

        # ── Col 2: MAGYP freshness ────────────────────────────────────────────
        with dh2:
            st.markdown(f"**📡 MAGYP · {cfg['cosecha']}**")
            _mp_dh = Path(_dh_mp(cfg))
            magyp_total_kt = None
            if _mp_dh.exists():
                try:
                    _serie_dh = _dh_json.loads(_mp_dh.read_text(encoding="utf-8")).get("serie", [])
                except Exception:
                    _serie_dh = []
                if _serie_dh:
                    last_pt = _serie_dh[-1]
                    last_fecha_dh = last_pt["fecha"]
                    magyp_total_kt = float(last_pt.get("ph_fijado_acum_kt", 0))
                    ph_kt_dh  = float(last_pt.get("ph_acum_kt", 0) or 0)
                    fij_kt_dh = float(last_pt.get("fij_acum_kt", 0) or 0)
                    last_d_dh = _dh_date.fromisoformat(last_fecha_dh)
                    days_old_magyp = (_dh_date.today() - last_d_dh).days
                    st.metric("Last weekly cut", last_d_dh.strftime("%d/%m/%Y"))
                    st.metric("PH + Pricing acum.", f"{magyp_total_kt:,.0f} kt".replace(",", "."))
                    st.caption(f"PH {ph_kt_dh:,.0f} · Pricing {fij_kt_dh:,.0f}".replace(",", "."))
                    if days_old_magyp <= 8:
                        st.success(f"✓ {days_old_magyp} days since last cut")
                    elif days_old_magyp <= 14:
                        st.warning(f"⚠ {days_old_magyp} days old")
                    else:
                        st.error(f"🔴 {days_old_magyp} days old — scraper stuck?")
                else:
                    st.info("MAGYP JSON exists but is empty.")
            else:
                st.info(f"No MAGYP JSON at `{_mp_dh.name}`.")

        # ── Col 3: Cross-checks ───────────────────────────────────────────────
        with dh3:
            st.markdown("**🔗 Cross-checks**")
            # 1) Matrix vs Destinations
            _dest_path_dh = DATA_DIR / cfg["matriz_csv"].replace("matriz_", "destinos_")
            if _dest_path_dh.exists():
                try:
                    _df_dh_d = pd.read_csv(_dest_path_dh)
                    if "total" in _df_dh_d.columns:
                        destinos_total = int(pd.to_numeric(_df_dh_d["total"], errors="coerce").fillna(0).sum())
                        delta_md = destinos_total - total_all
                        pct_md = (delta_md / total_all * 100) if total_all else 0
                        if abs(pct_md) < 0.5:
                            st.metric("Matrix = Σ Destinations",
                                      f"✓ {fmt_tn(total_all)} kt",
                                      delta=f"Δ {fmt_tn(abs(delta_md))} kt ({pct_md:+.2f}%)" if delta_md else "exact",
                                      delta_color="off")
                        else:
                            st.metric("Matrix = Σ Destinations",
                                      f"⚠ {pct_md:+.2f}%",
                                      delta=f"Matrix {fmt_tn(total_all)} vs Dest {fmt_tn(destinos_total)}",
                                      delta_color="inverse")
                except Exception as _e:
                    st.caption(f"⚠ Couldn't read destinations: {_e}")
            else:
                st.caption("ℹ No destinations CSV.")

            # 2) Origins activity
            _orig_path_dh = DATA_DIR / cfg["matriz_csv"].replace("matriz_", "origenes_")
            if _orig_path_dh.exists():
                try:
                    _df_dh_o = pd.read_csv(_orig_path_dh)
                    st.metric("Active provinces (origin)", str(_df_dh_o["provincia"].nunique()))
                    if "localidad" in _df_dh_o.columns:
                        st.metric("Active localities (origin)", str(_df_dh_o["localidad"].nunique()))
                except Exception as _e:
                    st.caption(f"⚠ Couldn't read origins: {_e}")

            # 3) FS vs MINAGRI sanity (within ±15%)
            if magyp_total_kt is not None and total_all > 0:
                fs_kt = total_all / 1000
                delta_kt = fs_kt - magyp_total_kt
                pct_fm = (delta_kt / magyp_total_kt * 100) if magyp_total_kt else 0
                tol = 15
                if abs(pct_fm) <= tol:
                    st.metric(f"FS vs MAGYP (±{tol}%)",
                              f"✓ {pct_fm:+.1f}%",
                              delta=f"FS {fs_kt:,.0f} vs MAGYP {magyp_total_kt:,.0f} kt".replace(",", "."),
                              delta_color="off")
                else:
                    st.metric(f"FS vs MAGYP (±{tol}%)",
                              f"⚠ {pct_fm:+.1f}%",
                              delta=f"FS {fs_kt:,.0f} vs MAGYP {magyp_total_kt:,.0f} kt".replace(",", "."),
                              delta_color="inverse")

        st.caption(
            "💡 Pipeline runs daily at 10:00 + 17:00 (launchd). MAGYP only publishes weekly, "
            "so 6-8 days old is normal. SIO should refresh every business day. "
            "Matrix vs Destinations should match exactly (same delivery filter). "
            "FS vs MAGYP measures the same universe but FS is split per delivery group, "
            "so a small gap (<15%) is normal."
        )

    st.markdown(
        f"##### 📋 Commercial Position · {cfg['label']}"
        f" <span style='color:#888;font-size:0.8em;font-weight:normal'>"
        f"(rows = trade month · columns = delivery group · values in kt)</span>",
        unsafe_allow_html=True,
    )

    rows_tabla = []
    sub = {"Trade": ""}
    for g in GRUPOS:
        sub[g] = GRUPO_SUBTITULOS[g]
    sub["Total"] = ""; sub["% tot"] = ""
    rows_tabla.append(sub)

    def _add_data_row(row, label_override=None):
        rt = int(row["total"])
        entry = {"Trade": label_override if label_override else row["label"]}
        for g in GRUPOS:
            v = int(row[g])
            ct = totales_col.get(g, 1) or 1
            if view_mode == "Kilotonnes":
                entry[g] = fmt_tn(v)
            elif view_mode == "% of month":
                entry[g] = fmt_pct(v/rt*100) if rt and v else "—"
            elif view_mode == "% of group":
                entry[g] = fmt_pct(v/ct*100) if v else "—"
            else:
                entry[g] = fmt_pct(v/total_all*100) if total_all and v else "—"
        entry["Total"]  = fmt_tn(rt)
        entry["% tot"]  = fmt_pct(rt/total_all*100) if total_all else "—"
        rows_tabla.append(entry)

    # 1. Monthly rows (Mar-25 → Apr-26)
    for _, row in df_mens.iterrows():
        _add_data_row(row)

    # 2. "May-26" bold row: cumulative of May days published
    if len(df_dias_show) > 0:
        mayo_total_row = {"label": "May-26", "total": int(df_dias_show["total"].sum())}
        for g in GRUPOS:
            mayo_total_row[g] = int(df_dias_show[g].sum())
        _add_data_row(mayo_total_row)

    # 3. Daily rows (May only)
    for _, row in df_dias_show.iterrows():
        _add_data_row(row)

    if len(df_targets) > 0:
        sep = {"Trade": "── May · Projection ──"}
        for g in GRUPOS:
            sep[g] = ""
        sep["Total"] = ""; sep["% tot"] = ""
        rows_tabla.append(sep)
        for _, row in df_targets.iterrows():
            rt = int(row["total"])
            entry = {"Trade": row["label"]}
            for g in GRUPOS:
                entry[g] = fmt_tn(int(row[g]))
            entry["Total"] = fmt_tn(rt)
            entry["% tot"] = "— /day" if "ritmo" in row["label"] else fmt_pct(rt/exp*100)
            rows_tabla.append(entry)

    total_entry = {"Trade": "TOTAL"}
    for g in GRUPOS:
        total_entry[g] = fmt_tn(totales_col[g]) if view_mode == "Kilotonnes" else "—"
    total_entry["Total"]  = fmt_tn(total_all)
    total_entry["% tot"]  = fmt_pct(total_all/exp*100) + " exp"
    rows_tabla.append(total_entry)

    df_tabla = pd.DataFrame(rows_tabla).set_index("Trade")

    def style_matrix(row):
        idx = row.name
        if idx == "TOTAL":
            return ["font-weight:bold; background-color:rgba(0,0,0,0.06)"] * len(row)
        if idx == "May-26":
            return ["font-weight:bold; background-color:rgba(29,158,117,0.10)"] * len(row)
        if idx == "" or idx.startswith("──"):
            return ["color:gray; font-size:0.82em; font-style:italic; background-color:rgba(0,0,0,0.03)"] * len(row)
        match = df[df["label"].str.replace(" acum", "", regex=False) == idx.replace(" acum", "")]
        if not match.empty:
            r = match.iloc[0]
            if r.get("prior"):            return ["color:gray; font-style:italic"] * len(row)
            if r.get("low"):              return ["color:gray; font-size:0.85em"] * len(row)
            if r["tipo"] == "diario":     return ["background-color:rgba(55,138,221,0.07)"] * len(row)
            if r["tipo"] == "mayo_target":
                if "objetivo"  in idx:   return ["background-color:rgba(29,158,117,0.12); font-weight:500"] * len(row)
                if "falta"     in idx:   return ["background-color:rgba(226,75,74,0.10); color:#A32D2D"] * len(row)
                if "real"      in idx:   return ["background-color:rgba(55,138,221,0.10); color:#185FA5; font-style:italic"] * len(row)
                if "necesario" in idx:   return ["background-color:rgba(186,117,23,0.12); color:#633806; font-weight:500"] * len(row)
        return [""] * len(row)

    st.dataframe(
        df_tabla.style.apply(style_matrix, axis=1),
        use_container_width=True,
        height=min(55 + len(df_tabla)*35, 800),
    )

    # Restore unfiltered dataframes so other tabs see the full crop.
    df            = _orig_df
    df_mens       = _orig_df_mens
    df_dias       = _orig_df_dias
    df_dias_show  = _orig_df_dias_show
    df_targets    = _orig_df_targets
    _df_dias_mayo = _orig_df_dias_mayo
    total_all     = _orig_total_all
    totales_col   = _orig_totales_col


# ── TAB 2: GRÁFICOS ───────────────────────────────────────────────────────────



# ── TAB 2: GRÁFICOS ───────────────────────────────────────────────────────────

with tab2:

  # Old hardcoded corn-only charts: disabled (all crops use the unified
  # line + tower + sales/group format further down).
  if False:
    st.subheader("Proyección 26/27 vs MINAGRI real — acumulado por mes")
    st.caption(
        "**Línea azul**: proyección 26/27 acumulada. "
        "**Línea verde**: MINAGRI real 25/26 (PH+Fijado). "
        "**Curvas tenues**: mayos históricos (19/20 a 24/25). "
        "**Líneas punteadas**: techo exportaciones y producción."
    )

    _HIST_RAW_G5 = {
        "19/20": [5,36,210,541,281,543,769,77,117,159,314,1452,3096,3894,2827,4635,3771,2494,2511,2896,2902,3555,1247,1024,522],
        "20/21": [26,93,235,1969,853,605,348,1011,1868,2594,1520,884,898,2136,2123,2330,3254,3258,2904,2206,1831,1365,1878,1192,304],
        "21/22": [0,1,19,103,749,1999,788,1424,1116,564,657,2836,2871,2457,4008,3793,2224,2625,2720,2801,1961,1986,2266,808,602],
        "22/23": [25,35,920,676,563,456,517,769,875,1160,1234,718,1435,4951,3170,2613,2644,2638,3843,1788,1688,1809,2895,515,200],
        "23/24": [15,52,177,209,151,128,364,146,254,160,178,477,1186,1649,1138,1422,2001,4492,3849,1657,830,1200,1828,1660,937],
        "24/25": [0,8,3,75,99,300,329,236,305,164,464,946,1681,2990,2972,2938,3061,3727,3534,2407,2267,2672,2894,1943,806],
    }
    _CAMP_COLORES_G5 = {
        "19/20": "#A8C4E0", "20/21": "#A8D4BB", "21/22": "#F2B8A0",
        "22/23": "#E0C87A", "23/24": "#C4A8D4", "24/25": "#A8D4D0",
    }

    _MESES_G5 = [
        "PRIOR","Mar-25","Abr-25","May-25","Jun-25","Jul-25","Ago-25","Sep-25",
        "Oct-25","Nov-25","Dic-25","Ene-26","Feb-26","Mar-26","Abr-26","May-26",
        "Jun-26","Jul-26","Ago-26","Sep-26","Oct-26","Nov-26","Dic-26","Ene-27","Feb-27"
    ]
    _rows_hist_g5 = []
    for camp, vals in _HIST_RAW_G5.items():
        acum = 0
        for i, v in enumerate(vals):
            acum += v * 1000
            if i < len(_MESES_G5):
                _rows_hist_g5.append({"Mes": _MESES_G5[i], "tn": acum, "Serie": camp})
    _df_hist_g5 = pd.DataFrame(_rows_hist_g5)

    _CAMP_DOM = list(_CAMP_COLORES_G5.keys())
    _CAMP_RANGE = [_CAMP_COLORES_G5[c] for c in _CAMP_DOM]

    _lineas_hist_g5 = alt.Chart(_df_hist_g5).mark_line(opacity=0.4, strokeWidth=1.2).encode(
        x=alt.X("Mes:N", sort=_MESES_G5),
        y="tn:Q",
        color=alt.Color("Serie:N",
                        scale=alt.Scale(domain=_CAMP_DOM, range=_CAMP_RANGE),
                        legend=alt.Legend(title="Histórico", orient="bottom", columns=6)),
        tooltip=["Serie","Mes", alt.Tooltip("tn:Q", format=",.0f")]
    )

    DATA_2627 = [
        {"mes":"PRIOR",  "proy":0,        "min":None},
        {"mes":"Mar-25", "proy":0,        "min":None},
        {"mes":"Abr-25", "proy":23000,    "min":None},
        {"mes":"May-25", "proy":33000,    "min":None},
        {"mes":"Jun-25", "proy":51000,    "min":None},
        {"mes":"Jul-25", "proy":76000,    "min":None},
        {"mes":"Ago-25", "proy":290000,   "min":491300},
        {"mes":"Sep-25", "proy":751000,   "min":696400},
        {"mes":"Oct-25", "proy":1206000,  "min":1524700},
        {"mes":"Nov-25", "proy":2469000,  "min":3271700},
        {"mes":"Dic-25", "proy":4043000,  "min":5099900},
        {"mes":"Ene-26", "proy":6623000,  "min":8322800},
        {"mes":"Feb-26", "proy":9107000,  "min":10251900},
        {"mes":"Mar-26", "proy":12922000, "min":11513200},
        {"mes":"Abr-26", "proy":16495000, "min":17588200},
        {"mes":"May-26", "proy":19321000, "min":17910600},
        {"mes":"Jun-26", "proy":22303000, "min":None},
        {"mes":"Jul-26", "proy":26198000, "min":None},
        {"mes":"Ago-26", "proy":29230000, "min":None},
        {"mes":"Sep-26", "proy":31323000, "min":None},
        {"mes":"Oct-26", "proy":32924000, "min":None},
        {"mes":"Nov-26", "proy":34664000, "min":None},
        {"mes":"Dic-26", "proy":36877000, "min":None},
        {"mes":"Ene-27", "proy":39048000, "min":None},
        {"mes":"Feb-27", "proy":40862000, "min":None},
    ]

    sort_meses_g5 = [d["mes"] for d in DATA_2627]
    rows_g5 = []
    for d in DATA_2627:
        if not MODO_PUBLICO:
            rows_g5.append({"Mes": d["mes"], "tn": d["proy"], "Serie": "Proyección propia"})
        if d["min"] is not None:
            rows_g5.append({"Mes": d["mes"], "tn": d["min"], "Serie": "MINAGRI real"})
        rows_g5.append({"Mes": d["mes"], "tn": round(exp),  "Serie": "Exportaciones"})
        rows_g5.append({"Mes": d["mes"], "tn": round(prod), "Serie": "Producción"})

    df_g5 = pd.DataFrame(rows_g5)

    if MODO_PUBLICO:
        _series_g5 = ["MINAGRI real", "Exportaciones", "Producción"]
        color_g5 = alt.Scale(domain=_series_g5, range=["#1D9E75", "#E24B4A", "#BA7517"])
        dash_g5  = alt.Scale(domain=_series_g5, range=[[0], [6,3], [6,3]])
        width_g5 = alt.Scale(domain=_series_g5, range=[2.5, 1.5, 1.5])
    else:
        _series_g5 = ["Proyección propia", "MINAGRI real", "Exportaciones", "Producción"]
        color_g5 = alt.Scale(domain=_series_g5, range=["#185FA5", "#1D9E75", "#E24B4A", "#BA7517"])
        dash_g5  = alt.Scale(domain=_series_g5, range=[[0], [0], [6,3], [6,3]])
        width_g5 = alt.Scale(domain=_series_g5, range=[2, 2.5, 1.5, 1.5])

    lineas_g5 = alt.Chart(df_g5).mark_line(point=False).encode(
        x=alt.X("Mes:N", sort=sort_meses_g5, title="Mes de concertación"),
        y=alt.Y("tn:Q", title="Toneladas acumuladas",
                axis=alt.Axis(format=",.0f"),
                scale=alt.Scale(domain=[0, 65000000])),
        color=alt.Color("Serie:N", scale=color_g5,
                       legend=alt.Legend(title="", orient="bottom", columns=4)),
        strokeDash=alt.StrokeDash("Serie:N", scale=dash_g5),
        strokeWidth=alt.StrokeWidth("Serie:N", scale=width_g5),
        tooltip=["Mes","Serie", alt.Tooltip("tn:Q", format=",.0f", title="Toneladas")]
    )

    df_puntos_g5 = df_g5[df_g5["Serie"].isin(_series_g5[:2] if not MODO_PUBLICO else ["MINAGRI real"])].copy()
    puntos_g5 = alt.Chart(df_puntos_g5).mark_point(filled=True, size=50).encode(
        x=alt.X("Mes:N", sort=sort_meses_g5),
        y="tn:Q",
        color=alt.Color("Serie:N", scale=color_g5, legend=None),
        tooltip=["Mes","Serie", alt.Tooltip("tn:Q", format=",.0f", title="Toneladas")]
    )

    df_proy_only = pd.DataFrame([{"Mes": d["mes"], "proy": d["proy"], "min": d["min"]}
                                  for d in DATA_2627 if d["min"] is not None])
    df_proy_only["diferencia"] = df_proy_only["min"] - df_proy_only["proy"]

    chart_g5 = (_lineas_hist_g5 + lineas_g5 + puntos_g5).properties(height=420).configure_axis(
        labelFontSize=10, titleFontSize=11, labelAngle=-45
    ).configure_legend(labelFontSize=11)
    st.altair_chart(chart_g5, use_container_width=True)

    if not MODO_PUBLICO and len(df_proy_only) > 0:
        st.markdown("**Diferencia real vs proyección (donde hay datos MINAGRI):**")
        df_diff_show = df_proy_only.copy()
        df_diff_show["Proyección"] = df_diff_show["proy"].apply(lambda x: f"{int(x):,}".replace(",", "."))
        df_diff_show["MINAGRI real"] = df_diff_show["min"].apply(lambda x: f"{int(x):,}".replace(",", "."))
        df_diff_show["Diferencia"] = df_diff_show["diferencia"].apply(
            lambda x: ("+" if x >= 0 else "") + f"{int(x):,}".replace(",", ".")
        )
        df_diff_show["Diferencia %"] = (df_diff_show["diferencia"]/df_diff_show["proy"]*100).apply(
            lambda x: f"{x:+.1f}%"
        )
        st.dataframe(
            df_diff_show[["Mes", "Proyección", "MINAGRI real", "Diferencia", "Diferencia %"]],
            use_container_width=True, hide_index=True
        )

    _MAYO_HIST = {
        "19/20": 4635000, "20/21": 2330000, "21/22": 3793000,
        "22/23": 2613000, "23/24": 1422000, "24/25": 2938000,
    }
    _MAYO_HIST_COLORES = {
        "19/20": "#A8C4E0", "20/21": "#A8D4BB", "21/22": "#F2B8A0",
        "22/23": "#E0C87A", "23/24": "#C4A8D4", "24/25": "#A8D4D0",
    }
    _rows_mayo_hist = []
    for _camp_h, _total_h in _MAYO_HIST.items():
        _ritmo_h = _total_h / 19
        for _i_h, _dia_h in enumerate(DIAS_HABILES_MAYO):
            _rows_mayo_hist.append({
                "Día": _dia_h, "tn": round(_ritmo_h * (_i_h + 1)), "Serie": _camp_h
            })
    _df_mayo_hist = pd.DataFrame(_rows_mayo_hist)
    _dom_h = list(_MAYO_HIST_COLORES.keys())
    _rng_h = [_MAYO_HIST_COLORES[c] for c in _dom_h]

    if cultivo_slug == "maiz" and not MODO_PUBLICO and len(df_dias) > 0:
        st.subheader("Mayo 2026 — real vs proyectado (acumulado)")
        st.caption(
            "**Proyectado** (verde): 148.737 tn/día hábil — llega exacto a 2.826.000 tn el 29/05. "
            "**Real** (azul): acumulado real. "
            "**Al ritmo actual** (naranja punteado): si seguimos al ritmo de los días disponibles. "
            "**Línea roja**: objetivo 2.826.000 tn."
        )

        dia_to_idx = {l: i for i, l in enumerate(DIAS_HABILES_MAYO)}
        real_vals  = [None] * 19
        acum = 0
        for _, dr in df_dias.iterrows():
            acum += int(dr["total"])
            lbl = dr["label"]
            if lbl in dia_to_idx:
                real_vals[dia_to_idx[lbl]] = acum

        proyectado = [min(RITMO_NECESARIO*(i+1), OBJETIVO_MAYO) for i in range(19)]

        idxs_con_dato = [i for i, v in enumerate(real_vals) if v is not None]
        ritmo_act = [None] * 19
        if idxs_con_dato:
            ultimo_idx = max(idxs_con_dato)
            ultimo_val = real_vals[ultimo_idx]
            ritmo_calc = ultimo_val / (ultimo_idx + 1)
            for i in range(ultimo_idx, 19):
                ritmo_act[i] = round(min(ultimo_val + ritmo_calc*(i-ultimo_idx), OBJETIVO_MAYO*1.2))

        rows5 = []
        for i, lbl in enumerate(DIAS_HABILES_MAYO):
            rows5.append({"Día": lbl, "tn": round(proyectado[i]), "Serie": "Proyectado (objetivo)"})
            if real_vals[i] is not None:
                rows5.append({"Día": lbl, "tn": round(real_vals[i]), "Serie": "Real"})
            if ritmo_act[i] is not None:
                rows5.append({"Día": lbl, "tn": round(ritmo_act[i]), "Serie": "Al ritmo actual"})

        df5 = pd.DataFrame(rows5)

        color_scale = alt.Scale(
            domain=["Proyectado (objetivo)", "Real", "Al ritmo actual"],
            range=["#1D9E75", "#185FA5", "#BA7517"]
        )
        dash_scale = alt.Scale(
            domain=["Proyectado (objetivo)", "Real", "Al ritmo actual"],
            range=[[0], [0], [6,3]]
        )
        size_scale = alt.Scale(
            domain=["Proyectado (objetivo)", "Real", "Al ritmo actual"],
            range=[2, 3, 2]
        )

        lineas = alt.Chart(df5).mark_line(point=True).encode(
            x=alt.X("Día:N", sort=DIAS_HABILES_MAYO, title="Día hábil mayo"),
            y=alt.Y("tn:Q", title="Toneladas acumuladas",
                    scale=alt.Scale(domain=[0, round(OBJETIVO_MAYO*1.08)])),
            color=alt.Color("Serie:N", scale=color_scale,
                           legend=alt.Legend(title="", orient="bottom", columns=3)),
            strokeDash=alt.StrokeDash("Serie:N", scale=dash_scale),
            strokeWidth=alt.StrokeWidth("Serie:N", scale=size_scale),
            tooltip=["Día","Serie", alt.Tooltip("tn:Q", format=",.0f", title="Toneladas")]
        )

        df_obj_line = pd.DataFrame([
            {"Día": DIAS_HABILES_MAYO[0],  "obj": OBJETIVO_MAYO},
            {"Día": DIAS_HABILES_MAYO[-1], "obj": OBJETIVO_MAYO},
        ])
        linea_obj = alt.Chart(df_obj_line).mark_line(
            color="#E24B4A", strokeDash=[4, 2], strokeWidth=1.5
        ).encode(
            x=alt.X("Día:N", sort=DIAS_HABILES_MAYO),
            y=alt.Y("obj:Q", title="Toneladas"),
        )
        texto_obj = alt.Chart(pd.DataFrame([{
            "Día": DIAS_HABILES_MAYO[-1],
            "obj": round(OBJETIVO_MAYO/1e6, 2),
            "t": f"Obj: {OBJETIVO_MAYO:,.0f} tn"
        }])).mark_text(align="right", dx=-4, dy=-10, fontSize=11, color="#E24B4A").encode(
            x=alt.X("Día:N", sort=DIAS_HABILES_MAYO),
            y="obj:Q", text="t:N"
        )

        _lineas_mayo_hist = alt.Chart(_df_mayo_hist).mark_line(
            opacity=0.35, strokeWidth=1.2, strokeDash=[4, 2]
        ).encode(
            x=alt.X("Día:N", sort=DIAS_HABILES_MAYO),
            y=alt.Y("tn:Q", scale=alt.Scale(domain=[0, round(OBJETIVO_MAYO*1.08)])),
            color=alt.Color("Serie:N",
                scale=alt.Scale(domain=_dom_h, range=_rng_h),
                legend=alt.Legend(title="Histórico mayo", orient="bottom", columns=6)
            ),
            tooltip=["Serie","Día", alt.Tooltip("tn:Q", format=",.0f")]
        )
        chart1 = (_lineas_mayo_hist + lineas + linea_obj + texto_obj).properties(height=380).configure_axis(
            labelFontSize=11, titleFontSize=12
        ).configure_legend(labelFontSize=11)
        st.altair_chart(chart1, use_container_width=True)

        if idxs_con_dato:
            ultimo_val_real = real_vals[max(idxs_con_dato)]
            ritmo_real_diario = ultimo_val_real / (max(idxs_con_dato)+1)
            llegamos = ritmo_real_diario * 19
            mc1, mc2, mc3 = st.columns(3)
            mc1.metric("Real acumulado", f"{ultimo_val_real:,.0f} tn".replace(",", "."))
            mc2.metric("Ritmo real/día hábil", f"{ritmo_real_diario:,.0f} tn".replace(",", "."),
                       delta=f"{ritmo_real_diario-RITMO_NECESARIO:+,.0f} tn vs necesario".replace(",", "."),
                       delta_color="normal")
            mc3.metric("Si seguimos igual", f"{llegamos:,.0f} tn".replace(",", "."),
                       delta=f"{llegamos-OBJETIVO_MAYO:+,.0f} tn vs objetivo".replace(",", "."),
                       delta_color="normal")

        st.divider()

  # ── End of corn-specific charts ──────────────────────────────────────────

  # ── MINAGRI evolution + last cut tower ───────────────────────────────────
  import json as _json
  from cultivos import minagri_json_path
  _minagri_path = Path(minagri_json_path(cfg))
  if _minagri_path.exists():
      _serie_raw = _json.loads(_minagri_path.read_text(encoding="utf-8")).get("serie", [])
  else:
      _serie_raw = []

  if _serie_raw:
      st.subheader(f"📈 MINAGRI · {cfg['label']} {cfg.get('cosecha_label', cfg['cosecha'])}")
      st.caption("Above: weekly cumulative evolution. Below: monthly increment broken down by PH and Pricing.")

      df_minagri = pd.DataFrame(_serie_raw)
      df_minagri["fecha"] = pd.to_datetime(df_minagri["fecha"])
      df_minagri = df_minagri.sort_values("fecha").reset_index(drop=True)

      # Filter "contaminated" points: when MAGYP re-classifies the harvest
      # between weeks, the cumulative can drop sharply. Discard points where
      # the drop is >20% of the previous value — those are crop-transition
      # artifacts.
      _vals = df_minagri["ph_fijado_acum_kt"].astype(float).values
      _keep = [True] * len(_vals)
      for _i in range(1, len(_vals)):
          if _vals[_i] < _vals[_i-1] * 0.8 and _vals[_i-1] > 100:
              _keep[_i] = False
      _filtered = sum(1 for k in _keep if not k)
      if _filtered > 0:
          df_minagri = df_minagri[_keep].reset_index(drop=True)
          st.info(f"⚠ {_filtered} MAGYP point(s) filtered: sharp cumulative drop, "
                  f"likely a crop re-classification in MAGYP.")

      # Cumulative line
      line_chart = alt.Chart(df_minagri).mark_line(
          point=True, strokeWidth=2.5, color="#1D9E75"
      ).encode(
          x=alt.X("fecha:T", title="Week", axis=alt.Axis(format="%d %b %y")),
          y=alt.Y("ph_fijado_acum_kt:Q", title="PH + Pricing cumulative (kt)",
                  axis=alt.Axis(format=",.0f")),
          tooltip=[alt.Tooltip("fecha:T", title="Date", format="%d/%m/%Y"),
                   alt.Tooltip("ph_fijado_acum_kt:Q", title="Total kt", format=",.1f"),
                   alt.Tooltip("ph_acum_kt:Q", title="PH kt", format=",.1f"),
                   alt.Tooltip("fij_acum_kt:Q", title="Pricing kt", format=",.1f")],
      ).properties(height=280).configure_axis(labelFontSize=11, titleFontSize=12)
      st.altair_chart(line_chart, use_container_width=True)

      # Stacked tower below: monthly delta of PH + Pricing
      _MES_ES = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
      tiene_desglose = ("ph_acum_kt" in df_minagri.columns and
                        "fij_acum_kt" in df_minagri.columns and
                        df_minagri["ph_acum_kt"].fillna(0).abs().sum() > 0)

      df_minagri["año_mes"] = df_minagri["fecha"].dt.to_period("M").astype(str)
      cierre_mes = df_minagri.groupby("año_mes").last().reset_index()

      def _label_ym(s):
          y, m = s.split("-")
          return f"{_MES_ES[int(m)-1]}-{y[-2:]}"
      cierre_mes["mes"] = cierre_mes["año_mes"].apply(_label_ym)

      if tiene_desglose:
          # Monthly delta of PH and Pricing separately
          cierre_mes["ph_acum_kt"]  = pd.to_numeric(cierre_mes["ph_acum_kt"], errors="coerce").fillna(0)
          cierre_mes["fij_acum_kt"] = pd.to_numeric(cierre_mes["fij_acum_kt"], errors="coerce").fillna(0)
          cierre_mes["ph_delta"]  = cierre_mes["ph_acum_kt"].diff().fillna(cierre_mes["ph_acum_kt"].iloc[0])
          cierre_mes["fij_delta"] = cierre_mes["fij_acum_kt"].diff().fillna(cierre_mes["fij_acum_kt"].iloc[0])
          rows_torre = []
          for _, r in cierre_mes.iterrows():
              rows_torre.append({"mes": r["mes"], "componente": "PH",      "kt": float(r["ph_delta"]),  "orden": 1})
              rows_torre.append({"mes": r["mes"], "componente": "Pricing", "kt": float(r["fij_delta"]), "orden": 2})
      else:
          # Fallback: only total delta (JSONs without breakdown)
          cierre_mes["total"] = pd.to_numeric(cierre_mes["ph_fijado_acum_kt"], errors="coerce").fillna(0)
          cierre_mes["delta"] = cierre_mes["total"].diff().fillna(cierre_mes["total"].iloc[0])
          rows_torre = [{"mes": r["mes"], "componente": "PH+Pricing", "kt": float(r["delta"]), "orden": 1}
                        for _, r in cierre_mes.iterrows()]
          st.warning("The JSONs don't have PH and Pricing separately yet. "
                     "Run `make backfill-minagri` to see the breakdown.")

      df_torre = pd.DataFrame(rows_torre)
      orden_meses = list(cierre_mes["mes"])
      _domain = ["PH", "Pricing"] if tiene_desglose else ["PH+Pricing"]
      _range  = ["#1D9E75", "#185FA5"] if tiene_desglose else ["#1D9E75"]
      torre = alt.Chart(df_torre).mark_bar().encode(
          x=alt.X("mes:N", sort=orden_meses, title="Month"),
          y=alt.Y("kt:Q", title="Δ kt in the month", axis=alt.Axis(format=",.0f"), stack="zero"),
          color=alt.Color("componente:N",
              scale=alt.Scale(domain=_domain, range=_range),
              legend=alt.Legend(title=None, orient="bottom")),
          order=alt.Order("orden:Q"),
          tooltip=["mes", "componente", alt.Tooltip("kt:Q", format=",.1f")],
      ).properties(height=280).configure_axis(labelFontSize=11, titleFontSize=12)
      st.altair_chart(torre, use_container_width=True)

      ultimo = df_minagri.iloc[-1]
      tot_kt = float(ultimo["ph_fijado_acum_kt"])
      if tiene_desglose:
          ph_kt  = float(ultimo.get("ph_acum_kt", 0) or 0)
          fij_kt = float(ultimo.get("fij_acum_kt", 0) or 0)
          st.caption(f"💡 Last cut {ultimo['fecha'].strftime('%d/%m/%Y')}: "
                     f"**PH {ph_kt:,.1f}** + **Pricing {fij_kt:,.1f}** = **{tot_kt:,.1f} kt** cumulative.".replace(",", "."))
      else:
          st.caption(f"💡 Last cut {ultimo['fecha'].strftime('%d/%m/%Y')}: "
                     f"**{tot_kt:,.1f} kt** cumulative.".replace(",", "."))

      st.divider()

  # ── PH by trade month (stacked by delivery group) ────────────────────────
  st.subheader("PH by trade month — broken down by delivery group")
  stacked_rows = []
  for _, row in df_mens.iterrows():
      for g in GRUPOS:
          stacked_rows.append({
              "Month": row["label"],
              "Group": f"{g} ({GRUPO_SUBTITULOS[g]})",
              "Group_key": g,
              "kt": int(row[g]) / 1000,
          })
  df_stacked = pd.DataFrame(stacked_rows)
  chart4 = alt.Chart(df_stacked).mark_bar().encode(
      x=alt.X("Month:N", sort=list(df_mens["label"]), title="Trade month"),
      y=alt.Y("kt:Q", title="Kilotonnes", axis=alt.Axis(format=",.0f")),
      color=alt.Color("Group:N",
          scale=alt.Scale(domain=[f"{g} ({GRUPO_SUBTITULOS[g]})" for g in GRUPOS], range=GRUPO_COLORES),
          legend=alt.Legend(title="Delivery group", orient="bottom")),
      order=alt.Order("Group_key:N"),
      tooltip=["Month","Group", alt.Tooltip("kt:Q", format=",.0f", title="kt")]
  ).properties(height=360).configure_axis(labelFontSize=12, titleFontSize=12).configure_legend(labelFontSize=11)
  st.altair_chart(chart4, use_container_width=True)

  st.divider()

  # ── Cumulative sales by delivery group ────────────────────────────────────
  st.subheader("Cumulative sales by delivery group (kt)")
  df_delivery = pd.DataFrame([{
      "Group": f"{g}\n({GRUPO_SUBTITULOS[g]})",
      "Group_key": g,
      "kt": round(totales_col[g] / 1000),
      "% exp": round(totales_col[g]/exp*100, 1) if exp > 0 else 0,
  } for g in GRUPOS])

  bars3 = alt.Chart(df_delivery).mark_bar().encode(
      x=alt.X("Group:N", sort=[f"{g}\n({GRUPO_SUBTITULOS[g]})" for g in GRUPOS], title="Delivery group"),
      y=alt.Y("kt:Q", title="Kilotonnes", axis=alt.Axis(format=",.0f")),
      color=alt.Color("Group:N",
          scale=alt.Scale(domain=[f"{g}\n({GRUPO_SUBTITULOS[g]})" for g in GRUPOS], range=GRUPO_COLORES),
          legend=None),
      tooltip=["Group", alt.Tooltip("kt:Q", format=",.0f"), "% exp"]
  )
  text3 = bars3.mark_text(dy=-10, fontSize=11).encode(text=alt.Text("kt:Q", format=",.0f"))
  chart3 = (bars3 + text3).properties(height=340).configure_axis(labelFontSize=12, titleFontSize=12)
  st.altair_chart(chart3, use_container_width=True)

  st.divider()

  # ── May day-by-day chart by group (all crops with daily_mes) ──────────────
  if len(df_dias) > 0:
      st.subheader(f"May 2026 — daily trades · {cfg['label']}")
      # May days only in this chart
      df_dias_habiles = df_dias[(~df_dias["low"]) & df_dias["label"].str.endswith("/05")].copy()
      mayo_rows = []
      for _, row in df_dias_habiles.iterrows():
          for g in GRUPOS:
              mayo_rows.append({
                  "Day":       row["label"],
                  "Group":     f"{g} ({GRUPO_SUBTITULOS[g]})",
                  "Group_key": g,
                  "kt":        round(int(row[g]) / 1000, 1),
              })
      df_mayo = pd.DataFrame(mayo_rows)
      chart_mayo = alt.Chart(df_mayo).mark_bar().encode(
          x=alt.X("Day:N", sort=list(df_dias_habiles["label"]), title="Business day"),
          y=alt.Y("kt:Q", title="Kilotonnes", axis=alt.Axis(format=",.1f")),
          color=alt.Color("Group:N",
              scale=alt.Scale(domain=[f"{g} ({GRUPO_SUBTITULOS[g]})" for g in GRUPOS], range=GRUPO_COLORES),
              legend=alt.Legend(title="Delivery group", orient="bottom")),
          order=alt.Order("Group_key:N"),
          tooltip=["Day","Group", alt.Tooltip("kt:Q", format=",.1f")]
      ).properties(height=300).configure_axis(labelFontSize=12, titleFontSize=12).configure_legend(labelFontSize=11)
      st.altair_chart(chart_mayo, use_container_width=True)


# ── TAB 3: DESTINATIONS ──────────────────────────────────────────────────────

with tab3:
    from destinos import DESTINOS, DESTINOS_LABEL, DESTINOS_COLOR

    _dest_path = DATA_DIR / cfg["matriz_csv"].replace("matriz_", "destinos_")
    if not _dest_path.exists():
        st.warning(f"📂 Can't find `{_dest_path.name}`. Run `make backfill-matrices` to generate it.")
    else:
        df_dest = pd.read_csv(_dest_path)
        for d in DESTINOS:
            df_dest[d] = pd.to_numeric(df_dest[d], errors="coerce").fillna(0).astype(int)
        df_dest["total"] = pd.to_numeric(df_dest["total"], errors="coerce").fillna(0).astype(int)

        # ── Metrics: cumulative total per destination ────────────────────
        st.subheader(f"🚢 Destinations · {cfg['label']} {cfg.get('cosecha_label', cfg['cosecha'])}")
        st.caption("Categorization of the SIO CSV's LUGAR ENTREGA field. "
                   "Bs As and SIO Zonas 1-26 are grouped as 'Interior'.")

        # ── Annex: how each destination is assigned ──────────────────────
        with st.expander("ℹ How is each destination assigned?", expanded=False):
            st.markdown(
                "Each operation has a **LUGAR ENTREGA** field in the SIO CSV "
                "(examples: *Rosario S/En destino*, *B.Blanca/En origen*, "
                "*Quequén/En destino*, *Zona 13*, *Bs As Norte*, etc.). "
                "We categorize it into one of 4 destinations based on keywords in that field. "
                "The \"/En destino\" or \"/En origen\" suffix only indicates who pays the freight, "
                "not the physical location — we ignore it when categorizing."
            )
            st.markdown(
                f"""
                | Destination | Keywords in LUGAR ENTREGA | What it includes |
                |---|---|---|
                | <span style='color:{DESTINOS_COLOR["uprivers"]};'>● **Up River**</span> | contains `rosario` | Paraná river ports: Rosario N, Rosario S, San Lorenzo, San Martín, Timbúes, etc. |
                | <span style='color:{DESTINOS_COLOR["bahia"]};'>● **Bahía Blanca**</span> | `b.blanca`, `bahia blanca`, `bahía blanca`, `ing. white` | Bahía Blanca port + Ing. White |
                | <span style='color:{DESTINOS_COLOR["necochea"]};'>● **Necochea**</span> | `quequen`, `quequén`, `necochea` | Quequén / Necochea port |
                | <span style='color:{DESTINOS_COLOR["interior"]};'>● **Interior**</span> | the rest | Bs As Norte/Sur, Córdoba, all SIO Zonas 1-26, internal plants, etc. |
                """,
                unsafe_allow_html=True,
            )
            st.caption(
                "Up River, Bahía Blanca and Necochea are export destinations (ports). "
                "Interior groups what stays in-country (domestic consumption, plants, "
                "feedlots, regional origination)."
            )

        totales = {d: int(df_dest[d].sum()) for d in DESTINOS}
        total_global = sum(totales.values()) or 1
        cols = st.columns(len(DESTINOS))
        for col, d in zip(cols, DESTINOS):
            pct = totales[d] / total_global * 100
            col.metric(DESTINOS_LABEL[d], fmt_tn(totales[d]) + " kt", delta=f"{pct:.1f}%", delta_color="off")

        st.divider()

        # ── Donut: % per destination ─────────────────────────────────────
        df_pie = pd.DataFrame([{"Destination": DESTINOS_LABEL[d],
                                "kt": round(totales[d]/1000)} for d in DESTINOS])
        donut = alt.Chart(df_pie).mark_arc(innerRadius=70).encode(
            theta=alt.Theta("kt:Q", stack=True),
            color=alt.Color("Destination:N",
                scale=alt.Scale(domain=[DESTINOS_LABEL[d] for d in DESTINOS],
                                range=[DESTINOS_COLOR[d] for d in DESTINOS]),
                legend=alt.Legend(title=None, orient="right")),
            tooltip=["Destination", alt.Tooltip("kt:Q", format=",.0f")],
        ).properties(height=300, title="Total split by destination")
        st.altair_chart(donut, use_container_width=True)

        st.divider()

        # ── Monthly stacked: kt per destination per month ────────────────
        st.subheader("Monthly evolution by destination")
        rows_stack = []
        for _, r in df_dest.iterrows():
            for d in DESTINOS:
                rows_stack.append({"Month": r["label"], "Destination": DESTINOS_LABEL[d],
                                   "kt": round(int(r[d])/1000)})
        df_stack = pd.DataFrame(rows_stack)
        chart_dest = alt.Chart(df_stack).mark_bar().encode(
            x=alt.X("Month:N", sort=list(df_dest["label"]), title="Trade month"),
            y=alt.Y("kt:Q", title="Kilotonnes", axis=alt.Axis(format=",.0f")),
            color=alt.Color("Destination:N",
                scale=alt.Scale(domain=[DESTINOS_LABEL[d] for d in DESTINOS],
                                range=[DESTINOS_COLOR[d] for d in DESTINOS]),
                legend=alt.Legend(title=None, orient="bottom")),
            tooltip=["Month", "Destination", alt.Tooltip("kt:Q", format=",.0f")],
        ).properties(height=380).configure_axis(labelFontSize=12, titleFontSize=12).configure_legend(labelFontSize=11)
        st.altair_chart(chart_dest, use_container_width=True)

        st.divider()

        # ── Detail table ─────────────────────────────────────────────────
        st.subheader("Monthly detail")
        df_show = df_dest.rename(columns={"label": "Month",
                                          **{d: DESTINOS_LABEL[d] for d in DESTINOS},
                                          "total": "Total"})
        for c in [DESTINOS_LABEL[d] for d in DESTINOS] + ["Total"]:
            df_show[c] = df_show[c].apply(lambda v: f"{int(v):,}".replace(",", "."))
        st.dataframe(df_show, use_container_width=True, hide_index=True,
                     height=min(55 + len(df_show)*35, 600))


# ── TAB 4: ORIGIN MAP ────────────────────────────────────────────────────────

with tab4:
    from provincias import a_iso, ISO_A_LABEL
    from datetime import date as _date, timedelta as _timedelta

    st.subheader(f"🗺️ Geographic origin · {cfg['label']} {cfg.get('cosecha_label', cfg['cosecha'])}")

    _orig_path = DATA_DIR / cfg["matriz_csv"].replace("matriz_", "origenes_")
    if not _orig_path.exists():
        st.warning(f"📂 Can't find `{_orig_path.name}`. Run `make backfill-matrices`.")
    else:
        df_orig = pd.read_csv(_orig_path)
        df_orig["fecha"] = pd.to_datetime(df_orig["fecha"])
        df_orig["tn"] = pd.to_numeric(df_orig["tn"], errors="coerce").fillna(0).astype(int)

        c_dias, c_info = st.columns([1, 3])
        with c_dias:
            dias_atras = st.number_input(
                "Days back",
                min_value=1, max_value=730, value=30, step=5,
                key=f"dias_atras_{cultivo_slug}",
            )
        hoy_d = _date.today()
        desde = hoy_d - _timedelta(days=int(dias_atras))
        with c_info:
            st.caption(f"Showing trades from **{desde.strftime('%d/%m/%Y')}** "
                       f"to **{hoy_d.strftime('%d/%m/%Y')}** ({dias_atras} days).")

        df_filt = df_orig[df_orig["fecha"].dt.date >= desde].copy()
        # localidad may not exist if the CSV is old
        if "localidad" not in df_filt.columns:
            df_filt["localidad"] = "(no data)"

        df_filt["iso"] = df_filt["provincia"].apply(a_iso)
        sin_iso = df_filt[df_filt["iso"].isna()]["provincia"].unique()
        df_filt_iso = df_filt.dropna(subset=["iso"])

        agg = df_filt_iso.groupby("iso", as_index=False)["tn"].sum()
        agg["Provincia"] = agg["iso"].map(ISO_A_LABEL)
        agg = agg.sort_values("tn", ascending=False)

        if len(agg) == 0:
            st.info("No trades in that range.")
        else:
            tot = int(agg["tn"].sum())
            cm1, cm2, cm3 = st.columns(3)
            cm1.metric("Total kt (origin)", fmt_tn(tot))
            cm2.metric("Active provinces", str(len(agg)))
            cm3.metric("Top province", agg.iloc[0]["Provincia"],
                       help=f"{fmt_tn(int(agg.iloc[0]['tn']))} kt")

            # ── Map with locality bubbles (provinces in background) ──────
            geo_path = DATA_DIR / "argentina_provincias.geojson"
            loc_path = DATA_DIR / "localidades_ar.csv"

            if not loc_path.exists():
                st.info("📂 Missing the locality coordinates dataset. Download it with:\n\n"
                        f"```bash\ncurl -L -o {loc_path} \\\n"
                        "  \"https://apis.datos.gob.ar/georef/api/localidades?max=5000&campos=nombre,provincia.nombre,centroide.lat,centroide.lon&formato=csv\"\n```")
            else:
                import unicodedata as _u

                def _norm(s):
                    s = _u.normalize("NFD", str(s).upper().strip())
                    return "".join(c for c in s if _u.category(c) != "Mn")

                # Province GeoJSON (optional — if it fails, we show bubbles only)
                geo_data = None
                geo_error = None
                if geo_path.exists():
                    try:
                        import json as _gj
                        txt = geo_path.read_text(encoding="utf-8").lstrip("﻿").strip()
                        if not txt.startswith(("{", "[")):
                            raise ValueError(f"file doesn't look like JSON (starts with: {txt[:30]!r})")
                        geo_data = _gj.loads(txt)
                    except Exception as e:
                        geo_error = f"{type(e).__name__}: {e}"

                try:
                    def _cargar_geo_csv(path: Path) -> pd.DataFrame | None:
                        if not path.exists():
                            return None
                        df = pd.read_csv(path)
                        cols_lower = {c.lower(): c for c in df.columns}

                        def _find(*candidatos):
                            for cand in candidatos:
                                if cand in cols_lower:
                                    return cols_lower[cand]
                            for cand in candidatos:
                                for k, v in cols_lower.items():
                                    if cand in k:
                                        return v
                            return None

                        c_lat  = _find("localidad_centroide_lat", "departamento_centroide_lat",
                                       "centroide_lat", "centroide.lat", "lat")
                        c_lon  = _find("localidad_centroide_lon", "departamento_centroide_lon",
                                       "centroide_lon", "centroide.lon", "lon", "lng")
                        c_pcia = _find("provincia_nombre", "provincia.nombre", "provincia")
                        c_nom  = _find("localidad_nombre", "departamento_nombre", "nombre")
                        if not all([c_lat, c_lon, c_pcia, c_nom]):
                            raise ValueError(
                                f"Missing required columns in {path.name}. "
                                f"Columns present: {list(df.columns)}"
                            )
                        df = df[[c_nom, c_pcia, c_lat, c_lon]].dropna()
                        df.columns = ["nombre", "pcia_nombre", "lat", "lon"]
                        df["nom_norm"]  = df["nombre"].apply(_norm)
                        df["pcia_norm"] = df["pcia_nombre"].apply(_norm)
                        return df

                    df_loc_geo = _cargar_geo_csv(loc_path)
                    df_dep_geo = _cargar_geo_csv(DATA_DIR / "departamentos_ar.csv")

                    # Combine: localities first, departments as fallback
                    fuentes = []
                    if df_loc_geo is not None:
                        fuentes.append(df_loc_geo.assign(_origen="localidad"))
                    if df_dep_geo is not None:
                        fuentes.append(df_dep_geo.assign(_origen="depto"))
                    if not fuentes:
                        raise ValueError("No geographic source available.")
                    df_geo = pd.concat(fuentes, ignore_index=True)
                    # If an entry exists as both locality and department, prefer locality
                    df_geo = df_geo.drop_duplicates(subset=["nom_norm", "pcia_norm"], keep="first")
                    df_loc = df_geo.rename(columns={"nombre": "loc_nombre", "nom_norm": "loc_norm"})

                    # Aggregate df_filt by (province, locality), convert to kt
                    df_loc_agg = df_filt.groupby(["provincia", "localidad"], as_index=False)["tn"].sum()
                    df_loc_agg["kt"] = (df_loc_agg["tn"] / 1000).round(1)
                    df_loc_agg["pcia_norm"] = df_loc_agg["provincia"].apply(_norm)
                    df_loc_agg["loc_norm"]  = df_loc_agg["localidad"].apply(_norm)

                    # Match by (loc_norm, pcia_norm)
                    df_bubbles = df_loc_agg.merge(
                        df_loc[["loc_norm", "pcia_norm", "lat", "lon"]],
                        on=["loc_norm", "pcia_norm"], how="left",
                    )
                    sin_match = df_bubbles[df_bubbles["lat"].isna()]
                    df_bubbles = df_bubbles.dropna(subset=["lat", "lon"])
                    if "kt" not in df_bubbles.columns:
                        df_bubbles["kt"] = (df_bubbles["tn"] / 1000).round(1)
                    df_bubbles["Localidad"]  = df_bubbles["localidad"].str.title()
                    df_bubbles["Provincia"]  = df_bubbles["provincia"].apply(
                        lambda p: ISO_A_LABEL.get(a_iso(p) or "", p.title())
                    )

                    capas = []

                    # Layer 1 (optional): provinces in gray.
                    # Pasamos el FeatureCollection completo y le decimos a Vega que
                    # extraiga `features` (forma idiomática de Altair para geoshape).
                    if geo_data is not None:
                        capa_provincias = alt.Chart(
                            alt.Data(values=geo_data,
                                     format=alt.DataFormat(property="features",
                                                           type="json"))
                        ).mark_geoshape(
                            fill="#2a2a2a", stroke="#666", strokeWidth=0.5,
                        )
                        capas.append(capa_provincias)

                    # Layer 2: bubbles (sized/colored by kt)
                    if len(df_bubbles) > 0:
                        capa_bubbles = alt.Chart(df_bubbles).mark_circle(opacity=0.75).encode(
                            longitude="lon:Q", latitude="lat:Q",
                            size=alt.Size("kt:Q",
                                scale=alt.Scale(range=[20, 1500]),
                                legend=alt.Legend(title="kt", orient="right")),
                            color=alt.Color("kt:Q",
                                scale=alt.Scale(scheme="greens"),
                                legend=None),
                            tooltip=["Provincia", "Localidad",
                                     alt.Tooltip("kt:Q", title="kt", format=",.1f")],
                        )
                        capas.append(capa_bubbles)

                    if capas:
                        # alt.layer() + .project() en la capa combinada
                        # garantiza que ambas capas usen la misma proyección.
                        mapa = (alt.layer(*capas)
                                  .project(type="mercator")
                                  .properties(height=600))
                        st.altair_chart(mapa, use_container_width=True)
                    else:
                        st.info("No points to display.")

                    if geo_error:
                        st.caption(f"ℹ Map without province outlines (invalid GeoJSON: {geo_error}). "
                                   f"Re-download with: `curl -L -o {geo_path} "
                                   "\"https://raw.githubusercontent.com/PoliticaArgentina/data_warehouse/master/geoAr/data_raw/provincias.geojson\"`")

                    if len(sin_match) > 0:
                        tn_sin = int(sin_match["tn"].sum())
                        st.caption(f"⚠ {len(sin_match)} localit{'y' if len(sin_match)==1 else 'ies'} without coordinates in the dataset "
                                   f"(adding to {fmt_tn(tn_sin)} tn, ~{tn_sin/tot*100:.1f}% of total). "
                                   f"E.g.: {', '.join(sin_match['localidad'].head(5).tolist())}.")
                except Exception as e:
                    st.warning(f"Couldn't render the map: {type(e).__name__}: {e}")

            st.divider()

            # Ranking by province (always)
            st.subheader("Ranking by province")
            agg["kt"] = (agg["tn"] / 1000).round(1)
            bars_orig = alt.Chart(agg).mark_bar().encode(
                y=alt.Y("Provincia:N", sort="-x", title=None),
                x=alt.X("kt:Q", title="Kilotonnes", axis=alt.Axis(format=",.0f")),
                color=alt.Color("kt:Q", scale=alt.Scale(scheme="greens"), legend=None),
                tooltip=["Provincia", alt.Tooltip("kt:Q", format=",.1f")],
            ).properties(height=max(300, 25 * len(agg)))
            st.altair_chart(bars_orig, use_container_width=True)

            st.divider()

            # ── Top localities ──────────────────────────────────────────
            st.subheader("Top localities (more detail)")
            if "localidad" in df_filt.columns and df_filt["localidad"].notna().any():
                agg_loc = (df_filt.groupby(["provincia", "localidad"], as_index=False)["tn"]
                                  .sum()
                                  .sort_values("tn", ascending=False)
                                  .head(30))
                agg_loc["Provincia"] = agg_loc["provincia"].apply(
                    lambda p: ISO_A_LABEL.get(a_iso(p) or "", p.title())
                )
                agg_loc["Localidad"] = agg_loc["localidad"].str.title()
                agg_loc["Kt"] = agg_loc["tn"].apply(lambda v: fmt_tn(int(v)))
                st.dataframe(
                    agg_loc[["Provincia", "Localidad", "Kt"]],
                    use_container_width=True, hide_index=True,
                    height=min(55 + len(agg_loc)*35, 700),
                )
                st.caption(f"Top 30 of {df_filt['localidad'].nunique()} active localities in the range.")
            else:
                st.info("Localities appear only after regenerating the matrices "
                        "(`make backfill-matrices`) with the new script.")

            if len(sin_iso) > 0:
                st.caption(f"⚠ {len(sin_iso)} province(s) without ISO mapping: {', '.join(sin_iso[:5])}"
                           + (" ..." if len(sin_iso) > 5 else ""))


