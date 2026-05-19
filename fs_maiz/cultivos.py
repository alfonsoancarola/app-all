"""
cultivos.py — Central per-crop configuration.

Each crop has its own commercial year and therefore its own delivery bucket
set. Corn and Sorghum are harvested in autumn and marketed the following
year; Wheat and Barley are harvested at calendar year-end and marketed
across the following year.

Harvest 25/26:
    - Corn / Sorghum: harvest Mar-Jun 2026 → trading Mar 26 to Feb 27
    - Wheat / Barley: harvest Nov 25 to Jan 26 → trading Nov 25 to Oct 26
"""
from __future__ import annotations
from datetime import date


# Supply/demand balance in M tn — source: LDC Country Balance Sheet (May 2026).
# Internal official data. The user can edit them from the sidebar.

_BALANCE_MAIZ = {
    "14/15": {"ci":1.490, "prod":29.547, "imp":0.037, "dom":11.003, "exp":16.844, "co":3.227},
    "15/16": {"ci":3.227, "prod":29.839, "imp":0.040, "dom":11.604, "exp":18.860, "co":2.643},
    "16/17": {"ci":2.643, "prod":30.186, "imp":0.001, "dom":10.752, "exp":21.181, "co":0.897},
    "17/18": {"ci":0.897, "prod":41.025, "imp":0.015, "dom":11.580, "exp":25.586, "co":4.772},
    "18/19": {"ci":4.772, "prod":32.498, "imp":0.007, "dom":12.828, "exp":22.171, "co":2.277},
    "19/20": {"ci":2.277, "prod":51.108, "imp":0.045, "dom":13.272, "exp":36.841, "co":3.317},
    "20/21": {"ci":3.317, "prod":51.163, "imp":0.015, "dom":14.052, "exp":35.804, "co":4.639},
    "21/22": {"ci":4.639, "prod":50.949, "imp":0.037, "dom":13.488, "exp":40.486, "co":1.651},
    "22/23": {"ci":1.651, "prod":54.057, "imp":0.087, "dom":14.160, "exp":34.144, "co":7.491},
    "23/24": {"ci":7.491, "prod":35.099, "imp":0.016, "dom":14.064, "exp":24.931, "co":3.611},
    "24/25": {"ci":3.611, "prod":48.971, "imp":0.001, "dom":14.172, "exp":35.549, "co":2.862},
    "25/26": {"ci":2.862, "prod":46.407, "imp":0.003, "dom":16.297, "exp":28.928, "co":4.046},
    "26/27": {"ci":4.046, "prod":59.619, "imp":0.000, "dom":17.803, "exp":40.941, "co":4.920},
}

_BALANCE_TRIGO = {
    "13/14": {"ci":0.863, "prod":10.456, "imp":0.000, "dom":5.976, "exp":1.521, "co":3.823},
    "14/15": {"ci":3.823, "prod":12.451, "imp":0.033, "dom":6.124, "exp":4.478, "co":5.705},
    "15/16": {"ci":5.705, "prod":11.416, "imp":0.017, "dom":5.640, "exp":8.624, "co":2.874},
    "16/17": {"ci":2.874, "prod":17.454, "imp":0.000, "dom":6.420, "exp":12.430, "co":1.479},
    "17/18": {"ci":1.479, "prod":17.797, "imp":0.000, "dom":6.096, "exp":11.781, "co":1.398},
    "18/19": {"ci":1.398, "prod":18.302, "imp":0.000, "dom":6.636, "exp":11.261, "co":1.803},
    "19/20": {"ci":1.803, "prod":19.008, "imp":0.000, "dom":6.792, "exp":11.751, "co":2.267},
    "20/21": {"ci":2.267, "prod":16.523, "imp":0.000, "dom":6.912, "exp":10.333, "co":1.545},
    "21/22": {"ci":1.545, "prod":22.129, "imp":0.000, "dom":6.924, "exp":14.880, "co":1.870},
    "22/23": {"ci":1.870, "prod":10.775, "imp":0.000, "dom":6.972, "exp":3.107, "co":2.566},
    "23/24": {"ci":2.566, "prod":15.448, "imp":0.001, "dom":7.116, "exp":7.645, "co":3.254},
    "24/25": {"ci":3.254, "prod":19.152, "imp":0.000, "dom":7.140, "exp":12.561, "co":2.705},
    "25/26": {"ci":2.705, "prod":27.894, "imp":0.000, "dom":7.176, "exp":17.315, "co":6.109},
}

