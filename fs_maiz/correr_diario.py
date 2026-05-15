"""
correr_diario.py — Orquestador del flujo diario multi-cultivo.

Pasos:
    1. Descarga el CSV de SIO (Playwright, últimos 180 días, todos los productos).
    2. Mergea ese CSV con data/sio_historico.csv (con dedup por fila exacta).
    3. Por cada cultivo configurado:
         a. Chequea MINAGRI (descarga si hay archivo nuevo y agrega punto al JSON específico).
         b. Regenera data/matriz_<cultivo>.csv leyendo del histórico SIO.

Uso:
    python correr_diario.py                           # todos los cultivos
    python correr_diario.py --cultivos maiz,trigo     # solo algunos
    python correr_diario.py --skip-sio                # sin re-bajar SIO
    python correr_diario.py --skip-minagri            # sin chequear MAGYP
"""
from __future__ import annotations

import argparse
import csv
import io
import sys
import traceback
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

DATA_DIR = SCRIPT_DIR / "data"
HISTORICO_PATH = DATA_DIR / "sio_historico.csv"


def _ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _log(msg: str) -> None:
    print(f"{_ts()} {msg}", flush=True)


def _read_utf16(path: Path) -> list[list[str]]:
    raw = path.read_bytes()
    for enc in ("utf-16", "utf-16-le", "utf-8-sig", "utf-8", "latin-1"):
        try:
            text = raw.decode(enc); break
        except UnicodeDecodeError:
            continue
    else:
        raise RuntimeError(f"No pude decodificar {path}")
    return list(csv.reader(io.StringIO(text), delimiter=";", quotechar='"'))


def _write_utf16(rows: list[list[str]], path: Path) -> None:
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", quotechar='"', quoting=csv.QUOTE_MINIMAL)
    for r in rows:
        w.writerow(r)
    path.write_bytes(buf.getvalue().encode("utf-16-le"))


def merge_sio_historico(nuevo_csv: Path, historico_csv: Path) -> tuple[int, int]:
    nuevo = _read_utf16(nuevo_csv)
    if not nuevo:
        return 0, 0
    header_nuevo = nuevo[0]
    if historico_csv.exists():
        viejo = _read_utf16(historico_csv)
        header_viejo = viejo[0] if viejo else header_nuevo
        rows_old = viejo[1:] if viejo else []
    else:
        header_viejo = header_nuevo
        rows_old = []
    seen = set(tuple(r) for r in rows_old)
    nuevas = []
    for r in nuevo[1:]:
        t = tuple(r)
        if t not in seen:
            seen.add(t); nuevas.append(r)
    todas = rows_old + nuevas
    _write_utf16([header_viejo] + todas, historico_csv)
    return len(todas), len(nuevas)


