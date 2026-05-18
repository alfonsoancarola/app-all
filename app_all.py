"""
app_all.py — Launcher unificado de Farmer Selling + Lineups

Muestra un menú principal con dos botones. Cada botón abre, dentro del
mismo proceso de Streamlit, la app correspondiente (apuntando a sus
carpetas originales, sin duplicar código ni datos).

Run:
    streamlit run app_all.py
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import streamlit as st

# ──────────────────────────────────────────────────────────────────────────────
# Config global (única llamada a set_page_config en toda la sesión)
# ──────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="FS / Lineups / Repl.",
    page_icon="🌾",
    layout="wide",
)

# ──────────────────────────────────────────────────────────────────────────────
# Rutas de las dos apps embebidas (ahora viven dentro de App All)
# ──────────────────────────────────────────────────────────────────────────────
APP_ALL_DIR = Path(__file__).resolve().parent

FS_MAIZ_DIR = APP_ALL_DIR / "fs_maiz"
FS_MAIZ_SCRIPT = "app.py"

LINEUPS_DIR = APP_ALL_DIR / "Lineups"
LINEUPS_SCRIPT = "lineups_app.py"

# La carpeta MARS es hermana de Lineups por convención (Lineups la busca como
# ../0. MARS). La dejamos también adentro de App All.
MARS_DIR = APP_ALL_DIR / "0. MARS"
# Le decimos a Lineups dónde está, por si moviste la carpeta:
os.environ.setdefault("LINEUPS_MARS_DIR", str(MARS_DIR))

APPS = {
    "dashboard": {
        "label": "Dashboard",
        "emoji": "📊",
        "desc": "Vista ejecutiva · compras de ayer, pace, shippers y pizarra",
        "dir": None,            # No es una app embebida — se renderiza inline
        "script": None,
    },
    "fs_maiz": {
        "label": "Farmer Selling",
        "emoji": "🌽",
        "desc": "Cadencia de ventas de productores · maíz, trigo, cebada y sorgo",
        "dir": FS_MAIZ_DIR,
        "script": FS_MAIZ_SCRIPT,
    },
    "lineups": {
        "label": "Lineups",
        "emoji": "🚢",
        "desc": "Embarques de granos en puertos argentinos",
        "dir": LINEUPS_DIR,
        "script": LINEUPS_SCRIPT,
    },
    "pos_fisica": {
        "label": "Pos. Física",
        "emoji": "📦",
        "desc": "FS vendido vs Lineups pipeline por cultivo, destino y mes",
        "dir": None,
        "script": None,
    },
}

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

_SET_PAGE_CONFIG_RE = re.compile(
    r"st\.set_page_config\s*\([^)]*\)\s*",
    re.DOTALL,
)


def _strip_set_page_config(source: str) -> str:
    """Elimina la primera llamada a st.set_page_config(...) del script.

    El wrapper ya hizo la configuración una vez por sesión; si se vuelve a
    llamar, Streamlit lanza StreamlitAPIException.
    """
    return _SET_PAGE_CONFIG_RE.sub("# set_page_config skipped by app_all wrapper\n", source, count=1)


def _ensure_sys_path(app_dir: Path) -> None:
    p = str(app_dir.resolve())
    if p in sys.path:
        sys.path.remove(p)
    sys.path.insert(0, p)


def run_embedded_app(app_key: str) -> None:
    """Ejecuta el script de una app embebida en este mismo proceso."""
    cfg = APPS[app_key]
    if cfg.get("dir") is None or cfg.get("script") is None:
        st.error(f"`{app_key}` no es una app embebida.")
        return
    app_dir: Path = cfg["dir"]
    script_path: Path = app_dir / cfg["script"]

    if not script_path.exists():
        st.error(
            f"No encontré el script `{script_path}`. "
            "Revisá que la ruta esté bien o moviste la carpeta."
        )
        return

    # Para que `Path("data")`, `open("file.xls")`, etc., funcionen igual que
    # cuando se corre la app directamente desde su carpeta.
    try:
        os.chdir(app_dir)
    except OSError as e:
        st.error(f"No pude entrar a `{app_dir}`: {e}")
        return

    # Que los `import cultivos`, `from cultivos import ...` (y similares)
    # resuelvan los .py vecinos de la app embebida.
    _ensure_sys_path(app_dir)

    source = script_path.read_text(encoding="utf-8")
    source = _strip_set_page_config(source)

    code = compile(source, str(script_path), "exec")
    globals_dict = {
        "__file__": str(script_path),
        "__name__": "__main__",
        "__package__": None,
    }
    exec(code, globals_dict)


# ──────────────────────────────────────────────────────────────────────────────
# Estado y navegación
# ──────────────────────────────────────────────────────────────────────────────
if "current_app" not in st.session_state:
    st.session_state.current_app = None


def _go_to(app_key: str | None) -> None:
    st.session_state.current_app = app_key
    st.rerun()


# ──────────────────────────────────────────────────────────────────────────────
# UI: menú o app embebida
# ──────────────────────────────────────────────────────────────────────────────
if st.session_state.current_app is None:
    # Estética básica del menú
    st.markdown(
        """
        <style>
            .main .block-container { max-width: 1100px; padding-top: 3rem; }
            div.stButton > button {
                height: 170px;
                font-size: 1.25rem;
                font-weight: 600;
                border-radius: 16px;
                border: 1px solid rgba(120,120,120,0.25);
            }
            div.stButton > button:hover {
                border-color: rgba(0,120,255,0.6);
            }
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.title("🌾 FS / Lineups / Repl.")
    st.caption("Elegí qué sección querés abrir.")
    st.write("")

    # Cuatro tarjetas: Dashboard / Farmer Selling / Lineups / Pos. Física
    cols = st.columns(4, gap="medium")
    for col, key in zip(cols, ["dashboard", "fs_maiz", "lineups", "pos_fisica"]):
        with col:
            cfg = APPS[key]
            if st.button(
                f"{cfg['emoji']}\n\n{cfg['label']}",
                use_container_width=True,
                key=f"btn_{key}",
            ):
                _go_to(key)
            st.caption(cfg["desc"])

else:
    # Barra superior con botón de volver al menú
    cfg = APPS[st.session_state.current_app]
    top_l, top_r = st.columns([1, 6])
    with top_l:
        if st.button("← Menú", key="btn_back_to_menu"):
            _go_to(None)
    with top_r:
        st.caption(f"{cfg['emoji']} {cfg['label']}")

    st.divider()

    # Render según destino
    if st.session_state.current_app == "dashboard":
        # Dashboard nativo del wrapper (no embebe ningún script externo)
        import dashboard as _dash_mod  # noqa: WPS433
        _dash_mod.render_dashboard(APP_ALL_DIR)
    elif st.session_state.current_app == "pos_fisica":
        import pos_fisica as _pf_mod  # noqa: WPS433
        _pf_mod.render_pos_fisica(APP_ALL_DIR)
    else:
        # Ejecutamos la app embebida (fs_maiz o lineups)
        run_embedded_app(st.session_state.current_app)
