"""
actualizar_minagri.py — Chequea si MAGYP publicó datos nuevos de "Compras del
Sector Exportador" (Maíz 25/26) y, si sí, agrega un punto a
data/minagri_historico.json.

Estructura real de la fuente (verificada en vivo el 08/05/26):

  Página índice (https://...2026/2026.php):
      Tabla con celdas que linkean a 01_embarque_YYYY-MM-DD.php
      Los <a> tienen href="javascript:window.open('REAL_URL'); ..."

  Página semanal (01_embarque_YYYY-MM-DD.php):
      Tabs: Trigo | Maíz | Sorgo | Cebada Cervecera | Cebada Forrajera | Soja | Girasol
      Tabla con columnas:
          Cosecha | Semanal | Total Comprado | Total Precio Hecho |
          Total a Fijar | Total Fijado | Saldo a Fijar | DJVE Acumulado
      Filas: "Compras Sector Exportador", "Compras de la Industria", "Total"
      Sub-filas por cosecha: 25/26 y 24/25 (etc.)
      Datos en miles de toneladas. Coma decimal AR.

Lo que extraemos: PH + Fijado del Maíz 25/26 en "Compras Sector Exportador".

Uso:
    python actualizar_minagri.py             # corre, agrega punto si hay archivo nuevo
    python actualizar_minagri.py --force     # ignora cache, reparsea siempre
    python actualizar_minagri.py --discover  # imprime lo que encuentra y sale
    python actualizar_minagri.py --cultivo Trigo --cosecha 25/26   # otro cultivo
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urljoin

SCRIPT_DIR = Path(__file__).resolve().parent
DATA_DIR = SCRIPT_DIR / "data"
MINAGRI_PATH = DATA_DIR / "minagri_historico.json"  # legacy: maíz cuando no hay --json-out

BASE_URL = (
    "https://www.magyp.gob.ar/sitio/areas/ss_mercados_agropecuarios/"
    "areas/granos/_archivos/000058_Estad%C3%ADsticas/_compras_historicos"
)
PAGE_URL = f"{BASE_URL}/2026/2026.php"  # default: año actual

def page_url_for_year(year: int) -> str:
    return f"{BASE_URL}/{year}/{year}.php"


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

def _log(msg: str) -> None:
    print(f"[minagri] {msg}", flush=True)


def _strip_accents(s: str) -> str:
    s = unicodedata.normalize("NFD", str(s))
    return "".join(c for c in s if unicodedata.category(c) != "Mn").upper().strip()


def _to_float_ar(v) -> float | None:
    """Convierte '16.101,7', '7973,8', '1.486,5' (formato AR) a float.
    Devuelve None si no es número, está en blanco, es '-', o está entre paréntesis
    (lo que indica el comparativo de la cosecha anterior, que ignoramos)."""
    if v is None:
        return None
    s = str(v).replace("\xa0", " ").strip()
    if not s or s == "-":
        return None
    # Si el valor está completamente entre paréntesis (ej. "(853,1)"), es comparativo.
    if s.startswith("(") and s.endswith(")"):
        return None
    # Quitamos anotaciones inline tipo (*) que sí son válidas
    s = re.sub(r"\([^)]*\)", "", s).strip()
    if not s:
        return None
    # AR: punto = miles, coma = decimal
    if re.fullmatch(r"-?\d{1,3}(?:\.\d{3})+(?:,\d+)?", s):
        return float(s.replace(".", "").replace(",", "."))
    if re.fullmatch(r"-?\d+(?:,\d+)?", s):           # sin separador de miles, con o sin decimal
        return float(s.replace(",", "."))
    if re.fullmatch(r"-?\d+(?:\.\d+)?", s):           # formato US plano (fallback)
        return float(s)
    return None


def _http_get(url: str) -> bytes:
    try:
        import httpx
    except ImportError:
        print("Falta httpx. Corré:  make setup", file=sys.stderr)
        raise
    with httpx.Client(follow_redirects=True, timeout=60.0,
                      headers={"User-Agent": "fs-maiz/1.0"}) as c:
        r = c.get(url)
        r.raise_for_status()
        return r.content


# ---------------------------------------------------------------------------
# Página índice → URL del último embarque
# ---------------------------------------------------------------------------

# Regex para extraer la URL de href="javascript:NewWindow=window.open('REAL_URL', ...
_RE_WINDOW_OPEN = re.compile(r"window\.open\(['\"]([^'\"]+)['\"]")
_RE_FECHA_EMBARQUE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


def _parse_index_links(html: bytes) -> list[tuple[str, date]]:
    """Versión legacy con base PAGE_URL (default). Kept for tests."""
    return _parse_index_links_relative(html, PAGE_URL)


def _fecha_de_url(url: str) -> date | None:
    m = _RE_FECHA_EMBARQUE.search(url)
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def _fecha_de_texto(s: str) -> date | None:
    m = re.search(r"(\d{2})/(\d{2})/(\d{4})", s)
    if m:
        try:
            return datetime.strptime(m.group(0), "%d/%m/%Y").date()
        except ValueError:
            return None
    return None


def encontrar_ultimo_embarque(year: int | None = None) -> tuple[str, date]:
    url_idx = page_url_for_year(year) if year else PAGE_URL
    _log(f"GET {url_idx}")
    html = _http_get(url_idx)
    links = _parse_index_links_relative(html, url_idx)
    if not links:
        raise RuntimeError(f"No encontré links de embarques en {url_idx}.")
    links.sort(key=lambda x: x[1], reverse=True)
    url, f = links[0]
    _log(f"último embarque: {f.isoformat()}  →  {url}")
    return url, f


def listar_embarques_de_anio(year: int) -> list[tuple[str, date]]:
    """Devuelve todos los (url, fecha) de embarques publicados en el año dado."""
    url_idx = page_url_for_year(year)
    _log(f"GET {url_idx}")
    html = _http_get(url_idx)
    return _parse_index_links_relative(html, url_idx)


def _parse_index_links_relative(html: bytes, base_url: str) -> list[tuple[str, date]]:
    """Versión que resuelve URLs relativas contra base_url."""
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        print("Falta beautifulsoup4. Corré:  make setup", file=sys.stderr)
        raise
    soup = BeautifulSoup(html, "html.parser")
    out: list[tuple[str, date]] = []
    for a in soup.find_all("a", href=True):
        m = _RE_WINDOW_OPEN.search(a["href"])
        if not m:
            continue
        target = m.group(1)
        fecha = _fecha_de_url(target) or _fecha_de_texto(a.get_text())
        if fecha is None:
            continue
        out.append((urljoin(base_url, target), fecha))
    return out


# ---------------------------------------------------------------------------
# Página semanal → PH + Fijado del cultivo / cosecha
# ---------------------------------------------------------------------------

def _panel_para_cultivo(html_bytes: bytes, cultivo: str):
    """MAGYP usa Spry framework: .TabbedPanelsTab y .TabbedPanelsContent en orden.
    Encuentra el índice del tab por texto y devuelve el panel correspondiente."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html_bytes, "html.parser")
    target = _strip_accents(cultivo)
    tabs = soup.select(".TabbedPanelsTab")
    panels = soup.select(".TabbedPanelsContent")
    if not tabs or not panels:
        return None
    for i, tab in enumerate(tabs):
        if _strip_accents(tab.get_text()) == target and i < len(panels):
            return panels[i]
    return None


