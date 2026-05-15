"""
scrapers/bcr_boletin.py — BCR Boletín Diario de Granos parser.

Extrae todo lo que necesitamos para la sección Prices desde el PDF diario
publicado por BCR (sale ~18:30 hs Argentina):

    Página index:  https://www.bcr.com.ar/es/mercados/boletin-diario/mercado-de-granos
    PDF directo:   https://www.bcr.com.ar/sites/default/files/boletin-mercado-granos-{N}.pdf

Lo que extraemos:
  • Pizarra (USD/tn): trigo, maíz, sorgo, cebada (pág 1, columnas USD)
  • MAT futures (USD/tn) por mes: MAI.ROS/*, TRI.ROS/* (pág 2-3, columna "Ajuste")
  • CBOT futures (USD/tn) por mes: Chicago SRW, Kansas HRW, Maíz (pág 8, tabla "Chicago y Kansas")
  • Minagri FOB (USD/tn): mapeado a slugs (pág 8, primer bloque)
  • TC BNA del día (pág 1)

CLI:
    python -m scrapers.bcr_boletin                   # auto-download latest + parse + update
    python -m scrapers.bcr_boletin --pdf path.pdf    # usar un PDF ya descargado
    python -m scrapers.bcr_boletin --dry-run         # no escribir, solo print
    python -m scrapers.bcr_boletin --list            # listar los últimos 7 boletines de la página

Requiere: httpx, beautifulsoup4, pdfplumber.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date as _date
from pathlib import Path

import httpx

INDEX_URL = "https://www.bcr.com.ar/es/mercados/boletin-diario/mercado-de-granos"
CAC_PIZARRA_URL = "https://www.cac.bcr.com.ar/es/precios-de-pizarra"
DATA_DIR  = Path(__file__).resolve().parent.parent / "data"
PRICES_JSON = DATA_DIR / "prices.json"
PRICES_HISTORY_JSONL = DATA_DIR / "prices_history.jsonl"

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/124.0.0.0 Safari/537.36"),
}

# Map BCR boletín pizarra row (Spanish) → our crop slug
PIZARRA_ROW_TO_SLUG = {
    "Trigo pan":   "trigo",
    "Maíz duro":   "maiz",
    "Sorgo":       "sorgo",
    "Cebada":      "cebada",
}

# Months we care about in CBOT (corn + wheat share same contract calendar).
# Soja has additional contracts (Ene, Ago, Nov) that we exclude here because
# they would produce false positives for corn/wheat (their first 3 columns
# would be empty, but the extracted text just collapses to the soja values).
CBOT_GRAIN_MONTHS = {"Mar", "May", "Jul", "Sep", "Dic"}

# Minagri FOB mapping: product name in boletín → our slug + which column (cercano vs cosecha_nueva)
MINAGRI_MAP = {
    # "Maíz" row has two prices: Cerc=213 Cos.Nva=229 — usamos Cercano por default
    "Maíz":              ("maiz",   "cercano"),
    "Sorgo":             ("sorgo",  "cercano"),
    "Trigo Pan":         ("trigo",  "cercano"),
    "Cebada en grano":   ("cebada", "cercano"),
}


# ─────────────────────────────────────────────────────────────────────────
# 1. Discovery: find latest PDF URL from the index page
# ─────────────────────────────────────────────────────────────────────────

def find_pdf_urls(index_url: str = INDEX_URL, limit: int = 7) -> list[tuple[str, str]]:
    """Returns [(date_str, pdf_url)] for the latest N boletines on the index page.
    date_str is the human "11 de Mayo de 2026"-style text shown next to each link.
    """
    from bs4 import BeautifulSoup
    with httpx.Client(timeout=20.0, headers=HEADERS, follow_redirects=True) as cli:
        r = cli.get(index_url)
        r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    out: list[tuple[str, str]] = []
    # The page shows: title, date heading, "Descargar" link → PDF. Find all PDF anchors.
    for a in soup.find_all("a", href=re.compile(r"boletin-mercado-granos-\d+\.pdf$")):
        href = a["href"]
        if not href.startswith("http"):
            href = "https://www.bcr.com.ar" + href
        # Find the closest preceding text node that looks like a date
        prev_text = ""
        for el in a.find_all_previous(string=True, limit=20):
            t = (el or "").strip()
            if re.match(r"\d{1,2} de \w+ de \d{4}", t):
                prev_text = t
                break
        out.append((prev_text or "?", href))
        if len(out) >= limit:
            break
    return out


def fetch_pizarra_cac() -> dict:
    """Scrapea cac.bcr.com.ar/es/precios-de-pizarra para la pizarra USD/tn
    Rosario MÁS RECIENTE — actualiza el día mismo (~10:30 AM), antes que el
    boletín PDF (que sale ~18:30 con la pizarra de AYER).

    Returns: {'date': 'YYYY-MM-DD', 'prices': {'trigo': 214.10, 'maiz': 189.51, 'sorgo': 200.00}}
    Cebada no se publica acá (BCR CAC no la lista). Retorna {} si falla.
    """
    from bs4 import BeautifulSoup
    BCR_TO_SLUG = {"Trigo": "trigo", "Maíz": "maiz", "Sorgo": "sorgo"}
    try:
        with httpx.Client(timeout=20.0, headers=HEADERS, follow_redirects=True) as cli:
            r = cli.get(CAC_PIZARRA_URL)
            r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
    except Exception as e:
        print(f"⚠ CAC pizarra fetch failed: {e}", file=sys.stderr)
        return {}

    # Fecha del heading "Precios Pizarra del día DD/MM/YYYY"
    page_date = None
    for h in soup.find_all(["h2", "h3", "h4"]):
        text = h.get_text(strip=True)
        m = re.search(r"(\d{2})/(\d{2})/(\d{4})", text)
        if m:
            d, mo, y = m.groups()
            page_date = f"{y}-{mo}-{d}"
            break

    prices: dict = {}
    for h in soup.find_all(["h2", "h3", "h4"]):
        crop_name = h.get_text(strip=True)
        if crop_name not in BCR_TO_SLUG:
            continue
        for sib in h.find_all_next():
            sib_text = sib.get_text(" ", strip=True)
            if "US$" in sib_text:
                m = re.search(r"US\$\s*\(?[EeS]?\)?\s*([\d.]+,\d+)", sib_text)
                if m:
                    val_s = m.group(1).replace(".", "").replace(",", ".")
                    try:
                        prices[BCR_TO_SLUG[crop_name]] = float(val_s)
                    except ValueError:
                        pass
                break
            if sib.name in ("h2", "h3", "h4") and sib.get_text(strip=True) in BCR_TO_SLUG:
                break
    return {"date": page_date, "prices": prices}


def download_pdf(url: str, dest: Path) -> Path:
    """Downloads a PDF to dest. Returns the path."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=60.0, headers=HEADERS, follow_redirects=True) as cli:
        with cli.stream("GET", url) as r:
            r.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in r.iter_bytes(chunk_size=8192):
                    f.write(chunk)
    return dest


