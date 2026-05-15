#!/usr/bin/env bash
# run_and_publish.sh — Wrapper invocado por launchd.
#
# 1. Corre el pipeline diario (descargar SIO + MINAGRI + regenerar matrices).
# 2. Si el pipeline termina OK y hay cambios en data/, hace git add+commit+push
#    para que Streamlit Cloud detecte los datos nuevos y se redesploye.
#
# Por qué este wrapper (y no `make daily` + push en el plist):
#   - El plist queda más simple y no se rompe si cambian los argumentos.
#   - Acá podemos manejar el caso "pipeline falló → NO pushear" explícitamente.
#   - Es fácil de debuggear: corré `./run_and_publish.sh` a mano y mirá la salida.
#
# Requisitos:
#   - El repo tiene remote SSH (git@github.com:...) y la SSH key del usuario
#     está cargada en el Keychain de macOS (ver DEPLOY.md sección "SSH").
#   - `.venv/bin/python` existe (creado por `make setup`).

set -u  # error si referenciamos variable no definida; NO -e porque queremos manejar fallos
set -o pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

# Asegurar PATH razonable cuando nos invoca launchd (que arranca con PATH minimal).
export PATH="/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin:${PATH:-}"
# HOME suele estar seteado pero por las dudas:
: "${HOME:?HOME no está seteado, no puedo encontrar las SSH keys}"

ts() { date +"%Y-%m-%d %H:%M:%S"; }
log() { echo "$(ts) [publish] $*"; }

log "================================================================"
log "Inicio run_and_publish (cwd=$HERE)"

# ── 1. Correr pipeline ──────────────────────────────────────────────
log "Corriendo correr_diario.py ..."
if ./.venv/bin/python correr_diario.py; then
    PIPELINE_RC=0
    log "Pipeline OK"
else
    PIPELINE_RC=$?
    log "Pipeline terminó con errores (rc=$PIPELINE_RC). Aborto publish para no pushear datos parciales."
    exit "$PIPELINE_RC"
fi

# ── 2. ¿Hay cambios en data/ que valga la pena pushear? ─────────────
# Solo nos interesan los archivos derivados que la app realmente consume.
# El sio_historico.csv y _sio_chunks/ están en .gitignore desde antes.
PATHS_TO_PUBLISH=(
    "data/matriz_*.csv"
    "data/minagri_*.json"
    "data/historical_metrics_*.json"
    "data/destinos_*.csv"
    "data/origenes_*.csv"
    "data/prices.json"
)

# git add — usamos -A en los paths para detectar también borrados (si algún día limpiamos)
git add -A -- ${PATHS_TO_PUBLISH[@]} 2>/dev/null || true

if git diff --cached --quiet; then
    log "Sin cambios en data/, no hay nada para pushear."
    exit 0
fi

CHANGED_COUNT=$(git diff --cached --name-only | wc -l | tr -d ' ')
log "Hay $CHANGED_COUNT archivo(s) modificados en data/, commiteando..."

# ── 3. Commit + push ─────────────────────────────────────────────────
git -c user.name="fs-publisher" \
    -c user.email="alfonso.ancarola@gmail.com" \
    commit -m "data: actualización automática $(date +%Y-%m-%d_%H:%M)" \
    --quiet

log "Pusheando a origin/master..."
if git push origin master --quiet; then
    log "Push OK — Streamlit Cloud va a detectar el commit y redesployar."
    exit 0
else
    PUSH_RC=$?
    log "Push falló (rc=$PUSH_RC). El commit quedó local; el próximo run lo va a re-intentar."
    exit "$PUSH_RC"
fi
