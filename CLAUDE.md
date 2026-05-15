# CLAUDE.md — App All

Guía para Claude (y para vos cuando volvés en 3 meses) sobre la mega-app
que combina Farmer Selling + Lineups + Dashboard ejecutivo.

## Qué es esto

Una única app de Streamlit con un menú de tres botones:

- 📊 **Dashboard** — vista ejecutiva con pizarra, FS de ayer/semana,
  nuestras compras (Recap), Monthly Pace 2×2, Top 5 shippers 2×2.
- 🌽 **Farmer Selling** — la app `fs_maiz/app.py` original, ejecutada en
  el mismo proceso por el wrapper.
- 🚢 **Lineups** — la app `Lineups/lineups_app.py` original, ejecutada
  igual.

El menú está en `app_all.py`. El dashboard nativo está en `dashboard.py`.

## Arquitectura del wrapper

`app_all.py` hace lo siguiente cuando arranca:

1. Llama una vez a `st.set_page_config()` (Streamlit no permite dos por sesión).
2. Muestra el menú con tres botones si `st.session_state.current_app is None`.
3. Cuando elegís FS o Lineups:
   - `os.chdir()` a su subcarpeta (para que `Path("data")` y `*.xls`
     funcionen igual que cuando se corre cada app sola).
   - Inserta su carpeta en `sys.path` (para que `import cultivos`, etc.,
     resuelvan los `.py` vecinos).
   - Lee el script original, le saca al vuelo la llamada a `set_page_config`
     con un regex, y hace `exec()` pasando `__file__` y `__name__="__main__"`.
4. Cuando elegís Dashboard, importa `dashboard.py` y llama a
   `render_dashboard(APP_ALL_DIR)`. No hay `exec` — es un módulo nativo.

**Importante**: el código de `fs_maiz/app.py` y `Lineups/lineups_app.py`
queda **intacto**. Si en algún momento querés volver a tener apps separadas,
copiás esas subcarpetas a otro lugar y corrés `streamlit run app.py` de cada
una.

## Estructura de archivos

```
10. App All/                          ← repo raíz (en GitHub: app-all)
├── app_all.py                        ← launcher
├── dashboard.py                      ← módulo nativo del Dashboard
├── requirements.txt                  ← deps combinadas
├── README.md, CLAUDE.md, DEPLOY.md
├── run_ngrok.sh                      ← launcher + tunnel local
├── .streamlit/config.toml            ← light theme, XSRF off para ngrok
│
├── fs_maiz/                          ← app embebida 1
│   ├── app.py                        ← UI (tabs: Monthly Pace, Charts, Origin)
│   ├── correr_diario.py              ← orquestador del pipeline
│   ├── actualizar_fs.py              ← regenera matrices
│   ├── actualizar_minagri.py
│   ├── descargar_sio.py              ← Playwright + SIO scraping
│   ├── scrapers/bcr_boletin.py       ← pizarra + MAT + CBOT
│   ├── cultivos.py                   ← config maíz/trigo/cebada/sorgo
│   ├── destinos.py                   ← puertos (uprivers/bahia/necochea/interior)
│   ├── Makefile                      ← `make daily`, `make pizarra`, etc.
│   ├── run_and_publish.sh            ← wrapper invocado por launchd
│   ├── com.alfonso.fsmaiz.plist      ← template del cron
│   ├── .venv/                        ← venv del pipeline (NO va al repo)
│   └── data/
│       ├── matriz_<slug>.csv         ← consolidado por cultivo
│       ├── matriz_<slug>_<port>.csv  ← por puerto
│       ├── destinos_<slug>.csv
│       ├── origenes_<slug>.csv
│       ├── historical_metrics_<slug>.json
│       ├── minagri_<slug>_<cosecha>.json
│       ├── prices.json               ← pizarra + MAT + CBOT + minagri
│       ├── prices_history.jsonl
│       ├── sio_historico.csv         ← 2 GB, NO va al repo
│       ├── _sio_chunks/              ← 2 GB, NO va al repo
│       ├── boletines/                ← PDFs de BCR
│       └── *.geojson
│
├── Lineups/                          ← app embebida 2
│   ├── lineups_app.py
│   ├── _lineups_loader.py            ← parser sin streamlit, lo usa el dashboard
│   ├── GRAIN-SBS-BARLEY-MALT SHIPMENTS <Mes 2026>.xls
│   └── .venv/                        ← NO va al repo
│
├── 0. MARS/                          ← Country Balance Sheets (LDC interno)
│   └── Country Balance Sheet (29-32).xlsx
│
└── .venv/                            ← venv del launcher (streamlit + xlrd + openpyxl)
```