def _tabla_del_panel(panel) -> "BeautifulSoup":
    table = panel.find("table") if panel else None
    if table is None:
        raise RuntimeError("No encontré <table> dentro del panel.")
    return table


def _parse_tabla(table) -> list[list[str]]:
    """Devuelve la tabla como lista de filas con celdas como texto plano."""
    out: list[list[str]] = []
    for tr in table.find_all("tr"):
        row = []
        for cell in tr.find_all(["td", "th"]):
            row.append(cell.get_text(" ", strip=True))
        if row:
            out.append(row)
    return out


def _indice_columna(headers: list[str], target_keywords: list[str]) -> int | None:
    norm = [_strip_accents(h) for h in headers]
    target = [_strip_accents(t) for t in target_keywords]
    for i, h in enumerate(norm):
        if all(t in h for t in target):
            return i
    return None


def extraer_ph_fijado(html_bytes: bytes,
                      cultivo: str = "Maíz",
                      cosecha: str = "25/26",
                      seccion: str = "Compras Sector Exportador"
                      ) -> tuple[float, float, dict]:
    """Devuelve (ph_kt, fijado_kt, debug). Suma PH+Fijado para el cultivo/cosecha."""
    panel = _panel_para_cultivo(html_bytes, cultivo)
    if panel is not None:
        table = _tabla_del_panel(panel)
    else:
        # fallback: buscar la primera tabla que contenga las columnas que esperamos
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html_bytes, "html.parser")
        table = None
        for t in soup.find_all("table"):
            txt = _strip_accents(t.get_text(" "))
            if "PRECIO HECHO" in txt and "FIJADO" in txt and _strip_accents(cultivo) in txt:
                table = t
                break
        if table is None:
            raise RuntimeError(f"No encontré tabla para el cultivo {cultivo!r}.")

    rows = _parse_tabla(table)
    if not rows:
        raise RuntimeError("Tabla vacía.")

    headers = rows[0]
    col_ph = _indice_columna(headers, ["PRECIO", "HECHO"])
    col_fij = _indice_columna(headers, ["FIJADO"])
    # En esta página: "Total Fijado" tiene la columna correcta;
    # "Saldo a Fijar" también contiene FIJAR pero no FIJADO.
    if col_fij is None:
        col_fij = _indice_columna(headers, ["TOTAL", "FIJAD"])
    if col_ph is None or col_fij is None:
        raise RuntimeError(f"No identifiqué columnas PH/Fijado. Headers={headers}")

    seccion_target = _strip_accents(seccion)
    cosecha_target = cosecha.strip().replace("/", "/")

    ph = fij = None
    matched_row_idx = None
    seccion_actual = ""
    for ri in range(1, len(rows)):
        row = rows[ri]
        # En tablas con rowspan, la primera celda puede ser la sección;
        # algunas filas no la traen y heredan la anterior.
        joined = " | ".join(row)
        if seccion_target in _strip_accents(joined):
            seccion_actual = seccion
        # Buscamos celda con cosecha
        if seccion_actual != seccion:
            continue
        if cosecha_target in joined and not _strip_accents(joined).startswith("TOTAL"):
            ph_v = _to_float_ar(row[col_ph]) if col_ph < len(row) else None
            fij_v = _to_float_ar(row[col_fij]) if col_fij < len(row) else None
            if ph_v is not None and fij_v is not None:
                ph, fij = ph_v, fij_v
                matched_row_idx = ri
                break

    if ph is None or fij is None:
        raise RuntimeError(
            f"No encontré fila para {seccion!r} cosecha {cosecha!r} en {cultivo!r}.\n"
            f"Headers: {headers}\nFilas: {rows[1:]}"
        )

    debug = {
        "headers": headers, "row": rows[matched_row_idx],
        "col_ph": col_ph, "col_fij": col_fij,
        "ph_kt": ph, "fij_kt": fij, "ph_mas_fij_kt": ph + fij,
    }
    return ph, fij, debug


