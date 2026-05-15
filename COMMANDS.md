# COMMANDS.md — Cheat sheet App All

Resumen de todos los comandos operativos. Copiar-pegar friendly.

> 💡 **Atajo:** hay un `Makefile` en la raíz con casi todo lo de abajo
> envuelto. Tipeá `make` (sin args) en `10. App All/` para ver el help.

## ⚡ Atajos del Makefile (recomendado)

```bash
cd "/Users/alfonsoancarola/10. App All"

make help            # Lista todos los comandos disponibles
make status          # Muestra cuándo se actualizó cada fuente de data

# Correr la app
make run             # Streamlit local
make ngrok           # Streamlit + ngrok tunnel

# Refrescar inputs (delegan a fs_maiz/)
make daily           # FS completo (~5 min)
make precios         # Pizarra + MAT + CBOT + MINAGRI (~10s)
make pizarra         # Solo pizarra CAC (~5s)
make sio             # Solo SIO
make minagri         # Chequear MAGYP

# Procesar Recap LDC
make recap CONSO=RecapConsolidadoFOB_15-05-2026.xls

# Git push rápido
make push MSG="lo que cambiaste"
```

Los `make` de arriba delegan a los scripts originales — todo lo de
abajo sigue funcionando igual si preferís los comandos largos.

## 🚀 Correr la app

```bash
# Con ngrok (compartir externo) — recomendado
cd "/Users/alfonsoancarola/10. App All"
./run_ngrok.sh

# Solo local (sin ngrok)
cd "/Users/alfonsoancarola/10. App All"
source .venv/bin/activate
streamlit run app_all.py

# Si 8501 está pisado por algo viejo
lsof -ti tcp:8501 | xargs kill -9
```

## 📊 Actualizar Farmer Selling (SIO + MAGYP + pizarra)

```bash
cd "/Users/alfonsoancarola/10. App All/fs_maiz"

# Pipeline completo (~3-5 min)
make daily

# Solo pizarra CAC (intra-día rápido, no toca MAT/CBOT/MINAGRI) — ~5 seg
make pizarra

# Refrescar TODOS los precios del dashboard (pizarra + MAT + CBOT + MINAGRI) — ~10 seg
make precios

# Solo SIO (sin merge, sin matrices)
make sio

# Solo chequear MAGYP por XLSX nuevos
make minagri

# Backfill SIO 180 días (más lento, ~30 min)
make daily-full

# Saltearse el paso de precios
.venv/bin/python correr_diario.py --skip-prices
```

## 🤖 Manejar el cron de FS (launchd)

```bash
cd "/Users/alfonsoancarola/10. App All/fs_maiz"

# Programar (default 10:45 y 18:45)
make schedule

# Programar a otros horarios
make schedule HORAS=10:00,17:00

# Desprogramar (vacaciones)
make unschedule

# Forzar que el cron corra YA
launchctl start com.$(whoami).fsmaiz

# Ver log del cron en vivo
tail -f launchd.log
```

## 💼 Actualizar Compras LDC (Recap)

```bash
cd "/Users/alfonsoancarola/5. Recap Totalizado"

# Después de pegar el RecapConsolidadoFOB_<fecha>.xls en la carpeta
python3 update_totalizado.py "RecapConsolidadoFOB_<DD-MM-YYYY>.xls"

# Verificar que se generó el nuevo Totalizado
ls -lt RecapTotalizado*.xlsx | head -3

# Ver qué procesó
cat update_log_<DD.MM.YY>.txt
```

## 🚢 Subir XLS nuevo de Alpemar (Lineups)

```bash
# 1. Guardás el xls en Lineups/ con el nombre del mes correspondiente:
#    GRAIN-SBS-BARLEY-MALT SHIPMENTS Mayo 2026.xls

# 2. Commit + push
cd "/Users/alfonsoancarola/10. App All"
git add "Lineups/GRAIN-SBS-BARLEY-MALT SHIPMENTS Mayo 2026.xls"
git commit -m "Lineups Alpemar mayo"
git push
```

## 📒 Subir Country Balance Sheet nuevo (MARS)

```bash
# Reemplazás el archivo en 0. MARS/
# Después:
cd "/Users/alfonsoancarola/10. App All"
git add "0. MARS/"
git commit -m "MARS update"
git push
```

## 💻 Workflow de código

```bash
cd "/Users/alfonsoancarola/10. App All"

# Ver qué cambió
git status
git diff

# Commit + push
git add -A
git commit -m "lo que tocaste"
git push

# Ver historia
git log --oneline | head -10
```

## 🛠️ Setup si se rompe algo

```bash
# Recrear el venv del launcher
cd "/Users/alfonsoancarola/10. App All"
rm -rf .venv
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Recrear el venv del pipeline
cd fs_maiz
rm -rf .venv
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium    # para que SIO scrapee
```

## 🔍 Debug

```bash
# ¿Cuál es el último Totalizado que está leyendo el dashboard?
ls -lt "/Users/alfonsoancarola/5. Recap Totalizado/"RecapTotalizado*.xlsx | head -1

# ¿Cuándo corrió el cron por última vez?
tail -50 "/Users/alfonsoancarola/10. App All/fs_maiz/launchd.log"

# ¿Hay errores en el último run?
grep -i "error\|fail" "/Users/alfonsoancarola/10. App All/fs_maiz/launchd.log" | tail -20

# Ver qué procesos Streamlit están corriendo
lsof -i tcp:8501 -i tcp:8502 -i tcp:8503

# Matar todos los Streamlit
pkill -f streamlit
```

## 📁 Paths importantes

```
/Users/alfonsoancarola/10. App All/          ← repo principal (en GitHub: app-all)
├── app_all.py                                 ← launcher
├── dashboard.py                               ← Dashboard ejecutivo
├── fs_maiz/                                   ← app Farmer Selling
│   ├── app.py
│   ├── data/                                  ← matrices generadas por make daily
│   ├── Makefile                               ← make daily / pizarra / schedule
│   └── launchd.log                            ← log del cron
├── Lineups/                                   ← app Lineups
│   ├── lineups_app.py
│   └── GRAIN-SBS-*.xls                        ← drops semanales de Alpemar
└── 0. MARS/                                   ← Country Balance Sheets

/Users/alfonsoancarola/5. Recap Totalizado/   ← compras LDC (NO en repo)
├── update_totalizado.py
└── RecapTotalizado <DD.MM.YY>.xlsx           ← el dashboard lee el más nuevo
```

## ⏰ Frecuencias resumidas

| Tarea | Quién | Cuándo |
|---|---|---|
| `make daily` (FS + pizarra) | Cron automático | 10:45 y 18:45 |
| Push de FS data al repo | Cron (`run_and_publish.sh`) | Después del cron |
| `update_totalizado.py` | Vos | Día a día cuando hay operaciones |
| Drop XLS Alpemar | Vos | Semanal cuando llega el mail |
| Drop xlsx MARS | Vos | Cuando hay revisión nueva |
| Cambios de código + push | Vos | Cuando edités algo |

## 🔗 URLs importantes

- Repo GitHub: https://github.com/alfonsoancarola/app-all
- Streamlit Cloud (pendiente deploy): https://app-all.streamlit.app
- ngrok dashboard: http://127.0.0.1:4040 (mientras corre `run_ngrok.sh`)