**Fuera del repo, pero usado por el Dashboard:**

```
~/5. Recap Totalizado/                ← carpeta LDC con nuestras compras
├── RecapTotalizado <DD.MM.YY>.xlsx   ← se actualiza con update_totalizado.py
├── update_totalizado.py
└── README_AUTOMATIZACION.md
```

El dashboard lee la última `RecapTotalizado*.xlsx` por `mtime`. Se puede
sobreescribir con `RECAP_DIR=/ruta/...` antes de lanzar Streamlit.

## Data flow y frecuencias de actualización

| Fuente | Quién lo actualiza | Frecuencia | Output |
|---|---|---|---|
| SIO Granos | `correr_diario.py` (cron launchd) | 10:45 y 18:45 | `data/sio_historico.csv` |
| MAGYP / MINAGRI | `actualizar_minagri.py` (cron) | mismo cron, solo si hay XLSX nuevo | `data/minagri_*.json` |
| Matrices por cultivo | `actualizar_fs.py` (cron) | mismo cron | `data/matriz_*.csv` |
| Pizarra CAC + MAT + CBOT | `scrapers/bcr_boletin.py` (cron) | mismo cron | `data/prices.json` |
| `git push` automático | `run_and_publish.sh` | después del cron | repo `app-all` |
| Lineups XLS (Alpemar) | **vos a mano** | semanal por mail | `Lineups/*.xls` |
| MARS XLSX | **vos a mano** | cuando se actualiza el BS | `0. MARS/*.xlsx` |
| Recap Totalizado | `update_totalizado.py` (vos) | día a día | `~/5. Recap Totalizado/RecapTotalizado *.xlsx` |

**Limitación actual**: el cron corre en tu Mac. Si está apagada a las 10:45 /
18:45, ese día no se actualiza FS. La app sigue online con los últimos datos
pusheados.

## Convenciones importantes (no obvias del código)

### "Hoy" se excluye de "realizado"

Tanto en Monthly Pace de FS como en el Dashboard, el día de hoy **no entra**
como dato realizado. La razón: el pipeline corre a las 10:45/18:45, así que
durante el día la fila de hoy puede estar incompleta o no existir. La curva
verde llega hasta ayer; la curva amarilla (forecast) arranca en hoy y va
hasta fin de mes.

### Lineups: cap por mtime, no por today

Los xls de Alpemar llegan **una vez por semana**. Más allá del `mtime` del
archivo, todo es proyección. El acumulado Sailed corta en `min(today,
file_mtime)`, y desde ahí el forecast distribuye `At Roads + Lineup`
linealmente sobre los días hábiles restantes hasta fin de mes.

Implementado en `_lineups_loader.monthly_cumulative()` con el param
`last_data_date`. La función `file_last_date_for_month()` lo computa
automático.

### Trigo: solo exportación

Cuando el slug es `trigo`, `load_matriz()` (en `fs_maiz/app.py` y `dashboard.py`)
**no** lee `matriz_trigo.csv`. Lee y suma `matriz_trigo_uprivers.csv` +
`matriz_trigo_bahia.csv` + `matriz_trigo_necochea.csv`. El Interior queda
excluido a nivel data. Esto afecta todos los displays de trigo en toda la app.

Si querés revertir esto: editar `_WHEAT_EXPORT_PORTS` o pasarle un set vacío.

### OC vs NC

Cosecha "actual" (OC) y "nueva" (NC) por cultivo:

- Maíz / Sorgo: OC = 2025/2026, NC = 2026/2027 (cosecha Mar/Feb)
- Trigo / Cebada: OC = 2025/2026, NC = 2026/2027 (cosecha Dec/Nov)

En el dashboard, los pace y averages **solo cuentan OC**. NC se muestra al
lado pero no entra en el "Pace OC · Semana" ni "Pace OC · 10d".

### Replacement de la Pizarra

Solo **maíz** tiene Chicago asociado. Para los demás, replacement es solo
el FOB equivalente:

- 🌽 **Maíz**: `(pizarra + MINAGRI_cercano × 0.085 + $12) × 100 / 39.368 −
  CBOT_corn_<next_cycle>` → resultado en cents/bushel.
- 🌾 **Trigo**, 🌱 **Sorgo**, 🌿 **Cebada**: `pizarra + MINAGRI_cercano ×
  retención + $12` → resultado en USD/tn.

El CBOT usado para maíz es el "next cycle" del ciclo H/K/N/U/Z (Mar/May/Jul/
Sep/Dic). Si hoy es mayo, el next cycle es Jul. Esto está en
`_next_cycle_cbot_label()` en `dashboard.py`.

Los valores de CBOT en `prices.json` son los del **close del día anterior**
(scrape después del settle de US). Eso se muestra como "close DD/MM" en la
tarjeta de pizarra.

### Compras propias (Recap)

Lo que cuenta como "compra" en el Recap Totalizado:

- `COMPRAS A PRECIO`, `FIJACIONES COMPRA`, `FIJACIONES COMPRA FAS EN PREMIO`,
  `COMPRAS PAF`
- `AMPLIACION` con `qtty` positiva
- `ANULACION` con `qtty` negativa (resta automáticamente al sumar)

**No cuenta**: `VENTAS A PRECIO`, `FIJACIONES VENTAS`.

Variantes de mayúsculas/tilde están todas en `COMPRA_OPS` en `dashboard.py`.

### Share vs FS

`share = nuestras_compras / FS_total × 100`, calculado por cultivo y período
(ayer / semana). Para trigo usa FS de exportación únicamente (consecuente
con el filtro de trigo descripto arriba).

### Fines de semana

El chart Monthly Pace usa eje X **ordinal** (`dia:O`), no temporal. Eso
hace que sábados y domingos no aparezcan como huecos planos en la curva —
lunes a viernes quedan visualmente contiguos.

## Comandos clave

```bash
cd "/Users/alfonsoancarola/10. App All"

# Correr local (con ngrok)
./run_ngrok.sh

# Correr local sin ngrok
source .venv/bin/activate
streamlit run app_all.py

# Pipeline diario manual (refresca data FS)
cd fs_maiz && make daily             # ~5 min, full pipeline (SIO + MAGYP + matrices + precios)
cd fs_maiz && make precios           # ~10 seg, solo precios del boletín BCR (pizarra + MAT + CBOT + MINAGRI)
cd fs_maiz && make pizarra           # ~5 seg, solo pizarra CAC intra-día

# Forzar el cron a correr ahora
launchctl start com.$(whoami).fsmaiz

# Ver logs del cron
tail -f fs_maiz/launchd.log

# Reprogramar el cron
cd fs_maiz
make unschedule
make schedule HORAS=10:45,18:45
```

## Cómo iterar hacia adelante

### Día a día (tareas operativas)

| Qué | Cómo |
|---|---|
| Refrescar FS manualmente | `cd fs_maiz && make daily` |
| Refrescar solo pizarra | `cd fs_maiz && make pizarra` |
| Subir un xls nuevo de Alpemar | Copiar a `Lineups/`, después `git add Lineups/ && git commit && git push` |
| Subir una nueva versión de MARS | Reemplazar el xlsx en `0. MARS/`, después `git push` |
| Refrescar el Recap | `cd "~/5. Recap Totalizado" && python3 update_totalizado.py RecapConsolidadoFOB_<fecha>.xls` |
| Ver la app online | https://app-all.streamlit.app (cuando deployemos) |