_BALANCE_CEBADA = {
    "13/14": {"ci":0.129, "prod":4.473, "imp":0.000, "dom":1.323, "exp":2.890, "co":0.389},
    "14/15": {"ci":0.389, "prod":2.837, "imp":0.000, "dom":1.434, "exp":1.430, "co":0.362},
    "15/16": {"ci":0.362, "prod":4.495, "imp":0.000, "dom":1.224, "exp":3.111, "co":0.522},
    "16/17": {"ci":0.522, "prod":3.320, "imp":0.000, "dom":1.116, "exp":2.618, "co":0.108},
    "17/18": {"ci":0.108, "prod":3.325, "imp":0.000, "dom":1.020, "exp":2.331, "co":0.082},
    "18/19": {"ci":0.082, "prod":4.476, "imp":0.028, "dom":1.152, "exp":3.290, "co":0.144},
    "19/20": {"ci":0.144, "prod":3.813, "imp":0.000, "dom":1.152, "exp":2.714, "co":0.091},
    "20/21": {"ci":0.091, "prod":4.150, "imp":0.012, "dom":1.408, "exp":2.443, "co":0.401},
    "21/22": {"ci":0.401, "prod":5.245, "imp":0.000, "dom":1.405, "exp":3.928, "co":0.315},
    "22/23": {"ci":0.315, "prod":4.157, "imp":0.000, "dom":1.431, "exp":2.992, "co":0.049},
    "23/24": {"ci":0.049, "prod":4.710, "imp":0.000, "dom":1.421, "exp":3.030, "co":0.308},
    "24/25": {"ci":0.308, "prod":5.283, "imp":0.000, "dom":1.615, "exp":3.481, "co":0.495},
    "25/26": {"ci":0.495, "prod":5.785, "imp":0.000, "dom":1.620, "exp":4.028, "co":0.631},
}

_BALANCE_SORGO = {
    "14/15": {"ci":0.503, "prod":4.094, "imp":0.000, "dom":2.627, "exp":1.268, "co":0.702},
    "15/16": {"ci":0.702, "prod":3.408, "imp":0.001, "dom":2.460, "exp":0.942, "co":0.709},
    "16/17": {"ci":0.709, "prod":3.337, "imp":0.000, "dom":2.626, "exp":0.644, "co":0.776},
    "17/18": {"ci":0.776, "prod":3.224, "imp":0.000, "dom":2.617, "exp":0.375, "co":1.008},
    "18/19": {"ci":1.008, "prod":2.279, "imp":0.000, "dom":2.400, "exp":0.070, "co":0.818},
    "19/20": {"ci":0.818, "prod":2.337, "imp":0.000, "dom":2.198, "exp":0.246, "co":0.711},
    "20/21": {"ci":0.711, "prod":2.121, "imp":0.000, "dom":1.260, "exp":0.617, "co":0.955},
    "21/22": {"ci":0.955, "prod":3.489, "imp":0.001, "dom":1.456, "exp":2.453, "co":0.536},
    "22/23": {"ci":0.536, "prod":3.357, "imp":0.000, "dom":1.843, "exp":1.744, "co":0.306},
    "23/24": {"ci":0.306, "prod":2.457, "imp":0.000, "dom":1.988, "exp":0.655, "co":0.120},
    "24/25": {"ci":0.120, "prod":3.409, "imp":0.001, "dom":2.237, "exp":1.060, "co":0.233},
    "25/26": {"ci":0.233, "prod":4.062, "imp":0.000, "dom":2.324, "exp":0.203, "co":1.768},
    "26/27": {"ci":1.768, "prod":3.084, "imp":0.000, "dom":1.900, "exp":1.170, "co":1.782},
}

