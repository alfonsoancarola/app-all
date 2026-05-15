"""
compute_historical_metrics.py — Pre-compute per-cosecha historical metrics
for the comparison panel in app.py.

For each cosecha (current + N_HIST_YEARS history), computes:
  - Est. Exports (from cultivos.BALANCE_HIST)
  - PH + Pricing acum. (from MAGYP at the same calendar date as current's last cut,
    shifted N years back)
  - FS / Exports (= PH+Pricing / Est Exports)
  - Per-group breakdown (MAM/JJ/AS/OND/JF or NDJ/FMA/MJJ/ASO) using the
    MINAGRI×split SIO formula, with delivery_groups year-shifted per cosecha.

Reads:
  - data/sio_historico.csv (full backfill — 10y of SIO ops)
  - data/minagri_<slug>_<cosecha>.json (one per cosecha)
  - cultivos.py BALANCE_HIST

Writes:
  - data/historical_metrics_<slug>.json

Usage:
    python compute_historical_metrics.py            # all crops
    python compute_historical_metrics.py --cultivo maiz
"""
from __future__ import annotations

import argparse
import calendar
import csv
import json
import sys
import unicodedata
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

from cultivos import CULTIVOS, get_cultivo, slug_de, minagri_json_path

DATA_DIR  = Path("data")
SIO_PATH  = DATA_DIR / "sio_historico.csv"
N_HIST    = 7  # historical cosechas to compute (besides current)


# ── Utilidades ────────────────────────────────────────────────────────────────

def _normalize_header(h: str) -> str:
    if not h:
        return ""
    s = unicodedata.normalize("NFD", h.upper().strip())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return " ".join(s.split())


def _normalize_cosecha(s: str) -> str:
    """Normaliza '25/26', '2025/2026', 'Cosecha 25/26', '25-26', '25\\26' → '25/26'."""
    if not s:
        return ""
    s = str(s).strip().upper()
    # Strip prefijo "COSECHA" o "COSECHA " si está presente
    if s.startswith("COSECHA"):
        s = s[len("COSECHA"):].strip()
    # Reemplazos: cualquier separador (-, ', \, espacio) → /
    for ch in ["'", "-", "\\", " "]:
        s = s.replace(ch, "/")
    # Colapsar múltiples /
    while "//" in s:
        s = s.replace("//", "/")
    parts = s.split("/")
    if len(parts) != 2:
        return s
    a, b = parts[0].strip(), parts[1].strip()
    # Convertir 4 dígitos → 2 dígitos
    if len(a) == 4 and a.isdigit():
        a = a[-2:]
    if len(b) == 4 and b.isdigit():
        b = b[-2:]
    return f"{a}/{b}"


def _parse_fecha(s: str) -> date | None:
    """Parse SIO date (DD/MM/YYYY HH:MM:SS)."""
    if not s:
        return None
    s_date = str(s).strip().split(" ")[0]
    try:
        d, m, y = s_date.split("/")
        return date(int(y), int(m), int(d))
    except Exception:
        return None


def _shift_groups(delivery_groups, year_shift: int):
    """Shift each (name, start, end) tuple by year_shift years."""
    out = []
    for name, start, end in delivery_groups:
        try:    new_start = start.replace(year=start.year + year_shift)
        except ValueError:
            new_start = start.replace(year=start.year + year_shift, day=28)
        try:    new_end = end.replace(year=end.year + year_shift)
        except ValueError:
            new_end = end.replace(year=end.year + year_shift, day=28)
        out.append((name, new_start, new_end))
    return out


def _grupo_de_entrega(d: date | None, groups) -> str | None:
    if d is None:
        return None
    for name, start, end in groups:
        if start <= d <= end:
            return name
    return None


def _shift_target_date(target: date, delta_years: int) -> date:
    """target − delta_years (handles 29 Feb edge)."""
    try:
        return target.replace(year=target.year - delta_years)
    except ValueError:
        return target.replace(year=target.year - delta_years, day=28)


# ── MAGYP ─────────────────────────────────────────────────────────────────────

def _load_minagri_clean(json_path: Path):
    """Carga MAGYP y trunca en el primer drop > 15% (re-categorización)."""
    if not json_path.exists():
        return []
    try:
        d = json.loads(json_path.read_text(encoding="utf-8"))
        serie = d.get("serie", [])
    except Exception:
        return []
    if not serie:
        return []
    cleaned = [serie[0]]
    for pt in serie[1:]:
        prev = float(cleaned[-1].get("ph_fijado_acum_kt", 0) or 0)
        curr = float(pt.get("ph_fijado_acum_kt", 0) or 0)
        if prev > 100 and curr < prev * 0.85:
            break
        cleaned.append(pt)
    return cleaned


