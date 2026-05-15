"""
descargar_geojson_ar.py — Downloads Argentina province GeoJSON.

Tries a few sources in order until one returns a valid file with ~24 provinces.
Saves to data/argentina_provincias.geojson.

Usage:
    python descargar_geojson_ar.py
"""
import json
import sys
import urllib.request
from pathlib import Path

OUT = Path("data/argentina_provincias.geojson")

SOURCES = [
    # 1. datos.gob.ar georef API — pedimos geometría, NO centroide
    ("georef API",
     "https://apis.datos.gob.ar/georef/api/provincias"
     "?campos=id,nombre&max=24&formato=geojson"),
    # 2. Natural Earth (full world, filter to AR)
    ("Natural Earth ADM1",
     "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/"
     "geojson/ne_10m_admin_1_states_provinces.geojson"),
    # 3. GeoJSON-AR community repo
    ("geojson-ar",
     "https://raw.githubusercontent.com/maxiarg/argentina-geojson/master/argentina.geojson"),
]


def _try_fetch(name: str, url: str) -> dict | None:
    print(f"  → {name}: GET {url[:80]}{'…' if len(url) > 80 else ''}")
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (fs_maiz dataset fetcher)"},
        )
        with urllib.request.urlopen(req, timeout=60) as r:
            data = r.read()
    except Exception as e:
        print(f"    ✗ {type(e).__name__}: {e}")
        return None
    try:
        parsed = json.loads(data)
    except json.JSONDecodeError as e:
        print(f"    ✗ not JSON: {e}")
        return None
    feats = parsed.get("features", [])
    if not feats:
        print(f"    ✗ 0 features")
        return None
    # Filter to AR if it's a worldwide file
    is_ar = any(
        f.get("properties", {}).get("iso_a2") == "AR"
        or f.get("properties", {}).get("admin", "").lower() == "argentina"
        for f in feats[:50]
    )
    if is_ar and len(feats) > 100:
        feats = [
            f for f in feats
            if f.get("properties", {}).get("iso_a2") == "AR"
            or f.get("properties", {}).get("admin", "").lower() == "argentina"
        ]
        parsed = {"type": "FeatureCollection", "features": feats}
    if len(feats) < 20:
        print(f"    ✗ only {len(feats)} features (expected ~24)")
        return None
    # Verificar que la geometría sea Polygon/MultiPolygon (no Point)
    geom_types = {
        f.get("geometry", {}).get("type", "?") for f in feats
    }
    if not geom_types & {"Polygon", "MultiPolygon"}:
        print(f"    ✗ geometries are {geom_types}, not Polygon/MultiPolygon")
        return None
    print(f"    ✓ {len(feats)} features ({', '.join(sorted(geom_types))})")
    return parsed


def main() -> int:
    print(f"Looking for Argentina provinces GeoJSON…")
    for name, url in SOURCES:
        data = _try_fetch(name, url)
        if data is not None:
            OUT.parent.mkdir(parents=True, exist_ok=True)
            OUT.write_text(json.dumps(data), encoding="utf-8")
            print(f"\n✅ Saved {len(data['features'])} provinces → {OUT}")
            return 0
    print("\n❌ Couldn't fetch from any source.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