# Business days published in the matrix as "daily" rows.
# Covers April + May 2026 to feed the rolling average of the last 10 business
# days even when May has just started.
# Argentine holidays we exclude:
#   02/04/2026 — Malvinas Veterans Day (Thursday)
#   03/04/2026 — Good Friday
#   01/05/2026 — Labour Day (Friday)
#   25/05/2026 — May Revolution Day (Monday)
_DIAS_HABILES_ABR_MAY_2026 = [
    # April 2026 — 20 business days
    "01/04",
    "06/04","07/04","08/04","09/04","10/04",
    "13/04","14/04","15/04","16/04","17/04",
    "20/04","21/04","22/04","23/04","24/04",
    "27/04","28/04","29/04","30/04",
    # May 2026 — 19 business days
    "04/05","05/05","06/05","07/05","08/05",
    "11/05","12/05","13/05","14/05","15/05",
    "18/05","19/05","20/05","21/05","22/05",
    "26/05","27/05","28/05","29/05",
]
# The "month" field is no longer used to discriminate — labels carry "DD/MM".
_DAILY_MAYO_2026 = {"year": 2026, "month": 5, "dias_habiles": _DIAS_HABILES_ABR_MAY_2026}


CULTIVOS = {
    "maiz": {
        "label":      "Corn",
        "emoji":      "🌽",
        "matriz_csv": "matriz_maiz.csv",
        "balance_hist":    _BALANCE_MAIZ,
        "balance_default": "26/27",  # LDC nomenclature: current crop = 26/27
        # SIO Granos
        "sio_producto":  "MAIZ",
        "sio_ddl_value": "2",
        # MAGYP / MINAGRI
        "magyp_tab":     "Maíz",
        "cosecha":       "25/26",    # SIO CSV filter + MAGYP tab (planting/harvest)
        "cosecha_label": "26/27",    # LDC display in title and metrics
        # Monthly rows: from this month up to the month before current
        "primer_mes_mensual": (2025, 3),   # Mar-25
        # Delivery buckets: fecha_desde range → group
        "grupos": ["MAM", "JJ", "AS", "OND", "JF", "NC"],
        "subtitulos": {
            "MAM": "Mar-May 26", "JJ":  "Jun-Jul 26",
            "AS":  "Aug-Sep 26", "OND": "Oct-Dec 26", "JF": "Jan-Feb 27",
            "NC":  "NC 26/27 (forward sales)",
        },
        "colores": ["#185FA5", "#1D9E75", "#E24B4A", "#BA7517", "#7F77DD", "#A86BA8"],
        "delivery_groups": [
            ("MAM", date(2026, 3, 1),  date(2026, 5, 31)),
            ("JJ",  date(2026, 6, 1),  date(2026, 7, 31)),
            ("AS",  date(2026, 8, 1),  date(2026, 9, 30)),
            ("OND", date(2026, 10, 1), date(2026, 12, 31)),
            ("JF",  date(2027, 1, 1),  date(2027, 2, 28)),
            # NC is populated from SIO ops with `cosecha = cosecha_nc` ("26/27"),
            # regardless of delivery date. The date range below is a placeholder
            # to keep the tuple shape consistent.
            ("NC",  date(2027, 3, 1),  date(2028, 2, 29)),
        ],
        "cosecha_nc": "26/27",   # cosecha nueva de maíz (se planta sep 26, cosecha 2027)
        "daily_mes": _DAILY_MAYO_2026,
    },

    "trigo": {
        "label":      "Bread Wheat",
        "emoji":      "🌾",
        "matriz_csv": "matriz_trigo.csv",
        "balance_hist":    _BALANCE_TRIGO,
        "balance_default": "25/26",
        "sio_producto":  "TRIGO PAN",
        "sio_ddl_value": "1",
        "magyp_tab":     "Trigo",
        "cosecha":       "25/26",
        "cosecha_label": "25/26",  # winter crop: SIO and LDC match
        # Mar-25: forward preharvest. Real harvest is Nov 25 - Jan 26.
        "primer_mes_mensual": (2025, 3),
        "grupos": ["NDJ", "FMA", "MJJ", "ASO", "NC"],
        "subtitulos": {
            "NDJ": "Nov 25 - Jan 26",
            "FMA": "Feb-Mar-Apr 26",
            "MJJ": "May-Jun-Jul 26",
            "ASO": "Aug-Sep-Oct 26",
            "NC":  "NC 26/27 (forward sales)",
        },
        "colores": ["#185FA5", "#1D9E75", "#E24B4A", "#BA7517", "#A86BA8"],
        "delivery_groups": [
            ("NDJ", date(2025, 11, 1), date(2026, 1, 31)),
            ("FMA", date(2026, 2, 1),  date(2026, 4, 30)),
            ("MJJ", date(2026, 5, 1),  date(2026, 7, 31)),
            ("ASO", date(2026, 8, 1),  date(2026, 10, 31)),
            # Placeholder — NC se llena via cosecha_nc, no por delivery date
            ("NC",  date(2026, 11, 1), date(2027, 10, 31)),
        ],
        "cosecha_nc": "26/27",   # cosecha nueva de trigo (cosecha nov-dic 2026)
        "daily_mes": _DAILY_MAYO_2026,
    },

    "sorgo": {
        "label":      "Sorghum",
        "emoji":      "🌱",
        "matriz_csv": "matriz_sorgo.csv",
        "balance_hist":    _BALANCE_SORGO,
        "balance_default": "26/27",  # same commercial year as corn
        "sio_producto":  "SORGO",
        "sio_ddl_value": "3",
        "magyp_tab":     "Sorgo",
        "cosecha":       "25/26",
        "cosecha_label": "26/27",
        "primer_mes_mensual": (2025, 3),
        "grupos": ["MAM", "JJ", "AS", "OND", "JF"],
        "subtitulos": {
            "MAM": "Mar-May 26", "JJ":  "Jun-Jul 26",
            "AS":  "Aug-Sep 26", "OND": "Oct-Dec 26", "JF": "Jan-Feb 27",
        },
        "colores": ["#185FA5", "#1D9E75", "#E24B4A", "#BA7517", "#7F77DD"],
        "delivery_groups": [
            ("MAM", date(2026, 3, 1),  date(2026, 5, 31)),
            ("JJ",  date(2026, 6, 1),  date(2026, 7, 31)),
            ("AS",  date(2026, 8, 1),  date(2026, 9, 30)),
            ("OND", date(2026, 10, 1), date(2026, 12, 31)),
            ("JF",  date(2027, 1, 1),  date(2027, 2, 28)),
        ],
        "daily_mes": _DAILY_MAYO_2026,
    },

    "cebada": {
        "label":      "Feed Barley",
        "emoji":      "🌾",
        "matriz_csv": "matriz_cebada.csv",
        "balance_hist":    _BALANCE_CEBADA,
        "balance_default": "25/26",
        "sio_producto":  "CEBADA FORR.",
        "sio_ddl_value": "7",
        "magyp_tab":     "Cebada Forrajera",
        "cosecha":       "25/26",
        "cosecha_label": "25/26",
        "primer_mes_mensual": (2025, 3),  # forward preharvest from mar-25
        "grupos": ["NDJ", "FMA", "MJJ", "ASO"],
        "subtitulos": {
            "NDJ": "Nov 25 - Jan 26",
            "FMA": "Feb-Mar-Apr 26",
            "MJJ": "May-Jun-Jul 26",
            "ASO": "Aug-Sep-Oct 26",
        },
        "colores": ["#185FA5", "#1D9E75", "#E24B4A", "#BA7517"],
        "delivery_groups": [
            ("NDJ", date(2025, 11, 1), date(2026, 1, 31)),
            ("FMA", date(2026, 2, 1),  date(2026, 4, 30)),
            ("MJJ", date(2026, 5, 1),  date(2026, 7, 31)),
            ("ASO", date(2026, 8, 1),  date(2026, 10, 31)),
        ],
        "daily_mes": _DAILY_MAYO_2026,
    },

}