def _interp_kt(serie, target: date) -> float:
    """Interpola ph_fijado_acum_kt en target."""
    if not serie:
        return 0.0
    pts = [(date.fromisoformat(p["fecha"]),
            float(p.get("ph_fijado_acum_kt", 0) or 0)) for p in serie]
    pts.sort()
    if target <= pts[0][0]:
        return 0.0
    if target >= pts[-1][0]:
        return pts[-1][1]
    for (d1, v1), (d2, v2) in zip(pts, pts[1:]):
        if d1 <= target <= d2:
            span = (d2 - d1).days or 1
            return v1 + (v2 - v1) * ((target - d1).days / span)
    return pts[-1][1]


def _ph_at(serie, target: date) -> float:
    """Cumulative PH+Pricing en target, usando el último punto ≤ target."""
    best = None
    for pt in serie:
        try:    pd_d = date.fromisoformat(pt["fecha"])
        except Exception:
            continue
        if pd_d <= target:
            if best is None or pd_d > date.fromisoformat(best["fecha"]):
                best = pt
    return float(best.get("ph_fijado_acum_kt", 0)) if best else 0.0


# ── SIO loading (filtered by cultivo) ─────────────────────────────────────────

def load_sio_for_cultivo(cfg) -> dict[str, list]:
    """
    Returns dict {cosecha_label: [(fecha_conc, fecha_desde, tn), ...]}
    filtered to this cultivo's SIO_PRODUCTO.
    """
    out: dict[str, list] = defaultdict(list)
    if not SIO_PATH.exists():
        print(f"  ⚠ {SIO_PATH} not found — per-group splits will be 0")
        return out

    sio_producto = cfg["sio_producto"].upper()
    print(f"  📂 Loading SIO from {SIO_PATH} (target producto={sio_producto})…")

    # SIO está en utf-16-le con ; como separador
    with open(SIO_PATH, encoding="utf-16-le", errors="replace") as f:
        text = f.read()
    if not text.strip():
        print("  ⚠ SIO file empty")
        return out

    reader = csv.reader(text.splitlines(), delimiter=";")
    header = next(reader)
    h_norm = [_normalize_header(h) for h in header]

    def find_col(*candidates):
        for cand in candidates:
            n = _normalize_header(cand)
            if n in h_norm:
                return h_norm.index(n)
        return None

    c_fconc = find_col("FECHA CONCERTACION", "FECHA CONCERTACION ")
    c_fdes  = find_col("FECHA ENTR. DESDE", "FECHA ENTR DESDE")
    c_cant  = find_col("CANT. (TN)", "CANT (TN)", "CANT TN")
    c_prod  = find_col("PRODUCTO")
    c_cos   = find_col("COSECHA")

    if any(c is None for c in (c_fconc, c_cant, c_prod, c_cos)):
        print(f"  ⚠ SIO missing required columns. Have: {header}")
        return out

    n_total = 0
    n_kept  = 0
    for row in reader:
        n_total += 1
        if len(row) <= max(c_fconc, c_cos, c_cant, c_prod):
            continue
        prod = (row[c_prod] or "").strip().upper()
        if prod != sio_producto:
            continue
        cos_norm = _normalize_cosecha(row[c_cos])
        if not cos_norm:
            continue
        try:    tn = float((row[c_cant] or "0").replace(",", "."))
        except Exception:
            tn = 0.0
        if tn <= 0:
            continue
        fconc = _parse_fecha(row[c_fconc])
        fdes  = _parse_fecha(row[c_fdes]) if c_fdes is not None else None
        out[cos_norm].append((fconc, fdes, tn))
        n_kept += 1

    print(f"  ✓ {n_kept:,} ops kept (of {n_total:,} total) across {len(out)} cosechas")
    # Debug: top cosechas por #ops para diagnosticar formato
    top = sorted(out.items(), key=lambda kv: -len(kv[1]))[:15]
    print(f"  🔎 top cosechas: {', '.join(f'{k!r}={len(v):,}' for k, v in top)}")
    return out


# ── Cómputo principal ────────────────────────────────────────────────────────

