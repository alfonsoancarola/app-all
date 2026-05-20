"""
pos_fisica_ldc_data.py — Datos manuales de Pos. Física LDC.

Este archivo lo edita el usuario a mano (con los números de LDC) y la app
los lee directo. NO se sobrescribe por ningún pipeline.

Estructura:
    LDC_DATA[slug][year_month][port] = {
        "business_plan":  int,   # plan de exports LDC (tn)
        "faltan_vender":  int,   # gap entre BP y ventas LDC hechas (tn)
        "stocks":         int,   # inventario físico disponible (tn)
        "open_vencido":   int,   # contratos abiertos vencidos (tn)
        "open_mes":       int,   # contratos abiertos a entregar este mes (tn)
        "falta_comprar":  int,   # cuánto falta comprar para cubrir ventas (tn)
    }

Puertos export: "uprivers", "bahia", "necochea" (Interior no exporta).
Meses: clave 'YYYY_MM' (ej. '2026_05'). Solo cargar meses con data; el resto
queda en 0 por default.

Para usar el helper desde código:
    from pos_fisica_ldc_data import get_ldc_cell, LDC_FIELDS
    cell = get_ldc_cell("maiz", 2026, 5, "uprivers")
    # cell = {"business_plan": ..., "faltan_vender": ..., ...}
"""
from __future__ import annotations

# Campos por celda (en orden de presentación)
LDC_FIELDS = [
    ("business_plan",  "Business Plan",   "#1d6e51"),  # verde — el objetivo
    ("faltan_vender",  "Faltan vender",   "#F57C00"),  # naranja
    ("stocks",         "Stocks",          "#1565C0"),  # azul
    ("open_vencido",   "Open vencido",    "#a32d2d"),  # rojo
    ("open_mes",       "Open del mes",    "#7B3FB8"),  # violeta
    ("falta_comprar",  "Falta comprar",   "#444444"),  # gris oscuro
]

# Plantilla por defecto (todo 0). El usuario reemplaza por sus valores.
_EMPTY_CELL = {k: 0 for k, _, _ in LDC_FIELDS}


def _empty():
    return dict(_EMPTY_CELL)


# ──────────────────────────────────────────────────────────────────────────────
# DATA — EDITAR MANUALMENTE LOS VALORES POR CULTIVO / MES / PUERTO
# ──────────────────────────────────────────────────────────────────────────────
# Ejemplo de cómo llenar maíz / mayo 2026:
#
# LDC_DATA["maiz"]["2026_05"]["uprivers"] = {
#     "business_plan": 200_000,
#     "faltan_vender":  35_000,
#     "stocks":         80_000,
#     "open_vencido":   12_000,
#     "open_mes":       45_000,
#     "falta_comprar":  20_000,
# }
#
# Por ahora todo está en 0. Llená lo que necesites usar.

LDC_DATA: dict = {
    "maiz":   {},
    "trigo":  {},
    "sorgo":  {},
    "cebada": {},
}


# ──────────────────────────────────────────────────────────────────────────────
# Helper de acceso (devuelve dict de campos, con default = 0)
# ──────────────────────────────────────────────────────────────────────────────

def get_ldc_cell(slug: str, year: int, month: int, port: str) -> dict:
    """Devuelve los 6 campos para (cultivo, año, mes, puerto). Si no está
    cargado, devuelve todos en 0."""
    ym = f"{year:04d}_{month:02d}"
    cultivo_data = LDC_DATA.get(slug, {})
    month_data = cultivo_data.get(ym, {})
    cell = month_data.get(port, {})
    out = dict(_EMPTY_CELL)
    out.update(cell)
    return out


def get_ldc_total_month(slug: str, year: int, month: int) -> dict:
    """Suma los 3 puertos export para un mes específico."""
    out = dict(_EMPTY_CELL)
    for port in ("uprivers", "bahia", "necochea"):
        cell = get_ldc_cell(slug, year, month, port)
        for k in out:
            out[k] += cell[k]
    return out