# ---------------------------------------------------------------------------
# JSON state
# ---------------------------------------------------------------------------

JSON_PATH_ACTUAL = MINAGRI_PATH  # se sobreescribe en main() según --json-out


def cargar_json() -> dict:
    if not JSON_PATH_ACTUAL.exists():
        return {"serie": []}
    return json.loads(JSON_PATH_ACTUAL.read_text(encoding="utf-8"))


def guardar_json(data: dict) -> None:
    JSON_PATH_ACTUAL.parent.mkdir(parents=True, exist_ok=True)
    JSON_PATH_ACTUAL.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def backfill(años: list[int], cultivo: str, cosecha: str, seccion: str) -> int:
    """Itera sobre los años, baja TODAS las semanas que falten en el JSON."""
    data = cargar_json()
    fechas_existentes = {pt["fecha"] for pt in data.get("serie", [])}
    nuevos = 0
    todos = []
    for y in años:
        try:
            todos.extend(listar_embarques_de_anio(y))
        except Exception as e:
            _log(f"⚠ Año {y}: {e}")
    todos.sort(key=lambda x: x[1])  # más viejo primero
    _log(f"{len(todos)} embarques publicados en {años}, {len(fechas_existentes)} ya cacheados.")
    for url, fecha in todos:
        f_iso = fecha.isoformat()
        if f_iso in fechas_existentes:
            continue
        try:
            content = _http_get(url)
            if url.lower().endswith(".pdf"):
                _log(f"⚠ {f_iso}: es PDF, salteo.")
                continue
            ph, fij, _ = extraer_ph_fijado(content, cultivo, cosecha, seccion)
            total_kt = ph + fij
            data.setdefault("serie", []).append({
                "fecha": f_iso,
                "ph_fijado_acum_kt": float(round(total_kt, 2)),
                "ph_acum_kt":  float(round(ph, 2)),
                "fij_acum_kt": float(round(fij, 2)),
            })
            fechas_existentes.add(f_iso)
            nuevos += 1
            _log(f"  + {f_iso}: PH={ph} + Fij={fij} = {total_kt} kt")
        except Exception as e:
            _log(f"  ✗ {f_iso}: {e}")
    data["serie"].sort(key=lambda pt: pt["fecha"])
    if data["serie"]:
        data["_actualizado"] = data["serie"][-1]["fecha"]
    guardar_json(data)
    _log(f"Backfill completo: {nuevos} puntos nuevos, {len(data['serie'])} totales.")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Actualiza data/minagri_historico.json desde MAGYP.")
    p.add_argument("--force", action="store_true",
                   help="Ignora cache, reparsea aunque la URL coincida.")
    p.add_argument("--discover", action="store_true",
                   help="Imprime los embarques que encuentra y sale.")
    p.add_argument("--backfill", action="store_true",
                   help="Iterar sobre todos los años y bajar TODAS las semanas históricas.")
    p.add_argument("--anios", default="2025,2026",
                   help="Años a recorrer en --backfill (CSV). Default: 2025,2026.")
    p.add_argument("--cultivo", default="Maíz",
                   help="Tab del MAGYP (Maíz | Sorgo | Trigo | Cebada Cervecera | ...).")
    p.add_argument("--cosecha", default="25/26")
    p.add_argument("--seccion", default="Compras Sector Exportador")
    p.add_argument("--json-out", default=None,
                   help="Path del JSON a escribir. Default: data/minagri_historico.json (legacy).")
    args = p.parse_args(argv)

    global JSON_PATH_ACTUAL
    if args.json_out:
        JSON_PATH_ACTUAL = Path(args.json_out)

    if args.backfill:
        años = [int(x.strip()) for x in args.anios.split(",") if x.strip()]
        return backfill(años, args.cultivo, args.cosecha, args.seccion)

    data = cargar_json()
    last_url = data.get("_last_file_url")
    last_hash = data.get("_last_file_sha1")

    if args.discover:
        html = _http_get(PAGE_URL)
        for url, f in sorted(_parse_index_links(html), key=lambda x: x[1], reverse=True):
            print(f"  {f.isoformat()}  →  {url}")
        return 0

    url, fecha = encontrar_ultimo_embarque()

    if not args.force and url == last_url:
        _log("Sin cambios (URL del último embarque coincide con la cacheada).")
        return 0

    _log(f"Descargando {url}")
    content = _http_get(url)
    sha1 = hashlib.sha1(content).hexdigest()
    if not args.force and sha1 == last_hash:
        _log("Sin cambios (mismo hash). No agrego punto.")
        data["_last_file_url"] = url
        guardar_json(data)
        return 0

    ph, fij, debug = extraer_ph_fijado(content, args.cultivo, args.cosecha, args.seccion)
    total_kt = ph + fij
    _log(f"{args.cultivo} {args.cosecha} ({args.seccion}): "
         f"PH={ph} kt + Fijado={fij} kt = {total_kt} kt")

    f_iso = fecha.isoformat()
    serie = data.get("serie", [])
    serie = [pt for pt in serie if pt["fecha"] != f_iso]
    serie.append({
        "fecha": f_iso,
        "ph_fijado_acum_kt": float(round(total_kt, 2)),
        "ph_acum_kt":  float(round(ph, 2)),
        "fij_acum_kt": float(round(fij, 2)),
    })
    serie.sort(key=lambda pt: pt["fecha"])
    data["serie"] = serie
    data["_actualizado"] = f_iso
    data["_last_file_url"] = url
    data["_last_file_sha1"] = sha1
    guardar_json(data)
    _log(f"Punto agregado: {f_iso} → {total_kt} kt   ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
