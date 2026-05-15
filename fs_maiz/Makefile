# Makefile — FS Maíz 25/26
# Targets:
#   make setup                                    crea .venv, instala deps + Chromium
#   make daily                                    flujo full: SIO + MINAGRI + matriz
#   make sio                                      solo bajar el CSV de SIO
#   make minagri                                  solo chequear MINAGRI
#   make update SIO=ruta/al/sio.csv               regenera matriz desde un CSV existente
#   make run                                      levanta la app Streamlit
#   make schedule [HORA=18:30]                    programa make daily en launchd
#   make unschedule                               quita el job
#   make discover-sio / discover-minagri          modo debug: imprime selectores/links
#   make clean                                    borra .venv

PY      := .venv/bin/python
PIP     := .venv/bin/pip
HERE    := $(shell pwd)
USER    := $(shell whoami)
PLIST   := com.$(USER).fsmaiz.plist
PLIST_T := com.alfonso.fsmaiz.plist
LAUNCHD := $(HOME)/Library/LaunchAgents/$(PLIST)

.DEFAULT_GOAL := help

help:
	@echo "FS Maíz 25/26 — comandos disponibles:"
	@echo "  make setup                                  → .venv + deps + Chromium"
	@echo "  make backfill                               → backfill MINAGRI + SIO histórico (one-time)"
	@echo "  make backfill-minagri                       → solo MINAGRI 25/26 (4 cultivos)"
	@echo "  make backfill-minagri-historico             → MINAGRI últimas 10 cosechas (lento, una vez)"
	@echo "  make backfill-sio-historico                 → SIO desde 2017 (~30-60min, ~2GB, una vez)"
	@echo "  make historical-metrics                     → recompute métricas históricas para el panel"
	@echo "  make geojson-ar                             → bajar GeoJSON de provincias para el mapa"
	@echo "  make backfill-sio  [DESDE=2025-03-01]       → solo SIO: histórico en chunks de 180d"
	@echo "  make daily                                  → flujo diario (SIO+merge+MINAGRI+matriz)"
	@echo "  make publish                                → daily + git push de matrices (lo que corre launchd)"
	@echo "  make sio                                    → solo bajar SIO a ~/Downloads/sio.csv"
	@echo "  make minagri                                → solo chequear MINAGRI semanal"
	@echo "  make update SIO=ruta/al/sio.csv             → regenera matriz desde un CSV existente"
	@echo "  make run                                    → levanta la app Streamlit"
	@echo "  make schedule [HORA=18:30]                  → programa make daily en launchd"
	@echo "  make unschedule                             → quita el job"
	@echo "  make discover-sio                           → debug: imprime DOM SIO"
	@echo "  make discover-minagri                       → debug: imprime links MAGYP"
	@echo "  make debug-sio                              → corre con browser visible"
	@echo "  make clean                                  → borra .venv"

# ─── Setup ──────────────────────────────────────────────────────────────────
.venv:
	python3 -m venv .venv
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt
	$(PY) -m playwright install chromium

setup: .venv
	@echo "Listo. Probá:  make daily"

# ─── Backfill (one-time, multi-cultivo) ─────────────────────────────────────
DESDE ?= 2025-03-01

backfill: backfill-minagri backfill-sio backfill-matrices
	@echo "Backfill completo. SIO histórico + MINAGRI por cultivo + 4 matrices."

backfill-minagri: backfill-minagri-maiz backfill-minagri-trigo backfill-minagri-cebada backfill-minagri-sorgo

backfill-minagri-maiz: .venv
	@$(PY) actualizar_minagri.py --backfill --anios 2025,2026 \
		--cultivo "Maíz" --cosecha 25/26 \
		--json-out data/minagri_maiz_25_26.json

backfill-minagri-trigo: .venv
	@$(PY) actualizar_minagri.py --backfill --anios 2025,2026 \
		--cultivo "Trigo" --cosecha 25/26 \
		--json-out data/minagri_trigo_25_26.json