def get_cultivo(slug: str) -> dict:
    """Returns the crop config. Accepts slug or label."""
    if slug in CULTIVOS:
        return CULTIVOS[slug]
    for c in CULTIVOS.values():
        if c["label"].lower() == slug.lower():
            return c
    raise KeyError(f"Crop not found: {slug!r}. Options: {list(CULTIVOS)}")


def grupo_de_entrega(d: date | None, cultivo_cfg: dict) -> str | None:
    """Maps a delivery date to the crop's bucket. None if outside range."""
    if d is None:
        return None
    for g, ini, fin in cultivo_cfg["delivery_groups"]:
        if ini <= d <= fin:
            return g
    return None


# ── Granularidad mensual (matriz nueva con cols por mes) ─────────────────────
#
# La matriz histórica tenía columnas por bucket (MAM/JJ/AS/OND/JF/NC). Para
# tener detalle mes-a-mes en Pos. Física, ahora las matrices tienen columnas
# por mes calendario individual (`2026_03`, `2026_04`, ...). Los buckets se
# reconstruyen al vuelo en los loaders vía `expand_buckets_from_months`.

def _mes_key(year: int, month: int) -> str:
    """Identifier estable para mes calendario: '2026_03'."""
    return f"{year:04d}_{month:02d}"


def meses_cols(cultivo_cfg: dict) -> list[str]:
    """Lista ordenada cronológicamente de columnas mensuales del cultivo,
    cubriendo el rango total de delivery_groups (excluyendo NC). Si el
    cultivo tiene bucket 'NC', éste se agrega al final como columna aparte.
    """
    out: list[str] = []
    for g, ini, fin in cultivo_cfg["delivery_groups"]:
        if g == "NC":
            continue  # NC se agrega al final
        y, m = ini.year, ini.month
        while (y, m) <= (fin.year, fin.month):
            key = _mes_key(y, m)
            if key not in out:
                out.append(key)
            m += 1
            if m == 13:
                m, y = 1, y + 1
    if any(g == "NC" for g, _, _ in cultivo_cfg["delivery_groups"]):
        out.append("NC")
    return out