def compute_for_crop(cultivo_slug: str) -> bool:
    cfg    = get_cultivo(cultivo_slug)
    slug   = slug_de(cfg)
    grupos = cfg["grupos"]
    print(f"\n🌾 {cultivo_slug} ({cfg['label']})")

    # 1) Reference date = current MAGYP last cut
    cur_path = DATA_DIR / f"minagri_{slug}_{cfg['cosecha'].replace('/', '_')}.json"
    cur_serie = _load_minagri_clean(cur_path)
    if not cur_serie:
        print(f"  ⚠ No MAGYP for current cosecha ({cur_path.name})")
        return False
    cur_last_date = date.fromisoformat(cur_serie[-1]["fecha"])
    print(f"  📅 Reference date (current MAGYP): {cur_last_date}")

    # Mes corriente: tomamos HOY (no la última fecha MAGYP).
    # Si MAGYP actualizó el 29/Abr y hoy es 9/May, el "mes corriente" debe ser May.
    today = date.today()
    current_month_idx   = today.month
    current_month_name  = calendar.month_name[current_month_idx]
    current_year_actual = today.year
    print(f"  📅 Current calendar month: {current_month_name} {current_year_actual}")

    cosecha_actual    = cfg["cosecha"]                                # MAGYP
    cosecha_actual_ldc = cfg.get("cosecha_label", cosecha_actual)      # LDC
    year_actual        = int(cosecha_actual.split("/")[0])
    # Offset MAGYP→LDC (corn/sorgo = +1, trigo/cebada = 0)
    ldc_offset = int(cosecha_actual_ldc.split("/")[0]) - year_actual

    def _ldc_label_for(magyp_cosecha: str) -> str:
        y1, y2 = magyp_cosecha.split("/")
        return f"{(int(y1)+ldc_offset)%100:02d}/{(int(y2)+ldc_offset)%100:02d}"

    # 2) Lista de cosechas a procesar
    targets = [(year_actual, cosecha_actual, True)]
    for i in range(1, N_HIST + 1):
        y = year_actual - i
        targets.append((y, f"{y:02d}/{y+1:02d}", False))

    # 3) Cargar SIO una sola vez
    sio_by_cosecha = load_sio_for_cultivo(cfg)
    balance_hist   = cfg["balance_hist"]

    # 4) Calcular cada fila
    rows = []
    for year_h, cosecha_h, is_current in targets:
        delta_years = year_actual - year_h
        target = cur_last_date if is_current else _shift_target_date(cur_last_date, delta_years)

        # LDC label correspondiente a esta cosecha MAGYP
        cosecha_h_ldc = _ldc_label_for(cosecha_h)

        # Production y Est Exports — del Country Balance Sheet usando LDC label
        bal = balance_hist.get(cosecha_h_ldc, {})
        prod_kt    = round(bal.get("prod", 0) * 1000)
        est_exp_kt = round(bal.get("exp", 0) * 1000)

        # MAGYP serie (current ya cargado, history desde JSON)
        if is_current:
            magyp_serie = cur_serie
        else:
            mp = DATA_DIR / f"minagri_{slug}_{cosecha_h.replace('/', '_')}.json"
            magyp_serie = _load_minagri_clean(mp)

        ph_pricing_kt = round(_ph_at(magyp_serie, target))
        fs_pct = round(ph_pricing_kt / est_exp_kt * 100, 1) if est_exp_kt > 0 else 0.0

        # Splits por grupo (MINAGRI × split SIO, mensual)
        groups_kt = {g: 0 for g in grupos}
        ops_cos = sio_by_cosecha.get(cosecha_h, [])
        if ops_cos and magyp_serie:
            shifted_groups = _shift_groups(cfg["delivery_groups"], -delta_years)
            sio_per_month: dict[tuple[int, int], dict[str, float]] = defaultdict(
                lambda: {g: 0.0 for g in grupos})
            for fconc, fdes, tn in ops_cos:
                if fconc is None or fconc > target:
                    continue
                g = _grupo_de_entrega(fdes, shifted_groups)
                if g is None:
                    continue
                sio_per_month[(fconc.year, fconc.month)][g] += tn

            total_per_group_tn = {g: 0.0 for g in grupos}
            for (y, m), sio_g in sio_per_month.items():
                total_sio_mes = sum(sio_g.values())
                if total_sio_mes <= 0:
                    continue
                ini = date(y, m, 1)
                fin = date(y + 1, 1, 1) if m == 12 else date(y, m + 1, 1)
                v_ini = _interp_kt(magyp_serie, ini) * 1000
                v_fin = _interp_kt(magyp_serie, fin) * 1000
                total_minagri_mes = max(0.0, v_fin - v_ini)
                if total_minagri_mes > 0:
                    for g in grupos:
                        total_per_group_tn[g] += total_minagri_mes * (sio_g[g] / total_sio_mes)
                else:
                    # Fallback: SIO crudo si MAGYP no tenía data ese mes
                    for g in grupos:
                        total_per_group_tn[g] += sio_g[g]

            for g in grupos:
                groups_kt[g] = round(total_per_group_tn[g] / 1000)

        # ── Tonelaje del mes corriente para esta cosecha ───────────────
        # Para current cosecha: mayo del año actual (parcial).
        # Para históricas: mayo del año correspondiente shifteado.
        target_year_for_month = current_year_actual - delta_years
        month_ops = [
            (fc, fd, t) for fc, fd, t in ops_cos
            if fc and fc.year == target_year_for_month and fc.month == current_month_idx
        ]
        month_total_tn = sum(t for _, _, t in month_ops)
        month_groups_tn = {g: 0.0 for g in grupos}
        if ops_cos:
            shifted_groups_for_month = _shift_groups(cfg["delivery_groups"], -delta_years)
            for fc, fd, t in month_ops:
                g = _grupo_de_entrega(fd, shifted_groups_for_month)
                if g:
                    month_groups_tn[g] += t

        # Proyección del mes (solo para cosecha actual)
        month_projected_tn = month_total_tn
        if is_current and month_ops:
            ops_by_date: dict[date, float] = defaultdict(float)
            for fc, _, t in month_ops:
                ops_by_date[fc] += t
            recent = sorted(ops_by_date.keys(), reverse=True)[:10]
            avg_per_day = (sum(ops_by_date[d] for d in recent) / len(recent)
                           if recent else 0)
            last_dom = calendar.monthrange(current_year_actual, current_month_idx)[1]
            remaining_dates = [
                date(current_year_actual, current_month_idx, d)
                for d in range(cur_last_date.day + 1, last_dom + 1)
            ]
            remaining_biz = sum(1 for d in remaining_dates if d.weekday() < 5)
            month_projected_tn = month_total_tn + avg_per_day * remaining_biz

        month_actual_kt    = round(month_total_tn / 1000)
        month_projected_kt = round(month_projected_tn / 1000)
        month_groups_kt    = {g: round(month_groups_tn[g] / 1000) for g in grupos}

        rows.append({
            "cosecha":              cosecha_h,        # MAGYP (matching key)
            "cosecha_label":        cosecha_h_ldc,    # LDC (display key)
            "is_current":           is_current,
            "target_date":          target.isoformat(),
            "production_kt":        prod_kt,
            "est_exports_kt":       est_exp_kt,
            "ph_pricing_kt":        ph_pricing_kt,
            "fs_pct":               fs_pct,
            "groups_kt":            groups_kt,
            # Mes corriente
            "month_year":           target_year_for_month,
            "month_actual_kt":      month_actual_kt,
            "month_projected_kt":   month_projected_kt,
            "month_groups_kt":      month_groups_kt,
        })
        n_ops = len(ops_cos)
        print(f"  ✓ MAGYP {cosecha_h} (LDC {cosecha_h_ldc}){'  (current)' if is_current else ''} @ {target}: "
              f"prod={prod_kt:,} kt, est.exp={est_exp_kt:,} kt, "
              f"PH+Pricing={ph_pricing_kt:,} kt, FS={fs_pct:.1f}%, ops={n_ops:,}")

    # 5) Guardar
    out_path = DATA_DIR / f"historical_metrics_{slug}.json"
    out_path.write_text(json.dumps({
        "computed_at":       datetime.now().isoformat(),
        "current_cosecha":   cosecha_actual,
        "current_cosecha_label": cfg.get("cosecha_label", cosecha_actual),
        "current_date":      cur_last_date.isoformat(),
        "current_month_idx": current_month_idx,
        "current_month_name": current_month_name,
        "n_hist_years":      N_HIST,
        "grupos":            grupos,
        "subtitulos":        cfg["subtitulos"],
        "rows":              rows,
    }, indent=2, default=str), encoding="utf-8")
    print(f"  💾 Saved → {out_path}")
    return True


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--cultivo", default="all",
                   help="Slug del cultivo o 'all' (default).")
    args = p.parse_args()

    if args.cultivo == "all":
        for slug in CULTIVOS:
            try:
                compute_for_crop(slug)
            except Exception as e:
                print(f"  ✗ {slug} failed: {type(e).__name__}: {e}")
    else:
        compute_for_crop(args.cultivo)
    return 0


if __name__ == "__main__":
    sys.exit(main())