# ─────────────────────────────────────────────────────────────────────────
# 2. Parsing
# ─────────────────────────────────────────────────────────────────────────

def _num(s: str) -> float | None:
    """Parses '187,60' or '13.252' → 187.6 or 13252.0."""
    if s is None:
        return None
    s = s.strip()
    if not s:
        return None
    # Spanish format: thousands "." + decimals ","
    s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _parse_cbot_with_coords(path: Path) -> dict:
    """Returns {'wheat_chicago': {Mon-YY: val}, 'wheat_kansas': {...}, 'corn': {...}}.

    Uses pdfplumber's extract_words() to get X-coordinates so we can map each
    value to the correct column (Trigo /1 SRW, /2 HRW, /3 Maíz) regardless of
    which crops are missing in any given row of the "Chicago y Kansas" table
    on page 8.
    """
    import pdfplumber

    out = {"wheat_chicago": {}, "wheat_kansas": {}, "corn": {}}
    # Tolerance in X (PDF points) when matching a value to its column.
    X_TOL = 25.0

    with pdfplumber.open(str(path)) as pdf:
        # The Chicago y Kansas table is on page 8 (index 7) — but to be safe
        # we'll scan every page and only process the one that has the header.
        for page in pdf.pages:
            words = page.extract_words(use_text_flow=False) or []
            if not words:
                continue
            # Build line groups (words with similar Y)
            words = sorted(words, key=lambda w: (round(w["top"], 1), w["x0"]))
            # Group into rows by Y (3-point tolerance)
            rows: list[list[dict]] = []
            for w in words:
                if rows and abs(w["top"] - rows[-1][0]["top"]) < 3:
                    rows[-1].append(w)
                else:
                    rows.append([w])

            # Find header row by detecting "/1 /2 /3" markers
            srw_x = hrw_x = corn_x = None
            header_idx = -1
            for i, row in enumerate(rows):
                texts = [w["text"] for w in row]
                if "/1" in texts and "/2" in texts and "/3" in texts:
                    # Header: pick the X positions of /1, /2, /3
                    for w in row:
                        if w["text"] == "/1":
                            srw_x = w["x0"]
                        elif w["text"] == "/2":
                            hrw_x = w["x0"]
                        elif w["text"] == "/3":
                            corn_x = w["x0"]
                    header_idx = i
                    break
            if header_idx < 0 or srw_x is None:
                continue  # not the right page

            # Walk data rows after the header
            for row in rows[header_idx + 1:]:
                texts = [w["text"] for w in row]
                # Find a month-year token at the start (e.g. "May-26")
                m_first = None
                for w in row:
                    if re.fullmatch(r"[A-Z][a-z]{2}-\d{2}", w["text"]):
                        m_first = w
                        break
                if not m_first:
                    continue
                mon_part = m_first["text"]
                mon_name = mon_part.split("-")[0]
                if mon_name not in CBOT_GRAIN_MONTHS:
                    continue

                # For each price-value token, find the nearest column.
                # Skip the delta values (we want only the FIRST of each pair —
                # the one closest to a column header X position).
                value_tokens = [w for w in row
                                if re.fullmatch(r"-?[\d.]+,\d+", w["text"])]
                # Sort by X
                value_tokens.sort(key=lambda w: w["x0"])

                # Walk through tokens. The first token NEAR srw_x is the SRW price,
                # the next is its delta. Then next near hrw_x, etc.
                # Strategy: for each column header, find the leftmost value token
                # within X_TOL.
                columns = [("wheat_chicago", srw_x),
                           ("wheat_kansas",  hrw_x),
                           ("corn",          corn_x)]
                key = mon_part  # e.g. "May-26"
                for col_key, col_x in columns:
                    if col_x is None:
                        continue
                    for w in value_tokens:
                        if abs(w["x0"] - col_x) < X_TOL:
                            out[col_key][key] = _num(w["text"])
                            break
            return out  # done — found the right page
    return out


