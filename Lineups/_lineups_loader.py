"""
_lineups_loader.py — Loader minimalista de los XLS de Alpemar (lineups),
pensado para que fs_maiz pueda superponer los embarques con sus compras
sin duplicar/correr todo lineups_app.py (que tiene st.set_page_config y
otros side-effects).

Solo expone funciones puras de parsing/agregado. No depende de Streamlit.

Mantener en sync con lineups_app.py:
  - MONTH_FILES
  - CARGO_NORMALIZE
  - secciones del parser (LOADED / AT ROADS / ANNOUNCED|LINEUP)
"""

from __future__ import annotations

from pathlib import Path
import pandas as pd

# ── Files & mappings ─────────────────────────────────────────────────────────

DATA_DIR = Path(__file__).parent

MONTH_FILES: dict[str, tuple[str, str]] = {
    "March 2026": ("GRAIN-SBS-BARLEY-MALT SHIPMENTS March 2026.xls", "finalized"),
    "April 2026": ("GRAIN-SBS-BARLEY-MALT SHIPMENTS April 2026.xls", "finalized"),
    "May 2026":   ("GRAIN-SBS-BARLEY-MALT SHIPMENTS May 2026.xls",   "current"),
}

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

# Mapping desde el slug de fs_maiz al CARGO normalizado de Lineups
FS_SLUG_TO_CARGO = {
    "maiz":   "Maize",
    "trigo":  "Wheat",
    "sorgo":  "Sorghum",
    "cebada": "Barley",
}


# ── Parser ───────────────────────────────────────────────────────────────────

def _parse_one(path: Path) -> pd.DataFrame:
    """Parse un xls de Alpemar — réplica reducida del de lineups_app.py.

    Devuelve cols: CARGO, TONS, ETA, STATUS.
    """
    raw = pd.read_excel(path, sheet_name=0, header=None)
    sections: list[tuple[int, str]] = []
    end_row = len(raw)
    for i, row in raw.iterrows():
        cell = str(row[0]).strip() if pd.notna(row[0]) else ""
        if not cell:
            continue
        up = cell.upper()
        if "BEST REGARDS" in up:
            end_row = i
            break
        if up.startswith("LOADED"):
            sections.append((i, "Sailed"))
        elif up == "AT ROADS":
            sections.append((i, "At Roads"))
        elif up in ("ANNOUNCED", "LINEUP"):
            sections.append((i, "Lineup"))

    frames = []
    for idx, (start, status) in enumerate(sections):
        nxt = sections[idx + 1][0] if idx + 1 < len(sections) else end_row
        sub = raw.iloc[start + 1:nxt].copy()
        try:
            sub.columns = ["CARGO", "VESSEL", "PORT", "BERTH", "ETA",
                           "TONS", "SHIPPER", "COORD", "DEST"]
        except Exception:
            continue
        sub["STATUS"] = status
        sub = sub[sub["CARGO"].notna() & sub["VESSEL"].notna()]
        frames.append(sub)

    if not frames:
        return pd.DataFrame(columns=["CARGO", "TONS", "ETA", "STATUS"])

    df = pd.concat(frames, ignore_index=True)
    df["TONS"] = pd.to_numeric(df["TONS"], errors="coerce").fillna(0)
    df = df[df["TONS"] > 0]
    df["CARGO"] = df["CARGO"].astype(str).str.strip().map(
        lambda x: CARGO_NORMALIZE.get(x, x)
    )
    df["ETA"] = pd.to_datetime(df["ETA"], errors="coerce", dayfirst=True)
    # Normalizar shipper (mismas reglas que lineups_app.normalize_shipper)
    import re as _re
    def _norm_shipper(s):
        if not isinstance(s, str):
            return ""
        s = _re.sub(r"\s+", " ", s).strip()
        low = s.lower()
        if low.startswith("cofco"):        return "Cofco Int. Arg."
        if low.startswith("molinos agro"): return "Molinos Agro"
        if low.startswith("adm"):          return "ADM Agro"
        return s
    df["SHIPPER"] = df["SHIPPER"].map(_norm_shipper) if "SHIPPER" in df.columns else ""
    return df[["CARGO", "TONS", "ETA", "STATUS", "SHIPPER"]]


