"""
descargar_sio.py — Descarga CSV de SIO Granos automáticamente (Playwright headless).

Página: https://www.siogranos.com.ar/Consulta_publica/operaciones_informadas_exportar.aspx

Filtros base aplicados (verificados en vivo):
    Es Final   = SI                     (ddlEsDestinoFinal = "1")
    Precio/Monto >= 20                  (txtPrecioTN, evita basura)
    Producto/Tipo/Precio = TODOS        (se filtran después en actualizar_fs.py)

IDs útiles del form:
    ddlEsDestinoFinal       Es Final           (TODOS=, NO=0, SI=1)
    txtPrecioTN             Precio/Monto Mayor o Igual
    txtFechaConcertacionDesde / Hasta    rango Fecha Concertación
    btn_generar_csv         botón GENERAR ARCHIVO

SIO restringe la consulta a 180 días por petición. Para back-fill histórico
usamos --backfill-desde, que parte el rango en chunks <= 180 días, descarga
cada uno y concatena en un único CSV.

Uso:
    python descargar_sio.py                                     # último 180d → ~/Downloads/sio.csv
    python descargar_sio.py --out /tmp/sio.csv                  # otra ruta
    python descargar_sio.py --debug                             # browser visible
    python descargar_sio.py --discover                          # imprime DOM y sale
    python descargar_sio.py --desde 2026-01-01 --hasta 2026-04-30
    python descargar_sio.py --backfill-desde 2025-03-01 --out data/sio_historico.csv
"""
from __future__ import annotations

import argparse
import io
import sys
from datetime import date, timedelta
from pathlib import Path

URL = "https://www.siogranos.com.ar/Consulta_publica/operaciones_informadas_exportar.aspx"

CHUNK_DAYS = 175    # margen sobre el límite de 180

# Filtros base
FILTROS_BASE = {
    "ddlEsDestinoFinal": "1",   # SI
    "txtPrecioTN":       "20",
}
BTN_EXPORTAR = "#btn_generar_csv"


def _parse_iso(s: str) -> date:
    return date.fromisoformat(s)


def _chunks_de_180(desde: date, hasta: date, chunk_days: int = CHUNK_DAYS):
    """Devuelve [(d1, d2), ...] cubriendo [desde, hasta] con chunks <= chunk_days."""
    out = []
    cur = desde
    while cur <= hasta:
        nxt = min(cur + timedelta(days=chunk_days - 1), hasta)
        out.append((cur, nxt))
        cur = nxt + timedelta(days=1)
    return out


def _aplicar_filtros(page, filtros: dict[str, str]) -> None:
    # Espera a que el form esté completamente listo (algunos selects cargan opciones por AJAX)
    page.wait_for_function(
        "document.getElementById('ddlEsDestinoFinal') && "
        "document.getElementById('ddlEsDestinoFinal').options.length > 1",
        timeout=30_000,
    )
    for sel_id, valor in filtros.items():
        if valor is None:
            continue
        el = page.locator(f"#{sel_id}")
        tag = el.evaluate("e => e.tagName")
        readonly = el.evaluate("e => e.readOnly === true || e.hasAttribute('readonly')")

        # Retry hasta 3 veces ante flakiness
        last_err = None
        for intento in range(3):
            try:
                if tag == "SELECT":
                    el.select_option(value=valor, timeout=15_000)
                elif readonly:
                    # Inputs readonly (ej. datepicker jQuery UI): set vía JS + dispatch change
                    page.evaluate(
                        """({sel, val}) => {
                            const el = document.getElementById(sel);
                            el.value = val;
                            el.dispatchEvent(new Event('input',  {bubbles: true}));
                            el.dispatchEvent(new Event('change', {bubbles: true}));
                        }""",
                        {"sel": sel_id, "val": valor},
                    )
                else:
                    el.fill(valor, timeout=15_000)
                last_err = None
                break
            except Exception as e:
                last_err = e
                page.wait_for_timeout(1_000)
        if last_err:
            raise last_err
        print(f"[sio] {sel_id} = {valor}  ✓", flush=True)


