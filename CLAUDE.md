# CLAUDE.md — App All

Guía para Claude (y para vos cuando volvés en 3 meses) sobre la mega-app
que combina Farmer Selling + Lineups + Dashboard ejecutivo.

## Qué es esto

Una única app de Streamlit con un menú de **cuatro** botones:

- 📊 **Dashboard** — vista ejecutiva con pizarra (con MAT + CBOT +
  Replacement), Farmer Selling vs LDC ayer/semana/pace OC unificado en
  un solo card por cultivo, Monthly Pace 2×2, Top 5 shippers 2×2 (con 4
  barras por shipper: Total/Sailed/AtRoads/Lineup).
- 🌽 **Farmer Selling** — la app `fs_maiz/app.py` original, ejecutada en
  el mismo proceso por el wrapper. Solo se muestran 3 tabs: Monthly Pace,
  Charts, Origin map (Matrix y Destinations están desactivadas).
- 🚢 **Lineups** — la app `Lineups/lineups_app.py` original, con overlay
  de compras FS (violeta) sobre los charts mensuales.
- 📦 **Pos. Física** — heatmap por cultivo: rows = **meses calendario**
  (12 meses, con el bucket como sublabel), cols = **Total + 4 puertos**
  (Up River + Bahía + Necochea + Interior). Cada celda muestra FS /
  Exports / Pos / Pace en 2×2. Toggle "Por mes / Acumulada" arriba.
  8 summary cards: FS PH+Fij, A_Fijar (MAGYP), Exports Real, Pos. Real
  Física, Stock/Usage (en meses), Exports Estimados, Pos. Total y Pace
  a flat.

El menú está en `app_all.py`. El dashboard y la pos. física son módulos
nativos (`dashboard.py`, `pos_fisica.py`).

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
├── app_all.py                        ← launcher (4 botones)
├── dashboard.py                      ← módulo nativo del Dashboard
├── pos_fisica.py                     ← módulo nativo de Pos. Física
├── Makefile                          ← make daily/precios/recap/run/status/push
├── requirements.txt                  ← deps combinadas
├── README.md, CLAUDE.md, COMMANDS.md, DEPLOY.md
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
│   ├── _lineups_loader.py            ← parser sin streamlit, lo usa el
│   │                                   dashboard + pos_fisica. Devuelve
│   │                                   CARGO/TONS/ETA/STATUS/SHIPPER/PORT/ZONE
│   ├── GRAIN-SBS-BARLEY-MALT SHIPMENTS NOV 2025.xls   ← 7 xls cargados
│   ├── GRAIN-SBS-BARLEY-MALT SHIPMENTS DEC 2025.xls      hoy (Nov 25 → May 26)
│   ├── GRAIN-SBS-BARLEY-MALT SHIPMENTS JAN 2026.xls
│   ├── GRAIN-SBS-BARLEY-MALT SHIPMENTS FEB 2026.xls
│   ├── GRAIN-SBS-BARLEY-MALT SHIPMENTS March 2026.xls
│   ├── GRAIN-SBS-BARLEY-MALT SHIPMENTS April 2026.xls
│   ├── GRAIN-SBS-BARLEY-MALT SHIPMENTS May 2026.xls
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

### Schema mensual de las matrices (granularidad nativa)

A partir de mayo-26 las matrices FS tienen columnas por **mes calendario
individual** (`2026_03, 2026_04, 2026_05, ..., 2027_02, NC`) en lugar de
columnas por bucket (MAM/JJ/AS/...). Esto le da a Pos. Física granularidad
mensual real para el detalle FS por (mes × puerto).

Los buckets siguen existiendo como concepto y se calculan **al vuelo**
con el helper `expand_buckets_from_months(df, cfg)` en `cultivos.py`. Los
consumidores legacy (`fs_maiz/app.py`, `dashboard.py`) leen el CSV mensual
y obtienen las columnas de bucket virtuales sumando las cols mensuales
correspondientes — así Monthly Pace, Charts, Dashboard, todo sigue
funcionando sin tocar una línea más.