def parse_pdf(path: Path) -> dict:
    """Parses a BCR boletín PDF and returns a dict with all extracted fields."""
    import pdfplumber

    result: dict = {
        "boletin": {"number": None, "date_iso": None, "pizarra_date_iso": None},
        "tc_bna_compra": None,
        "pizarra_usd_tn": {},
        "pizarra_pesos_tn": {},
        "mat_usd_tn": {"maiz": {}, "trigo": {}, "sorgo": {}},
        "cbot_usd_tn": {"corn": {}, "wheat_chicago": {}, "wheat_kansas": {}},
        "minagri_fob_usd_tn": {},
    }

    with pdfplumber.open(str(path)) as pdf:
        all_text = "\n".join((p.extract_text() or "") for p in pdf.pages)

    # ── boletín number + date ─────────────────────────────────────────
    m = re.search(r"AÑO\s+\w+\s*-\s*([\d.]+)\s*[–-]\s*(\d{1,2})/(\d{1,2})/(\d{4})", all_text)
    if m:
        result["boletin"]["number"] = m.group(1).replace(".", "")
        result["boletin"]["date_iso"] = f"{m.group(4)}-{int(m.group(3)):02d}-{int(m.group(2)):02d}"

    m = re.search(r"Precios pizarra del día (\d{2})/(\d{2})/(\d{4})", all_text)
    if m:
        result["boletin"]["pizarra_date_iso"] = f"{m.group(3)}-{m.group(2)}-{m.group(1)}"

    # ── TC: usamos Dólar BCRA A3500 (página de Cotizaciones Spot)
    # Formato: "Dólar BCRA A3500 11/5/2026 1.399,4749 8/5/2026 1.394,1232 0,38"
    # El TC BNA divisas comprador real está en pág 1 pero no es text-extractable.
    # A3500 es prácticamente idéntico para nuestros fines (conversión sorgo/cebada).
    m = re.search(
        r"D[óo]lar\s+BCRA\s+A3500\s+\d{1,2}/\d{1,2}/\d{4}\s+([\d.]+,\d+)",
        all_text,
        re.IGNORECASE,
    )
    if m:
        result["tc_bna_compra"] = _num(m.group(1))

    # ── Pizarra Rosario (page 1): siempre usamos la columna CAC Rosario
    # en PESOS y convertimos vía TC. NO usamos las columnas de otras plazas
    # (Bahía Blanca, BA Quequén, etc.) porque su USD viene de un TC y plaza
    # distintos — no son apples-to-apples con Rosario.
    #
    # Formato de cada fila:
    #   Trigo pan 295.160 [...otras plazas con U$S Y,Y]
    #   Sorgo 277.800
    #   Cebada                ← vacío
    #
    # El número INMEDIATAMENTE después del row_label es siempre la pizarra
    # Rosario en pesos.
    for row_label, slug in PIZARRA_ROW_TO_SLUG.items():
        pat_pesos = re.compile(
            rf"^{re.escape(row_label)}\s+([\d.]+(?:,\d+)?)",
            re.MULTILINE,
        )
        m = pat_pesos.search(all_text)
        if m:
            pesos = _num(m.group(1))
            result["pizarra_pesos_tn"][slug] = pesos
            if pesos is not None and result["tc_bna_compra"]:
                result["pizarra_usd_tn"][slug] = round(pesos / result["tc_bna_compra"], 2)

    # ── MAT futures (pages 2-3): MAI.ROS/, TRI.ROS/, SOR.ROS/ ──────────
    # Format: SYMBOL/MMMYY  fecha  AjAnt  Aper  Min  Max  Ult  Vol  AJUSTE  Var%  IA  VarIA
    # We want the "Ajuste" column (index 8 after splitting by whitespace).
    mat_pat = re.compile(
        r"^(MAI|TRI|SOR)\.ROS/([A-Z]{3}\d{2})\s+"
        r"\d{1,2}/\d{1,2}/\d{4}\s+"           # fecha
        r"([\d.,]+)\s+"                         # AjAnt
        r"[\d.,]+\s+[\d.,]+\s+[\d.,]+\s+"       # Aper, Min, Max
        r"[\d.,]+\s+"                           # Último
        r"[\d.,]+\s+"                           # Vol
        r"([\d.,]+)\s+"                         # Ajuste ← capturamos
        r"[\d.,-]+\s+[\d.,]+\s+[\d.,-]+",      # Var%, IA, VarIA
        re.MULTILINE,
    )
    sym_to_slug = {"MAI": "maiz", "TRI": "trigo", "SOR": "sorgo"}
    for m in mat_pat.finditer(all_text):
        sym, contract = m.group(1), m.group(2)
        slug = sym_to_slug.get(sym)
        if not slug:
            continue
        # Skip "DIS" (disponible — same-day spot, not a future)
        if contract.startswith("DIS"):
            continue
        ajuste = _num(m.group(4))
        if ajuste is not None and ajuste > 0:
            result["mat_usd_tn"][slug][contract] = ajuste

    # ── CBOT Chicago/Kansas (page 8) — uses X-coordinates from extract_words()
    # to correctly assign each price to its column even when some crops are
    # missing in the middle of the row (e.g. Sep-28 has only Corn+Aceite+Harina).
    cbot_parsed = _parse_cbot_with_coords(path)
    for col_key, prices in cbot_parsed.items():
        for month_key, val in prices.items():
            result["cbot_usd_tn"][col_key][month_key] = val

    # ── Minagri FOB (page 8, first block) ─────────────────────────────
    # Format: <Product> <Embarque> <Precio> [<Precio2>] ...   (3 columns side-by-side)
    # Examples:
    #   "Cebada en grano Cercano 235 Maíz Cerc/Cos.Nva 213 229 Aceite Girasol..."
    # We use the product NAME at start-of-line OR after a known column boundary.
    for prod_name, (slug, _kind) in MINAGRI_MAP.items():
        # Try Cerc/Cos.Nva format (2 prices, captured first one — Cercano)
        pat_two = re.compile(
            rf"{re.escape(prod_name)}\s+Cerc/Cos\.?Nva\s+(\d+)\s+(\d+)",
            re.IGNORECASE,
        )
        m = pat_two.search(all_text)
        if m:
            result["minagri_fob_usd_tn"][slug] = {
                "cercano":     int(m.group(1)),
                "cosecha_nva": int(m.group(2)),
            }
            continue
        # Try single Cercano
        pat_one = re.compile(
            rf"{re.escape(prod_name)}\s+Cercano\s+(\d+)",
            re.IGNORECASE,
        )
        m = pat_one.search(all_text)
        if m:
            result["minagri_fob_usd_tn"][slug] = {
                "cercano":     int(m.group(1)),
                "cosecha_nva": None,
            }

    return result


