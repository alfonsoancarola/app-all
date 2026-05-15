"""
backfill_prices_history.py — Rellena data/prices_history.jsonl iterando
hacia atrás desde el número de boletín actual.

Estrategia:
  1. Determinar el boletín más reciente (desde data/prices.json o argv).
  2. Iterar N → N-1 → N-2 → ... hasta `--max-tries` boletines o hasta llegar
     a un piso `--stop-at`.
  3. Para cada N: si el PDF ya está en data/boletines/, reusarlo; sino bajarlo
     desde BCR. Parsear, hacer append al JSONL (con dedup por número).
  4. Saltear 404 silenciosamente (los fines de semana / feriados no se publica).

Uso:
    python backfill_prices_history.py                  # default: 60 boletines hacia atrás
    python backfill_prices_history.py --max-tries 200  # ir más atrás
    python backfill_prices_history.py --from 19057     # arrancar desde un N específico
    python backfill_prices_history.py --stop-at 18000  # piso de N
    python backfill_prices_history.py --dry-run        # no escribir, solo log
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from scrapers.bcr_boletin import (
    DATA_DIR,
    PRICES_HISTORY_JSONL,
    PRICES_JSON,
    append_history_snapshot,
    download_pdf,
    parse_pdf,
)

PDF_DIR = DATA_DIR / "boletines"
PDF_URL_TEMPLATE = (
    "https://www.bcr.com.ar/sites/default/files/boletin-mercado-granos-{n}.pdf"
)


def _existing_boletines() -> set[str]:
    """Lee los números de boletín ya presentes en prices_history.jsonl."""
    out: set[str] = set()
    if not PRICES_HISTORY_JSONL.exists():
        return out
    for line in PRICES_HISTORY_JSONL.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
            if rec.get("boletin"):
                out.add(str(rec["boletin"]))
        except Exception:
            continue
    return out


def _latest_boletin_from_json() -> int | None:
    """Devuelve el número de boletín actualmente en data/prices.json."""
    if not PRICES_JSON.exists():
        return None
    try:
        pj = json.loads(PRICES_JSON.read_text(encoding="utf-8"))
        n  = (pj.get("boletin") or {}).get("number")
        return int(n) if n else None
    except Exception:
        return None


def backfill(start: int, max_tries: int, stop_at: int, dry_run: bool = False) -> None:
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    PRICES_HISTORY_JSONL.parent.mkdir(parents=True, exist_ok=True)

    have = _existing_boletines()
    print(f"📚 Ya en historial: {len(have)} boletines", file=sys.stderr)

    n_added   = 0
    n_skipped = 0
    n_failed  = 0
    n         = start

    for _ in range(max_tries):
        if n < stop_at:
            print(f"🛑 Llegué al piso N={stop_at}", file=sys.stderr)
            break

        if str(n) in have:
            n_skipped += 1
            n -= 1
            continue

        pdf_path = PDF_DIR / f"{n}.pdf"
        if not pdf_path.exists():
            url = PDF_URL_TEMPLATE.format(n=n)
            print(f"⬇  Bajando boletín {n} …", file=sys.stderr)
            try:
                download_pdf(url, pdf_path)
                time.sleep(0.3)  # gentle
            except Exception as e:
                msg = str(e)
                if "404" in msg or "Not Found" in msg:
                    print(f"   (404 — se salta {n})", file=sys.stderr)
                else:
                    print(f"   ⚠ falló {n}: {e}", file=sys.stderr)
                    n_failed += 1
                # PDF roto/no existe — limpiarlo y seguir
                if pdf_path.exists() and pdf_path.stat().st_size < 50_000:
                    pdf_path.unlink()
                n -= 1
                continue

        # Parsear
        try:
            parsed = parse_pdf(pdf_path)
        except Exception as e:
            print(f"   ⚠ parse falló para {n}: {e}", file=sys.stderr)
            n_failed += 1
            n -= 1
            continue

        if dry_run:
            print(f"   [dry-run] boletín {n} fecha {parsed['boletin'].get('date_iso')}",
                  file=sys.stderr)
        else:
            added = append_history_snapshot(parsed, pizarra_cac=None)
            if added:
                n_added += 1
                print(f"   ✓ {n} ({parsed['boletin'].get('date_iso')})", file=sys.stderr)
            else:
                n_skipped += 1

        n -= 1

    print(
        f"\n✅ Backfill terminado · added={n_added} · skipped={n_skipped} · "
        f"failed={n_failed}",
        file=sys.stderr,
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="start", type=int, default=None,
                    help="Boletín N de partida (default: el de prices.json)")
    ap.add_argument("--max-tries", type=int, default=60,
                    help="Cuántos N probar hacia atrás (default 60)")
    ap.add_argument("--stop-at", type=int, default=10_000,
                    help="Piso de N — no bajar más de este número")
    ap.add_argument("--dry-run", action="store_true",
                    help="No escribir, solo log")
    args = ap.parse_args()

    start = args.start
    if start is None:
        start = _latest_boletin_from_json()
    if start is None:
        print("✗ No pude determinar el N de partida. Pasá --from N", file=sys.stderr)
        return 1

    print(f"🔄 Backfill desde N={start} hacia atrás (max {args.max_tries} tries, "
          f"piso {args.stop_at})", file=sys.stderr)
    backfill(start, args.max_tries, args.stop_at, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
