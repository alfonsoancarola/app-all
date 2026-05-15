"""
logistica.py — Programa de buques de Gral Lagos (granos).

Reglas (versión inicial mínima):
    - Cada barco tarda 18 hs en cargar (duración fija).
    - Eje Y = cultivo (Maíz / Trigo / Sorgo / Cebada).
    - Dos barcos NUNCA se pueden solapar en el tiempo (un solo loader).
"""
from datetime import datetime, timedelta

DURATION_HOURS = 18

PRODUCTOS = ["maiz", "trigo", "sorgo", "cebada"]
PRODUCTO_LABEL = {"maiz": "Maíz", "trigo": "Trigo", "sorgo": "Sorgo", "cebada": "Cebada"}
PRODUCTO_COLOR = {
    "maiz":   "#F2B705",
    "trigo":  "#A67C52",
    "sorgo":  "#C0392B",
    "cebada": "#7E57C2",
}

# Programa baseline (buques reales del Grains Book de Gral Lagos)
DEFAULT_BARCOS = [
    {"producto": "trigo", "buque": "MV Hessah",        "eta": datetime(2026, 1, 25,  6,  0), "tn": 40000, "counterpart": "FW Vietnam"},
    {"producto": "trigo", "buque": "MV Trigon Trader", "eta": datetime(2026, 1, 27,  8,  0), "tn": 42000, "counterpart": "JSW JAN"},
    {"producto": "trigo", "buque": "MV Adventurer",    "eta": datetime(2026, 1, 29,  6,  0), "tn": 30000, "counterpart": "Algeria 2"},
    {"producto": "trigo", "buque": "MV RB Jordana",    "eta": datetime(2026, 1, 30, 12,  0), "tn": 45000, "counterpart": "Vietnam MFM"},
    {"producto": "trigo", "buque": "MV Lady Serra",    "eta": datetime(2026, 2,  3,  6,  0), "tn": 30000, "counterpart": "COFCO"},
    {"producto": "maiz",  "buque": "MV Bunge",         "eta": datetime(2026, 3,  5,  8,  0), "tn": 60000, "counterpart": "Bunge"},
    {"producto": "maiz",  "buque": "MV Cofco Maiz",    "eta": datetime(2026, 3, 22,  6,  0), "tn": 60000, "counterpart": "COFCO"},
]


def detectar_overlaps(barcos: list[dict]) -> list[dict]:
    """
    Devuelve lista de overlaps. Cada item:
        { "buque_a": str, "buque_b": str, "inicio": datetime, "fin": datetime }
    Un overlap = dos barcos cuyos intervalos [eta, eta+18h] se intersectan.
    Funciona globalmente (no permite ningún solapamiento, ni siquiera entre cultivos).
    """
    items = []
    for b in barcos:
        if b.get("eta") is None:
            continue
        items.append({
            "buque":    b["buque"],
            "producto": b["producto"],
            "eta":      b["eta"],
            "fin":      b["eta"] + timedelta(hours=DURATION_HOURS),
        })

    overlaps = []
    for i, a in enumerate(items):
        for b in items[i+1:]:
            inicio = max(a["eta"], b["eta"])
            fin    = min(a["fin"], b["fin"])
            if inicio < fin:
                overlaps.append({
                    "buque_a": a["buque"],
                    "buque_b": b["buque"],
                    "inicio":  inicio,
                    "fin":     fin,
                    "horas":   round((fin - inicio).total_seconds() / 3600, 1),
                })
    return overlaps


def buques_en_overlap(barcos: list[dict]) -> set[str]:
    """Set de nombres de buques que están involucrados en al menos un overlap."""
    overlaps = detectar_overlaps(barcos)
    s = set()
    for o in overlaps:
        s.add(o["buque_a"])
        s.add(o["buque_b"])
    return s