# ─────────────────────────────────────────────────────────────────────────
# 3. Update prices.json
# ─────────────────────────────────────────────────────────────────────────

def append_history_snapshot(parsed: dict, pizarra_cac: dict = None) -> bool:
    """Append a one-line JSON record per boletín to data/prices_history.jsonl.
    Deduplicates by boletín number — if the number already exists in the file,
    skip the append. Returns True if appended, False if duplicate / no data.

    Schema (one line per boletín):
        {
          "boletin": "19057",
          "date":    "2026-05-12",            # boletín date_iso
          "tc":      1386.52,                 # TC BNA compra
          "pizarra": {"maiz": 190.0, "trigo": 215.0, "sorgo": 200.0, ...},
          "mat":     {"maiz": {"MAY26": 190.5, ...}, "trigo": {...}},
          "cbot":    {"corn": {...}, "wheat_chicago": {...}, "wheat_kansas": {...}},
          "minagri": {"maiz": {"cercano": 214, "cosecha_nva": 231}, ...}
        }

    Pizarra siempre la tomamos del CAC scrape (más fresca, intra-día) si está
    disponible; sino del boletín como fallback.
    """
    if not parsed:
        return False
    bn = (parsed.get("boletin") or {}).get("number")
    if not bn:
        return False

    # Dedup: si el número ya está, skip
    if PRICES_HISTORY_JSONL.exists():
        for line in PRICES_HISTORY_JSONL.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if str(rec.get("boletin")) == str(bn):
                return False

    # Pizarra preference: CAC > boletín
    piz = (pizarra_cac or {}).get("prices") or parsed.get("pizarra_usd_tn") or {}

    record = {
        "boletin": str(bn),
        "date":    (parsed.get("boletin") or {}).get("date_iso"),
        "tc":      parsed.get("tc_bna_compra"),
        "pizarra": piz,
        "mat":     parsed.get("mat_usd_tn") or {},
        "cbot":    parsed.get("cbot_usd_tn") or {},
        "minagri": parsed.get("minagri_fob_usd_tn") or {},
    }

    PRICES_HISTORY_JSONL.parent.mkdir(parents=True, exist_ok=True)
    with PRICES_HISTORY_JSONL.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return True