Funciones clave en `fs_maiz/cultivos.py`:
- `meses_cols(cfg) → list[str]`: cols mensuales del cultivo (incluye NC al final si aplica).
- `mes_de_entrega(date, cfg) → str | None`: mapea `fecha_desde` → `"2026_03"` (o None si fuera de rango).
- `bucket_to_meses(cfg) → dict`: mapping `{"MAM": ["2026_03","2026_04","2026_05"], ...}`.
- `expand_buckets_from_months(df, cfg)`: agrega cols de bucket virtuales sumando las mensuales.

### Pos. Física: bucket → meses (sigue válido como concepto)

Cada bucket agrupa 2 o 3 meses de delivery:

- Maíz / Sorgo: MAM=Mar–May, JJ=Jun–Jul, AS=Aug–Sep, OND=Oct–Dec, JF=Jan–Feb
- Trigo / Cebada: NDJ=Nov–Jan, FMA=Feb–Apr, MJJ=May–Jul, ASO=Aug–Oct

En `pos_fisica.py` están las constantes `BUCKETS_BY_SLUG` (mes → bucket)
y `BUCKET_MONTHS_BY_SLUG` (bucket → lista de meses). El heatmap muestra
los **meses individuales** como filas, con el bucket como sublabel.

### Pos. Física: Interior no tiene Lineup

Interior está en la 4ta columna del heatmap pero su **Lineup siempre es 0**
(no exporta — consumo doméstico). La columna se muestra con fondo gris
neutro, el celda Lineup dice "—", y `POS = FS` para esos casos. Sirve
para reconciliar el total FS con el FS app que sí incluye Interior.

### Pos. Física: proyección Lineups con MARS × share

Para los meses del bucket **sin xls cargado** (ej. JJ hoy = Jun+Jul 26),
el Lineup se **proyecta**:

```
proj_per_month = MARS_Exports[month] × port_share
```

Donde `port_share` es la fracción `total_zone_tons / total_cargo_tons`
calculada sobre **todos los xls cargados** (estable, aggregate). Se ve
con un asterisco `*` en la celda y en los totales. La proyección NO se
breakdownea por Sailed/Roads/Lineup — es un total agregado.

Sumar más xls al directorio Lineups/ (cuando llegan los del mes nuevo)
reduce la parte proyectada y aumenta la parte real automáticamente.

### Pos. Física: A_Fijar (saldo a fijar de MAGYP)

El A_Fijar (Saldo a Fijar columna 5 de MAGYP) es **commitment físico** —
tonelada vendida con precio abierto. Se levanta de
`data/minagri_<slug>_<cosecha>.json` vía `_load_a_fijar_kt()`.

Distribución:
- **TODO el A_Fijar va al bucket de cosecha** (MAM maíz/sorgo, NDJ trigo/cebada).
- **Solo a puertos de exportación** (Up River + Bahía + Necochea). Interior recibe 0.
- **Pro-rata por peso del FS PH+Fij** de cada celda (mes × puerto) dentro
  del bucket de cosecha: `weight = FS_celda / SUMA_FS_export_en_cosecha`.

Asunción: las nuevas fijaciones se distribuyen como las fijaciones cerradas
históricamente. Es heurística — no sabemos el destino real hasta que se
fija precio.

### Pos. Física: Posición REAL vs Posición TOTAL

Dos posiciones que se muestran en summary cards:

- **Pos. Real Física = (FS PH+Fij + A_Fijar) − Exports Real**
  Todo lo comprometido físicamente HOY (priced + open price) vs lo ya
  embarcado. Lo que efectivamente sobre/falta hoy.
- **Pos. Total = (FS PH+Fij + A_Fijar) − Exports Estimados**
  Misma posición pero comparando contra MARS-projected exports. Forward
  looking — incluye proyección de lo que vamos a embarcar.