backfill-minagri-cebada: .venv
	@$(PY) actualizar_minagri.py --backfill --anios 2025,2026 \
		--cultivo "Cebada Forrajera" --cosecha 25/26 \
		--json-out data/minagri_cebada_25_26.json

backfill-minagri-sorgo: .venv
	@$(PY) actualizar_minagri.py --backfill --anios 2025,2026 \
		--cultivo "Sorgo" --cosecha 25/26 \
		--json-out data/minagri_sorgo_25_26.json

# Backfill histórico de MINAGRI: últimas 10 cosechas para los 4 cultivos.
# Toma su tiempo (~5-10 min) — solo se corre una vez.
SEASONS_HIST := 16/17 17/18 18/19 19/20 20/21 21/22 22/23 23/24 24/25 25/26

backfill-minagri-historico: .venv
	@for season in $(SEASONS_HIST); do \
	  season_safe=$$(echo $$season | tr '/' '_'); \
	  y1=20$$(echo $$season | cut -d'/' -f1); \
	  y2=20$$(echo $$season | cut -d'/' -f2); \
	  for cult_triple in \
	    "maiz:Maíz:Compras Sector Exportador" \
	    "trigo:Trigo:Compras Sector Exportador" \
	    "sorgo:Sorgo:Compras Sector Exportador" \
	    "cebada:Cebada Forrajera:Compras Sector Exportador"; do \
	    slug=$$(echo $$cult_triple | cut -d':' -f1); \
	    name=$$(echo $$cult_triple | cut -d':' -f2); \
	    sec=$$(echo $$cult_triple | cut -d':' -f3); \
	    out=data/minagri_$${slug}_$${season_safe}.json; \
	    if [ -f "$$out" ] && [ "$$season" != "25/26" ]; then \
	      echo "  ✓ $$out (ya existe, skip)"; \
	    else \
	      echo "==> $$name $$season ($$y1,$$y2) [seccion=$$sec] → $$out"; \
	      $(PY) actualizar_minagri.py --backfill --anios $$y1,$$y2 \
	        --cultivo "$$name" --cosecha $$season --seccion "$$sec" \
	        --json-out "$$out" || echo "  ⚠ falló $$name $$season, sigo"; \
	    fi; \
	  done; \
	done
	@echo "Backfill histórico completo. Mirá data/minagri_*_*.json"

backfill-sio: .venv
	@$(PY) descargar_sio.py --backfill-desde $(DESDE) --out data/sio_historico.csv

# Backfill SIO histórico extendido (10 años, ~30-60 min, ~2GB en disco).
# Una sola vez. Después regenerás con `make historical-metrics`.
backfill-sio-historico: .venv
	@$(PY) descargar_sio.py --backfill-desde 2017-01-01 --out data/sio_historico.csv

# Cómputo de métricas históricas para el panel de comparación en la app.
# Lee SIO histórico + MINAGRI JSONs + BALANCE_HIST. Genera un JSON por cultivo.
historical-metrics: .venv
	@$(PY) compute_historical_metrics.py
	@echo "✅ Historical metrics computed for all crops."

backfill-matrices: .venv
	@$(PY) actualizar_fs.py --sio data/sio_historico.csv --cultivo maiz
	@$(PY) actualizar_fs.py --sio data/sio_historico.csv --cultivo trigo
	@$(PY) actualizar_fs.py --sio data/sio_historico.csv --cultivo cebada
	@$(PY) actualizar_fs.py --sio data/sio_historico.csv --cultivo sorgo

# Descarga el GeoJSON de provincias argentinas (one-time, para el mapa origen)
geojson-ar: .venv
	@$(PY) descargar_geojson_ar.py

# Backfill del histórico de precios desde boletines BCR viejos (one-time).
# Lee el N actual de prices.json y va N-1, N-2, ... hasta MAX boletines.
# Pasame MAX=120 para ir más atrás (default 60 → ~3 meses).
MAX ?= 60
backfill-prices-history: .venv
	@$(PY) backfill_prices_history.py --max-tries $(MAX)

