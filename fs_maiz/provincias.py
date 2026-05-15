"""
provincias.py — Mapeo de nombres de provincias del CSV de SIO a códigos
ISO 3166-2:AR para mapas coropléticos.

SIO usa nombres en mayúsculas con/sin tildes (ej. "BUENOS AIRES",
"ENTRE RÍOS", "SANTA FE", "CÓRDOBA"). Los normalizamos a códigos ISO
para enlazarlos con el GeoJSON oficial de Argentina.
"""
import unicodedata


# Normalizado SIO → ISO 3166-2:AR
NOMBRE_A_ISO = {
    "BUENOS AIRES":          "AR-B",
    "CABA":                  "AR-C",
    "CIUDAD AUTONOMA DE BUENOS AIRES": "AR-C",
    "CATAMARCA":             "AR-K",
    "CHACO":                 "AR-H",
    "CHUBUT":                "AR-U",
    "CORDOBA":               "AR-X",
    "CORRIENTES":            "AR-W",
    "ENTRE RIOS":            "AR-E",
    "FORMOSA":               "AR-P",
    "JUJUY":                 "AR-Y",
    "LA PAMPA":              "AR-L",
    "LA RIOJA":              "AR-F",
    "MENDOZA":               "AR-M",
    "MISIONES":              "AR-N",
    "NEUQUEN":               "AR-Q",
    "RIO NEGRO":             "AR-R",
    "SALTA":                 "AR-A",
    "SAN JUAN":              "AR-J",
    "SAN LUIS":              "AR-D",
    "SANTA CRUZ":            "AR-Z",
    "SANTA FE":              "AR-S",
    "SANTIAGO DEL ESTERO":   "AR-G",
    "TIERRA DEL FUEGO":      "AR-V",
    "TUCUMAN":               "AR-T",
}

# ISO → nombre limpio para mostrar
ISO_A_LABEL = {
    "AR-B": "Buenos Aires", "AR-C": "CABA",
    "AR-K": "Catamarca", "AR-H": "Chaco", "AR-U": "Chubut",
    "AR-X": "Córdoba", "AR-W": "Corrientes", "AR-E": "Entre Ríos",
    "AR-P": "Formosa", "AR-Y": "Jujuy", "AR-L": "La Pampa",
    "AR-F": "La Rioja", "AR-M": "Mendoza", "AR-N": "Misiones",
    "AR-Q": "Neuquén", "AR-R": "Río Negro", "AR-A": "Salta",
    "AR-J": "San Juan", "AR-D": "San Luis", "AR-Z": "Santa Cruz",
    "AR-S": "Santa Fe", "AR-G": "Santiago del Estero",
    "AR-V": "Tierra del Fuego", "AR-T": "Tucumán",
}


def _normalizar(nombre: str) -> str:
    s = unicodedata.normalize("NFD", str(nombre).upper().strip())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def a_iso(nombre: str) -> str | None:
    """Devuelve el código ISO de la provincia o None si no matchea."""
    n = _normalizar(nombre)
    return NOMBRE_A_ISO.get(n)