La diferencia entre ambas = parte proyectada de Exports (real + proj − real
= proj). Importante: el **A_Fijar entra en ambas** porque es commitment
físico igual que el PH+Fij.

Convención de signos:
- **Positivo (LONG)** 🟢 — vendimos/comprometimos más de lo embarcado.
- **Negativo (SHORT)** 🔴 — vamos a embarcar más de lo comprometido (hay
  que comprar más o cubrir con stock).
- **Cerca de cero** — alineado.

### Pos. Física: Stock to Usage (en meses)

Card de cobertura en meses. La lógica:

1. Consume el LONG (Pos. Real Física) contra los exports MARS mes a mes
   en orden cronológico.
2. Arranca desde el **mes siguiente al actual** (los meses pasados se
   asumen ya embarcados).
3. Respeta la estacionalidad real de MARS (cosecha = ritmo alto, valles
   = ritmo bajo). No es un cálculo lineal anual.
4. Output: cuántos meses dura el LONG actual al ritmo MARS proyectado.

Para SHORT (Pos. Real < 0), el signo se invierte y representa "faltan X
meses para cerrar el gap al ritmo MARS".

### Pos. Física: vista mes × puerto

El heatmap pasó de `destino × bucket` a `mes × puerto`:
- **Filas:** 12 meses calendario del cultivo (con bucket como sublabel).
- **Cols:** Total + Up River + Bahía Blanca + Necochea + Interior.
- **Toggle "Por mes / Acumulada":** en modo Acumulada cada celda muestra
  el running total desde el primer mes hasta el actual.
- **PACE por celda:** días hábiles desde HOY hasta el fin del mes
  calendario específico (más fino que el PACE viejo por bucket).

Es razonable que los meses futuros (JJ/AS/OND/JF en maíz; ASO en
trigo) muestren SHORT grande, porque MARS proyecta el flujo completo
pero FS solo registra lo ya fijado.

### Pos. Física: subtotales por destino y bucket

El heatmap tiene una columna `Total` a la derecha (suma por destino,
todos los buckets) y una fila `Total` abajo (suma por bucket, todos los
destinos). La celda esquina-inferior-derecha es el grand total — debería
matchear con las cards del summary arriba del heatmap.

## Comandos clave

Hay un `Makefile` en la raíz de `10. App All/` que envuelve todo. Tipear
`make` (sin args) muestra el help. Ver también `COMMANDS.md` para el
cheat sheet completo.

