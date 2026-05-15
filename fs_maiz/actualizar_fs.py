"""
actualizar_fs.py — Genera la matriz FS para el cultivo elegido.

Multi-cultivo: la config (buckets, año comercial, IDs SIO/MAGYP) vive en
cultivos.py. Este script lee el CSV de SIO compartido, filtra por producto +
cosecha + TIPO (PH/FP), agrupa por mes/grupo de delivery, y aplica la lógica:

    cell[mes][grupo] = volumen MINAGRI mes × (split_sio_grupo / total_sio_mes)

Si no hay MINAGRI para ese mes → fallback SIO crudo.
Filas diarias del "mes en curso" cuando el cultivo lo tiene configurado.

Uso:
    python actualizar_fs.py --sio data/sio_historico.csv                  # default: maiz
    python actualizar_fs.py --sio data/sio_historico.csv --cultivo trigo
    python actualizar_fs.py --sio data/sio_historico.csv --cultivo cebada
    python actualizar_fs.py --sio data/sio_historico.csv --cultivo sorgo
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import shutil
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Iterable

from cultivos import CULTIVOS, get_cultivo, grupo_de_entrega, minagri_json_path

SCRIPT_DIR = Path(__file__).resolve().parent
DATA_DIR = SCRIPT_DIR / "data"

MESES_ES = ["Ene", "Feb", "Mar", "Abr", "May", "Jun",
            "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]


# ── Utilidades ────────────────────────────────────────────────────────────────

def _log(msg: str) -> None:
    print(f"[fs] {msg}", flush=True)


def parse_fecha(s: str) -> date | None:
    if s is None:
        return None
    s = str(s).strip().strip('"').strip("'")
    if not s or s.lower() in {"nan", "none", "null"}:
        return None
    s = s.split(" ", 1)[0] if " " in s else s
    for fmt in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d",
                "%d-%m-%Y", "%d-%m-%y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s).date()
    except Exception:
        return None


def parse_cantidad(s: str) -> float:
    if s is None:
        return 0.0
    s = str(s).strip().strip('"')
    if not s:
        return 0.0
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def label_mes(year: int, month: int) -> str:
    return f"{MESES_ES[month - 1]}-{str(year)[-2:]}"


def meses_mensuales(desde: tuple[int, int], hasta: tuple[int, int]) -> list[tuple[int, int]]:
    """(year, month) desde inicio hasta hasta_mes inclusive."""
    out: list[tuple[int, int]] = []
    y, m = desde
    yh, mh = hasta
    while (y, m) <= (yh, mh):
        out.append((y, m))
        m += 1
        if m == 13:
            m, y = 1, y + 1
    return out


def mes_anterior(d: date) -> tuple[int, int]:
    return (d.year - 1, 12) if d.month == 1 else (d.year, d.month - 1)


# ── CSV SIO ───────────────────────────────────────────────────────────────────

@dataclass
class Operacion:
    fecha_conc: date
    tipo: str
    cant_tn: float
    fecha_desde: date | None
    lugar_entrega: str = ""
    procedencia_pcia: str = ""
    procedencia_loc: str = ""
    producto: str = ""
    cosecha: str = ""


def _abrir_sio(path: Path) -> str:
    raw = path.read_bytes()
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16")
    for enc in ("utf-16-le", "utf-16", "utf-8-sig", "utf-8", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise RuntimeError(f"No pude decodificar {path}")


def _normalizar_header(h: str) -> str:
    s = (h.strip().replace("﻿", "").upper()
         .replace("Á", "A").replace("É", "E").replace("Í", "I")
         .replace("Ó", "O").replace("Ú", "U"))
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"\s*([.,()])\s*", r"\1", s)
    return s.strip()


def leer_sio(path: Path) -> list[Operacion]:
    text = _abrir_sio(path)
    sample = "\n".join(text.splitlines()[:5])
    sep = ";" if sample.count(";") >= sample.count(",") else ","
    rows = list(csv.reader(io.StringIO(text), delimiter=sep, quotechar='"'))
    if not rows:
        return []
    header = [_normalizar_header(c) for c in rows[0]]

    def col(*nombres: str) -> int:
        for n in nombres:
            n = _normalizar_header(n)
            if n in header:
                return header.index(n)
        return -1

    i_fc    = col("FECHA CONCERTACION", "F. CONCERTACION")
    i_tipo  = col("PRECIO", "TIPO")
    i_cant  = col("CANT.(TN)", "CANT (TN)", "CANTIDAD (TN)", "CANTIDAD")
    i_desde = col("FECHA ENTR. DESDE", "FECHA ENTRG. DESDE", "FECHA ENTR DESDE")
    i_prod  = col("PRODUCTO", "PROD", "CULTIVO")
    i_cos   = col("COSECHA", "CAMPAÑA", "CAMPANA")
    i_lugar = col("LUGAR ENTREGA", "LUGAR DE ENTREGA")
    i_pcia  = col("PROCEDENCIA PCIA", "PROCEDENCIA PROVINCIA", "PROVINCIA")
    i_loc   = col("PROCEDENCIA LOCALID.", "PROCEDENCIA LOCALIDAD", "LOCALIDAD")

    faltantes = [n for n, idx in [
        ("FECHA CONCERTACION", i_fc),
        ("CANT.(TN)", i_cant),
        ("FECHA ENTR. DESDE", i_desde),
    ] if idx < 0]
    if faltantes:
        raise RuntimeError(f"Faltan columnas en SIO: {faltantes}\nHeader: {header}")

    ops: list[Operacion] = []
    for r in rows[1:]:
        if not r or all((c or "").strip() == "" for c in r):
            continue
        try:
            fc = parse_fecha(r[i_fc]) if i_fc < len(r) else None
            tipo = r[i_tipo].strip() if 0 <= i_tipo < len(r) else ""
            cant = parse_cantidad(r[i_cant]) if i_cant < len(r) else 0.0
            d_des = parse_fecha(r[i_desde]) if i_desde < len(r) else None
            prod = r[i_prod].strip() if 0 <= i_prod < len(r) else ""
            cos = r[i_cos].strip() if 0 <= i_cos < len(r) else ""
            lugar = r[i_lugar].strip() if 0 <= i_lugar < len(r) else ""
            pcia  = r[i_pcia].strip()  if 0 <= i_pcia  < len(r) else ""
            loc   = r[i_loc].strip()   if 0 <= i_loc   < len(r) else ""
        except Exception:
            continue
        if fc is None or cant <= 0:
            continue
        ops.append(Operacion(fecha_conc=fc, tipo=tipo, cant_tn=cant,
                             fecha_desde=d_des, lugar_entrega=lugar,
                             procedencia_pcia=pcia, procedencia_loc=loc,
                             producto=prod, cosecha=cos))
    return ops


def filtrar_producto(ops: Iterable[Operacion], target: str) -> list[Operacion]:
    """Match exacto del valor SIO (ej. 'MAIZ', 'TRIGO PAN', 'CEBADA CERV.', 'SORGO')."""
    t = _normalizar_header(target)
    out = []
    for o in ops:
        if not o.producto:
            continue  # CSV nuevo sí trae producto: si no hay, descartamos
        if _normalizar_header(o.producto) == t:
            out.append(o)
    return out


def filtrar_cosecha(ops: Iterable[Operacion], cosecha: str) -> list[Operacion]:
    """La columna COSECHA del SIO viene como 'COSECHA 25/26'. Match parcial."""
    target = cosecha.strip().replace("'", "/").replace("-", "/")
    out = []
    for o in ops:
        if not o.cosecha:
            out.append(o); continue  # legacy sin columna: lo dejamos pasar
        c = o.cosecha.strip().replace("'", "/").replace("-", "/")
        if target in c:
            out.append(o)
    return out


def filtrar_tipo(ops: Iterable[Operacion]) -> list[Operacion]:
    """Mantiene solo Precio Hecho y Fijar Precio (col PRECIO del CSV)."""
    out = []
    for o in ops:
        t = o.tipo.upper()
        for a, b in (("Á","A"),("É","E"),("Í","I"),("Ó","O"),("Ú","U")):
            t = t.replace(a, b)
        if "PRECIO HECHO" in t or "FIJAR PRECIO" in t or t in {"PH", "FP"}:
            out.append(o)
    return out


# ── MINAGRI ──────────────────────────────────────────────────────────────────

def cargar_minagri(json_path: Path) -> list[dict]:
    if not json_path.exists():
        return []
    return json.loads(json_path.read_text(encoding="utf-8")).get("serie", [])


def _interp_acum(serie: list[dict], target: date) -> float:
    if not serie:
        return 0.0
    pts = [(date.fromisoformat(p["fecha"]), float(p["ph_fijado_acum_kt"])) for p in serie]
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


def delta_minagri_mes(serie: list[dict], year: int, month: int) -> int:
    inicio = date(year, month, 1)
    fin = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    delta_kt = _interp_acum(serie, fin) - _interp_acum(serie, inicio)
    return int(round(max(0.0, delta_kt) * 1000))


# ── Construcción de la matriz ────────────────────────────────────────────────

def construir_matriz(ops: list[Operacion], hoy: date, cultivo_cfg: dict,
                      ops_nc: list[Operacion] | None = None) -> list[dict]:
    """Construye la matriz del cultivo.

    ops:    operaciones de la cosecha "actual" (cfg["cosecha"]).
            Se reparten en los delivery_groups normales, EXCLUYENDO el bucket NC.
    ops_nc: operaciones de la cosecha "nueva" (cfg["cosecha_nc"]) — opcional.
            TODAS van al bucket NC (sin importar la fecha de entrega), ya que
            representan forward sales de la cosecha que aún no se cosechó.
            Si el cultivo no tiene grupo "NC", se ignora.
    """
    ops_nc = ops_nc or []
    minagri = cargar_minagri(SCRIPT_DIR / minagri_json_path(cultivo_cfg))
    grupos = cultivo_cfg["grupos"]
    has_nc = "NC" in grupos
    base = {g: 0 for g in grupos}
    filas: list[dict] = []

    # ── Mensuales ─────────────────────────────────────────────────────────
    primer = cultivo_cfg["primer_mes_mensual"]
    hasta  = mes_anterior(hoy)
    for (y, m) in meses_mensuales(primer, hasta):
        sio = base.copy()
        # Pass 1: operaciones cosecha actual → reparto por delivery group (sin NC)
        for o in ops:
            if o.fecha_conc.year == y and o.fecha_conc.month == m:
                g = grupo_de_entrega(o.fecha_desde, cultivo_cfg)
                if g and g != "NC":
                    sio[g] += o.cant_tn
        # Pass 2: operaciones cosecha NC → todo a "NC"
        if has_nc:
            for o in ops_nc:
                if o.fecha_conc.year == y and o.fecha_conc.month == m:
                    sio["NC"] += o.cant_tn

        # MINAGRI×split aplica solo a la cosecha actual (NC es otro universo)
        total_actual = sum(sio[g] for g in grupos if g != "NC")
        total_minagri = delta_minagri_mes(minagri, y, m)

        if total_minagri > 0 and total_actual > 0:
            cells = {g: int(round(total_minagri * (sio[g] / total_actual)))
                     for g in grupos if g != "NC"}
            if has_nc:
                cells["NC"] = int(round(sio["NC"]))  # NC queda como raw SIO
            fuente = "MINAGRI×split SIO"
        else:
            cells = {g: int(round(sio[g])) for g in grupos}
            total_any = total_actual + (sio.get("NC", 0) if has_nc else 0)
            fuente = "SIO crudo" if total_any > 0 else "vacío"

        filas.append({
            "tipo": "mensual", "label": label_mes(y, m),
            **cells, "total": sum(cells.values()),
            "low": False, "prior": False, "min": total_minagri,
            "_fuente": fuente,
        })

    # ── Diarios del "mes en curso" si está configurado ────────────────────
    # Freeze line: el último día cubierto por MINAGRI. Los días <= last_min en
    # el mes en curso se escalan por MINAGRI/SIO para que su total ≡ MINAGRI
    # (más confiable que SIO crudo, que sub-reporta ventas tardías). Los días
    # posteriores quedan en SIO crudo. NC nunca se escala (otra cosecha).
    daily = cultivo_cfg.get("daily_mes")
    if daily:
        y, m = daily["year"], daily["month"]

        # Computar la freeze line y el factor de escala (por mes en curso)
        last_min_date = None
        if minagri:
            try:
                last_min_date = max(
                    date.fromisoformat(p["fecha"]) for p in minagri
                    if p.get("fecha")
                )
            except Exception:
                last_min_date = None

        freeze_scale = 1.0
        minagri_freeze_tn = 0.0
        sio_freeze_total  = 0.0
        if last_min_date is not None and last_min_date >= date(y, m, 1):
            # MINAGRI delta entre fin de mes anterior y last_min_date
            from datetime import timedelta as _td
            ini_mes = date(y, m, 1)
            fin_mes_ant = ini_mes - _td(days=1)
            acum_cutoff = _interp_acum(minagri, last_min_date)
            acum_ini    = _interp_acum(minagri, fin_mes_ant)
            minagri_freeze_tn = max(0.0, (acum_cutoff - acum_ini)) * 1000.0

            # SIO total (non-NC) en la ventana frozen
            for o in ops:
                if (o.fecha_conc.year == y and o.fecha_conc.month == m
                        and ini_mes <= o.fecha_conc <= last_min_date):
                    g = grupo_de_entrega(o.fecha_desde, cultivo_cfg)
                    if g and g != "NC":
                        sio_freeze_total += o.cant_tn

            if minagri_freeze_tn > 0 and sio_freeze_total > 0:
                freeze_scale = minagri_freeze_tn / sio_freeze_total

        for d_label in daily["dias_habiles"]:
            dd, mm = d_label.split("/")
            d = date(y, int(mm), int(dd))
            if d > hoy:
                break
            agg = base.copy()
            is_frozen = (last_min_date is not None and d <= last_min_date)
            # Pass 1: cosecha actual — escalar si día frozen
            scale = freeze_scale if is_frozen else 1.0
            for o in ops:
                if o.fecha_conc == d:
                    g = grupo_de_entrega(o.fecha_desde, cultivo_cfg)
                    if g and g != "NC":
                        agg[g] += o.cant_tn * scale
            # Pass 2: cosecha NC → todo a NC (SIN escalar)
            if has_nc:
                for o in ops_nc:
                    if o.fecha_conc == d:
                        agg["NC"] += o.cant_tn
            agg_int = {g: int(round(agg[g])) for g in grupos}
            # min: contribución MINAGRI atribuida a ese día (frozen) o 0
            day_min = int(round(
                sum(agg_int[g] for g in grupos if g != "NC")
            )) if is_frozen else 0
            filas.append({
                "tipo": "diario", "label": d_label,
                **agg_int, "total": sum(agg_int.values()),
                "low": False, "prior": False, "min": day_min,
            })

    return filas


def construir_destinos(ops: list[Operacion], cultivo_cfg: dict) -> list[dict]:
    """CSV paralelo: tn por (mes_concertacion, destino).
    Solo cuenta operaciones que caen en alguno de los buckets de delivery
    (MAM/JJ/AS/OND/JF para maíz/sorgo, NDJ/FMA/MJJ/ASO para trigo/cebada),
    para que los totales coincidan con la matriz mensual."""
    from destinos import categorizar, DESTINOS

    primer = cultivo_cfg["primer_mes_mensual"]
    if not ops:
        return []
    fecha_max = max(o.fecha_conc for o in ops)
    hasta = (fecha_max.year, fecha_max.month)

    filas: list[dict] = []
    base = {d: 0.0 for d in DESTINOS}
    for (y, m) in meses_mensuales(primer, hasta):
        agg = base.copy()
        for o in ops:
            if o.fecha_conc.year == y and o.fecha_conc.month == m:
                # Filtro: solo si la entrega cae en algún bucket de delivery
                if grupo_de_entrega(o.fecha_desde, cultivo_cfg) is None:
                    continue
                d = categorizar(o.lugar_entrega)
                agg[d] += o.cant_tn
        agg_int = {d: int(round(agg[d])) for d in DESTINOS}
        filas.append({"label": label_mes(y, m), **agg_int,
                      "total": sum(agg_int.values())})
    return filas


def construir_origenes(ops: list[Operacion]) -> list[dict]:
    """CSV de orígenes: por (fecha_conc, provincia, localidad) sumamos tn."""
    from collections import defaultdict
    bucket = defaultdict(float)
    for o in ops:
        pcia = (o.procedencia_pcia or "").strip().upper()
        loc  = (o.procedencia_loc or "").strip().upper() or "(sin localidad)"
        if not pcia:
            continue
        bucket[(o.fecha_conc.isoformat(), pcia, loc)] += o.cant_tn
    return [{"fecha": k[0], "provincia": k[1], "localidad": k[2], "tn": int(round(v))}
            for k, v in sorted(bucket.items())]


def escribir_origenes(filas: list[dict], path: Path) -> None:
    cols = ["fecha", "provincia", "localidad", "tn"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for fila in filas:
            w.writerow({k: fila.get(k, 0) for k in cols})


def construir_matriz_solo_sio(ops: list[Operacion], hoy: date, cultivo_cfg: dict,
                                ops_nc: list[Operacion] | None = None) -> list[dict]:
    """Versión SIN MINAGRI×split (solo SIO crudo). Mismo split NC que construir_matriz."""
    ops_nc = ops_nc or []
    grupos = cultivo_cfg["grupos"]
    has_nc = "NC" in grupos
    base = {g: 0 for g in grupos}
    filas: list[dict] = []

    primer = cultivo_cfg["primer_mes_mensual"]
    hasta = mes_anterior(hoy)
    for (y, m) in meses_mensuales(primer, hasta):
        sio = base.copy()
        for o in ops:
            if o.fecha_conc.year == y and o.fecha_conc.month == m:
                g = grupo_de_entrega(o.fecha_desde, cultivo_cfg)
                if g and g != "NC":
                    sio[g] += o.cant_tn
        if has_nc:
            for o in ops_nc:
                if o.fecha_conc.year == y and o.fecha_conc.month == m:
                    sio["NC"] += o.cant_tn
        cells = {g: int(round(sio[g])) for g in grupos}
        filas.append({
            "tipo": "mensual", "label": label_mes(y, m),
            **cells, "total": sum(cells.values()),
            "low": False, "prior": False, "min": 0,
        })

    daily = cultivo_cfg.get("daily_mes")
    if daily:
        for d_label in daily["dias_habiles"]:
            dd, mm = d_label.split("/")
            d = date(daily["year"], int(mm), int(dd))
            if d > hoy:
                break
            agg = base.copy()
            for o in ops:
                if o.fecha_conc == d:
                    g = grupo_de_entrega(o.fecha_desde, cultivo_cfg)
                    if g and g != "NC":
                        agg[g] += o.cant_tn
            if has_nc:
                for o in ops_nc:
                    if o.fecha_conc == d:
                        agg["NC"] += o.cant_tn
            agg_int = {g: int(round(agg[g])) for g in grupos}
            filas.append({
                "tipo": "diario", "label": d_label,
                **agg_int, "total": sum(agg_int.values()),
                "low": False, "prior": False, "min": 0,
            })
    return filas


def escribir_destinos(filas: list[dict], path: Path) -> None:
    from destinos import DESTINOS
    cols = ["label", *DESTINOS, "total"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for fila in filas:
            w.writerow({k: fila.get(k, 0) for k in cols})


def escribir_matriz(filas: list[dict], path: Path, grupos: list[str]) -> None:
    cols = ["tipo", "label", *grupos, "total", "low", "prior", "min"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for fila in filas:
            row = {k: fila[k] for k in cols}
            row["low"] = "True" if row["low"] else "False"
            row["prior"] = "True" if row["prior"] else "False"
            w.writerow(row)


# ── CLI ───────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Genera la matriz FS de un cultivo.")
    p.add_argument("--sio", required=True, help="CSV histórico de SIO (compartido).")
    p.add_argument("--cultivo", default="maiz",
                   help=f"slug del cultivo. Opciones: {list(CULTIVOS)}")
    p.add_argument("--copiar-a", default=None,
                   help="Directorio destino opcional (ej. una copia en OneDrive).")
    p.add_argument("--hoy", default=None, help="Override fecha hoy YYYY-MM-DD (testing).")
    args = p.parse_args(argv)

    cfg = get_cultivo(args.cultivo)
    hoy = parse_fecha(args.hoy) if args.hoy else date.today()
    if hoy is None:
        _log("Fecha --hoy inválida."); return 2

    sio_path = Path(args.sio).expanduser()
    if not sio_path.exists():
        _log(f"No existe el archivo SIO: {sio_path}"); return 2

    ops_raw  = leer_sio(sio_path)
    ops_prod = filtrar_producto(ops_raw, cfg["sio_producto"])
    ops_cos  = filtrar_cosecha(ops_prod, cfg["cosecha"])
    ops      = filtrar_tipo(ops_cos)
    _log(f"{cfg['label']}: {len(ops_raw)} → {len(ops_prod)} (Producto={cfg['sio_producto']}) "
         f"→ {len(ops_cos)} (Cosecha={cfg['cosecha']}) → {len(ops)} (PH/FP)")

    # NC: operaciones de la cosecha siguiente (forward sales). Solo si cfg lo define.
    ops_nc: list[Operacion] = []
    if cfg.get("cosecha_nc"):
        ops_nc_cos = filtrar_cosecha(ops_prod, cfg["cosecha_nc"])
        ops_nc     = filtrar_tipo(ops_nc_cos)
        _log(f"  NC ({cfg['cosecha_nc']}): {len(ops_nc_cos)} → {len(ops_nc)} (PH/FP)")

    filas = construir_matriz(ops, hoy, cfg, ops_nc=ops_nc)
    matriz_path = DATA_DIR / cfg["matriz_csv"]
    escribir_matriz(filas, matriz_path, cfg["grupos"])
    _log(f"Escrito: {matriz_path}")

    # Compat: maíz también escribe matriz_fs.csv (la app vieja lo carga)
    if cfg["matriz_csv"] == "matriz_maiz.csv":
        escribir_matriz(filas, DATA_DIR / "matriz_fs.csv", cfg["grupos"])
        _log("Escrito: data/matriz_fs.csv (alias legacy)")

    # CSV paralelo: desglose por destino (Up River / Bahía / Necochea / Interior)
    filas_dest = construir_destinos(ops, cfg)
    slug_cultivo = cfg["matriz_csv"].replace("matriz_", "destinos_")
    dest_path = DATA_DIR / slug_cultivo
    escribir_destinos(filas_dest, dest_path)
    _log(f"Escrito: {dest_path}  ({len(filas_dest)} meses)")

    # Matrices por destino (solo SIO crudo, sin MINAGRI). Para la pestaña
    # "Matriz por destino" donde se selecciona una combinación de destinos.
    from destinos import categorizar, DESTINOS
    for dest in DESTINOS:
        ops_dest    = [o for o in ops    if categorizar(o.lugar_entrega) == dest]
        ops_nc_dest = [o for o in ops_nc if categorizar(o.lugar_entrega) == dest]
        filas_d = construir_matriz_solo_sio(ops_dest, hoy, cfg, ops_nc=ops_nc_dest)
        p_dest = DATA_DIR / cfg["matriz_csv"].replace(".csv", f"_{dest}.csv")
        escribir_matriz(filas_d, p_dest, cfg["grupos"])
    _log(f"Matrices por destino escritas: 4 × {cfg['label']}")

    # CSV de orígenes (provincia × fecha) para el mapa coroplético.
    filas_orig = construir_origenes(ops)
    orig_path = DATA_DIR / cfg["matriz_csv"].replace("matriz_", "origenes_")
    escribir_origenes(filas_orig, orig_path)
    _log(f"Escrito: {orig_path}  ({len(filas_orig)} filas)")

    if args.copiar_a:
        destino = Path(args.copiar_a).expanduser()
        destino.mkdir(parents=True, exist_ok=True)
        sub = destino / "data" if (destino / "app.py").exists() else destino
        sub.mkdir(parents=True, exist_ok=True)
        shutil.copy2(matriz_path, sub / cfg["matriz_csv"])
        _log(f"Copiado a: {sub / cfg['matriz_csv']}")

    print()
    print("Resumen:")
    for f in filas:
        if f["tipo"] != "diario":
            grupos_str = "  ".join(f"{g}={f[g]:>9}" for g in cfg["grupos"])
            print(f"  [{f['tipo']:<11}] {f['label']:<15} {grupos_str}  total={f['total']:>10}  "
                  f"min={f['min']:>9}  {f.get('_fuente','')}")
    n_diarios = sum(1 for f in filas if f["tipo"] == "diario")
    if n_diarios:
        print(f"  ({n_diarios} filas diarias generadas, fuente: SIO crudo)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