def update_json(parsed: dict, pizarra_cac: dict = None, dry_run: bool = False) -> dict:
    """parsed = output of parse_pdf (boletin). pizarra_cac = output of
    fetch_pizarra_cac (más fresca — opcional). Si cac está disponible Y su
    fecha es >= la del PDF, usa cac. Sino, usa la del PDF.
    """
    if not PRICES_JSON.exists():
        sys.exit(f"prices.json not found at {PRICES_JSON}")
    pj = json.loads(PRICES_JSON.read_text(encoding="utf-8"))

    # ── Snapshot del boletín anterior antes de sobrescribir (para DoD) ──
    # Si la fecha del boletín nuevo es distinta al guardado, copiamos
    # MAT/CBOT/Minagri actuales a sus *_prev correspondientes.
    new_boletin_date = (parsed.get("boletin") or {}).get("date_iso")
    old_boletin_date = (pj.get("boletin") or {}).get("date_iso")
    if new_boletin_date and old_boletin_date and old_boletin_date != new_boletin_date:
        pj["mat_usd_tn_prev"]         = pj.get("mat_usd_tn", {})
        pj["cbot_usd_tn_prev"]        = pj.get("cbot_usd_tn", {})
        pj["minagri_fob_usd_tn_prev"] = pj.get("minagri_fob_usd_tn", {})

    pj["updated_at"]   = _date.today().isoformat()
    pj["boletin"]      = parsed["boletin"]
    pj["tc_bna_compra"] = parsed.get("tc_bna_compra")

    # ── Pizarra: SIEMPRE de CAC (cac.bcr.com.ar) — fuente única ──────────
    # No usamos la pizarra del boletín (viene con 1 día de lag).
    # Si CAC falla, NO sobreescribimos lo que ya está en el JSON.
    cac_date  = (pizarra_cac or {}).get("date")
    cac_prices = (pizarra_cac or {}).get("prices") or {}

    pj["pizarra_source"] = "cac"
    if cac_prices and cac_date:
        pj_piz = pj.setdefault("pizarra_usd_tn", {})
        for slug, usd in cac_prices.items():
            slot = pj_piz.setdefault(slug, {"today": None, "yesterday": None, "as_of": None})
            if slot.get("as_of") != cac_date:
                slot["yesterday"] = slot.get("today")
                slot["today"]     = usd
                slot["as_of"]     = cac_date
    else:
        print("⚠ CAC pizarra no disponible — manteniendo valores anteriores en prices.json",
              file=sys.stderr)

    # MAT — overwrite the whole per-crop dict (curve changes every day)
    pj["mat_usd_tn"] = {
        **parsed["mat_usd_tn"],
        "as_of": parsed["boletin"].get("date_iso"),
    }

    # CBOT — overwrite (whole curve)
    pj["cbot_usd_tn"] = {
        **parsed["cbot_usd_tn"],
        "as_of": parsed["boletin"].get("date_iso"),
    }

    # Minagri FOB — store all (cercano + cos.nva) per crop
    pj["minagri_fob_usd_tn"] = {
        **parsed["minagri_fob_usd_tn"],
        "as_of": parsed["boletin"].get("date_iso"),
    }

    if dry_run:
        # Print a summary, not the full JSON
        summary = {
            "boletin":        parsed["boletin"],
            "tc_bna":         parsed.get("tc_bna_compra"),
            "pizarra_usd_tn": parsed["pizarra_usd_tn"],
            "mat_maiz":       list(parsed["mat_usd_tn"].get("maiz", {}).keys()),
            "mat_trigo":      list(parsed["mat_usd_tn"].get("trigo", {}).keys()),
            "cbot_corn":      list(parsed["cbot_usd_tn"].get("corn", {}).keys()),
            "cbot_wheat":     list(parsed["cbot_usd_tn"].get("wheat_chicago", {}).keys()),
            "minagri":        parsed["minagri_fob_usd_tn"],
        }
        print(json.dumps(summary, indent=2, ensure_ascii=False))
    else:
        PRICES_JSON.write_text(json.dumps(pj, indent=2, ensure_ascii=False) + "\n",
                                encoding="utf-8")
        # Snapshot histórico: append-only, dedupea por número de boletín
        try:
            _appended = append_history_snapshot(parsed, pizarra_cac=pizarra_cac)
            if _appended:
                print(f"📚 prices_history.jsonl ← boletín {parsed['boletin']['number']}",
                      file=sys.stderr)
        except Exception as e:
            print(f"⚠ append_history_snapshot falló: {e}", file=sys.stderr)

    return parsed


