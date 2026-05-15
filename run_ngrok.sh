#!/usr/bin/env bash
# run_ngrok.sh — lanza la mega-app y la expone con ngrok en un solo paso.
#
# Uso:
#   ./run_ngrok.sh                  # intenta 8501; si está ocupado, Streamlit
#                                   # salta a 8502/3/… y ngrok lo sigue automático.
#   PORT=8505 ./run_ngrok.sh        # forzar otro puerto base.
#
# Para parar todo: Ctrl+C en esta terminal (mata streamlit + ngrok juntos).

set -e

HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"

PORT="${PORT:-8501}"

# Activar venv si existe
if [ -f ".venv/bin/activate" ]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

# Verificar que ngrok esté instalado
if ! command -v ngrok >/dev/null 2>&1; then
  echo "❌ ngrok no está instalado. Instalalo:"
  echo "    brew install --cask ngrok"
  echo "    ngrok config add-authtoken <tu_token>     # una sola vez"
  exit 1
fi

# Cleanup al salir
cleanup() {
  echo ""
  echo "→ cerrando streamlit y ngrok…"
  [ -n "$STREAMLIT_PID" ] && kill $STREAMLIT_PID 2>/dev/null || true
  [ -n "$NGROK_PID" ] && kill $NGROK_PID 2>/dev/null || true
  exit 0
}
trap cleanup INT TERM

LOG=/tmp/app_all_streamlit.log
: > "$LOG"

# Lanzar Streamlit. Le pedimos $PORT pero si está ocupado va a saltar al
# siguiente y lo loguea — abajo lo detectamos.
echo "→ arrancando Streamlit (intentando :$PORT) …"
streamlit run app_all.py \
  --server.port "$PORT" \
  --server.headless true \
  > "$LOG" 2>&1 &
STREAMLIT_PID=$!

# Esperar hasta que Streamlit esté escuchando y averiguar EN QUÉ puerto quedó.
# (Si 8501 estaba ocupado por otra cosa, Streamlit se mueve a 8502/3/… solo.)
ACTUAL_PORT=""
for i in $(seq 1 40); do
  # lsof sobre el PID de streamlit nos dice qué puerto está bindeado
  ACTUAL_PORT="$(lsof -nP -iTCP -sTCP:LISTEN -a -p "$STREAMLIT_PID" 2>/dev/null \
    | awk 'NR>1 {print $9}' | sed -E 's/.*:([0-9]+)$/\1/' | head -1)"
  if [ -n "$ACTUAL_PORT" ]; then
    break
  fi
  # Si streamlit murió, salir
  if ! kill -0 "$STREAMLIT_PID" 2>/dev/null; then
    echo "❌ Streamlit no levantó. Últimas líneas del log:"
    tail -20 "$LOG"
    exit 1
  fi
  sleep 0.25
done

if [ -z "$ACTUAL_PORT" ]; then
  echo "❌ no pude detectar el puerto de Streamlit. Mirá $LOG"
  cleanup
fi

if [ "$ACTUAL_PORT" != "$PORT" ]; then
  echo "⚠ Streamlit no pudo usar :$PORT (estaba ocupado), está en :$ACTUAL_PORT"
fi

# Lanzar ngrok contra el puerto REAL
echo "→ arrancando ngrok hacia :$ACTUAL_PORT …"
ngrok http "$ACTUAL_PORT" --log=stdout > /tmp/app_all_ngrok.log 2>&1 &
NGROK_PID=$!

# Esperar a que ngrok arme el túnel y leer la URL pública desde su API local
PUBLIC_URL=""
for i in $(seq 1 30); do
  PUBLIC_URL="$(curl -s http://127.0.0.1:4040/api/tunnels 2>/dev/null \
    | python3 -c 'import sys,json
try:
    d=json.load(sys.stdin)
    t=d.get("tunnels",[])
    print(t[0]["public_url"]) if t else None
except Exception: pass' 2>/dev/null)"
  [ -n "$PUBLIC_URL" ] && break
  sleep 0.5
done

echo ""
echo "════════════════════════════════════════════════════════════════"
if [ -n "$PUBLIC_URL" ]; then
  echo "  URL pública:   $PUBLIC_URL"
else
  echo "  URL pública:   abrí http://127.0.0.1:4040 para verla"
fi
echo "  Local:         http://localhost:$ACTUAL_PORT"
echo "  Streamlit log: $LOG"
echo "  ngrok log:     /tmp/app_all_ngrok.log"
echo "  Ctrl+C acá apaga las dos cosas."
echo "════════════════════════════════════════════════════════════════"
echo ""

# Si cualquiera de los dos muere, matamos al otro
wait -n $STREAMLIT_PID $NGROK_PID 2>/dev/null || true
cleanup