### Cuando edités código

```bash
cd "/Users/alfonsoancarola/10. App All"
git status                    # ver qué cambió
git add -A
git commit -m "lo que tocaste"
git push                      # → auto-redeploy en Streamlit Cloud
```

### Agregar un cultivo nuevo (ej. soja)

1. `fs_maiz/cultivos.py` — agregar entry en `CULTIVOS`.
2. `fs_maiz/scrapers/bcr_boletin.py` — agregar mapping de pizarra si aplica.
3. `Lineups/_lineups_loader.py` — agregar a `FS_SLUG_TO_CARGO`.
4. `dashboard.py` — agregar a `CULTIVOS`, `FS_TO_CARGO`,
   `SLUG_TO_RECAP_PROD`, `_FS_OC_GROUPS`, `_CBOT_VIEW` si aplica.
5. Correr `make daily` para que se generen las matrices.

### Cambiar un color, etiqueta o umbral

Casi todos los colores están hardcodeados con hex codes en cada archivo:

- Colores de Lineups (Sailed/At Roads/Lineup/Target/Forecast): `COL_*` en
  `Lineups/lineups_app.py` ~líneas 188-195.
- Colores de destinos (uprivers/bahia/necochea/interior): `DESTINOS_COLOR`
  en `fs_maiz/destinos.py`.
- Colores del Monthly Pace en FS: dentro del `with tab_pace:` block en
  `fs_maiz/app.py`, en el dict de `_mp_color_full`.
- Colores del Dashboard: `SHIPPER_BAR_COLORS`, paletas del chart de
  pace en `dashboard.py`.

### Agregar una sección al Dashboard

`dashboard.py` está dividido en bloques numerados (0. Pizarra, 1. FS, 1B.
Nuestras Compras, 2. Monthly Pace, 3. Shippers, 4. ya no existe). Cada
bloque arranca con un comentario `# ====` y termina con `st.divider()`.
Agregá uno nuevo entre los existentes siguiendo el patrón.

Para sumar data de otra fuente nueva: si es xlsx, agregá un loader
`@st.cache_data` con el `mtime` del archivo como invalidador (mirá
`_load_recap_database` como modelo).

### Cambiar la regla de "qué cuenta como compra"

Editar `COMPRA_OPS` en `dashboard.py`. Las anulaciones vienen con `qtty`
negativa del Recap, así que al sumarlas restan automáticamente.

### Cambiar el filtro de trigo

`_WHEAT_EXPORT_PORTS` en `fs_maiz/app.py` y `dashboard.py`. Si querés
agregar el Interior de vuelta: ponelo en esa lista.

## Cosas a evitar

- **No llamar `st.set_page_config()` dentro de `fs_maiz/app.py` o
  `lineups_app.py`** — el wrapper lo hace una vez y se lo strippea a los
  scripts embebidos con regex. Si alguien agrega otra llamada, romper.
- **No commitear `sio_historico.csv` ni `data/_sio_chunks/`** — son ~4 GB.
  Están en `.gitignore`.
- **No commitear `.venv/`** — distinta por usuario.
- **No editar a mano `matriz_<slug>.csv`** — los reescribe `make daily`.
  Si querés un override, hacelo en `actualizar_fs.py`.
- **No mezclar `git status` antes de saber qué está en el .gitignore** —
  el `prices_history.jsonl` crece a ~5 KB/día y entra al repo (es chico, OK).

## Deploy (pendiente)

La semana que viene movemos a la nube:

- App → Streamlit Community Cloud apuntando al repo `alfonsoancarola/app-all`.
- Pipeline → opciones: VPS argentino ($5-10/mes), mini-PC dedicado, o
  seguir con el modelo híbrido (Mac + cloud).
- Lineups y Recap → seguir manual por ahora, automatizar después con
  Gmail forwarder + Drive sync.

Ver `fs_maiz/DEPLOY.md` para el camino híbrido ya documentado del fs_maiz
original (sin Lineups ni Dashboard).