# ─────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────

def update_pizarra_only(dry_run: bool = False) -> int:
    """Refresh ONLY the CAC pizarra in data/prices.json — no boletín download.
    Útil para correr rápido durante el día cuando solo querés actualizar Pizarra
    (CAC se mueve intra-día; el boletín BCR sale a las ~18:30).
    """
    if not PRICES_JSON.exists():
        print(f"prices.json not found at {PRICES_JSON}", file=sys.stderr)
        return 1
    pj = json.loads(PRICES_JSON.read_text(encoding="utf-8"))

    cac = fetch_pizarra_cac()
    cac_date = (cac or {}).get("date")
    cac_prices = (cac or {}).get("prices") or {}
    if not cac_prices or not cac_date:
        print("⚠ CAC pizarra no disponible — no se hicieron cambios", file=sys.stderr)
        return 2

    pj["pizarra_source"] = "cac"
    pj_piz = pj.setdefault("pizarra_usd_tn", {})
    for slug, usd in cac_prices.items():
        slot = pj_piz.setdefault(slug, {"today": None, "yesterday": None, "as_of": None})
        if slot.get("as_of") != cac_date:
            slot["yesterday"] = slot.get("today")
            slot["today"] = usd
            slot["as_of"] = cac_date
    pj["updated_at"] = _date.today().isoformat()

    if dry_run:
        print(json.dumps({"date": cac_date, "prices": cac_prices}, indent=2,
                         ensure_ascii=False))
    else:
        PRICES_JSON.write_text(json.dumps(pj, indent=2, ensure_ascii=False) + "\n",
                                encoding="utf-8")
        print(f"✓ Pizarra CAC actualizada · {cac_date} · "
              f"{', '.join(f'{k}={v}' for k, v in cac_prices.items())}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Parse BCR boletín → data/prices.json")
    ap.add_argument("--pdf", default=None,
                    help="Path to an existing PDF (skip download).")
    ap.add_argument("--list", action="store_true",
                    help="List latest 7 boletines from the index page and exit.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print summary, don't write prices.json.")
    ap.add_argument("--pizarra-only", action="store_true",
                    help="Solo actualizar la Pizarra CAC (rápido, no descarga PDF).")
    args = ap.parse_args()

    if args.list:
        for date_str, url in find_pdf_urls():
            print(f"{date_str:<30s}  {url}")
        return 0

    if args.pizarra_only:
        return update_pizarra_only(dry_run=args.dry_run)

    if args.pdf:
        pdf_path = Path(args.pdf)
        if not pdf_path.exists():
            print(f"PDF not found: {pdf_path}", file=sys.stderr)
            return 1
    else:
        # Auto-discover latest from index
        urls = find_pdf_urls(limit=1)
        if not urls:
            print("⚠ No boletín found on index page", file=sys.stderr)
            return 2
        date_str, url = urls[0]
        # Filename from URL
        pdf_path = DATA_DIR / "boletines" / Path(url).name
        print(f"→ Downloading {url} ({date_str}) → {pdf_path}")
        download_pdf(url, pdf_path)

    print(f"→ Parsing {pdf_path}")
    parsed = parse_pdf(pdf_path)

    # Try CAC pizarra (más fresca — del día actual cuando ya publicó)
    print("→ Fetching pizarra fresca de cac.bcr.com.ar")
    pizarra_cac = fetch_pizarra_cac()
    if pizarra_cac.get("prices"):
        print(f"  CAC pizarra date={pizarra_cac.get('date')} "
              f"prices={pizarra_cac.get('prices')}")
    else:
        print("  CAC pizarra no disponible — uso la del boletín")

    update_json(parsed, pizarra_cac=pizarra_cac, dry_run=args.dry_run)

    bn = parsed["boletin"]
    print(f"✓ Boletín N°{bn.get('number')} fecha={bn.get('date_iso')} "
          f"· pizarra={list(parsed['pizarra_usd_tn'].keys())} "
          f"· MAT maíz={len(parsed['mat_usd_tn'].get('maiz', {}))} contratos "
          f"· MAT trigo={len(parsed['mat_usd_tn'].get('trigo', {}))} contratos "
          f"· CBOT corn={len(parsed['cbot_usd_tn'].get('corn', {}))} "
          f"· CBOT wheat={len(parsed['cbot_usd_tn'].get('wheat_chicago', {}))} "
          f"· Minagri={list(parsed['minagri_fob_usd_tn'].keys())}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