def _click_y_capturar_download(page, dest: Path) -> Path:
    import shutil as _sh
    print(f"[sio] click en GENERAR ARCHIVO ...", flush=True)
    with page.expect_download(timeout=300_000) as dl_info:
        try:
            page.locator(BTN_EXPORTAR).click(no_wait_after=True, timeout=10_000)
        except Exception:
            page.evaluate("__doPostBack('btn_generar_csv','')")
    download = dl_info.value
    # download.path() bloquea hasta que el download termina y devuelve la ruta
    # del archivo en el cache temporal de Playwright. Más confiable que save_as
    # para archivos grandes.
    src = download.path()
    if src is None:
        # En algunos modos save_as funciona y path() no — fallback
        download.save_as(str(dest))
    else:
        _sh.copy2(src, dest)
    size = dest.stat().st_size if dest.exists() else 0
    print(f"[sio] guardado: {dest}  ({size:,} bytes)", flush=True)
    return dest


def descargar(out_path: Path, headless: bool = True, slow_mo: int = 0,
              modo_discover: bool = False,
              desde: date | None = None, hasta: date | None = None) -> Path:
    """Descarga UN CSV con los filtros base + opcionalmente un rango de fechas."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Falta Playwright. Corré:  make setup", file=sys.stderr); raise

    out_path = out_path.expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    filtros = dict(FILTROS_BASE)
    if desde:
        filtros["txtFechaConcertacionDesde"] = desde.strftime("%d/%m/%Y")
    if hasta:
        filtros["txtFechaConcertacionHasta"] = hasta.strftime("%d/%m/%Y")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless, slow_mo=slow_mo)
        ctx = browser.new_context(accept_downloads=True)
        page = ctx.new_page()
        try:
            print(f"[sio] navegando a {URL}", flush=True)
            # `domcontentloaded` en lugar de `networkidle`: SIO es ASP.NET con
            # polling/postbacks que nunca dejan la red "idle", lo cual hace que
            # `networkidle` se cuelgue desde conexiones con latencia (ej. GitHub
            # Actions). Después `_aplicar_filtros` espera explícitamente a que
            # el dropdown tenga opciones, así que no perdemos garantías.
            page.goto(URL, wait_until="domcontentloaded", timeout=90_000)
            if modo_discover:
                _discover(page); return out_path
            _aplicar_filtros(page, filtros)
            _click_y_capturar_download(page, out_path)
            return out_path
        finally:
            ctx.close(); browser.close()


def backfill(desde: date, hasta: date, out_path: Path,
             headless: bool = True, slow_mo: int = 0) -> Path:
    """Baja todo el rango [desde, hasta] en chunks <= 180 días, concatena en un solo CSV."""
    chunks = _chunks_de_180(desde, hasta)
    print(f"[sio] backfill {desde} → {hasta}  en {len(chunks)} chunks", flush=True)
    out_path = out_path.expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    tmp_dir = out_path.parent / "_sio_chunks"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    archivos: list[Path] = []
    for i, (d1, d2) in enumerate(chunks, 1):
        f = tmp_dir / f"chunk_{i:02d}_{d1.isoformat()}_{d2.isoformat()}.csv"
        if f.exists() and f.stat().st_size > 0:
            print(f"[sio] === chunk {i}/{len(chunks)}: {d1} → {d2}  (ya existe, salto)", flush=True)
            archivos.append(f); continue
        print(f"\n[sio] === chunk {i}/{len(chunks)}: {d1} → {d2} ===", flush=True)
        descargar(f, headless=headless, slow_mo=slow_mo, desde=d1, hasta=d2)
        archivos.append(f)

    # Concatenar: header del primer archivo + filas de todos
    print(f"\n[sio] concatenando {len(archivos)} archivos en {out_path}", flush=True)
    concatenar_csvs_utf16(archivos, out_path)

    # Limpieza opcional de chunks: los dejamos por trazabilidad. El usuario los puede borrar.
    print(f"[sio] backfill completo. Chunks en {tmp_dir}", flush=True)
    return out_path


def concatenar_csvs_utf16(archivos: list[Path], out_path: Path) -> None:
    """Concatena varios CSVs UTF-16-LE preservando el header solo del primero."""
    out_text_parts: list[str] = []
    for i, f in enumerate(archivos):
        raw = f.read_bytes()
        # tolerante: BOM o sin BOM
        for enc in ("utf-16", "utf-16-le", "utf-8-sig", "utf-8", "latin-1"):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            print(f"  ⚠ no pude decodificar {f}, salteo", flush=True); continue
        lines = text.splitlines(keepends=True)
        if not lines:
            continue
        if i == 0:
            out_text_parts.extend(lines)
        else:
            out_text_parts.extend(lines[1:])  # sin header
    out_text = "".join(out_text_parts)
    out_path.write_bytes(out_text.encode("utf-16-le"))
    print(f"  ✓ {sum(1 for p in out_text_parts):,} líneas → {out_path}", flush=True)


def _discover(page) -> None:
    info = page.evaluate("""() => {
        const out = {selects:{}, inputs:[], buttons:[]};
        document.querySelectorAll('select').forEach(s => {
            out.selects[s.id || s.name] = {
                id: s.id, name: s.name,
                options: [...s.options].map(o => o.text + '=' + o.value)
            };
        });
        document.querySelectorAll('input').forEach(i => {
            if (i.type === 'hidden') return;
            if (i.id || i.name) out.inputs.push({
                id: i.id, name: i.name, type: i.type, value: i.value
            });
        });
        document.querySelectorAll('button, input[type=submit], input[type=button]')
            .forEach(b => out.buttons.push({
                tag: b.tagName, id: b.id, value: b.value,
                text: (b.textContent || '').trim().slice(0, 40)
            }));
        return out;
    }""")
    print("\n=== <select> ===")
    for k, v in info["selects"].items():
        print(f"  #{k}  options={v['options']}")
    print("\n=== <input> ===")
    for i in info["inputs"]:
        print(f"  type={i['type']:<8}  id={i['id']!r}  name={i['name']!r}  value={i['value']!r}")
    print("\n=== <button> ===")
    for b in info["buttons"]:
        print(f"  {b['tag']:<6}  id={b['id']!r}  value={b['value']!r}  text={b['text']!r}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Baja CSV de SIO Granos.")
    p.add_argument("--out", default=str(Path.home() / "Downloads" / "sio.csv"),
                   help="Ruta destino (default: ~/Downloads/sio.csv).")
    p.add_argument("--debug", action="store_true", help="Browser visible.")
    p.add_argument("--discover", action="store_true", help="Imprime DOM y sale.")
    p.add_argument("--desde", help="Fecha de Concertación Desde (YYYY-MM-DD).")
    p.add_argument("--hasta", help="Fecha de Concertación Hasta (YYYY-MM-DD).")
    p.add_argument("--backfill-desde",
                   help="Activa modo backfill: parte en chunks de 180d desde "
                        "esta fecha hasta hoy.")
    p.add_argument("--backfill-hasta",
                   help="Fecha final del backfill (default: hoy).")
    args = p.parse_args(argv)

    out = Path(args.out).expanduser().resolve()
    headless = not args.debug
    slow_mo = 200 if args.debug else 0

    if args.backfill_desde:
        desde = _parse_iso(args.backfill_desde)
        hasta = _parse_iso(args.backfill_hasta) if args.backfill_hasta else date.today()
        backfill(desde, hasta, out, headless=headless, slow_mo=slow_mo)
        return 0

    desde = _parse_iso(args.desde) if args.desde else None
    hasta = _parse_iso(args.hasta) if args.hasta else None
    descargar(out, headless=headless, slow_mo=slow_mo,
              modo_discover=args.discover, desde=desde, hasta=hasta)
    return 0


if __name__ == "__main__":
    sys.exit(main())