# ─── Flujo diario completo ──────────────────────────────────────────────────
# Default: SIO solo últimos 15 días (rápido). El histórico se mantiene actualizado
# vía merge con dedup, así que cada día solo necesitamos cubrir los huecos.
daily: .venv
	@$(PY) correr_diario.py

# Full refresh: baja SIO de los últimos 180 días (lo máximo permitido por SIO
# en una sola query). Usalo si quedaste atrasado o si querés recapturar
# operaciones publicadas tardíamente. ~10x más lento que `make daily`.
daily-full: .venv
	@$(PY) correr_diario.py --sio-days 180

# Como `daily` pero al final hace git add/commit/push de las matrices
# regeneradas para que Streamlit Cloud las recoja. Es el target que invoca
# el launchd vía run_and_publish.sh (ver com.alfonso.fsmaiz.plist).
publish: .venv
	@./run_and_publish.sh

sio: .venv
	@$(PY) descargar_sio.py

minagri: .venv
	@$(PY) actualizar_minagri.py

# Solo refresca la Pizarra CAC (intra-día rápido, sin tocar boletín / MAT / CBOT)
pizarra: .venv
	@$(PY) -m scrapers.bcr_boletin --pizarra-only

# Refresca TODO lo de precios desde el boletín BCR: pizarra + MAT + CBOT + MINAGRI.
# Tarda ~10 seg (baja el PDF del día). NO toca matrices ni SIO.
# Usalo cuando querés ver replacement actualizado sin esperar el cron.
precios: .venv
	@$(PY) -m scrapers.bcr_boletin

update: .venv
	@if [ -z "$(SIO)" ]; then \
	  echo "Falta SIO=... Ejemplo:  make update SIO=~/Downloads/sio.csv"; exit 2; \
	fi
	@$(PY) actualizar_fs.py --sio "$(SIO)" \
	  $(if $(MINAGRI),--minagri $(MINAGRI),) \
	  $(if $(COPIAR_A),--copiar-a "$(COPIAR_A)",)

# ─── Modos debug ────────────────────────────────────────────────────────────
discover-sio: .venv
	@$(PY) descargar_sio.py --discover

discover-minagri: .venv
	@$(PY) actualizar_minagri.py --discover

debug-sio: .venv
	@$(PY) descargar_sio.py --debug

# ─── Run app ────────────────────────────────────────────────────────────────
run: .venv
	$(PY) -m streamlit run app.py

# ─── Scheduling con launchd (nativo Mac) ────────────────────────────────────
# Acepta una o varias horas separadas por coma:
#   make schedule                       → 10:45 + 18:45 (default)
#                                          10:45 → después de que CAC publica pizarra (~10:30)
#                                          18:45 → después de que sale el boletín BCR (~18:30)
#   make schedule HORAS=08:00           → solo 08:00
#   make schedule HORAS=09:30,13:00,19:00 → 3 horarios
HORAS ?= 10:45,18:45

schedule: .venv
	@mkdir -p "$(HOME)/Library/LaunchAgents"
	@python3 _gen_plist.py "$(HERE)" "com.$(USER).fsmaiz" "$(HORAS)" "$(PLIST_T)" "$(LAUNCHD)"
	@launchctl unload "$(LAUNCHD)" 2>/dev/null || true
	@launchctl load   "$(LAUNCHD)"
	@echo "Job programado: corre todos los días a las $(HORAS)"
	@echo "  Plist:   $(LAUNCHD)"
	@echo "  Logs:    $(HERE)/launchd.log"

unschedule:
	@launchctl unload "$(LAUNCHD)" 2>/dev/null || true
	@rm -f "$(LAUNCHD)"
	@echo "Job removido."

# ─── Limpieza ───────────────────────────────────────────────────────────────
clean:
	rm -rf .venv

.PHONY: help setup daily publish sio minagri update run schedule unschedule \
        discover-sio discover-minagri debug-sio clean