```bash
cd "/Users/alfonsoancarola/10. App All"

# Correr la app
make run                              # streamlit local
make ngrok                            # streamlit + ngrok tunnel

# Status: cuándo se actualizó cada fuente
make status

# Pipeline FS (delegan a fs_maiz/)
make daily                            # ~5 min, full pipeline
make precios                          # ~10 seg, pizarra + MAT + CBOT + MINAGRI
make pizarra                          # ~5 seg, solo pizarra CAC intra-día
make sio                              # solo descarga SIO
make minagri                          # solo chequea MAGYP

# Procesar Recap LDC (compras propias)
make recap CONSO=RecapConsolidadoFOB_<DD-MM-YYYY>.xls

# Git
make push MSG="lo que cambiaste"      # add + commit + push

# Cron: forzar corrida + ver logs + reprogramar
launchctl start com.$(whoami).fsmaiz
tail -f fs_maiz/launchd.log
cd fs_maiz && make unschedule && make schedule HORAS=10:45,18:45
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

### Agregar un mes nuevo de Lineups (Alpemar)

Cuando llega un xls nuevo de Alpemar (mensual):

1. Guardalo en `Lineups/` con un nombre tipo
   `GRAIN-SBS-BARLEY-MALT SHIPMENTS <MES Año>.xls`. Convenciones que el
   loader ya soporta: meses en uppercase 3-letter (`NOV 2025`, `DEC
   2025`, `JAN 2026`, etc.) o nombre completo (`March 2026`, `April
   2026`, etc.).
2. Editar `MONTH_FILES` en **dos** lugares:
   - `Lineups/_lineups_loader.py`
   - `Lineups/lineups_app.py`
   La key del dict es el label en formato "Month YYYY" full (ej.
   `"November 2025"`); el value es `(filename, kind)` donde kind =
   `"finalized"` o `"current"`.
3. Si es un mes anterior al rango actual, también extender
   `_DEFAULT_CAMPAIGN_MONTHS` en `lineups_app.py` para que los charts
   anuales lo incluyan.
4. Commit + push. El dashboard y Pos. Física lo levantan solos.

Cada xls nuevo cargado **reduce automáticamente** la parte proyectada
en Pos. Física (porque ese mes deja de estar en `missing` y pasa a
ser real).

### Cambiar la regla de Posición Física

En `pos_fisica.py`, la posición se computa en el cell como
`pos = data["fs_tn"] - data["pipeline_total_tn"]`. Si quisieras que use
solo el lineup real (no estimado), cambialo a
`pos = data["fs_tn"] - data["pipeline_real_tn"]`. Ojo de actualizar
también la card de summary `total_pos` en la misma lógica.

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
- **No olvidar que MONTH_FILES está en DOS lugares** (loader y
  lineups_app.py). Si actualizás uno solo, el dashboard ve el mes nuevo
  pero la Lineups app no — o al revés.
- **No leer `matriz_<slug>.csv` directo para trigo en código nuevo** — el
  loader en `fs_maiz/app.py` y `dashboard.py` ya hace el merge de las 3
  sub-matrices de exportación. Si copiás código de otra parte que hace
  `pd.read_csv("matriz_trigo.csv")`, vas a estar leyendo data con
  Interior incluido.
- **No cambiar la `lineups_zone` de Interior a un string** en
  `pos_fisica.py` — `None` es el flag que el código usa para saber que
  no debe filtrar Lineups (Interior no exporta).
- **No leer `pd.read_csv("matriz_*.csv")` sin pasar por el helper** —
  el schema ahora es mensual (`2026_03, 2026_04, ...`). Los consumidores
  legacy esperan cols de bucket (`MAM, JJ, ...`). Hay que usar
  `_load_one_matriz_csv(path, GRUPOS, cfg=cfg)` en `fs_maiz/app.py` o
  `_read_matriz_csv_with_buckets(path, slug)` en `dashboard.py` —
  ambos detectan schema y expanden buckets virtuales via
  `expand_buckets_from_months`. En `pos_fisica.py` lo hace
  `_load_matriz_puerto` automáticamente.
- **No iterar `cfg["grupos"]` para parsear los valores numéricos del CSV
  en código nuevo** — `cfg["grupos"]` sigue siendo la lista de buckets
  (`["MAM","JJ","AS","OND","JF","NC"]` para maíz). Para las cols del CSV
  ahora se usa `meses_cols(cfg)` que devuelve los identifiers mensuales.
- **A_Fijar entra SIEMPRE en la Pos. Real Física** — es commitment
  físico, no opcional. La fórmula correcta es
  `Pos. Real = (FS PH+Fij + A_Fijar) − Exports Real`, NO
  `FS PH+Fij − Exports Real` solo.

## Deploy (pendiente)

La semana que viene movemos a la nube:

- App → Streamlit Community Cloud apuntando al repo `alfonsoancarola/app-all`.
- Pipeline → opciones: VPS argentino ($5-10/mes), mini-PC dedicado, o
  seguir con el modelo híbrido (Mac + cloud).
- Lineups y Recap → seguir manual por ahora, automatizar después con
  Gmail forwarder + Drive sync.

Ver `fs_maiz/DEPLOY.md` para el camino híbrido ya documentado del fs_maiz
original (sin Lineups ni Dashboard).
