"""
destinos.py — Categorization of the SIO CSV's LUGAR ENTREGA field into
4 broad destinations relevant for Argentine grain exports.

  - Up River   → Rosario N + Rosario S (Paraná ports: SL, SM, Timbúes, ...)
  - Bahía Blanca → BB port
  - Necochea   → Quequén port
  - Interior   → the rest (Bs As, Córdoba, all SIO Zonas 1-26)

The "/En destino" or "/En origen" suffix in the CSV only indicates who pays
the freight, not the physical place — we ignore it when categorizing.
"""

DESTINOS = ["uprivers", "bahia", "necochea", "interior"]
DESTINOS_LABEL = {
    "uprivers": "Up River",
    "bahia":    "Bahía Blanca",
    "necochea": "Necochea",
    "interior": "Interior",
}
DESTINOS_COLOR = {
    "uprivers": "#185FA5",
    "bahia":    "#1D9E75",
    "necochea": "#E24B4A",
    "interior": "#888780",
}


def categorizar(lugar_entrega: str) -> str:
    """Returns one of DESTINOS based on the free-form LUGAR ENTREGA string from SIO."""
    if not lugar_entrega:
        return "interior"
    s = str(lugar_entrega).strip().lower()
    if "rosario" in s:
        return "uprivers"
    if "b.blanca" in s or "bahia blanca" in s or "bahía blanca" in s or "ing. white" in s:
        return "bahia"
    if "quequen" in s or "quequén" in s or "necochea" in s:
        return "necochea"
    return "interior"