def load_all(data_dir: Path | None = None) -> pd.DataFrame:
    """Lee todos los xls de MONTH_FILES y devuelve un DF concatenado con MONTH."""
    base = Path(data_dir) if data_dir else DATA_DIR
    frames = []
    for month_lbl, (fname, kind) in MONTH_FILES.items():
        p = base / fname
        if not p.exists():
            continue
        try:
            df = _parse_one(p)
        except Exception:
            continue
        if df.empty:
            continue
        df["MONTH"] = month_lbl
        df["MONTH_STATE"] = kind
        frames.append(df)
    if not frames:
        return pd.DataFrame(columns=["CARGO", "TONS", "ETA", "STATUS",
                                     "MONTH", "MONTH_STATE"])
    return pd.concat(frames, ignore_index=True)


def load_for_crop(fs_slug: str, data_dir: Path | None = None) -> pd.DataFrame:
    """Filtra `load_all()` por el cargo correspondiente al slug de fs_maiz."""
    cargo = FS_SLUG_TO_CARGO.get(fs_slug)
    if cargo is None:
        return pd.DataFrame(columns=["CARGO", "TONS", "ETA", "STATUS",
                                     "MONTH", "MONTH_STATE"])
    df = load_all(data_dir)
    if df.empty:
        return df
    return df[df["CARGO"] == cargo].copy()


# ── Agregados convenientes ──────────────────────────────────────────────────

def file_last_date_for_month(month_lbl: str,
                             data_dir: Path | None = None) -> pd.Timestamp | None:
    """Fecha (normalizada al día) en que se actualizó el xls del mes pedido.

    Los archivos de Alpemar se cargan una vez por semana. Más allá de su mtime
    no podemos asegurar qué pasó — todo lo posterior es proyección.
    """
    base = Path(data_dir) if data_dir else DATA_DIR
    if month_lbl not in MONTH_FILES:
        return None
    fname, _ = MONTH_FILES[month_lbl]
    p = base / fname
    if not p.exists():
        return None
    return pd.Timestamp(p.stat().st_mtime, unit="s").normalize()


def monthly_cumulative(df_crop: pd.DataFrame, month_lbl: str,
                       month_start: pd.Timestamp,
                       month_end: pd.Timestamp,
                       today: pd.Timestamp,
                       last_data_date: pd.Timestamp | None = None) -> dict:
    """Devuelve un dict con el acumulado diario de Sailed más algunos totales.

    El acumulado realizado se corta en `last_data_date` (= mtime del xls). Si
    no se pasa, se usa el min(today, mtime_del_archivo) — para que más allá del
    último update del archivo todo sea proyección y no muestre líneas planas.

    Keys:
      - sailed_daily_cum: DataFrame[DATE, sailed_cum] hasta `cap_date`
      - sailed_total, roads_total, lineup_total, pipeline_total
      - cap_date: hasta dónde llega `sailed_daily_cum`
    """
    if last_data_date is None:
        last_data_date = pd.Timestamp(today).normalize()

    # Cap = min(today, last_data_date) — nunca pasamos del día actual ni del
    # último update del archivo.
    cap_date = min(pd.Timestamp(today).normalize(),
                   pd.Timestamp(last_data_date).normalize())
    cap_date = max(cap_date, pd.Timestamp(month_start).normalize())

    cur = df_crop[df_crop["MONTH"] == month_lbl].copy()
    sailed = cur[(cur["STATUS"] == "Sailed") & cur["ETA"].notna()].copy()
    sailed["DATE"] = sailed["ETA"].dt.normalize()
    # No contamos Sailed con ETA posterior al cap (raro, pero defensivo)
    sailed = sailed[sailed["DATE"] <= cap_date]
    daily = sailed.groupby("DATE")["TONS"].sum().sort_index()

    rng = pd.date_range(month_start, cap_date, freq="D")
    real_series = (daily.reindex(rng, fill_value=0).cumsum()
                        .reset_index())
    real_series.columns = ["DATE", "sailed_cum"]

    return {
        "sailed_daily_cum": real_series,
        "sailed_total":  float(cur[cur["STATUS"] == "Sailed"]["TONS"].sum()),
        "roads_total":   float(cur[cur["STATUS"] == "At Roads"]["TONS"].sum()),
        "lineup_total":  float(cur[cur["STATUS"] == "Lineup"]["TONS"].sum()),
        "pipeline_total": float(cur["TONS"].sum()),
        "month_start":   month_start,
        "month_end":     month_end,
        "cap_date":      cap_date,
    }


def monthly_totals(df_crop: pd.DataFrame) -> pd.DataFrame:
    """Total Sailed por mes (para overlay anual)."""
    if df_crop.empty:
        return pd.DataFrame(columns=["MONTH", "sailed_tn"])
    g = (df_crop[df_crop["STATUS"] == "Sailed"]
         .groupby("MONTH")["TONS"].sum()
         .reset_index()
         .rename(columns={"TONS": "sailed_tn"}))
    return g