def bucket_to_meses(cultivo_cfg: dict) -> dict[str, list[str]]:
    """Dict {bucket: [mes_keys]} para reconstruir buckets desde cols mensuales.

    Ej. maíz → {"MAM": ["2026_03","2026_04","2026_05"],
                "JJ":  ["2026_06","2026_07"], ..., "NC": ["NC"]}
    """
    out: dict[str, list[str]] = {}
    for g, ini, fin in cultivo_cfg["delivery_groups"]:
        if g == "NC":
            out["NC"] = ["NC"]
            continue
        keys: list[str] = []
        y, m = ini.year, ini.month
        while (y, m) <= (fin.year, fin.month):
            keys.append(_mes_key(y, m))
            m += 1
            if m == 13:
                m, y = 1, y + 1
        out[g] = keys
    return out


def mes_de_entrega(d: date | None, cultivo_cfg: dict) -> str | None:
    """Maps a delivery date to its individual calendar-month key
    (`'2026_05'`). Returns None si la fecha cae fuera de todos los
    delivery_groups (mismo filtro que `grupo_de_entrega`).
    """
    if d is None:
        return None
    for g, ini, fin in cultivo_cfg["delivery_groups"]:
        if g == "NC":
            continue  # NC se llena vía cosecha_nc, no por fecha
        if ini <= d <= fin:
            return _mes_key(d.year, d.month)
    return None


def expand_buckets_from_months(df, cultivo_cfg: dict):
    """Toma un DataFrame con cols mensuales (2026_03, 2026_04, ...) + NC y
    agrega columnas virtuales por bucket sumando las cols mensuales
    correspondientes. Si las cols de bucket ya existen, no las pisa.

    No requiere import de pandas a nivel de módulo (lazy-importado por uso).
    """
    mapping = bucket_to_meses(cultivo_cfg)
    for bucket, meses in mapping.items():
        if bucket in df.columns:
            continue  # ya existe (matriz vieja con buckets nativos)
        # Sumar cols mensuales que existen en el DF
        cols_presentes = [c for c in meses if c in df.columns]
        if not cols_presentes:
            df[bucket] = 0
        else:
            df[bucket] = df[cols_presentes].sum(axis=1)
    return df


def slug_de(cultivo_cfg: dict) -> str:
    """ASCII slug of the crop (searches in CULTIVOS)."""
    for slug, c in CULTIVOS.items():
        if c is cultivo_cfg:
            return slug
    return cultivo_cfg["label"].lower().split()[0]


def minagri_json_path(cultivo_cfg: dict) -> str:
    """Standard path for the per-crop MINAGRI historical JSON."""
    cosecha = cultivo_cfg["cosecha"].replace("/", "_")
    return f"data/minagri_{slug_de(cultivo_cfg)}_{cosecha}.json"
