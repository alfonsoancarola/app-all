# Makefile del App All — atajos para correr la app y refrescar cada input.
#
# Sin args: `make` (o `make help`) muestra ayuda.
# Inputs:
#   make daily        FS completo (SIO + MAGYP + matrices + precios)
#   make precios      Solo precios desde boletín BCR (pizarra + MAT + CBOT + MINAGRI)
#   make pizarra      Solo pizarra CAC intra-día
#   make sio          Solo SIO
#   make minagri      Solo MAGYP (chequea XLSX nuevo)
#   make recap CONSO=RecapConsolidadoFOB_<fecha>.xls   Procesa Consolidado nuevo
# Correr la app:
#   make run          Streamlit local
#   make ngrok        Streamlit + tunnel ngrok
# Utilidades:
#   make status       Última actualización de cada fuente de data
#   make push MSG=... git add + commit + push

HERE        := $(shell pwd)
FS_MAIZ_DIR := $(HERE)/fs_maiz
RECAP_DIR   := $(HOME)/5. Recap Totalizado
LINEUPS_DIR := $(HERE)/Lineups

.DEFAULT_GOAL := help
.PHONY: help run ngrok daily daily-full precios pizarra sio minagri recap status push

help:
	@echo ""
	@echo "🌾 App All — comandos disponibles:"
	@echo ""
	@echo "  Correr la app:"
	@echo "    make run               ── Streamlit local (http://localhost:8501)"
	@echo "    make ngrok             ── Streamlit + tunnel ngrok (URL pública)"
	@echo ""
	@echo "  Refrescar precios (delegan a fs_maiz/):"
	@echo "    make daily             ── FS completo: SIO + MAGYP + matrices + precios (~5 min)"
	@echo "    make daily-full        ── Igual pero con backfill 180 días de SIO (~30 min)"
	@echo "    make precios           ── Pizarra + MAT + CBOT + MINAGRI desde boletín BCR (~10s)"
	@echo "    make pizarra           ── Solo pizarra CAC intra-día (~5s)"
	@echo "    make sio               ── Solo descarga SIO (sin merge ni matrices)"
	@echo "    make minagri           ── Chequea si MAGYP publicó XLSX nuevo"
	@echo ""
	@echo "  Procesar Recap LDC:"
	@echo "    make recap CONSO=<archivo>"
	@echo "      ej: make recap CONSO=RecapConsolidadoFOB_15-05-2026.xls"
	@echo ""
	@echo "  Utilidades:"
	@echo "    make status            ── Última actualización de cada fuente"
	@echo "    make push MSG=...      ── git add + commit + push"
	@echo ""

# ── Correr la app ────────────────────────────────────────────────────────────

run:
	@if [ -f ".venv/bin/activate" ]; then \
		. .venv/bin/activate; \
	fi; \
	streamlit run app_all.py

ngrok:
	@./run_ngrok.sh

# ── FS pipeline (delega al Makefile de fs_maiz/) ─────────────────────────────

daily:
	@cd "$(FS_MAIZ_DIR)" && $(MAKE) daily

daily-full:
	@cd "$(FS_MAIZ_DIR)" && $(MAKE) daily-full

precios:
	@cd "$(FS_MAIZ_DIR)" && $(MAKE) precios

pizarra:
	@cd "$(FS_MAIZ_DIR)" && $(MAKE) pizarra

sio:
	@cd "$(FS_MAIZ_DIR)" && $(MAKE) sio

minagri:
	@cd "$(FS_MAIZ_DIR)" && $(MAKE) minagri

# ── Recap LDC (delega a 5. Recap Totalizado/update_totalizado.py) ────────────

recap:
	@if [ -z "$(CONSO)" ]; then \
		echo "❌ Falta CONSO=<archivo>. Ejemplo:"; \
		echo "    make recap CONSO=RecapConsolidadoFOB_15-05-2026.xls"; \
		exit 2; \
	fi
	@if [ ! -d "$(RECAP_DIR)" ]; then \
		echo "❌ No existe $(RECAP_DIR). Si la moviste, editá RECAP_DIR en este Makefile."; \
		exit 1; \
	fi
	@echo "→ Procesando $(CONSO)..."
	@cd "$(RECAP_DIR)" && python3 update_totalizado.py "$(CONSO)"
	@echo "✓ Recap actualizado. Refrescá el browser para ver los números nuevos."

# ── Status: cuándo fue la última actualización de cada fuente ───────────────

status:
	@echo ""
	@echo "📊 Status de inputs:"
	@echo ""
	@printf "  %-30s " "FS · sio_historico.csv:"
	@stat -f "%Sm" -t "%Y-%m-%d %H:%M" "$(FS_MAIZ_DIR)/data/sio_historico.csv" 2>/dev/null || echo "❌ no existe"
	@printf "  %-30s " "FS · prices.json:"
	@stat -f "%Sm" -t "%Y-%m-%d %H:%M" "$(FS_MAIZ_DIR)/data/prices.json" 2>/dev/null || echo "❌ no existe"
	@printf "  %-30s " "FS · matriz_maiz.csv:"
	@stat -f "%Sm" -t "%Y-%m-%d %H:%M" "$(FS_MAIZ_DIR)/data/matriz_maiz.csv" 2>/dev/null || echo "❌ no existe"
	@printf "  %-30s " "FS · matriz_trigo.csv:"
	@stat -f "%Sm" -t "%Y-%m-%d %H:%M" "$(FS_MAIZ_DIR)/data/matriz_trigo.csv" 2>/dev/null || echo "❌ no existe"
	@echo ""
	@printf "  %-30s\n" "Lineups (Alpemar):"
	@ls -1t "$(LINEUPS_DIR)"/GRAIN-SBS-*.xls 2>/dev/null | head -5 | sed 's|.*/||' | awk '{print "    └─ " $$0}' || echo "    ❌ ningún xls"
	@echo ""
	@printf "  %-30s\n" "MARS:"
	@ls -1t "$(HERE)/0. MARS"/*.xlsx 2>/dev/null | sed 's|.*/||' | awk '{print "    └─ " $$0}' || echo "    ❌ ningún xlsx"
	@echo ""
	@printf "  %-30s\n" "Recap LDC (último):"
	@ls -1t "$(RECAP_DIR)"/RecapTotalizado*.xlsx 2>/dev/null | head -3 | sed 's|.*/||' | awk '{print "    └─ " $$0}' || echo "    ❌ no encontrado"
	@echo ""

# ── Git push rápido ──────────────────────────────────────────────────────────

push:
	@MSG="$${MSG:-update}"; \
	git add -A && \
	echo "→ Commit: \"$$MSG\"" && \
	git commit -m "$$MSG" && \
	git push