def main(argv: list[str] | None = None) -> int:
    from cultivos import CULTIVOS, get_cultivo, minagri_json_path

    p = argparse.ArgumentParser(description="Orquestador diario FS multi-cultivo.")
    p.add_argument("--sio", default=None,
                   help="CSV ya descargado (en lugar de bajar de SIO).")
    p.add_argument("--skip-sio", action="store_true")
    p.add_argument("--skip-minagri", action="store_true")
    p.add_argument("--skip-prices", action="store_true",
                   help="No correr scrapers de precios (BCR / MAGYP DINEM / CME).")
    p.add_argument("--sio-days", type=int, default=15,
                   help="Cuántos días hacia atrás bajar de SIO (default: 15). "
                        "Para full refresh usar --sio-days 180.")
    p.add_argument("--out-sio", default=str(Path.home() / "Downloads" / "sio.csv"))
    p.add_argument("--cultivos", default=",".join(CULTIVOS.keys()),
                   help=f"CSV de slugs. Default: {','.join(CULTIVOS.keys())}")
    args = p.parse_args(argv)

    cultivos_run = [c.strip() for c in args.cultivos.split(",") if c.strip()]

    _log("=" * 60)
    _log(f"== Inicio corrida diaria FS — cultivos: {cultivos_run}")

    sio_diario = Path(args.sio) if args.sio else Path(args.out_sio)
    n_errores = 0

    # ── Paso 1: SIO ───────────────────────────────────────────────────────
    if args.skip_sio and not args.sio:
        _log(f"== Paso 1 (SIO): saltado por --skip-sio.")
    elif args.sio:
        _log(f"== Paso 1 (SIO): usando archivo provisto {sio_diario}")
        if not sio_diario.exists():
            _log(f"   ✗ No existe {sio_diario}"); n_errores += 1
    else:
        from datetime import date as _d, timedelta as _td
        _hasta = _d.today()
        _desde = _hasta - _td(days=args.sio_days)
        _log(f"== Paso 1 (SIO): descarga últimos {args.sio_days} días "
             f"({_desde.isoformat()} → {_hasta.isoformat()}) → {sio_diario}")
        try:
            from descargar_sio import descargar
            descargar(sio_diario, headless=True, desde=_desde, hasta=_hasta)
            _log(f"   ✓ SIO descargado")
        except Exception as e:
            _log(f"   ✗ SIO falló: {e}"); traceback.print_exc(); n_errores += 1

    # ── Paso 2: merge con histórico ──────────────────────────────────────
    if sio_diario.exists():
        _log(f"== Paso 2 (merge): {sio_diario} → {HISTORICO_PATH}")
        try:
            tot, nuev = merge_sio_historico(sio_diario, HISTORICO_PATH)
            _log(f"   ✓ histórico tiene {tot:,} filas (+{nuev:,} nuevas)")
        except Exception as e:
            _log(f"   ✗ Merge falló: {e}"); traceback.print_exc(); n_errores += 1
    else:
        _log("== Paso 2 (merge): saltado (no hay CSV diario)")

    # ── Paso 3: por cada cultivo ─────────────────────────────────────────
    fuente_sio = HISTORICO_PATH if HISTORICO_PATH.exists() else sio_diario

    for slug in cultivos_run:
        try:
            cfg = get_cultivo(slug)
        except KeyError as e:
            _log(f"⚠ {e}, salteo"); continue

        _log("─" * 60)
        _log(f"=== Cultivo: {cfg['label']} ({slug}) ===")

        # Paso 3a: MINAGRI por cultivo
        if args.skip_minagri:
            _log(f"== MINAGRI {cfg['label']}: saltado por --skip-minagri.")
        else:
            _log(f"== MINAGRI {cfg['label']}: chequeando archivo nuevo")
            try:
                from actualizar_minagri import main as minagri_main
                seccion = cfg.get("magyp_seccion", "Compras Sector Exportador")
                rc = minagri_main([
                    "--cultivo", cfg["magyp_tab"],
                    "--cosecha", cfg["cosecha"],
                    "--seccion", seccion,
                    "--json-out", str(SCRIPT_DIR / minagri_json_path(cfg)),
                ])
                _log("   ✓ MINAGRI OK" if rc == 0 else f"   ⚠ MINAGRI rc={rc}")
            except Exception as e:
                _log(f"   ✗ MINAGRI falló: {e}"); traceback.print_exc(); n_errores += 1

        # Paso 3b: matriz por cultivo
        if not fuente_sio.exists():
            _log(f"== Matriz {cfg['label']}: SKIP — falta CSV de SIO."); n_errores += 1
            continue
        _log(f"== Matriz {cfg['label']}: regenerando desde {fuente_sio}")
        try:
            from actualizar_fs import main as fs_main
            rc = fs_main(["--sio", str(fuente_sio), "--cultivo", slug])
            _log("   ✓ Matriz regenerada" if rc == 0 else f"   ✗ rc={rc}")
            if rc != 0:
                n_errores += 1
        except Exception as e:
            _log(f"   ✗ Matriz falló: {e}"); traceback.print_exc(); n_errores += 1

    # ── Paso 4: Precios (BCR Boletín Diario PDF) ──────────────────────────
    if args.skip_prices:
        _log("== Paso 4 (Precios): saltado por --skip-prices.")
    else:
        _log("─" * 60)
        _log("== Paso 4: BCR Boletín Diario → data/prices.json")
        try:
            from scrapers.bcr_boletin import (
                find_pdf_urls, download_pdf, parse_pdf,
                fetch_pizarra_cac, update_json as _bp_update,
            )
            from pathlib import Path as _Path

            urls = find_pdf_urls(limit=1)
            if not urls:
                _log("   ⚠ No se encontró boletín en la página index")
            else:
                date_str, url = urls[0]
                pdf_path = SCRIPT_DIR / "data" / "boletines" / _Path(url).name
                if pdf_path.exists():
                    _log(f"   → {pdf_path.name} ya existe localmente — reusando")
                else:
                    _log(f"   → bajando {url} ({date_str})")
                    download_pdf(url, pdf_path)
                parsed = parse_pdf(pdf_path)
                # Try CAC pizarra (más fresca, mismo día)
                cac_piz = fetch_pizarra_cac()
                _bp_update(parsed, pizarra_cac=cac_piz, dry_run=False)
                bn = parsed["boletin"]
                _src = "cac" if cac_piz.get("prices") else "boletin"
                _log(f"   ✓ BCR Boletín N°{bn.get('number')} · {bn.get('date_iso')} "
                     f"· pizarra src={_src} (date={cac_piz.get('date') or bn.get('pizarra_date_iso')}) "
                     f"· MAT maíz={len(parsed['mat_usd_tn'].get('maiz', {}))} "
                     f"· MAT trigo={len(parsed['mat_usd_tn'].get('trigo', {}))} "
                     f"· CBOT corn={len(parsed['cbot_usd_tn'].get('corn', {}))} "
                     f"· Minagri={list(parsed['minagri_fob_usd_tn'].keys())}")
        except Exception as e:
            _log(f"   ⚠ BCR Boletín falló: {e} (continúa, otros pasos OK)")
            traceback.print_exc()

    _log("─" * 60)
    _log(f"== Fin corrida — errores: {n_errores}")
    _log("=" * 60)
    return 0 if n_errores == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
